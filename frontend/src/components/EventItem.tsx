import { ChevronDown, Loader2, Play } from "lucide-react";
import { useState } from "react";
import type { MouseEvent } from "react";
import type { AgentListItem, EventItem as EventType } from "../api/types";
import { t, type UiLanguage } from "../i18n";
import { AgentAvatar } from "./AgentAvatar";

type DialogueLine = {
  speaker_agent_id?: string | null;
  target_agent_id?: string | null;
  text: string;
  tone?: string | null;
};

export function EventItem({
  event,
  agents,
  onRequestTts,
  language = "zh"
}: {
  event: EventType;
  agents: AgentListItem[];
  onRequestTts?: (eventId: number) => Promise<string>;
  language?: UiLanguage;
}) {
  const [open, setOpen] = useState(false);
  const [loadingTts, setLoadingTts] = useState(false);
  const actor = agents.find((agent) => agent.agent_id === event.actor_agent_id);
  const dialogueLines = dialogueLinesFromEvent(event);
  const isSpeechEvent = dialogueLines.length > 0;
  const primaryLine = dialogueLines[0];
  const primarySpeaker = primaryLine ? agents.find((agent) => agent.agent_id === primaryLine.speaker_agent_id) || actor : actor;
  const audioUrl = typeof event.payload?.tts_audio_data_url === "string" ? event.payload.tts_audio_data_url : "";
  const canPlayTts = Boolean(dialogueLines.length === 1 && primarySpeaker?.tts_enabled && onRequestTts);
  const displayText = localizeEventText(event, actor?.display_name, language);
  const locationMarker = event.location_color ? (
    <span
      className="location-marker"
      title={t(event.location_name || event.location_id || "未知地点", language)}
      style={{ backgroundColor: event.location_color }}
    />
  ) : <span className="location-marker empty" />;

  if (event.event_type === "image_generation") {
    const status = typeof event.payload?.status === "string" ? event.payload.status : "pending";
    const imageUrl = typeof event.payload?.image_data_url === "string" ? event.payload.image_data_url : "";
    const error = typeof event.payload?.error === "string" ? event.payload.error : "";
    const title = typeof event.payload?.summary_title === "string" ? event.payload.summary_title : t("生图", language);
    return (
      <article className={`event-item image-event ${event.color_class}`}>
        <button className="event-main image-event-main" onClick={() => setOpen(!open)}>
          <span className="event-time">{t(event.world_time_label, language)}</span>
          <span className="image-event-body">
            <span className="image-event-title">{title}</span>
            {imageUrl ? (
              <img className="generated-event-image" src={imageUrl} alt={title} />
            ) : (
              <span className={`generated-image-placeholder ${status === "failed" ? "failed" : ""}`}>
                {status === "failed" ? t("图片生成失败", language) : t("图片生成中", language)}
              </span>
            )}
            {error && <span className="image-event-error">{error}</span>}
          </span>
          {locationMarker}
          <ChevronDown size={15} className={open ? "rotated" : ""} />
        </button>
        {open && (
          <pre className="event-detail image-event-detail">
{JSON.stringify(safeEventDetails(event, displayText), null, 2)}
          </pre>
        )}
      </article>
    );
  }

  if (isSpeechEvent) {
    const playTts = async (eventObject: MouseEvent) => {
      eventObject.stopPropagation();
      if (!onRequestTts) return;
      setLoadingTts(true);
      try {
        const nextUrl = audioUrl || await onRequestTts(event.event_id);
        if (nextUrl) await new Audio(nextUrl).play();
      } finally {
        setLoadingTts(false);
      }
    };
    return (
      <article className={`event-item dialogue-event ${event.color_class}`}>
        <button className="event-main dialogue-main" onClick={() => setOpen(!open)}>
          <span className="event-time">{t(event.world_time_label, language)}</span>
          <span className="dialogue-stack">
            {dialogueLines.map((line, index) => {
              const speaker = agents.find((agent) => agent.agent_id === line.speaker_agent_id) || (index === 0 ? actor : undefined);
              const target = agents.find((agent) => agent.agent_id === line.target_agent_id);
              return (
                <span className="dialogue-bubble-row" key={`${event.event_id}-${index}`}>
                  <AgentAvatar agent={speaker} />
                  <span className="dialogue-body">
                    <span className="dialogue-route">
                      {speaker?.display_name ?? t("某位居民", language)}
                      {target ? ` → ${target.display_name}` : ""}
                    </span>
                    <span className="dialogue-speech">
                      {line.text}
                      {index === 0 && canPlayTts && (
                        <span className="tts-play-control" role="button" tabIndex={0} title={t("播放这句 TTS", language)} onClick={playTts}>
                          {loadingTts ? <Loader2 size={14} className="spinning" /> : <Play size={14} />}
                        </span>
                      )}
                    </span>
                  </span>
                </span>
              );
            })}
          </span>
          {locationMarker}
          <ChevronDown size={15} className={open ? "rotated" : ""} />
        </button>
        {open && (
          <pre className="event-detail dialogue-detail">
{JSON.stringify(safeEventDetails(event, displayText), null, 2)}
          </pre>
        )}
      </article>
    );
  }

  return (
    <article className={`event-item ${event.color_class}`}>
      <button className="event-main" onClick={() => setOpen(!open)}>
        <span className="event-time">{t(event.world_time_label, language)}</span>
        <span className="event-text">{displayText}</span>
        {locationMarker}
        <ChevronDown size={15} className={open ? "rotated" : ""} />
      </button>
      {open && (
        <pre className="event-detail">
{JSON.stringify(safeEventDetails(event, displayText), null, 2)}
        </pre>
      )}
    </article>
  );
}

