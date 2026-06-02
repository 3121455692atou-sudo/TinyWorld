import type { AgentListItem, World } from "../api/types";
import { t, type UiLanguage } from "../i18n";

export function SimulationStatusPanel({ world, agents, language = "zh" }: { world: World; agents: AgentListItem[]; language?: UiLanguage }) {
  const alive = agents.filter((agent) => agent.lifecycle_state === "alive").length;
  const critical = agents.filter((agent) => agent.lifecycle_state === "critical").length;
  const dead = agents.filter((agent) => agent.lifecycle_state === "dead").length;
  const healthLabel = world.status === "running" ? "运行中" : world.status === "paused" ? "暂停" : world.status === "ended" ? "已结束" : world.status;
  const difficultyLabel = String(world.settings?.survival_difficulty_label || world.settings?.survival_difficulty || "普通");

  return (
    <section className="panel status-panel">
      <h2>{t("运行状态", language)}</h2>
      <div className="status-grid">
        <div><span>{t("后端", language)}</span><strong>{t("已连接", language)}</strong></div>
        <div><span>{t("世界", language)}</span><strong>{t(healthLabel, language)}</strong></div>
        <div><span>{t("难度", language)}</span><strong>{t(difficultyLabel, language)}</strong></div>
        <div><span>Agent</span><strong>{t(`${alive} 存活 / ${critical} 危急 / ${dead} 死亡`, language)}</strong></div>
      </div>
    </section>
  );
}
