import type { AgentListItem, EventItem } from "../api/types";
import { AgentAvatar } from "./AgentAvatar";

type DialogueLine = {
  speaker_agent_id?: string | null;
  target_agent_id?: string | null;
  text: string;
};

export function ConversationViewer({ events, agents = [] }: { events: EventItem[]; agents?: AgentListItem[] }) {
  const lines = events.flatMap((event) => dialogueLinesFromEvent(event).map((line, index) => ({ event, line, index }))).slice(-10);
  return (
    <section className="panel conversation-panel">
      <h2>对话</h2>
      <div className="conversation-list">
        {lines.length ? lines.map(({ event, line, index }) => {
          const speaker = agents.find((agent) => agent.agent_id === line.speaker_agent_id) || agents.find((agent) => agent.agent_id === event.actor_agent_id);
          const target = agents.find((agent) => agent.agent_id === line.target_agent_id);
          return (
            <div className="dialogue-bubble-row" key={`${event.event_id}-${index}`}>
              <AgentAvatar agent={speaker} />
              <span className="dialogue-body">
                <span className="dialogue-route">{event.world_time_label} · {speaker?.display_name ?? "某位居民"}{target ? ` → ${target.display_name}` : ""}</span>
                <span className="dialogue-speech">{line.text}</span>
              </span>
            </div>
          );
        }) : <p className="empty-events">暂无结构化台词。</p>}
      </div>
    </section>
  );
}

function dialogueLinesFromEvent(event: EventItem): DialogueLine[] {
  const rawLines = event.payload?.dialogue_lines;
  if (Array.isArray(rawLines)) {
    const parsed: DialogueLine[] = [];
    for (const line of rawLines) {
      if (!line || typeof line !== "object") continue;
      const record = line as Record<string, unknown>;
      const text = firstText(record.text, record.speech);
      if (!text || containsMechanicalBackendLanguage(text)) continue;
      parsed.push({
        speaker_agent_id: typeof record.speaker_agent_id === "string" ? record.speaker_agent_id : event.actor_agent_id,
        target_agent_id: typeof record.target_agent_id === "string" ? record.target_agent_id : event.target_agent_id,
        text
      });
    }
    return parsed;
  }
  const text = firstText(event.payload?.speech);
  if (!text || !event.actor_agent_id || containsMechanicalBackendLanguage(text)) return [];
  return [{ speaker_agent_id: event.actor_agent_id, target_agent_id: event.target_agent_id, text }];
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value !== "string") continue;
    const text = value.trim();
    if (text) return text;
  }
  return "";
}

function containsMechanicalBackendLanguage(text: string): boolean {
  return /工具调用格式错误|当前尝试的工具|请重新选择|failure_reason_code|llm_feedback|state_delta|payload|后端|硬规则|基础饱腹规则|数值变化|机制词|抽象结果|EffectEngine|RuleEngine/iu.test(text);
}