function dialogueLinesFromEvent(event: EventType): DialogueLine[] {
  const addressed = event.payload?.addressed_agent_ids;
  const isGroupAddress = Array.isArray(addressed) && addressed.length > 1;
  const rawLines = event.payload?.dialogue_lines;
  if (Array.isArray(rawLines)) {
    const parsed: DialogueLine[] = [];
    for (const line of rawLines) {
      if (!line || typeof line !== "object") continue;
      const record = line as Record<string, unknown>;
      const text = sanitizeSpeechText(firstText(record.text, record.speech));
      if (!text) continue;
      parsed.push({
        speaker_agent_id: typeof record.speaker_agent_id === "string" ? record.speaker_agent_id : event.actor_agent_id,
        target_agent_id: isGroupAddress ? null : (typeof record.target_agent_id === "string" ? record.target_agent_id : event.target_agent_id),
        tone: typeof record.tone === "string" ? record.tone : null,
        text
      });
    }
    return parsed;
  }
  const speech = sanitizeSpeechText(firstText(event.payload?.speech));
  if (speech && event.actor_agent_id) {
    return [{ speaker_agent_id: event.actor_agent_id, target_agent_id: isGroupAddress ? null : event.target_agent_id, text: speech, tone: typeof event.payload?.tone === "string" ? event.payload.tone : null }];
  }
  return fallbackDialogueLinesFromText(event);
}

function fallbackDialogueLinesFromText(_event: EventType): DialogueLine[] {
  // 新事件必须通过 payload.dialogue_lines / payload.speech 渲染成头像气泡。
  // 不再从 viewer_text / agent_visible_text 里提取台词，避免旁白承载角色发言。
  return [];
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value !== "string") continue;
    const text = value.trim();
    if (text) return text;
  }
  return "";
}

