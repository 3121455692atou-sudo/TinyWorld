import type { AgentListItem, World } from "../api/types";

export function SimulationStatusPanel({ world, agents }: { world: World; agents: AgentListItem[] }) {
  const alive = agents.filter((agent) => agent.lifecycle_state === "alive").length;
  const critical = agents.filter((agent) => agent.lifecycle_state === "critical").length;
  const dead = agents.filter((agent) => agent.lifecycle_state === "dead").length;
  const healthLabel = world.status === "running" ? "运行中" : world.status === "paused" ? "暂停" : world.status === "ended" ? "已结束" : world.status;
  const difficultyLabel = String(world.settings?.survival_difficulty_label || world.settings?.survival_difficulty || "普通");

  return (
    <section className="panel status-panel">
      <h2>运行状态</h2>
      <div className="status-grid">
        <div><span>后端</span><strong>已连接</strong></div>
        <div><span>世界</span><strong>{healthLabel}</strong></div>
        <div><span>难度</span><strong>{difficultyLabel}</strong></div>
        <div><span>Agent</span><strong>{alive} 存活 / {critical} 危急 / {dead} 死亡</strong></div>
      </div>
    </section>
  );
}
