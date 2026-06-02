import type { AgentListItem } from "../api/types";
import { AgentAvatar } from "./AgentAvatar";

export function AgentList({
  agents,
  selectedAgentId,
  onSelect
}: {
  agents: AgentListItem[];
  selectedAgentId: string | null;
  onSelect: (agentId: string) => void;
}) {
  return (
    <section className="panel agent-list-panel">
      <h2>居民</h2>
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
              <small title={agent.activity_status?.label ?? (agent.lifecycle_state === "dead" ? "死亡" : "清醒")}>
                {agent.location_name} · {agent.lifecycle_state === "dead" ? "死亡" : agent.mood_label} · {agent.activity_status?.label ?? (agent.lifecycle_state === "dead" ? "死亡" : "清醒")}
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