function humanizeEventText(text: string): string {
  if (!text) return "";
  const original = text.trim();
  let cleaned = original;

  cleaned = cleaned.replace(/^(.+?)\s+买了(.+?)。它没有改变基础饱腹规则，但带来了不同程度的享乐和消费期待。$/u, "$1买了$2。");
  cleaned = cleaned.replace(/^系统租客向\s+(.+?)\s+支付了\s+(.+?)\s+固定租金，没有产生任何对话或剧情互动。$/u, "系统租客向 $1 支付了 $2 租金。");
  cleaned = cleaned.replace(/^系统租客按固定合约向\s+(.+?)\s+支付\s+(.+?)\s+租金。$/u, "系统租客向 $1 支付了 $2 租金。");
  cleaned = cleaned.replace(/暂时没有回应，选择把注意力收回到自己身上。/gu, "没有接话，只是把目光移开，先顾着自己的事。");
  cleaned = cleaned.replace(/和对方一起走了一小段路，边走边慢慢说话。对方明确接受了请求，因此请求被完成。/gu, "并肩走了一小段路，边走边慢慢说话。");
  cleaned = cleaned.replace(/对方明确接受了请求，因此请求被完成。?/gu, "");
  cleaned = cleaned.replace(/这只是请求，正在等待对方接受或拒绝。?/gu, "");
  cleaned = cleaned.replace(/对方能听见这句话：『([^』]+)』/gu, "说话。");
  cleaned = cleaned.replace(/[：:]\s*[“『][^”』]{1,500}[”』]/gu, "。");
  cleaned = cleaned.replace(/(?:说|说道|回答|请求|求助)[^。！？!?“『]{0,24}[“『][^”』]{1,500}[”』]/gu, "说话");
  cleaned = cleaned.replace(/注意到了这个动作，有机会躲开、抗议或选择不躲。?/gu, "看见了，空气一下子绷紧。");
  cleaned = cleaned.replace(/；目标的主观理解:\s*/gu, "，心里更像是：");
  cleaned = cleaned.replace(/没有提前发现\/来不及阻止/gu, "没来得及反应");
  cleaned = cleaned.replace(/注意到了但没有成功阻止/gu, "察觉到了，却没能避开");
  cleaned = cleaned.replace(/注意到了并选择不躲开/gu, "看见了这个动作，没有躲开");
  cleaned = cleaned.replace(/没有先得到明确同意，就完成了一次拥抱/gu, "没等对方答应，就伸手抱了过去");
  cleaned = cleaned.replace(/没有先得到明确同意，就牵住了对方的手/gu, "没等对方答应，就牵住了对方的手");
  cleaned = cleaned.replace(/没有先得到明确同意，就直接介入帮助了对方/gu, "没等对方答应，就直接插手帮了忙");
  cleaned = cleaned.replace(/没有先得到明确同意，就把对方卷入了一段不自在的同行/gu, "没等对方答应，就把对方带进了一段不自在的同行");
  cleaned = cleaned.replace(/^(.+?)\s+没能执行\s+([a-z0-9_]+)\s*[:：]\s*(.+)$/iu, (_, name: string, toolName: string, reason: string) => {
    const action = TOOL_ACTION_LABELS[toolName] ?? "行动";
    return `${name}想${action}，但没有成功：${humanizeFailureReason(reason)}。`;
  });
  cleaned = cleaned.replace(/(.+?)\s+执行了\s*v\d+\s*目录工具「([^」]+)」/gu, "$1 $2");

  cleaned = stripMechanicalBackendLanguage(cleaned);
  cleaned = cleaned.replace(/它没有改变基础饱腹规则[^。！？!?]*[。！？!?]?/gu, "");
  cleaned = cleaned.replace(/没有产生任何对话或剧情互动[。！？!?]?/gu, "");
  cleaned = cleaned.replace(/\s+/g, " ").replace(/\s+([。！？!?])/gu, "$1").trim();

  if (cleaned) return cleaned;
  return containsMechanicalBackendLanguage(original) ? "有一次行动没有顺利完成。" : original;
}

const MECHANICAL_BACKEND_PATTERNS: RegExp[] = [
  /工具调用格式错误/iu,
  /当前尝试的工具/iu,
  /请重新选择/iu,
  /validation\.message/iu,
  /failure_reason_code/iu,
  /llm_feedback/iu,
  /state_delta/iu,
  /payload/iu,
  /后端/iu,
  /硬规则/iu,
  /基础饱腹规则/iu,
  /数值变化/iu,
  /机制词/iu,
  /抽象结果/iu,
  /effectengine/iu,
  /ruleengine/iu,
  /deprivation_pain/iu,
  /sickness_risk/iu,
  /当前生命状态不能执行这个行为/iu,
  /这个行动需要第二行/iu,
  /这个行动需要台词/iu,
  /参数完整且符合/iu,
  /工具失败/iu,
  /missing_visible_ref/iu,
  /missing_location/iu,
  /missing_known_name/iu,
  /missing_speech/iu,
  /missing_text/iu,
  /target_not_visible/iu,
  /private_room_blocked/iu,
  /tool_name/iu,
  /reason_code/iu,
  /当前工具可能不足/iu,
  /隐藏候选/iu,
  /候选工具/iu,
  /解释过滤原因/iu,
  /向系统申请/iu,
  /agent_requested_more_candidates/iu
];

function containsMechanicalBackendLanguage(text: string): boolean {
  return MECHANICAL_BACKEND_PATTERNS.some((pattern) => pattern.test(text));
}

