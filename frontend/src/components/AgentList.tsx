import type { CSSProperties, KeyboardEvent, MouseEvent } from "react";
import type { AgentListItem } from "../api/types";
import { t, type UiLanguage } from "../i18n";
import { AgentAvatar } from "./AgentAvatar";

export function AgentList({
  agents,
  selectedAgentId,
  onSelect,
  onLocationSelect,
  language = "zh"
}: {
  agents: AgentListItem[];
  selectedAgentId: string | null;
  onSelect: (agentId: string) => void;
  onLocationSelect?: (locationId: string) => void;
  language?: UiLanguage;
}) {
  const selectLocation = (
    locationId: string | null | undefined,
    event: MouseEvent | KeyboardEvent,
  ) => {
    event.stopPropagation();
    if (!locationId) return;
    onLocationSelect?.(locationId);
  };

  return (
    <section className="panel agent-list-panel">
      <h2>{t("居民", language)}</h2>
      <div className="agent-list">
        {agents.map((agent) => {
          const locationColor = agent.location_color || "#64748b";
          const showWarning = agent.lifecycle_state !== "dead" && agent.has_warning;
          const isWorking = agent.activity_status?.state === "working";
          return (
            <button
              key={agent.agent_id}
              className={`agent-row ${selectedAgentId === agent.agent_id ? "selected" : ""} ${agent.activity_status?.is_sleeping ? "sleeping" : ""} ${isWorking ? "working" : ""} ${agent.lifecycle_state === "dead" ? "dead" : ""}`}
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
              <span
                className="agent-location-chip"
                role={agent.location_id ? "button" : undefined}
                tabIndex={agent.location_id ? 0 : undefined}
                title={agent.location_name ? t(`展开地点：${agent.location_name}`, language) : t("暂无地点", language)}
                style={{ "--location-color": locationColor } as CSSProperties}
                onClick={(event) => selectLocation(agent.location_id, event)}
                onKeyDown={(event) => {
                  if (event.key !== "Enter" && event.key !== " ") return;
                  event.preventDefault();
                  selectLocation(agent.location_id, event);
                }}
              >
                <span />
              </span>
              {showWarning && (
                <span
                  className="warning-dot"
                  title={t("状态警告：生命、体力、饱腹或水分过低", language)}
                />
              )}
            </button>
          );
        })}
      </div>
    </section>
  );
}
