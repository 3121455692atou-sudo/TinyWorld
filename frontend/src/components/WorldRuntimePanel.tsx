import { useEffect, useState } from "react";
import type { LlmConcurrencySettings, PromptSettings, World, WorldRuntimeSettingsPayload } from "../api/types";
import { t, type UiLanguage } from "../i18n";

const DEFAULT_PROMPT_SETTINGS: PromptSettings = {
  memory_limit: 24,
  recent_event_limit: 14,
  recent_self_event_limit: 10,
  action_option_limit: 60,
  dream_memory_limit: 48,
  dream_important_limit: 10,
  dream_background_limit: 5
};

const DEFAULT_LLM_CONCURRENCY: LlmConcurrencySettings = {
  default_provider_limit: 0,
  provider_limits: {},
  model_limits: {}
};

export function WorldRuntimePanel({
  world,
  busy,
  onSave,
  language = "zh"
}: {
  world: World;
  busy: boolean;
  onSave: (payload: WorldRuntimeSettingsPayload) => Promise<void>;
  language?: UiLanguage;
}) {
  const settings = world.settings ?? {};
  const [promptDraft, setPromptDraft] = useState(String(settings.collective_core_prompt ?? ""));
  const [speedDraft, setSpeedDraft] = useState<"slow" | "fast">(settings.speed === "fast" ? "fast" : "slow");
  const [requestModeDraft, setRequestModeDraft] = useState<"serial" | "parallel">(settings.agent_request_mode === "parallel" ? "parallel" : "serial");
  const [displayModeDraft, setDisplayModeDraft] = useState<"batch" | "per_agent">(settings.event_display_mode === "per_agent" ? "per_agent" : "batch");
  const [promptSettingsDraft, setPromptSettingsDraft] = useState<PromptSettings>(() => normalizePromptSettings(settings.prompt_settings));
  const [concurrencyDraft, setConcurrencyDraft] = useState<LlmConcurrencySettings>(() => normalizeConcurrency(settings.llm_concurrency));
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setPromptDraft(String(world.settings?.collective_core_prompt ?? ""));
    setSpeedDraft(world.settings?.speed === "fast" ? "fast" : "slow");
    setRequestModeDraft(world.settings?.agent_request_mode === "parallel" ? "parallel" : "serial");
    setDisplayModeDraft(world.settings?.event_display_mode === "per_agent" ? "per_agent" : "batch");
    setPromptSettingsDraft(normalizePromptSettings(world.settings?.prompt_settings));
    setConcurrencyDraft(normalizeConcurrency(world.settings?.llm_concurrency));
  }, [world.world_id, world.settings?.collective_core_prompt, world.settings?.speed, world.settings?.agent_request_mode, world.settings?.event_display_mode, world.settings?.prompt_settings, world.settings?.llm_concurrency]);

  const worldviewName = t(String(settings.worldview_name ?? "未命名世界观"), language);
  const worldToolsetName = t(String(settings.world_toolset_name ?? settings.toolset_name ?? "未指定世界工具集"), language);
  const optionalNames = Array.isArray(settings.optional_toolset_names) ? settings.optional_toolset_names.map(String) : [];
  const survivalLabel = settings.survival_needs_enabled ? "生存需求开启" : "无吃喝生存压力";

  const save = async () => {
    setSaving(true);
    try {
      await onSave({
        collective_core_prompt: promptDraft,
        speed: speedDraft,
        prompt_settings: promptSettingsDraft,
        agent_request_mode: requestModeDraft,
        event_display_mode: requestModeDraft === "parallel" ? "batch" : displayModeDraft,
        llm_concurrency: concurrencyDraft
      });
    } finally {
      setSaving(false);
    }
  };
  const updatePromptSetting = (key: keyof PromptSettings, value: number) => {
    setPromptSettingsDraft((current) => ({ ...current, [key]: value }));
  };

  return (
    <section className="panel world-runtime-panel">
      <div className="panel-heading">
        <h2>{t("世界运行设置", language)}</h2>
        <button type="button" disabled={busy || saving} onClick={save}>{saving ? t("保存中", language) : t("保存", language)}</button>
      </div>
      <div className="world-runtime-body">
        <dl>
          <dt>{t("世界观", language)}</dt><dd title={worldviewName}>{worldviewName}</dd>
          <dt>{t("工具集", language)}</dt><dd title={worldToolsetName}>{worldToolsetName}</dd>
          <dt>{t("生存", language)}</dt><dd>{t(survivalLabel, language)}</dd>
          <dt>{t("可选", language)}</dt><dd title={optionalNames.map((item) => t(item, language)).join("、")}>{optionalNames.length ? optionalNames.map((item) => t(item, language)).join(language === "en" ? ", " : "、") : t("无", language)}</dd>
        </dl>
        <label>
          <span>{t("全体 Agent 共享提示词", language)}</span>
          <textarea
            className="runtime-prompt-editor"
            value={promptDraft}
            placeholder={t("这里会在所有 agent 每次行动的系统提示词最前面生效。适合临时加入世界公告、风格约束、社会规则或实验条件。", language)}
            onChange={(event) => setPromptDraft(event.target.value)}
          />
        </label>
        <label className="runtime-speed-row">
          <span>{t("模拟速度", language)}</span>
          <select value={speedDraft} onChange={(event) => setSpeedDraft(event.target.value === "fast" ? "fast" : "slow")}>
            <option value="slow">{t("慢速", language)}</option>
            <option value="fast">{t("快速", language)}</option>
          </select>
        </label>
        <label className="runtime-speed-row">
          <span>{t("Agent 请求模式", language)}</span>
          <select value={requestModeDraft} onChange={(event) => setRequestModeDraft(event.target.value === "parallel" ? "parallel" : "serial")}>
            <option value="serial">{t("串行请求", language)}</option>
            <option value="parallel">{t("并行请求", language)}</option>
          </select>
        </label>
        <label className="runtime-speed-row">
          <span>{t("事件显示方式", language)}</span>
          <select
            value={requestModeDraft === "parallel" ? "batch" : displayModeDraft}
            disabled={requestModeDraft === "parallel"}
            onChange={(event) => setDisplayModeDraft(event.target.value === "per_agent" ? "per_agent" : "batch")}
          >
            <option value="batch">{t("整批完成后显示", language)}</option>
            <option value="per_agent">{t("每个 Agent 完成后显示", language)}</option>
          </select>
        </label>
        <div className="runtime-prompt-settings">
          <h3>{t("并发限制", language)}</h3>
          <label>
            <span>{t("默认提供商并发", language)}</span>
            <input type="number" min="0" max="100000" value={concurrencyDraft.default_provider_limit} onChange={(event) => setConcurrencyDraft((current) => ({ ...current, default_provider_limit: Number(event.target.value) }))} />
          </label>
          <LimitMapEditor
            title={t("指定提供商并发", language)}
            keyPlaceholder={t("提供商名称或 URL", language)}
            value={concurrencyDraft.provider_limits}
            onChange={(provider_limits) => setConcurrencyDraft((current) => ({ ...current, provider_limits }))}
          />
          <LimitMapEditor
            title={t("指定模型并发", language)}
            keyPlaceholder={t("模型名", language)}
            value={concurrencyDraft.model_limits}
            onChange={(model_limits) => setConcurrencyDraft((current) => ({ ...current, model_limits }))}
          />
        </div>
        <div className="runtime-prompt-settings">
          <h3>{t("模型输入长度", language)}</h3>
          <label>
            <span>{t("短期记忆条数", language)}</span>
            <input type="number" min="0" max="200" value={promptSettingsDraft.memory_limit} onChange={(event) => updatePromptSetting("memory_limit", Number(event.target.value))} />
          </label>
          <label>
            <span>{t("最近事件条数", language)}</span>
            <input type="number" min="0" max="200" value={promptSettingsDraft.recent_event_limit} onChange={(event) => updatePromptSetting("recent_event_limit", Number(event.target.value))} />
          </label>
          <label>
            <span>{t("自身行动条数", language)}</span>
            <input type="number" min="0" max="100" value={promptSettingsDraft.recent_self_event_limit} onChange={(event) => updatePromptSetting("recent_self_event_limit", Number(event.target.value))} />
          </label>
          <label>
            <span>{t("行动编号上限", language)}</span>
            <input type="number" min="20" max="60" value={promptSettingsDraft.action_option_limit} onChange={(event) => updatePromptSetting("action_option_limit", Number(event.target.value))} />
          </label>
          <label>
            <span>{t("入梦记忆读取", language)}</span>
            <input type="number" min="4" max="200" value={promptSettingsDraft.dream_memory_limit} onChange={(event) => updatePromptSetting("dream_memory_limit", Number(event.target.value))} />
          </label>
          <label>
            <span>{t("梦中重要条数", language)}</span>
            <input type="number" min="0" max="40" value={promptSettingsDraft.dream_important_limit} onChange={(event) => updatePromptSetting("dream_important_limit", Number(event.target.value))} />
          </label>
          <label>
            <span>{t("梦中背景条数", language)}</span>
            <input type="number" min="0" max="40" value={promptSettingsDraft.dream_background_limit} onChange={(event) => updatePromptSetting("dream_background_limit", Number(event.target.value))} />
          </label>
        </div>
      </div>
    </section>
  );
}

