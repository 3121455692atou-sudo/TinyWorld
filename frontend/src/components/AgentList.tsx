import type { AgentListItem } from "../api/types";
import { t, type UiLanguage } from "../i18n";
import { AgentAvatar } from "./AgentAvatar";

export function AgentList({
  agents,
  selectedAgentId,
  onSelect,
  language = "zh"
}: {
  agents: AgentListItem[];
  selectedAgentId: string | null;
  onSelect: (agentId: string) => void;
  language?: UiLanguage;
}) {
  return (
    <section className="panel agent-list-panel">
      <h2>{t("居民", language)}</h2>
      <div className="agent-list">
        {agents.map((agent) => (
          <button
            key={agent.agent_id}
            className={`agent-row ${selectedAgentId === agent.agent_id ? "selected" : ""} ${agent.activity_status?.is_sleeping ? "sleeping" : ""} ${agent.lifecycle_state === "dead" ? "dead" : ""}`}
            onClick={() => onSelect(agent.agent_id)}
          >
            <AgentAvatar agent={agent} />
            <span className="agent-row-main">
              <strong>{agent.display_name}</strong>
              <small title={t(agent.activity_status?.label ?? (agent.lifecycle_state === "dead" ? "死亡" : "清醒"), language)}>
                {t(agent.location_name, language)} · {t(agent.lifecycle_state === "dead" ? "死亡" : agent.mood_label, language)} · {t(agent.activity_status?.label ?? (agent.lifecycle_state === "dead" ? "死亡" : "清醒"), language)}
              </small>
              <span className="micro-bars">
                <i style={{ width: `${agent.health}%` }} />
                <b style={{ width: `${agent.energy}%` }} />
              </span>
            </span>
            {agent.has_warning && <span className="warning-dot" />}
          </button>
        ))}
      </div>
    </section>
  );
}
