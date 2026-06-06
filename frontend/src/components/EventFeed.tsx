import { Download, Play, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { AgentListItem, EventFilters, EventItem as EventType, WorldLocation } from "../api/types";
import { t, type UiLanguage } from "../i18n";
import { EventItem } from "./EventItem";

export function EventFeed({
  agents,
  events,
  filters,
  locations,
  onFiltersChange,
  onRefresh,
  onRequestTts,
  exportUrl,
  language = "zh"
}: {
  agents: AgentListItem[];
  events: EventType[];
  filters: EventFilters;
  locations?: WorldLocation[];
  onFiltersChange: (filters: EventFilters) => void;
  onRefresh: () => void;
  onRequestTts?: (eventId: number) => Promise<string>;
  exportUrl: string;
  language?: UiLanguage;
}) {
  const [playingSequence, setPlayingSequence] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(() => {
    if (typeof window === "undefined" || !window.matchMedia) return true;
    return window.matchMedia("(min-width: 901px) and (orientation: landscape)").matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const media = window.matchMedia("(min-width: 901px) and (orientation: landscape)");
    const sync = () => setFiltersOpen(media.matches);
    sync();
    media.addEventListener?.("change", sync);
    return () => media.removeEventListener?.("change", sync);
  }, []);

  const eventLocations = Array.from(
    new Map(events.filter((event) => event.location_id).map((event) => [event.location_id as string, event.location_name || event.location_id as string])).entries()
  );
  const locationOptions = locations?.length ? locations.map((location) => [location.location_id, location.name] as const) : eventLocations;
  const ttsEvents = useMemo(
    () => events.filter((event) => {
      const actor = agents.find((agent) => agent.agent_id === event.actor_agent_id);
      return Boolean((actor?.tts_enabled || typeof event.payload?.tts_audio_data_url === "string") && speechFromEvent(event));
    }),
    [agents, events],
  );

  const playTtsSequence = async () => {
    if (!onRequestTts || playingSequence) return;
    setPlayingSequence(true);
    try {
      for (const event of ttsEvents) {
        const cached = typeof event.payload?.tts_audio_data_url === "string" ? event.payload.tts_audio_data_url : "";
        const audioUrl = cached || await onRequestTts(event.event_id);
        if (audioUrl) await playAudio(audioUrl);
      }
    } finally {
      setPlayingSequence(false);
    }
  };

  return (
    <section className="panel event-feed-panel">
      <div className="panel-heading event-feed-heading">
        <div className="event-feed-title-row">
          <h2>{t("事件流", language)}</h2>
          <button type="button" className="icon-button" title={t("刷新事件流", language)} onClick={onRefresh}>
            <RefreshCw size={15} />
          </button>
        </div>
        <details className="event-filter-details" open={filtersOpen} onToggle={(event) => setFiltersOpen(event.currentTarget.open)}>
          <summary>
            <span>{t("筛选 / 导出", language)}</span>
            <span className="event-filter-summary-count">{events.length}</span>
          </summary>
          <div className="filters">
            <label>
              <span>{t("记录筛选", language)}</span>
              <select
                value={filters.minImportance}
                onChange={(event) => onFiltersChange({ ...filters, minImportance: Number(event.target.value) })}
              >
                <option value={0}>{t("全部记录", language)}</option>
                <option value={15}>{t("隐藏琐碎", language)}</option>
                <option value={45}>{t("显著变化", language)}</option>
                <option value={70}>{t("危急/死亡", language)}</option>
              </select>
            </label>
            <label>
              <input
                type="checkbox"
                checked={filters.dialogueOnly}
                onChange={(event) => onFiltersChange({ ...filters, dialogueOnly: event.target.checked })}
              />
              {t("对话", language)}
            </label>
            <label>
              <input
                type="checkbox"
                checked={filters.showNarrator}
                onChange={(event) => onFiltersChange({ ...filters, showNarrator: event.target.checked })}
              />
              {t("解说", language)}
            </label>
            <label>
              <input
                type="checkbox"
                checked={filters.exportAvatars}
                onChange={(event) => onFiltersChange({ ...filters, exportAvatars: event.target.checked })}
              />
              {t("导出头像", language)}
            </label>
            <label>
              <input
                type="checkbox"
                checked={filters.exportAudio}
                onChange={(event) => onFiltersChange({ ...filters, exportAudio: event.target.checked })}
              />
              {t("导出音频", language)}
            </label>
            <select value={filters.agentId} onChange={(event) => onFiltersChange({ ...filters, agentId: event.target.value })}>
              <option value="">{t("全部居民", language)}</option>
              {agents.map((agent) => <option key={agent.agent_id} value={agent.agent_id}>{agent.display_name}</option>)}
            </select>
            <select value={filters.locationId} onChange={(event) => onFiltersChange({ ...filters, locationId: event.target.value })}>
              <option value="">{t("全部地点", language)}</option>
              {locationOptions.map(([locationId, name]) => <option key={locationId} value={locationId}>{t(name, language)}</option>)}
            </select>
            <label className="event-id-filter">
              <span>ID</span>
              <input
                type="number"
                min="1"
                placeholder={t("起", language)}
                value={filters.startEventId}
                onChange={(event) => onFiltersChange({ ...filters, startEventId: event.target.value })}
              />
              <input
                type="number"
                min="1"
                placeholder={t("止", language)}
                value={filters.endEventId}
                onChange={(event) => onFiltersChange({ ...filters, endEventId: event.target.value })}
              />
            </label>
            <label>
              <span>{t("最新渲染", language)}</span>
              <select
                value={filters.renderLimit}
                onChange={(event) => onFiltersChange({ ...filters, renderLimit: Number(event.target.value) })}
              >
                <option value={100}>100</option>
                <option value={200}>200</option>
                <option value={500}>500</option>
                <option value={1000}>1000</option>
                <option value={2000}>2000</option>
                <option value={5000}>5000</option>
                <option value={10000}>10000</option>
              </select>
            </label>
            {ttsEvents.length > 0 && onRequestTts && (
              <button type="button" className="event-export-button" disabled={playingSequence} onClick={playTtsSequence} title={t("按当前事件流从上到下播放已配置 TTS 的对话", language)}>
                <Play size={15} /> {playingSequence ? t("播放中", language) : t("顺序播放", language)}
              </button>
            )}
            <a className="event-export-button" href={exportUrl} title={t("按当前筛选导出带浏览界面的 zip 归档", language)}>
              <Download size={15} /> {t("导出归档", language)}
            </a>
          </div>
        </details>
      </div>
      <div className="event-feed">
        {events.length ? events.map((event) => <EventItem key={event.event_id} event={event} agents={agents} onRequestTts={onRequestTts} language={language} />) : <p className="empty-events">{t("暂无事件。启动世界后，如果模型正在思考，第一条行动事件会在本轮完成后出现。", language)}</p>}
      </div>
    </section>
  );
}

function speechFromEvent(event: EventType): string {
  const rawLines = event.payload?.dialogue_lines;
  if (Array.isArray(rawLines)) {
    for (const line of rawLines) {
      if (!line || typeof line !== "object") continue;
      const record = line as Record<string, unknown>;
      const value = typeof record.text === "string" ? record.text : typeof record.speech === "string" ? record.speech : "";
      if (value.trim() && !containsMechanicalBackendLanguage(value)) return value.trim();
    }
  }
  const value = event.payload?.speech;
  return typeof value === "string" && value.trim() && !containsMechanicalBackendLanguage(value) ? value.trim() : "";
}

function containsMechanicalBackendLanguage(text: string): boolean {
  return /工具调用格式错误|当前尝试的工具|请重新选择|failure_reason_code|llm_feedback|state_delta|payload|后端|硬规则|当前工具可能不足|隐藏候选|候选工具|解释过滤原因|向系统申请|agent_requested_more_candidates|基础饱腹规则|数值变化|机制词|抽象结果|EffectEngine|RuleEngine/iu.test(text);
}

function playAudio(audioUrl: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const audio = new Audio(audioUrl);
    audio.onended = () => resolve();
    audio.onerror = () => reject(new Error("audio playback failed"));
    audio.play().catch(reject);
  });
}
