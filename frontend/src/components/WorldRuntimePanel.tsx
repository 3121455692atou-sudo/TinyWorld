import { useEffect, useState } from "react";
import type { PromptSettings, World } from "../api/types";

const DEFAULT_PROMPT_SETTINGS: PromptSettings = {
  memory_limit: 10,
  recent_event_limit: 8,
  recent_self_event_limit: 6,
  action_option_limit: 90,
  dream_memory_limit: 24,
  dream_important_limit: 5,
  dream_background_limit: 3
};

export function WorldRuntimePanel({
  world,
  busy,
  onSave
}: {
  world: World;
  busy: boolean;
  onSave: (payload: { collective_core_prompt?: string; speed?: "slow" | "fast"; prompt_settings?: Record<string, number> }) => Promise<void>;
}) {
  const settings = world.settings ?? {};
  const [promptDraft, setPromptDraft] = useState(String(settings.collective_core_prompt ?? ""));
  const [speedDraft, setSpeedDraft] = useState<"slow" | "fast">(settings.speed === "fast" ? "fast" : "slow");
  const [promptSettingsDraft, setPromptSettingsDraft] = useState<PromptSettings>(() => normalizePromptSettings(settings.prompt_settings));
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setPromptDraft(String(world.settings?.collective_core_prompt ?? ""));
    setSpeedDraft(world.settings?.speed === "fast" ? "fast" : "slow");
    setPromptSettingsDraft(normalizePromptSettings(world.settings?.prompt_settings));
  }, [world.world_id, world.settings?.collective_core_prompt, world.settings?.speed, world.settings?.prompt_settings]);

  const worldviewName = String(settings.worldview_name ?? "未命名世界观");
  const worldToolsetName = String(settings.world_toolset_name ?? settings.toolset_name ?? "未指定世界工具集");
  const optionalNames = Array.isArray(settings.optional_toolset_names) ? settings.optional_toolset_names.map(String) : [];
  const survivalLabel = settings.survival_needs_enabled ? "生存需求开启" : "无吃喝生存压力";

  const save = async () => {
    setSaving(true);
    try {
      await onSave({ collective_core_prompt: promptDraft, speed: speedDraft, prompt_settings: promptSettingsDraft });
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
        <h2>世界运行设置</h2>
        <button type="button" disabled={busy || saving} onClick={save}>{saving ? "保存中" : "保存"}</button>
      </div>
      <div className="world-runtime-body">
        <dl>
          <dt>世界观</dt><dd title={worldviewName}>{worldviewName}</dd>
          <dt>工具集</dt><dd title={worldToolsetName}>{worldToolsetName}</dd>
          <dt>生存</dt><dd>{survivalLabel}</dd>
          <dt>可选</dt><dd title={optionalNames.join("、")}>{optionalNames.length ? optionalNames.join("、") : "无"}</dd>
        </dl>
        <label>
          <span>全体 Agent 共享提示词</span>
          <textarea
            className="runtime-prompt-editor"
            value={promptDraft}
            placeholder="这里会在所有 agent 每次行动的系统提示词最前面生效。适合临时加入世界公告、风格约束、社会规则或实验条件。"
            onChange={(event) => setPromptDraft(event.target.value)}
          />
        </label>
        <label className="runtime-speed-row">
          <span>模拟速度</span>
          <select value={speedDraft} onChange={(event) => setSpeedDraft(event.target.value === "fast" ? "fast" : "slow")}>
            <option value="slow">慢速</option>
            <option value="fast">快速</option>
          </select>
        </label>
        <div className="runtime-prompt-settings">
          <h3>模型输入长度</h3>
          <label>
            <span>短期记忆条数</span>
            <input type="number" min="0" max="200" value={promptSettingsDraft.memory_limit} onChange={(event) => updatePromptSetting("memory_limit", Number(event.target.value))} />
          </label>
          <label>
            <span>最近事件条数</span>
            <input type="number" min="0" max="200" value={promptSettingsDraft.recent_event_limit} onChange={(event) => updatePromptSetting("recent_event_limit", Number(event.target.value))} />
          </label>
          <label>
            <span>自身行动条数</span>
            <input type="number" min="0" max="100" value={promptSettingsDraft.recent_self_event_limit} onChange={(event) => updatePromptSetting("recent_self_event_limit", Number(event.target.value))} />
          </label>
          <label>
            <span>行动编号上限</span>
            <input type="number" min="20" max="500" value={promptSettingsDraft.action_option_limit} onChange={(event) => updatePromptSetting("action_option_limit", Number(event.target.value))} />
          </label>
          <label>
            <span>入梦记忆读取</span>
            <input type="number" min="4" max="200" value={promptSettingsDraft.dream_memory_limit} onChange={(event) => updatePromptSetting("dream_memory_limit", Number(event.target.value))} />
          </label>
          <label>
            <span>梦中重要条数</span>
            <input type="number" min="0" max="40" value={promptSettingsDraft.dream_important_limit} onChange={(event) => updatePromptSetting("dream_important_limit", Number(event.target.value))} />
          </label>
          <label>
            <span>梦中背景条数</span>
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