function normalizePromptSettings(raw: unknown): PromptSettings {
  const data = raw && typeof raw === "object" ? raw as Partial<Record<keyof PromptSettings, unknown>> : {};
  return {
    memory_limit: numberOrDefault(data.memory_limit, DEFAULT_PROMPT_SETTINGS.memory_limit),
    recent_event_limit: numberOrDefault(data.recent_event_limit, DEFAULT_PROMPT_SETTINGS.recent_event_limit),
    recent_self_event_limit: numberOrDefault(data.recent_self_event_limit, DEFAULT_PROMPT_SETTINGS.recent_self_event_limit),
    action_option_limit: numberOrDefault(data.action_option_limit, DEFAULT_PROMPT_SETTINGS.action_option_limit),
    dream_memory_limit: numberOrDefault(data.dream_memory_limit, DEFAULT_PROMPT_SETTINGS.dream_memory_limit),
    dream_important_limit: numberOrDefault(data.dream_important_limit, DEFAULT_PROMPT_SETTINGS.dream_important_limit),
    dream_background_limit: numberOrDefault(data.dream_background_limit, DEFAULT_PROMPT_SETTINGS.dream_background_limit)
  };
}

function numberOrDefault(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function normalizeConcurrency(raw: unknown): LlmConcurrencySettings {
  const data = raw && typeof raw === "object" ? raw as Partial<LlmConcurrencySettings> : {};
  return {
    default_provider_limit: numberOrDefault(data.default_provider_limit, DEFAULT_LLM_CONCURRENCY.default_provider_limit),
    provider_limits: normalizeLimitMap(data.provider_limits),
    model_limits: normalizeLimitMap(data.model_limits)
  };
}

function normalizeLimitMap(raw: unknown): Record<string, number> {
  if (!raw || typeof raw !== "object") return {};
  const result: Record<string, number> = {};
  Object.entries(raw as Record<string, unknown>).forEach(([key, value]) => {
    const name = key.trim();
    const limit = Number(value);
    if (name && Number.isFinite(limit) && limit > 0) result[name] = limit;
  });
  return result;
}

function LimitMapEditor({
  title,
  keyPlaceholder,
  value,
  onChange
}: {
  title: string;
  keyPlaceholder: string;
  value: Record<string, number>;
  onChange: (value: Record<string, number>) => void;
}) {
  const rows = Object.entries(value);
  const displayRows = rows.length ? rows : [["", 1] as [string, number]];
  const updateRow = (index: number, nextKey: string, nextValue: number) => {
    const next: Record<string, number> = {};
    displayRows.forEach(([key, limit], rowIndex) => {
      const name = rowIndex === index ? nextKey.trim() : key;
      const amount = rowIndex === index ? nextValue : limit;
      if (name && Number.isFinite(amount) && amount > 0) next[name] = amount;
    });
    onChange(next);
  };
  const removeRow = (index: number) => {
    const next: Record<string, number> = {};
    rows.forEach(([key, limit], rowIndex) => {
      if (rowIndex !== index) next[key] = limit;
    });
    onChange(next);
  };
  return (
    <div className="runtime-limit-map">
      <div className="runtime-limit-map-heading">
        <span>{title}</span>
        <button type="button" onClick={() => onChange({ ...value, "": 1 })}>+</button>
      </div>
      {displayRows.map(([key, limit], index) => (
        <div className="runtime-limit-row" key={`${key}-${index}`}>
          <input value={key} placeholder={keyPlaceholder} onChange={(event) => updateRow(index, event.target.value, limit)} />
          <input type="number" min="1" max="100000" value={limit} onChange={(event) => updateRow(index, key, Number(event.target.value))} />
          <button type="button" onClick={() => removeRow(index)}>-</button>
        </div>
      ))}
    </div>
  );
}
