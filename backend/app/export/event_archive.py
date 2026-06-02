from __future__ import annotations

import base64
import html
import json
import re
import zipfile
from io import BytesIO
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import format_world_time
from app.core.models import Agent, Event, Location, NarratorRun, World
from app.world.visibility import location_public_name


def build_event_archive_zip(session: Session, world: World, events: list[Event], *, include_avatars: bool = True, include_audio: bool = False) -> bytes:
    agents = sorted(world.agents, key=lambda agent: (agent.created_at_world_time or 0, agent.agent_id))
    location_ids = sorted({event.location_id for event in events if event.location_id})
    locations = [session.get(Location, location_id) for location_id in location_ids]
    archive_agents, avatar_files = _archive_agents(agents, include_avatars=include_avatars)
    archive_events, audio_files = _archive_events(session, events, include_audio=include_audio)
    daily_summaries = _daily_summaries(session, world)
    payload = {
        "world": {
            "worldId": world.world_id,
            "name": world.name,
            "status": world.status,
            "seed": world.seed,
            "timeLabel": format_world_time(world.current_world_time_minutes),
        },
        "summary": _summary(events),
        "agents": archive_agents,
        "locations": [
            {
                "locationId": location.location_id,
                "name": location.public_name,
                "color": _location_color(location.location_id),
                "count": sum(1 for event in events if event.location_id == location.location_id),
            }
            for location in locations
            if location
        ],
        "dailySummaries": daily_summaries,
        "events": archive_events,
        "includeAvatars": include_avatars,
        "includeAudio": include_audio,
    }
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("index.html", _archive_html(payload))
        zf.writestr("events.json", json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        zf.writestr("README.txt", "打开 index.html 浏览导出的事件/聊天记录。events.json 保留结构化原始数据。若导出时勾选音频，audio/ 目录会包含已缓存的 TTS 音频。\n")
        for path, content in avatar_files.items():
            zf.writestr(path, content)
        for path, content in audio_files.items():
            zf.writestr(path, content)
    return buffer.getvalue()


def _archive_agents(agents: list[Agent], *, include_avatars: bool) -> tuple[dict[str, dict[str, Any]], dict[str, bytes | str]]:
    result: dict[str, dict[str, Any]] = {}
    avatar_files: dict[str, bytes | str] = {}
    for index, agent in enumerate(agents):
        avatar_hint = agent.avatar_hint_json or {}
        color = _safe_color(str(avatar_hint.get("color") or _fallback_color(index)))
        avatar_path = None
        if include_avatars:
            avatar_path, content = _avatar_file(agent, color)
            avatar_files[avatar_path] = content
        result[agent.agent_id] = {
            "agentId": agent.agent_id,
            "name": agent.chosen_name or agent.agent_id,
            "appearance": agent.appearance_short or "",
            "status": agent.lifecycle_state,
            "gender": agent.gender_identity if agent.gender_publicity else "不愿公开",
            "color": color,
            "initial": (agent.chosen_name or "?")[:1],
            "avatarPath": avatar_path,
        }
    return result, avatar_files


def _archive_events(session: Session, events: list[Event], *, include_audio: bool) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    archived: list[dict[str, Any]] = []
    audio_files: dict[str, bytes] = {}
    for event in events:
        item = _archive_event(session, event, include_audio=include_audio)
        audio_data_url = item.pop("_audioDataUrlForFile", "")
        if include_audio and isinstance(audio_data_url, str) and audio_data_url.startswith("data:"):
            parsed = _parse_data_url(audio_data_url)
            if parsed:
                extension, content = parsed
                audio_path = f"audio/event_{event.event_id}.{extension}"
                audio_files[audio_path] = content
                item["ttsAudioDataUrl"] = audio_path
        archived.append(item)
    return archived, audio_files


def _archive_event(session: Session, event: Event, *, include_audio: bool) -> dict[str, Any]:
    payload = event.payload or {}
    speech = (payload.get("speech") or payload.get("message") or payload.get("content")) if isinstance(payload, dict) else None
    tts_audio = payload.get("tts_audio_data_url") if isinstance(payload.get("tts_audio_data_url"), str) else ""
    detail_payload = dict(payload) if isinstance(payload, dict) else {}
    if not include_audio:
        detail_payload.pop("tts_audio_data_url", None)
    elif tts_audio:
        detail_payload["tts_audio_data_url"] = "[exported as audio file]" if tts_audio.startswith("data:") else tts_audio
    return {
        "eventId": event.event_id,
        "worldTime": event.world_time,
        "timeLabel": format_world_time(event.world_time),
        "eventType": event.event_type,
        "actorAgentId": event.actor_agent_id,
        "targetAgentId": event.target_agent_id,
        "locationId": event.location_id,
        "locationName": location_public_name(session, event.location_id),
        "locationColor": _location_color(event.location_id),
        "importance": event.importance,
        "colorClass": event.color_class,
        "text": event.viewer_text,
        "speech": speech if isinstance(speech, str) else "",
        "ttsAudioDataUrl": tts_audio if include_audio else "",
        "_audioDataUrlForFile": tts_audio if include_audio else "",
        "detail": {
            "payload": detail_payload,
            "state_delta": event.state_delta or {},
            "visibility_scope": event.visibility_scope,
            "agent_visible_text": event.agent_visible_text,
            "no_state_changed": event.no_state_changed,
        },
    }


def _summary(events: list[Event]) -> dict[str, int]:
    return {
        "eventCount": len(events),
        "dialogueCount": sum(1 for event in events if event.event_type == "dialogue" or any(isinstance((event.payload or {}).get(key), str) for key in ("speech", "message", "content"))),
        "narrationCount": sum(1 for event in events if event.event_type == "narration"),
        "deathCount": sum(1 for event in events if event.event_type == "death"),
        "firstEventId": events[0].event_id if events else 0,
        "lastEventId": events[-1].event_id if events else 0,
    }


def _daily_summaries(session: Session, world: World) -> list[dict[str, Any]]:
    runs = list(
        session.execute(
            select(NarratorRun)
            .where(NarratorRun.world_id == world.world_id, NarratorRun.trigger_type == "daily_summary")
            .order_by(NarratorRun.created_world_time.asc(), NarratorRun.narrator_run_id.asc())
        ).scalars()
    )
    return [
        {
            "narratorRunId": run.narrator_run_id,
            "title": run.summary_title or format_world_time(run.created_world_time),
            "text": run.narration or "",
            "tone": run.tone,
            "importance": run.importance,
            "worldTime": run.created_world_time,
            "timeLabel": format_world_time(run.created_world_time),
            "inputEventIds": run.input_event_ids_json or [],
        }
        for run in runs
    ]


def _archive_html(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False, default=str).replace("</", "<\\/")
    title = html.escape(str(payload["world"]["name"]))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} 事件归档</title>
