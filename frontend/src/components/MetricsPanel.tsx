import type { World, WorldMetrics } from "../api/types";

type MetricRow = { key: string; label: string; value: string | number; enabled?: boolean };

export function MetricsPanel({ world, metrics }: { world: World; metrics: WorldMetrics | null }) {
  const flags = worldUiFlags(world);
  const rows: MetricRow[] = metrics ? [
    { key: "population", label: "人口", value: `${metrics.alive}/${metrics.population} 存活`, enabled: flags.metric("base") },
    { key: "death", label: flags.reproduction ? "出生/死亡" : "死亡", value: flags.reproduction ? `${metrics.births} / ${metrics.dead}` : metrics.dead, enabled: flags.metric("base") },
    { key: "children", label: "儿童/怀孕", value: `${metrics.children} / ${metrics.pregnant}`, enabled: flags.reproduction || metrics.children > 0 || metrics.pregnant > 0 },
    { key: "childRisk", label: "儿童照护风险", value: metrics.child_need_risk, enabled: flags.reproduction || metrics.child_need_risk > 0 },
    { key: "survival", label: "饥饿/口渴风险", value: `${metrics.hunger_risk} / ${metrics.thirst_risk}`, enabled: flags.survival || metrics.hunger_risk > 0 || metrics.thirst_risk > 0 },
    { key: "work", label: "就业/倦怠", value: `${Math.round(metrics.employment_rate * 100)}% / ${Math.round(metrics.burnout_rate * 100)}%`, enabled: flags.metric("work") || metrics.employment_rate > 0 || metrics.burnout_rate > 0 },
    { key: "law", label: "在押/通缉", value: `${metrics.jailed} / ${metrics.wanted}`, enabled: flags.metric("law") || metrics.jailed > 0 || metrics.wanted > 0 },
    { key: "crime", label: "犯罪/发现", value: `${metrics.crime_attempts} / ${metrics.crime_detected}`, enabled: flags.metric("law") || metrics.crime_attempts > 0 || metrics.crime_detected > 0 },
    { key: "sentence", label: "判刑/越狱", value: `${metrics.jail_sentences} / ${metrics.jail_escapes + metrics.jail_escape_failures}`, enabled: flags.metric("law") || metrics.jail_sentences > 0 || metrics.jail_escapes > 0 || metrics.jail_escape_failures > 0 },
    { key: "intimacy", label: "成年亲密事件", value: metrics.adult_intimacy_events, enabled: flags.adultIntimacy || metrics.adult_intimacy_events > 0 },
    { key: "toolFail", label: "工具失败率", value: `${Math.round(metrics.llm_invalid_tool_call_rate * 100)}%`, enabled: flags.metric("base") },
    { key: "cash", label: "平均现金/净资产", value: `${metrics.avg_cash ?? 0} / ${metrics.avg_net_worth ?? 0}`, enabled: flags.metric("economy") },
    { key: "debt", label: "总债务/债务压", value: `${metrics.total_debt ?? 0} / ${metrics.avg_debt_stress ?? 0}`, enabled: flags.metric("economy") || flags.metric("housing") },
    { key: "housing", label: "房东/无家可归", value: `${Math.round((metrics.landlord_rate ?? 0) * 100)}% / ${Math.round((metrics.homeless_rate ?? 0) * 100)}%`, enabled: flags.metric("housing") },
    { key: "hedonic", label: "高级餐/奢侈", value: `${metrics.premium_food_count ?? 0} / ${metrics.luxury_purchase_count ?? 0}`, enabled: flags.metric("hedonic") },
    { key: "rent", label: "逾租/驱逐", value: `${metrics.rent_late_count ?? 0} / ${metrics.eviction_count ?? 0}`, enabled: flags.metric("housing") },
    { key: "creator", label: "创作/爆红", value: `${metrics.creator_work_count ?? 0} / ${metrics.creator_viral_count ?? 0}`, enabled: flags.metric("creator") },
    { key: "stock", label: "证券账户/交易", value: `${metrics.stock_account_count ?? 0} / ${metrics.stock_trade_count ?? 0}`, enabled: flags.metric("finance") },
  ] : [];
  const visibleRows = rows.filter((row) => row.enabled !== false);

  return (
    <section className="panel metrics-panel">
      <h2>指标</h2>
      {metrics ? (
        <div className="status-grid metrics-grid">
          {visibleRows.map((row) => (
            <div key={row.key}><span>{row.label}</span><strong>{row.value}</strong></div>
          ))}
        </div>
      ) : (
        <p className="muted">暂无指标。</p>
      )}
    </section>
  );
}

function worldUiFlags(world: World) {
  const settings = world.settings ?? {};
  const ui = asRecord(settings.worldview_ui);
  const metricGroups = asRecord(ui.metric_groups);
  const panels = asRecord(ui.panels);
  const worldId = String(settings.worldview_id ?? "");
  const toolsetId = String(settings.world_toolset_id ?? settings.toolset_id ?? "");
  const defaultModern = worldId === "default_modern_worldview" || toolsetId === "default_modern_world_toolset" || toolsetId === "default_modern_toolset";
  const survival = boolValue(settings.survival_needs_enabled, false);
  const reproduction = boolValue(settings.reproduction_enabled, false);
  const finance = boolValue(settings.finance_investing_enabled, false);
  const adultIntimacy = reproduction;
  const fallbackByGroup: Record<string, boolean> = {
    base: true,
    survival,
    family: reproduction,
    adult_intimacy: adultIntimacy,
    work: defaultModern,
    law: boolValue(panels.law, true),
    economy: defaultModern || finance,
    housing: defaultModern,
    hedonic: defaultModern,
    creator: defaultModern,
    finance,
  };
  return {
    survival,
    reproduction,
    adultIntimacy,
    metric(group: string) {
      return boolValue(metricGroups[group], fallbackByGroup[group] ?? false);
    }
  };
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function boolValue(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}
