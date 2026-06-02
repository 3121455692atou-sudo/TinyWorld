import { ChevronDown, Loader2, Play } from "lucide-react";
import { useState } from "react";
import type { MouseEvent } from "react";
import type { AgentListItem, EventItem as EventType } from "../api/types";
import { t, type UiLanguage } from "../i18n";
import { AgentAvatar } from "./AgentAvatar";

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
  const speech = firstText(event.payload?.speech, event.payload?.message, event.payload?.content);
  const isSpeechEvent = Boolean(speech && actor);
  const audioUrl = typeof event.payload?.tts_audio_data_url === "string" ? event.payload.tts_audio_data_url : "";
  const canPlayTts = Boolean(isSpeechEvent && (audioUrl || actor?.tts_enabled) && onRequestTts);
  const displayText = localizeEventText(event, actor?.display_name, language);
  const narration = t(speechNarration(displayText, speech) || displayText || `${actor?.display_name ?? "某位居民"}说了一句话。`, language);
  const locationMarker = event.location_color ? (
    <span
      className="location-marker"
      title={t(event.location_name || event.location_id || "未知地点", language)}
      style={{ backgroundColor: event.location_color }}
    />
  ) : <span className="location-marker empty" />;

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
          <AgentAvatar agent={actor} />
          <span className="dialogue-body">
            <span className="dialogue-route">{actor?.display_name ?? t("某位居民", language)} {t("发言", language)}</span>
            <span className="dialogue-speech">
              “{speech}”
              {canPlayTts && (
                <span className="tts-play-control" role="button" tabIndex={0} title={t("播放这句 TTS", language)} onClick={playTts}>
                  {loadingTts ? <Loader2 size={14} className="spinning" /> : <Play size={14} />}
                </span>
              )}
            </span>
            <span className="dialogue-narration">{narration}</span>
          </span>
          {locationMarker}
          <ChevronDown size={15} className={open ? "rotated" : ""} />
        </button>
        {open && (
          <pre className="event-detail dialogue-detail">
{JSON.stringify({ event_id: event.event_id, type: event.event_type, importance: event.importance, payload: event.payload, state_delta: event.state_delta, original_text: event.viewer_text }, null, 2)}
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
{JSON.stringify({ event_id: event.event_id, type: event.event_type, importance: event.importance, payload: event.payload, state_delta: event.state_delta }, null, 2)}
        </pre>
      )}
    </article>
  );
}

function humanizeEventText(text: string): string {
  if (!text) return "";
  let cleaned = text.trim();

  cleaned = cleaned.replace(/^(.+?)\s+买了(.+?)。它没有改变基础饱腹规则，但带来了不同程度的享乐和消费期待。$/u, "$1买了$2。");
  cleaned = cleaned.replace(/^系统租客向\s+(.+?)\s+支付了\s+(.+?)\s+固定租金，没有产生任何对话或剧情互动。$/u, "系统租客向 $1 支付了 $2 租金。");
  cleaned = cleaned.replace(/^系统租客按固定合约向\s+(.+?)\s+支付\s+(.+?)\s+租金。$/u, "系统租客向 $1 支付了 $2 租金。");
  cleaned = cleaned.replace(/暂时没有回应，选择把注意力收回到自己身上。/gu, "没有接话，只是把目光移开，先顾着自己的事。");
  cleaned = cleaned.replace(/和对方一起走了一小段路，边走边慢慢说话。对方明确接受了请求，因此请求被完成。/gu, "并肩走了一小段路，边走边慢慢说话。");
  cleaned = cleaned.replace(/对方明确接受了请求，因此请求被完成。?/gu, "");
  cleaned = cleaned.replace(/这只是请求，正在等待对方接受或拒绝。?/gu, "");
  cleaned = cleaned.replace(/对方能听见这句话：『([^』]+)』/gu, "说了：“$1”");
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

  cleaned = cleaned.replace(/([^。！？!?]*?(后端|硬规则|payload|state_delta|基础饱腹规则|数值变化|机制词|抽象结果|thirst|mood|sickness_risk|curiosity|消费期待|享乐阈值|deprivation_pain)[^。！？!?]*[。！？!?]?)/giu, "");
  cleaned = cleaned.replace(/它没有改变基础饱腹规则[^。！？!?]*[。！？!?]?/gu, "");
  cleaned = cleaned.replace(/没有产生任何对话或剧情互动[。！？!?]?/gu, "");
  cleaned = cleaned.replace(/\s+/g, " ").replace(/\s+([。！？!?])/gu, "$1").trim();

  return cleaned || text;
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
  return reason
    .replace(/当前生命状态不能执行这个行为。?/gu, "现在的身体状态撑不住这个动作")
    .replace(/工具失败。?/gu, "行动没有完成")
    .replace(/。$/u, "");
}

function speechNarration(text: string, speech: string): string {
  if (!text || !speech) return "";
  const quoted = `“${speech}”`;
  let cleaned = text;
  if (cleaned.includes(quoted)) {
    cleaned = cleaned.split(quoted).join("");
  } else if (cleaned.includes(speech)) {
    cleaned = cleaned.split(speech).join("");
  }
  cleaned = cleaned.replace(/\s*[:：]\s*$/u, "").replace(/\s+/g, " ").trim();
  if (!cleaned || cleaned === text.trim()) return "";
  return /[。！？!?]$/u.test(cleaned) ? cleaned : `${cleaned}。`;
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
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