function stripMechanicalBackendLanguage(text: string): string {
  let cleaned = text;
  cleaned = cleaned.replace(/工具调用格式错误[:：]?/giu, "");
  cleaned = cleaned.replace(/当前尝试的工具是\s*[a-z0-9_]+[。.]?/giu, "");
  cleaned = cleaned.replace(/请重新选择[^。！？!?]*[。！？!?]?/giu, "");
  cleaned = cleaned.replace(/([^。！？!?]*?(后端|硬规则|payload|state_delta|failure_reason_code|failure_reason|reason_code|tool_name|llm_feedback|missing_visible_ref|missing_location|missing_known_name|missing_speech|missing_text|target_not_visible|private_room_blocked|当前工具可能不足|隐藏候选|候选工具|解释过滤原因|向系统申请|agent_requested_more_candidates|基础饱腹规则|数值变化|机制词|抽象结果|thirst|mood|sickness_risk|curiosity|消费期待|享乐阈值|deprivation_pain|EffectEngine|RuleEngine|validation\.message)[^。！？!?]*[。！？!?]?)/giu, "");
  return cleaned;
}


function hideBackendMechanicalText(text: string): string {
  if (!text) return "";
  return stripMechanicalBackendLanguage(text)
    .replace(/参数完整且符合当前地点\/目标的工具/giu, "合适的做法")
    .replace(/这是别人的私人小屋，不能直接移动进去。可以敲门请求进入；如果对方授权过你使用，也可以正常进入；也可以选择入室盗窃\/抢劫并承担后果。?/giu, "入口不对外开放，没能直接进去")
    .replace(/\s+/g, " ")
    .trim();
}

function sanitizeSpeechText(text: string): string {
  const cleaned = text.trim();
  if (!cleaned) return "";
  return containsMechanicalBackendLanguage(cleaned) ? "" : cleaned;
}

function safeEventDetails(event: EventType, displayText: string): Record<string, unknown> {
  return {
    event_id: event.event_id,
    type: event.event_type,
    importance: event.importance,
    text: displayText || "有一次行动被记录。"
  };
}

const TOOL_ACTION_LABELS: Record<string, string> = {
  drink_water: "喝水",
  drink_bottled_water: "喝水",
  eat_food: "吃饭",
  eat_portable_food: "吃东西",
  sleep: "睡觉",
  return_home: "回家",
  move_to_location: "移动",
  wash: "洗漱",
  buy_portable_food: "买食物",
  buy_bottled_water: "取水"
};

function humanizeFailureReason(reason: string): string {
  const cleaned = stripMechanicalBackendLanguage(reason)
    .replace(/这是别人的私人小屋，不能直接移动进去。可以敲门请求进入；如果对方授权过你使用，也可以正常进入；也可以选择入室盗窃\/抢劫并承担后果。?/gu, "入口不对外开放，没能直接进去")
    .replace(/当前生命状态不能执行这个行为。?/gu, "现在的身体状态撑不住这个动作")
    .replace(/工具失败。?/gu, "行动没有完成")
    .replace(/。$/u, "")
    .trim();
  return cleaned || "行动没有完成";
}



function localizeEventText(event: EventType, actorName: string | undefined, language: UiLanguage): string {
  const translated = t(humanizeEventText(event.viewer_text), language);
  if (language !== "en" || !containsCjk(translated)) return translated;
  return englishEventFallback(event, actorName);
}

function containsCjk(text: string): boolean {
  return /[\u3400-\u9fff]/u.test(text);
}

function englishEventFallback(event: EventType, actorName: string | undefined): string {
  const actor = actorName || "A resident";
  const location = typeof event.location_name === "string" && event.location_name.trim() ? t(event.location_name, "en") : "";
  const where = location ? ` at ${location}` : "";
  switch (event.event_type) {
    case "look":
      return `${actor} looked around${where}.`;
    case "observe":
      return `${actor} observed someone nearby${where}.`;
    case "self_status":
      return `${actor} checked their own condition.`;
    case "move":
      return `${actor} moved to another location.`;
    case "sleep":
    case "wake":
      return `${actor} rested or woke up.`;
    case "dream":
      return `${actor} dreamed and processed recent memories.`;
    case "dialogue":
      return `${actor} spoke.`;
    case "work":
    case "work_break":
      return `${actor} dealt with work or fatigue.`;
    case "supplies":
    case "supply":
    case "eat":
    case "drink":
      return `${actor} handled basic supplies.`;
    case "relationship":
    case "romance":
    case "boundary":
      return `${actor} dealt with a relationship matter.`;
    case "tool_failed":
      return `${actor} tried something, but it did not work.`;
    case "narration":
      return "The narrator recorded a scene.";
    default:
      return `${actor} did something${where}.`;
  }
}