<style>
:root {{
  color-scheme: light;
  --bg:#e9eef0; --surface:#ffffff; --surface-soft:#f6f8f8; --line:#c9d3d7;
  --topbar:#fbfcfd; --heading:#f9fbfb; --input:#ffffff; --detail:#f6f8f8;
  --text:#18232b; --muted:#60707a; --blue:#1f6fb2; --green:#2f8f58; --amber:#b77710; --red:#b42318; --violet:#6954bd;
  font-family: Inter, ui-sans-serif, system-ui, "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
}}
* {{ box-sizing: border-box; }}
body {{ margin:0; min-width:320px; background:var(--bg); color:var(--text); }}
body.theme-dark {{ color-scheme: dark; --bg:#14191d; --surface:#1d2429; --surface-soft:#20292e; --line:#33424a; --topbar:#1d2429; --heading:#20282d; --input:#151b1f; --detail:#151b1f; --text:#e8eef1; --muted:#a9b7bf; --blue:#6aa9e8; --green:#59b879; --amber:#d99b2b; --red:#ff7a70; --violet:#a99aff; }}
body.theme-green {{ --bg:#e4efec; --surface:#fbfdfc; --surface-soft:#eef7f3; --line:#bfd6cd; --topbar:#f7fbf9; --heading:#eef7f3; --input:#ffffff; --detail:#f1f8f5; --blue:#24777c; --green:#277a53; --amber:#a66d13; --violet:#6f5aae; }}
body.theme-warm {{ --bg:#efece5; --surface:#fffdf8; --surface-soft:#f8f3ea; --line:#d7cab7; --topbar:#fffaf1; --heading:#f8f1e5; --input:#fffdf8; --detail:#f9f4ea; --blue:#2f6d8e; --green:#587f48; --amber:#a36512; --violet:#7a5a94; }}
body.theme-mono {{ --bg:#e8e9ea; --surface:#ffffff; --surface-soft:#f3f4f5; --line:#c8ccd0; --topbar:#fafafa; --heading:#f1f2f3; --input:#ffffff; --detail:#f4f4f4; --blue:#4c6475; --green:#50645c; --amber:#77715f; --red:#884a4a; --violet:#5f5870; }}
.topbar {{ position:sticky; top:0; z-index:5; min-height:56px; padding:10px 16px; background:var(--topbar); border-bottom:1px solid var(--line); display:flex; align-items:center; justify-content:space-between; gap:12px; }}
.topbar strong {{ font-size:18px; }}
.topbar span {{ color:var(--muted); font-size:13px; }}
.shell {{ height:calc(100vh - 57px); display:grid; grid-template-columns:280px minmax(420px,1fr) 310px; gap:12px; padding:12px; }}
.rail, .feed {{ min-height:0; overflow:auto; }}
.panel {{ background:var(--surface); border:1px solid var(--line); border-radius:8px; overflow:hidden; box-shadow:0 1px 2px rgba(15,30,40,.05); margin-bottom:12px; }}
.panel h2 {{ margin:0; padding:11px 14px; background:var(--heading); border-bottom:1px solid var(--line); font-size:15px; }}
.panel-body {{ padding:10px 12px; }}
.stat-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }}
.stat-grid div, .agent-row, .location-row {{ background:var(--surface-soft); border:1px solid #e3e9eb; border-radius:7px; padding:8px; }}
.stat-grid span, .agent-row small, .location-row small {{ color:var(--muted); display:block; margin-top:3px; }}
.agent-list {{ display:grid; gap:8px; }}
.agent-row {{ display:grid; grid-template-columns:38px 1fr; gap:9px; align-items:center; }}
.avatar {{ width:38px; height:38px; border-radius:50%; display:grid; place-items:center; overflow:hidden; color:white; font-weight:700; background:#607d8b; box-shadow: inset 0 0 0 1px rgba(255,255,255,.45); }}
.avatar img {{ width:100%; height:100%; object-fit:cover; }}
.location-row {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:7px; }}
.loc-left {{ display:flex; align-items:center; gap:7px; }}
.swatch {{ width:10px; height:10px; border-radius:3px; display:inline-block; background:#8a99a1; }}
.swatch.empty {{ opacity:0; }}
.daily-summary {{ background:var(--surface-soft); border:1px solid var(--line); border-radius:7px; padding:10px; margin-bottom:9px; }}
.daily-summary strong {{ display:block; margin-bottom:6px; }}
.daily-summary p {{ margin:0; line-height:1.7; white-space:pre-wrap; overflow-wrap:anywhere; }}
.filters {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:10px; }}
.filters input, .filters select, .filters button {{ min-height:34px; border:1px solid var(--line); border-radius:6px; background:var(--input); color:var(--text); padding:6px 9px; }}
.filters button {{ cursor:pointer; }}
.event {{ background:var(--surface); border:1px solid #e3e9eb; border-left:4px solid #cfd8dc; border-radius:6px; margin-bottom:8px; overflow:hidden; }}
.event.dialogue {{ border-left-color:var(--blue); background:color-mix(in srgb, var(--surface) 92%, var(--blue)); }}
.event.important {{ border-left-color:var(--amber); }}
.event.danger, .event.death {{ border-left-color:var(--red); }}
.event.narrator {{ border-left-color:var(--violet); }}
.event-main {{ display:grid; grid-template-columns:86px 42px minmax(0,1fr) 12px; gap:10px; padding:10px 11px; align-items:start; }}
.event:not(.dialogue) .event-main {{ grid-template-columns:86px minmax(0,1fr) 12px; }}
.time {{ color:var(--muted); font-size:12px; }}
.route {{ color:var(--muted); font-size:12px; margin-bottom:3px; }}
.speech {{ font-size:15px; line-height:1.6; word-break:break-word; }}
.tts-btn {{ width:24px; height:24px; margin-left:8px; border:1px solid var(--line); border-radius:50%; background:var(--input); color:var(--text); cursor:pointer; }}
.speech-note {{ color:var(--muted); font-size:13px; margin-top:4px; line-height:1.5; }}
.text {{ line-height:1.6; word-break:break-word; }}
.loc-line {{ width:10px; min-height:34px; border-radius:999px; align-self:center; }}
details {{ border-top:1px solid rgba(0,0,0,.06); padding:8px 12px 12px 108px; }}
.event.dialogue details {{ padding-left:150px; }}
summary {{ cursor:pointer; color:var(--muted); font-size:13px; }}
pre {{ white-space:pre-wrap; overflow:auto; margin:8px 0 0; color:var(--text); background:var(--detail); border:1px solid var(--line); border-radius:6px; padding:8px; }}
.empty {{ padding:30px; text-align:center; color:var(--muted); }}
@media (max-width: 1020px) {{ .shell {{ height:auto; grid-template-columns:1fr; }} .rail,.feed {{ overflow:visible; }} }}
</style>
</head>
<body>
<header class="topbar">
  <div><strong id="world-title"></strong> <span id="world-meta"></span></div>
  <span>离线事件/聊天归档</span>
</header>
<main class="shell">
  <aside class="rail">
    <section class="panel"><h2>居民</h2><div id="agents" class="panel-body agent-list"></div></section>
  </aside>
  <section class="feed">
    <div class="panel"><h2>浏览</h2><div class="panel-body"><div class="filters">
      <input id="q" placeholder="搜索文本/姓名/地点">
      <select id="type"><option value="">全部类型</option><option value="dialogue">只看对话</option><option value="narration">只看解说</option><option value="death">只看死亡</option></select>
      <select id="agent"><option value="">全部居民</option></select>
      <select id="location"><option value="">全部地点</option></select>
      <select id="theme"><option value="light">浅色</option><option value="dark">深色</option><option value="green">青绿</option><option value="warm">暖色</option><option value="mono">灰度</option></select>
      <button id="reset">重置</button>
    </div></div></div>
    <div id="events"></div>
  </section>
  <aside class="rail">
    <section class="panel"><h2>每日总结</h2><div id="daily-summaries" class="panel-body"></div></section>
    <section class="panel"><h2>统计</h2><div id="stats" class="panel-body stat-grid"></div></section>
    <section class="panel"><h2>地点</h2><div id="locations" class="panel-body"></div></section>
  </aside>
</main>
<script id="archive-data" type="application/json">{data}</script>
<script>
const data = JSON.parse(document.getElementById("archive-data").textContent);
const agents = data.agents || {{}};
const events = data.events || [];
const locations = data.locations || [];
const dailySummaries = data.dailySummaries || [];
const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, ch => ({{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}}[ch]));
function avatar(agent) {{
  if (!agent) return '<span class="avatar">?</span>';
  if (agent.avatarPath) return `<span class="avatar"><img src="${{esc(agent.avatarPath)}}" alt="${{esc(agent.name)}}"></span>`;
  return `<span class="avatar" style="background:${{esc(agent.color)}}">${{esc(agent.initial || "?")}}</span>`;
}}
function applyTheme(value) {{
  document.body.className = value === "light" ? "" : `theme-${{value}}`;
  window.localStorage.setItem("tinyLivingWorldArchiveTheme", value);
}}
function speechNarration(text, speech) {{
  if (!text || !speech) return "";
  const quoted = `“${{speech}}”`;
  let cleaned = text;
  if (cleaned.includes(quoted)) cleaned = cleaned.split(quoted).join("");
  else if (cleaned.includes(speech)) cleaned = cleaned.split(speech).join("");
  cleaned = cleaned.replace(/\\s*[:：]\\s*$/u, "").replace(/\\s+/g, " ").trim();
  if (!cleaned || cleaned === String(text).trim()) return "";
  return /[。！？!?]$/u.test(cleaned) ? cleaned : `${{cleaned}}。`;
}}
function paintStatic() {{
  $("world-title").textContent = data.world.name;
  $("world-meta").textContent = `${{data.world.timeLabel}} · ${{data.summary.eventCount}} 条记录`;
  $("agents").innerHTML = Object.values(agents).map(agent => `<div class="agent-row">${{avatar(agent)}}<div><strong>${{esc(agent.name)}}</strong><small>${{esc(agent.status)}} · ${{esc(agent.gender)}}<br>${{esc(agent.appearance)}}</small></div></div>`).join("");
  $("stats").innerHTML = [
    ["事件", data.summary.eventCount], ["对话", data.summary.dialogueCount], ["解说", data.summary.narrationCount],
    ["死亡", data.summary.deathCount], ["起始ID", data.summary.firstEventId], ["结束ID", data.summary.lastEventId]
  ].map(([k,v]) => `<div><strong>${{esc(v)}}</strong><span>${{esc(k)}}</span></div>`).join("");
  $("locations").innerHTML = locations.map(loc => `<div class="location-row"><span class="loc-left">${{loc.color ? `<i class="swatch" style="background:${{esc(loc.color)}}"></i>` : '<i class="swatch empty"></i>'}}${{esc(loc.name)}}</span><small>${{loc.count}}</small></div>`).join("") || '<p class="empty">没有地点记录</p>';
  $("daily-summaries").innerHTML = dailySummaries.length ? dailySummaries.map(item => `<article class="daily-summary"><strong>${{esc(item.title)}} · ${{esc(item.timeLabel)}}</strong><p>${{esc(item.text)}}</p></article>`).join("") : '<p class="empty">没有每日总结。</p>';
  $("agent").innerHTML += Object.values(agents).map(agent => `<option value="${{esc(agent.agentId)}}">${{esc(agent.name)}}</option>`).join("");
  $("location").innerHTML += locations.map(loc => `<option value="${{esc(loc.locationId)}}">${{esc(loc.name)}}</option>`).join("");
}}
function eventHtml(event) {{
  const actor = agents[event.actorAgentId];
  const target = agents[event.targetAgentId];
  const isDialogue = Boolean(event.speech);
  const line = event.locationColor ? `<i class="loc-line" title="${{esc(event.locationName)}}" style="background:${{esc(event.locationColor)}}"></i>` : '<i></i>';
  const detail = esc(JSON.stringify({{eventId:event.eventId,type:event.eventType,importance:event.importance,payload:event.detail.payload,state_delta:event.detail.state_delta,agent_visible_text:event.detail.agent_visible_text}}, null, 2));
  if (isDialogue) {{
    const note = speechNarration(event.text, event.speech);
    const tts = event.ttsAudioDataUrl ? `<button class="tts-btn" title="播放 TTS" onclick="playTts(${{event.eventId}})">▶</button>` : "";
    return `<article class="event dialogue ${{esc(event.colorClass)}}"><div class="event-main"><span class="time">#${{event.eventId}}<br>${{esc(event.timeLabel)}}</span>${{avatar(actor)}}<div><div class="route">${{esc(actor?.name || "某位居民")}} → ${{esc(target?.name || "附近的人")}} · ${{esc(event.locationName)}}</div><div class="speech">“${{esc(event.speech)}}”${{tts}}</div>${{note ? `<div class="speech-note">${{esc(note)}}</div>` : ""}}</div>${{line}}</div><details><summary>显示详细</summary><pre>${{detail}}</pre></details></article>`;
  }}
  return `<article class="event ${{esc(event.colorClass)}}"><div class="event-main"><span class="time">#${{event.eventId}}<br>${{esc(event.timeLabel)}}</span><div class="text">${{esc(event.text)}}</div>${{line}}</div><details><summary>显示详细</summary><pre>${{detail}}</pre></details></article>`;
}}
function playTts(eventId) {{
  const event = data.events.find(item => item.eventId === eventId);
  if (event?.ttsAudioDataUrl) new Audio(event.ttsAudioDataUrl).play();
}}
function render() {{
  const q = $("q").value.trim().toLowerCase();
  const type = $("type").value;
  const agent = $("agent").value;
  const location = $("location").value;
  const filtered = events.filter(event => {{
    if (type === "dialogue" && !event.speech) return false;
    if (type && type !== "dialogue" && event.eventType !== type) return false;
    if (agent && event.actorAgentId !== agent && event.targetAgentId !== agent) return false;
    if (location && event.locationId !== location) return false;
    if (q) {{
      const actor = agents[event.actorAgentId]?.name || "";
      const target = agents[event.targetAgentId]?.name || "";
      const haystack = `${{event.text}} ${{event.speech}} ${{actor}} ${{target}} ${{event.locationName}}`.toLowerCase();
      if (!haystack.includes(q)) return false;
    }}
    return true;
  }});
  $("events").innerHTML = filtered.length ? filtered.map(eventHtml).join("") : '<p class="empty">没有符合筛选的记录。</p>';
}}
paintStatic();
const savedTheme = window.localStorage.getItem("tinyLivingWorldArchiveTheme") || "light";
$("theme").value = savedTheme;
applyTheme(savedTheme);
["q","type","agent","location"].forEach(id => $(id).addEventListener("input", render));
$("theme").addEventListener("input", () => applyTheme($("theme").value));
$("reset").addEventListener("click", () => {{ $("q").value=""; $("type").value=""; $("agent").value=""; $("location").value=""; render(); }});
render();
</script>
</body>
</html>
"""


def _avatar_file(agent: Agent, color: str) -> tuple[str, bytes | str]:
    image = (agent.avatar_hint_json or {}).get("image_data_url")
    if isinstance(image, str) and image.startswith("data:"):
        parsed = _parse_data_url(image)
        if parsed:
            extension, content = parsed
            return f"avatars/{_safe_filename(agent.agent_id)}.{extension}", content
    name = agent.chosen_name or "?"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96">
<rect width="96" height="96" rx="48" fill="{html.escape(color)}"/>
<text x="48" y="58" text-anchor="middle" font-family="Arial, sans-serif" font-size="42" font-weight="700" fill="white">{html.escape(name[:1])}</text>
</svg>"""
    return f"avatars/{_safe_filename(agent.agent_id)}.svg", svg


def _parse_data_url(value: str) -> tuple[str, bytes] | None:
    match = re.match(r"^data:([^;,]+);base64,(.*)$", value, re.S)
    if not match:
        return None
    mime = match.group(1).lower()
    extension = "png"
    if "mpeg" in mime or "mp3" in mime:
        extension = "mp3"
    elif "wav" in mime or "wave" in mime:
        extension = "wav"
    elif "ogg" in mime:
        extension = "ogg"
    elif "flac" in mime:
        extension = "flac"
    elif "webm" in mime:
        extension = "webm"
    elif "webp" in mime:
        extension = "webp"
    elif "jpeg" in mime or "jpg" in mime:
        extension = "jpg"
    elif "gif" in mime:
        extension = "gif"
    try:
        return extension, base64.b64decode(match.group(2), validate=False)
    except Exception:
        return None


def _location_color(location_id: str | None) -> str | None:
    key = _public_location_key(location_id)
    palette_by_key = {
        "central_square": "#2f80ed",
        "cafeteria": "#27ae60",
        "cabin": "#f2994a",
        "library": "#9b51e0",
        "lake": "#00a6a6",
        "workshop": "#b8860b",
        "medical_room": "#eb5757",
        "garden": "#4f6f52",
        "market": "#d94888",
        "campfire": "#c66a31",
        "notice_board": "#6c7a89",
        "jail": "#4d4d4d",
    }
    return palette_by_key.get(key) if key else None


def _public_location_key(location_id: str | None) -> str | None:
    if not location_id or ":" not in location_id:
        return None
    key = location_id.split(":", 1)[1]
    return None if key.startswith("private_cabin_") else key


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)[:80] or "item"


def _safe_color(value: str) -> str:
    return value if re.fullmatch(r"#[0-9a-fA-F]{6}", value) else "#607d8b"


def _fallback_color(index: int) -> str:
    palette = ["#4f7cac", "#b4656f", "#5d8a66", "#c0812d", "#7b68a6", "#2f7f7f"]
    return palette[index % len(palette)]
