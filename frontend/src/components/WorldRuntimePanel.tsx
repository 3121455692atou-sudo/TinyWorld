import { useEffect, useState } from "react";
import type { AgentListItem, ImageGenerationSettings, LlmConcurrencySettings, PromptSettings, ProviderDraft, World, WorldRuntimeSettingsPayload } from "../api/types";
import { t, type UiLanguage } from "../i18n";
import { ModelPicker } from "./ModelPicker";
import { WorkflowJsonInput } from "./WorkflowJsonInput";

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

const DEFAULT_IMAGE_GENERATION_SETTINGS: ImageGenerationSettings = {
  enabled: false,
  source_mode: "narration",
  provider_type: "sdxl",
  prompt_style: "auto",
  custom_prompt_style: "",
  prompt_llm_mode: "narrator",
  prompt_llm_provider_id: "",
  prompt_llm_provider_name: "",
  prompt_llm_base_url: "",
  prompt_llm_api_key: "",
  prompt_llm_model_name: "",
  prompt_llm_system_prompt: "",
  prompt_llm_generation: { temperature: 0.35, max_tokens: 1600 },
  prompt_llm_retry_count: 2,
  prompt_llm_retry_interval_ms: 1500,
  prompt_llm_request_timeout_ms: 300000,
  prompt_llm_rpm: 0,
  auto_frequency: "normal",
  display_mode: "placeholder",
  base_url: "",
  endpoint_path: "",
  api_key: "",
  model_name: "",
  style_prompt: "",
  negative_prompt: "",
  request_template_json: "",
  width: 1024,
  height: 1024,
  steps: 28,
  cfg_scale: 7,
  sampler: "",
  seed: -1,
  workflow_json: "",
  agent_aliases: {}
};

const IMAGE_PROMPT_STYLE_VALUES: ImageGenerationSettings["prompt_style"][] = [
  "auto",
  "novelai",
  "sdxl",
  "flux",
  "pony",
  "anima",
  "danbooru",
  "illustrious",
  "stable_diffusion",
  "midjourney",
  "dalle",
  "custom",
];

const IMAGE_PROMPT_STYLE_OPTIONS: Array<{ value: ImageGenerationSettings["prompt_style"]; label: string }> = [
  { value: "auto", label: "跟随请求方式" },
  { value: "sdxl", label: "SDXL" },
  { value: "flux", label: "Flux" },
  { value: "pony", label: "Pony v6/v7" },
  { value: "anima", label: "Anima / Pony v7" },
  { value: "novelai", label: "NovelAI" },
  { value: "danbooru", label: "Danbooru" },
  { value: "illustrious", label: "Illustrious / NoobAI" },
  { value: "stable_diffusion", label: "Stable Diffusion 1.5" },
  { value: "midjourney", label: "Midjourney" },
  { value: "dalle", label: "DALL-E" },
  { value: "custom", label: "自定义" }
];

type RuntimeSectionKey = "summary" | "prompt" | "speed" | "image" | "concurrency" | "length";
const DEFAULT_RUNTIME_OPEN: Record<RuntimeSectionKey, boolean> = {
  summary: true,
  prompt: true,
  speed: true,
  image: false,
  concurrency: false,
  length: false
};

export function WorldRuntimePanel({
  world,
  agents = [],
  providers = [],
  busy,
  onSave,
  language = "zh"
}: {
  world: World;
  agents?: AgentListItem[];
  providers?: ProviderDraft[];
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
  const [imageDraft, setImageDraft] = useState<ImageGenerationSettings>(() => normalizeImageGeneration(settings.image_generation, agents));
  const [runtimeOpen, setRuntimeOpen] = useState<Record<RuntimeSectionKey, boolean>>(DEFAULT_RUNTIME_OPEN);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setPromptDraft(String(world.settings?.collective_core_prompt ?? ""));
    setSpeedDraft(world.settings?.speed === "fast" ? "fast" : "slow");
    setRequestModeDraft(world.settings?.agent_request_mode === "parallel" ? "parallel" : "serial");
    setDisplayModeDraft(world.settings?.event_display_mode === "per_agent" ? "per_agent" : "batch");
    setPromptSettingsDraft(normalizePromptSettings(world.settings?.prompt_settings));
    setConcurrencyDraft(normalizeConcurrency(world.settings?.llm_concurrency));
    setImageDraft(normalizeImageGeneration(world.settings?.image_generation, agents));
  }, [world.world_id, world.settings?.collective_core_prompt, world.settings?.speed, world.settings?.agent_request_mode, world.settings?.event_display_mode, world.settings?.prompt_settings, world.settings?.llm_concurrency, world.settings?.image_generation]);

  const worldviewName = t(String(settings.worldview_name ?? "未命名世界观"), language);
  const worldToolsetName = t(String(settings.world_toolset_name ?? settings.toolset_name ?? "未指定世界工具集"), language);
  const optionalNames = Array.isArray(settings.optional_toolset_names) ? settings.optional_toolset_names.map(String) : [];
  const survivalLabel = settings.survival_needs_enabled ? "生存需求开启" : "无吃喝生存压力";
  const providerOptions = providers.filter((provider) => provider.baseUrl || provider.name || provider.providerId);
  const promptLlmProviderId = providerOptions.some((provider) => provider.providerId === imageDraft.prompt_llm_provider_id)
    ? imageDraft.prompt_llm_provider_id
    : providerOptions[0]?.providerId ?? "";
  const promptLlmProvider = providerOptions.find((provider) => provider.providerId === promptLlmProviderId) ?? providerOptions[0];

  const save = async () => {
    setSaving(true);
    try {
      await onSave({
        collective_core_prompt: promptDraft,
        speed: speedDraft,
        prompt_settings: promptSettingsDraft,
        agent_request_mode: requestModeDraft,
        event_display_mode: requestModeDraft === "parallel" ? "batch" : displayModeDraft,
        llm_concurrency: concurrencyDraft,
        image_generation: serializeImageGeneration(imageDraft)
      });
    } finally {
      setSaving(false);
    }
  };
  const updatePromptSetting = (key: keyof PromptSettings, value: number) => {
    setPromptSettingsDraft((current) => ({ ...current, [key]: value }));
  };
  const setRuntimeSectionOpen = (key: RuntimeSectionKey, open: boolean) => {
    setRuntimeOpen((current) => ({ ...current, [key]: open }));
  };
  const updateImageDraft = (patch: Partial<ImageGenerationSettings>) => {
    setImageDraft((current) => ({ ...current, ...patch }));
  };
  const updateImageAlias = (agentId: string, value: string) => {
    setImageDraft((current) => ({
      ...current,
      agent_aliases: { ...current.agent_aliases, [agentId]: value }
    }));
  };

  return (
    <section className="panel world-runtime-panel">
      <div className="panel-heading">
        <h2>{t("世界运行设置", language)}</h2>
        <button type="button" disabled={busy || saving} onClick={save}>{saving ? t("保存中", language) : t("保存", language)}</button>
      </div>
      <div className="world-runtime-body">
        <details className="runtime-section runtime-section-summary" open={runtimeOpen.summary} onToggle={(event) => setRuntimeSectionOpen("summary", event.currentTarget.open)}>
          <summary>{t("当前世界", language)}</summary>
          <dl>
            <dt>{t("世界观", language)}</dt><dd title={worldviewName}>{worldviewName}</dd>
            <dt>{t("工具集", language)}</dt><dd title={worldToolsetName}>{worldToolsetName}</dd>
            <dt>{t("生存", language)}</dt><dd>{t(survivalLabel, language)}</dd>
            <dt>{t("可选", language)}</dt><dd title={optionalNames.map((item) => t(item, language)).join("、")}>{optionalNames.length ? optionalNames.map((item) => t(item, language)).join(language === "en" ? ", " : "、") : t("无", language)}</dd>
          </dl>
        </details>
        <details className="runtime-section runtime-section-prompt" open={runtimeOpen.prompt} onToggle={(event) => setRuntimeSectionOpen("prompt", event.currentTarget.open)}>
          <summary>{t("共享提示词", language)}</summary>
          <label>
            <span>{t("全体 Agent 共享提示词", language)}</span>
            <textarea
              className="runtime-prompt-editor"
              value={promptDraft}
              placeholder={t("这里会在所有 agent 每次行动的系统提示词最前面生效。适合临时加入世界公告、风格约束、社会规则或实验条件。", language)}
              onChange={(event) => setPromptDraft(event.target.value)}
            />
          </label>
        </details>
        <details className="runtime-section runtime-section-speed" open={runtimeOpen.speed} onToggle={(event) => setRuntimeSectionOpen("speed", event.currentTarget.open)}>
          <summary>{t("运行节奏", language)}</summary>
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
        </details>
        <details className="runtime-section runtime-section-image" open={runtimeOpen.image || imageDraft.enabled} onToggle={(event) => setRuntimeSectionOpen("image", event.currentTarget.open)}>
          <summary>{t("生图设置", language)}</summary>
          <div className="runtime-prompt-settings runtime-image-settings">
            <label className="toggle-inline">
              <input type="checkbox" checked={imageDraft.enabled} onChange={(event) => updateImageDraft({ enabled: event.target.checked })} />
              {t("启用解说生图", language)}
            </label>
            {imageDraft.enabled && (
              <>
                <label>
                  <span>{t("生图模式", language)}</span>
                  <select value={imageDraft.source_mode} onChange={(event) => updateImageDraft({ source_mode: event.target.value as ImageGenerationSettings["source_mode"] })}>
                    <option value="narration">{t("根据解说生图", language)}</option>
                    <option value="auto_summary">{t("自动总结生图", language)}</option>
                  </select>
                </label>
                {imageDraft.source_mode === "auto_summary" && (
                  <label>
                    <span>{t("自动频率", language)}</span>
                    <select value={imageDraft.auto_frequency} onChange={(event) => updateImageDraft({ auto_frequency: event.target.value as ImageGenerationSettings["auto_frequency"] })}>
                      <option value="low">{t("较少", language)}</option>
                      <option value="normal">{t("普通", language)}</option>
                      <option value="high">{t("较多", language)}</option>
                    </select>
                  </label>
                )}
                <label>
                  <span>{t("请求方式", language)}</span>
                  <select value={imageDraft.provider_type} onChange={(event) => updateImageDraft({ provider_type: event.target.value as ImageGenerationSettings["provider_type"] })}>
                    <option value="sdxl">{t("OpenAI 兼容图片 API", language)}</option>
                    <option value="anima">{t("OpenAI 兼容图片 API（Anima 旧预设）", language)}</option>
                    <option value="novelai">NovelAI</option>
                    <option value="comfyui">ComfyUI workflow / API</option>
                  </select>
                </label>
                <label>
                  <span>{t("提示词风格", language)}</span>
                  <select value={imageDraft.prompt_style} onChange={(event) => updateImageDraft({ prompt_style: event.target.value as ImageGenerationSettings["prompt_style"] })}>
                    {IMAGE_PROMPT_STYLE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{t(option.label, language)}</option>)}
                  </select>
                </label>
                {imageDraft.prompt_style === "custom" && (
                  <label className="runtime-image-wide">
                    <span>{t("自定义提示词风格", language)}</span>
                    <textarea value={imageDraft.custom_prompt_style} onChange={(event) => updateImageDraft({ custom_prompt_style: event.target.value })} />
                  </label>
                )}
                <label>
                  <span>{t("提示词 LLM", language)}</span>
                  <select value={imageDraft.prompt_llm_mode} onChange={(event) => {
                    const mode = event.target.value as ImageGenerationSettings["prompt_llm_mode"];
                    updateImageDraft(mode === "custom" ? {
                      prompt_llm_mode: mode,
                      prompt_llm_provider_id: promptLlmProvider?.providerId ?? "",
                      prompt_llm_provider_name: promptLlmProvider?.name ?? "",
                      prompt_llm_base_url: promptLlmProvider?.baseUrl ?? "",
                      prompt_llm_api_key: promptLlmProvider?.apiKey ?? "",
                      prompt_llm_retry_count: promptLlmProvider?.retryCount ?? 2,
                      prompt_llm_retry_interval_ms: promptLlmProvider?.retryIntervalMs ?? 1500,
                      prompt_llm_request_timeout_ms: promptLlmProvider?.requestTimeoutMs ?? 300000,
                      prompt_llm_rpm: promptLlmProvider?.rpm ?? 0
                    } : { prompt_llm_mode: mode });
                  }}>
                    <option value="narrator">{t("沿用解说 AI", language)}</option>
                    <option value="custom">{t("单独配置", language)}</option>
                  </select>
                </label>
                {imageDraft.prompt_llm_mode === "custom" && (
                  <>
                    <label>
                      <span>{t("提示词提供商", language)}</span>
                      <select value={promptLlmProviderId} onChange={(event) => {
                        const provider = providerOptions.find((item) => item.providerId === event.target.value) ?? providerOptions[0];
                        updateImageDraft({
                          prompt_llm_provider_id: provider?.providerId ?? "",
                          prompt_llm_provider_name: provider?.name ?? "",
                          prompt_llm_base_url: provider?.baseUrl ?? "",
                          prompt_llm_api_key: provider?.apiKey ?? "",
                          prompt_llm_model_name: "",
                          prompt_llm_retry_count: provider?.retryCount ?? 2,
                          prompt_llm_retry_interval_ms: provider?.retryIntervalMs ?? 1500,
                          prompt_llm_request_timeout_ms: provider?.requestTimeoutMs ?? 300000,
                          prompt_llm_rpm: provider?.rpm ?? 0
                        });
                      }}>
                        {providerOptions.map((provider) => <option key={provider.providerId} value={provider.providerId}>{provider.name}</option>)}
                      </select>
                    </label>
                    <label>
                      <span>{t("提示词模型", language)}</span>
                      <ModelPicker
                        value={imageDraft.prompt_llm_model_name}
                        models={promptLlmProvider?.models ?? []}
                        emptyLabel={t("使用默认提示词模型", language)}
                        searchPlaceholder={t("搜索提示词模型", language)}
                        onChange={(prompt_llm_model_name) => updateImageDraft({
                          prompt_llm_provider_id: promptLlmProvider?.providerId ?? promptLlmProviderId,
                          prompt_llm_provider_name: promptLlmProvider?.name ?? "",
                          prompt_llm_base_url: promptLlmProvider?.baseUrl ?? imageDraft.prompt_llm_base_url,
                          prompt_llm_api_key: promptLlmProvider?.apiKey ?? imageDraft.prompt_llm_api_key,
                          prompt_llm_model_name,
                          prompt_llm_retry_count: promptLlmProvider?.retryCount ?? imageDraft.prompt_llm_retry_count,
                          prompt_llm_retry_interval_ms: promptLlmProvider?.retryIntervalMs ?? imageDraft.prompt_llm_retry_interval_ms,
                          prompt_llm_request_timeout_ms: promptLlmProvider?.requestTimeoutMs ?? imageDraft.prompt_llm_request_timeout_ms,
                          prompt_llm_rpm: promptLlmProvider?.rpm ?? imageDraft.prompt_llm_rpm
                        })}
                      />
                    </label>
                    <label className="runtime-image-wide">
                      <span>{t("提示词 LLM 附加提示", language)}</span>
                      <textarea value={imageDraft.prompt_llm_system_prompt} onChange={(event) => updateImageDraft({ prompt_llm_system_prompt: event.target.value })} />
                    </label>
                  </>
                )}
                <label>
                  <span>{t("图片显示方式", language)}</span>
                  <select value={imageDraft.display_mode} onChange={(event) => updateImageDraft({ display_mode: event.target.value as ImageGenerationSettings["display_mode"] })}>
                    <option value="placeholder">{t("占位图，剧情继续显示", language)}</option>
                    <option value="wait">{t("等待图片生成后显示后续剧情", language)}</option>
                  </select>
                </label>
                <label>
                  <span>Base URL</span>
                  <input value={imageDraft.base_url} placeholder={imageDraft.provider_type === "novelai" ? "NovelAI 可留空" : "http://127.0.0.1:8188"} onChange={(event) => updateImageDraft({ base_url: event.target.value })} />
                </label>
                <label>
                  <span>{t("接口路径", language)}</span>
                  <input
                    value={imageDraft.endpoint_path}
                    placeholder={imageDraft.provider_type === "comfyui" && imageDraft.workflow_json.trim() ? t("已填 workflow JSON 时忽略，实际请求 /prompt", language) : imageDraft.provider_type === "comfyui" ? t("无 workflow 时才使用，例如 /api/generate", language) : imageDraft.provider_type === "novelai" ? "/ai/generate-image" : "/images/generations"}
                    disabled={imageDraft.provider_type === "comfyui" && Boolean(imageDraft.workflow_json.trim())}
                    onChange={(event) => updateImageDraft({ endpoint_path: event.target.value })}
                  />
                </label>
                <label>
                  <span>API Key</span>
                  <input type="password" value={imageDraft.api_key || ""} placeholder={t("留空保持现有密钥，本地服务可留空", language)} onChange={(event) => updateImageDraft({ api_key: event.target.value })} />
                </label>
                <label>
                  <span>{t("模型", language)}</span>
                  <input value={imageDraft.model_name} placeholder={imageDraft.provider_type === "novelai" ? "nai-diffusion-4-full" : t("可留空", language)} onChange={(event) => updateImageDraft({ model_name: event.target.value })} />
                </label>
                <label>
                  <span>{t("宽度", language)}</span>
                  <input type="number" min="256" max="2048" step="64" value={imageDraft.width} onChange={(event) => updateImageDraft({ width: Number(event.target.value) })} />
                </label>
                <label>
                  <span>{t("高度", language)}</span>
                  <input type="number" min="256" max="2048" step="64" value={imageDraft.height} onChange={(event) => updateImageDraft({ height: Number(event.target.value) })} />
                </label>
                <label>
                  <span>Steps</span>
                  <input type="number" min="1" max="150" value={imageDraft.steps} onChange={(event) => updateImageDraft({ steps: Number(event.target.value) })} />
                </label>
                <label>
                  <span>CFG</span>
                  <input type="number" min="1" max="30" step="0.5" value={imageDraft.cfg_scale} onChange={(event) => updateImageDraft({ cfg_scale: Number(event.target.value) })} />
                </label>
                <label>
                  <span>{t("采样器", language)}</span>
                  <input value={imageDraft.sampler} placeholder={t("可选", language)} onChange={(event) => updateImageDraft({ sampler: event.target.value })} />
                </label>
                <label>
                  <span>Seed</span>
                  <input type="number" min="-1" value={imageDraft.seed} onChange={(event) => updateImageDraft({ seed: Number(event.target.value) })} />
                </label>
                <label className="runtime-image-wide">
                  <span>{t("固定画风提示词", language)}</span>
                  <textarea value={imageDraft.style_prompt} onChange={(event) => updateImageDraft({ style_prompt: event.target.value })} />
                </label>
                <label className="runtime-image-wide">
                  <span>{t("负面提示词", language)}</span>
                  <textarea value={imageDraft.negative_prompt} onChange={(event) => updateImageDraft({ negative_prompt: event.target.value })} />
                </label>
                <label className="runtime-image-wide">
                  <span>{t("请求体模板 JSON", language)}</span>
                  <textarea
                    value={imageDraft.request_template_json}
                    placeholder={'留空使用默认字段映射。自定义 API 可填 {"prompt":"{{prompt}}","negative_prompt":"{{negative_prompt}}"}；也支持 %prompt% 和 %negative_prompt%。'}
                    onChange={(event) => updateImageDraft({ request_template_json: event.target.value })}
                  />
                </label>
                {imageDraft.provider_type === "comfyui" && (
                  <WorkflowJsonInput
                    className="runtime-image-wide"
                    label="ComfyUI workflow JSON"
                    value={imageDraft.workflow_json}
                    placeholder={'有 workflow JSON 时请求固定走 ComfyUI /prompt；只有写成占位符的节点才会被外面的宽高、steps、CFG 替换。可用 {{prompt}}、{{negative_prompt}}、{{width}}、{{height}}、{{steps}}、{{cfg_scale}}。'}
                    onChange={(workflow_json) => updateImageDraft({ workflow_json })}
                  />
                )}
                <div className="runtime-image-aliases">
                  <h3>{t("Agent 生图角色名", language)}</h3>
                  {agents.length ? agents.map((agent) => (
                    <label key={agent.agent_id}>
                      <span>{agent.display_name || agent.agent_id}</span>
                      <input value={imageDraft.agent_aliases[agent.agent_id] ?? agent.image_prompt_name ?? ""} placeholder="saki / character tag" onChange={(event) => updateImageAlias(agent.agent_id, event.target.value)} />
                    </label>
                  )) : <p className="model-count">{t("暂无 Agent。", language)}</p>}
                </div>
              </>
            )}
          </div>
        </details>
        <details className="runtime-section runtime-section-concurrency" open={runtimeOpen.concurrency} onToggle={(event) => setRuntimeSectionOpen("concurrency", event.currentTarget.open)}>
          <summary>{t("并发限制", language)}</summary>
          <div className="runtime-prompt-settings">
          <label>
            <span>{t("默认提供商并发", language)}</span>
            <input type="number" min="0" max="100000" value={concurrencyDraft.default_provider_limit} onChange={(event) => setConcurrencyDraft((current) => ({ ...current, default_provider_limit: Number(event.target.value) }))} />
          </label>
          <ProviderLimitEditor
            title={t("指定提供商并发", language)}
            providers={providerOptions}
            value={concurrencyDraft.provider_limits}
            onChange={(provider_limits) => setConcurrencyDraft((current) => ({ ...current, provider_limits }))}
          />
          <ModelLimitEditor
            title={t("指定模型并发", language)}
            providers={providerOptions}
            value={concurrencyDraft.model_limits}
            onChange={(model_limits) => setConcurrencyDraft((current) => ({ ...current, model_limits }))}
          />
          </div>
        </details>
        <details className="runtime-section runtime-section-length" open={runtimeOpen.length} onToggle={(event) => setRuntimeSectionOpen("length", event.currentTarget.open)}>
          <summary>{t("记忆设置", language)}</summary>
          <div className="runtime-prompt-settings">
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
        </details>
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

function normalizeImageGeneration(raw: unknown, agents: AgentListItem[] = []): ImageGenerationSettings {
  const data = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  const sourceMode = String(data.source_mode ?? data.sourceMode ?? DEFAULT_IMAGE_GENERATION_SETTINGS.source_mode);
  const providerType = String(data.provider_type ?? data.providerType ?? DEFAULT_IMAGE_GENERATION_SETTINGS.provider_type);
  const promptStyle = String(data.prompt_style ?? data.promptStyle ?? DEFAULT_IMAGE_GENERATION_SETTINGS.prompt_style);
  const promptLlmMode = String(data.prompt_llm_mode ?? data.promptLlmMode ?? DEFAULT_IMAGE_GENERATION_SETTINGS.prompt_llm_mode);
  const autoFrequency = String(data.auto_frequency ?? data.autoFrequency ?? DEFAULT_IMAGE_GENERATION_SETTINGS.auto_frequency);
  const displayMode = String(data.display_mode ?? data.displayMode ?? DEFAULT_IMAGE_GENERATION_SETTINGS.display_mode);
  const aliases = data.agent_aliases ?? data.agentAliases;
  const agentAliases = aliases && typeof aliases === "object"
    ? Object.fromEntries(Object.entries(aliases as Record<string, unknown>).map(([key, value]) => [key, String(value ?? "")]).filter(([, value]) => value.trim()))
    : {};
  for (const agent of agents) {
    if (!agentAliases[agent.agent_id] && agent.image_prompt_name) agentAliases[agent.agent_id] = agent.image_prompt_name;
  }
  return {
    ...DEFAULT_IMAGE_GENERATION_SETTINGS,
    enabled: Boolean(data.enabled),
    source_mode: ["narration", "auto_summary"].includes(sourceMode) ? sourceMode as ImageGenerationSettings["source_mode"] : "narration",
    provider_type: ["novelai", "comfyui", "sdxl", "anima"].includes(providerType) ? providerType as ImageGenerationSettings["provider_type"] : "sdxl",
    prompt_style: IMAGE_PROMPT_STYLE_VALUES.includes(promptStyle as ImageGenerationSettings["prompt_style"]) ? promptStyle as ImageGenerationSettings["prompt_style"] : "auto",
    custom_prompt_style: String(data.custom_prompt_style ?? data.customPromptStyle ?? ""),
    prompt_llm_mode: ["narrator", "custom"].includes(promptLlmMode) ? promptLlmMode as ImageGenerationSettings["prompt_llm_mode"] : "narrator",
    prompt_llm_provider_id: String(data.prompt_llm_provider_id ?? data.promptLlmProviderId ?? ""),
    prompt_llm_provider_name: String(data.prompt_llm_provider_name ?? data.promptLlmProviderName ?? ""),
    prompt_llm_base_url: String(data.prompt_llm_base_url ?? data.promptLlmBaseUrl ?? ""),
    prompt_llm_api_key: String(data.prompt_llm_api_key === "***" ? "" : data.prompt_llm_api_key ?? data.promptLlmApiKey ?? ""),
    prompt_llm_model_name: String(data.prompt_llm_model_name ?? data.promptLlmModelName ?? ""),
    prompt_llm_system_prompt: String(data.prompt_llm_system_prompt ?? data.promptLlmSystemPrompt ?? ""),
    prompt_llm_generation: data.prompt_llm_generation && typeof data.prompt_llm_generation === "object" ? data.prompt_llm_generation as Partial<ImageGenerationSettings["prompt_llm_generation"]> : DEFAULT_IMAGE_GENERATION_SETTINGS.prompt_llm_generation,
    prompt_llm_retry_count: numberOrDefault(data.prompt_llm_retry_count ?? data.promptLlmRetryCount, DEFAULT_IMAGE_GENERATION_SETTINGS.prompt_llm_retry_count),
    prompt_llm_retry_interval_ms: numberOrDefault(data.prompt_llm_retry_interval_ms ?? data.promptLlmRetryIntervalMs, DEFAULT_IMAGE_GENERATION_SETTINGS.prompt_llm_retry_interval_ms),
    prompt_llm_request_timeout_ms: numberOrDefault(data.prompt_llm_request_timeout_ms ?? data.promptLlmRequestTimeoutMs, DEFAULT_IMAGE_GENERATION_SETTINGS.prompt_llm_request_timeout_ms),
    prompt_llm_rpm: numberOrDefault(data.prompt_llm_rpm ?? data.promptLlmRpm, DEFAULT_IMAGE_GENERATION_SETTINGS.prompt_llm_rpm),
    auto_frequency: ["low", "normal", "high"].includes(autoFrequency) ? autoFrequency as ImageGenerationSettings["auto_frequency"] : "normal",
    display_mode: ["placeholder", "wait"].includes(displayMode) ? displayMode as ImageGenerationSettings["display_mode"] : "placeholder",
    base_url: String(data.base_url ?? data.baseUrl ?? ""),
    endpoint_path: String(data.endpoint_path ?? data.endpointPath ?? ""),
    api_key: String(data.api_key === "***" ? "" : data.api_key ?? data.apiKey ?? ""),
    model_name: String(data.model_name ?? data.modelName ?? ""),
    style_prompt: String(data.style_prompt ?? data.stylePrompt ?? ""),
    negative_prompt: String(data.negative_prompt ?? data.negativePrompt ?? ""),
    request_template_json: String(data.request_template_json ?? data.requestTemplateJson ?? ""),
    width: numberOrDefault(data.width, DEFAULT_IMAGE_GENERATION_SETTINGS.width),
    height: numberOrDefault(data.height, DEFAULT_IMAGE_GENERATION_SETTINGS.height),
    steps: numberOrDefault(data.steps, DEFAULT_IMAGE_GENERATION_SETTINGS.steps),
    cfg_scale: numberOrDefault(data.cfg_scale ?? data.cfgScale, DEFAULT_IMAGE_GENERATION_SETTINGS.cfg_scale),
    sampler: String(data.sampler ?? ""),
    seed: numberOrDefault(data.seed, DEFAULT_IMAGE_GENERATION_SETTINGS.seed),
    workflow_json: String(data.workflow_json ?? data.workflowJson ?? ""),
    agent_aliases: agentAliases
  };
}

function serializeImageGeneration(config: ImageGenerationSettings): Partial<ImageGenerationSettings> {
  return {
    enabled: config.enabled,
    source_mode: config.source_mode,
    provider_type: config.provider_type,
    prompt_style: config.prompt_style,
    custom_prompt_style: config.custom_prompt_style,
    prompt_llm_mode: config.prompt_llm_mode,
    prompt_llm_provider_id: config.prompt_llm_provider_id,
    prompt_llm_provider_name: config.prompt_llm_provider_name,
    prompt_llm_base_url: config.prompt_llm_base_url,
    prompt_llm_api_key: config.prompt_llm_api_key || undefined,
    prompt_llm_model_name: config.prompt_llm_model_name,
    prompt_llm_system_prompt: config.prompt_llm_system_prompt,
    prompt_llm_generation: config.prompt_llm_generation,
    prompt_llm_retry_count: config.prompt_llm_retry_count,
    prompt_llm_retry_interval_ms: config.prompt_llm_retry_interval_ms,
    prompt_llm_request_timeout_ms: config.prompt_llm_request_timeout_ms,
    prompt_llm_rpm: config.prompt_llm_rpm,
    auto_frequency: config.auto_frequency,
    display_mode: config.display_mode,
    base_url: config.base_url,
    endpoint_path: config.endpoint_path,
    api_key: config.api_key || undefined,
    model_name: config.model_name,
    style_prompt: config.style_prompt,
    negative_prompt: config.negative_prompt,
    request_template_json: config.request_template_json,
    width: config.width,
    height: config.height,
    steps: config.steps,
    cfg_scale: config.cfg_scale,
    sampler: config.sampler,
    seed: config.seed,
    workflow_json: config.workflow_json,
    agent_aliases: Object.fromEntries(Object.entries(config.agent_aliases).filter(([, value]) => value.trim()))
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

function providerLimitKey(provider: ProviderDraft): string {
  const baseUrl = String(provider.baseUrl || "").replace(/\/+$/, "");
  const name = String(provider.name || provider.providerId || "default").trim();
  return baseUrl ? `${baseUrl}::${name}` : name;
}

function modelLimitKey(provider: ProviderDraft, modelName: string): string {
  const baseUrl = String(provider.baseUrl || "").replace(/\/+$/, "");
  return baseUrl ? `${baseUrl}::${modelName}` : modelName;
}

function providerDisplayName(provider: ProviderDraft): string {
  return provider.name || provider.providerId || provider.baseUrl || "未命名提供商";
}

function providerByLimitKey(providers: ProviderDraft[], key: string): ProviderDraft | undefined {
  return providers.find((provider) => providerLimitKey(provider) === key || provider.name === key || provider.baseUrl.replace(/\/+$/, "") === key);
}

function providerByModelLimitKey(providers: ProviderDraft[], key: string): ProviderDraft | undefined {
  return providers.find((provider) => {
    const baseUrl = String(provider.baseUrl || "").replace(/\/+$/, "");
    return Boolean(baseUrl && key.startsWith(`${baseUrl}::`));
  });
}

function modelNameFromLimitKey(provider: ProviderDraft | undefined, key: string): string {
  if (!provider) return key;
  const baseUrl = String(provider.baseUrl || "").replace(/\/+$/, "");
  const prefix = baseUrl ? `${baseUrl}::` : "";
  return prefix && key.startsWith(prefix) ? key.slice(prefix.length) : key;
}

function ProviderLimitEditor({
  title,
  providers,
  value,
  onChange
}: {
  title: string;
  providers: ProviderDraft[];
  value: Record<string, number>;
  onChange: (value: Record<string, number>) => void;
}) {
  const rows = Object.entries(value);
  const fallbackProvider = providers[0];
  const addRow = () => {
    if (!fallbackProvider) return;
    onChange({ ...value, [providerLimitKey(fallbackProvider)]: 1 });
  };
  const updateRow = (index: number, nextKey: string, nextValue: number) => {
    const next: Record<string, number> = {};
    rows.forEach(([key, limit], rowIndex) => {
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
        <button type="button" disabled={!fallbackProvider} onClick={addRow}>+</button>
      </div>
      {rows.length ? rows.map(([key, limit], index) => {
        const selectedProvider = providerByLimitKey(providers, key) ?? fallbackProvider;
        const selectedKey = selectedProvider ? providerLimitKey(selectedProvider) : key;
        return (
        <div className="runtime-limit-row" key={`${key}-${index}`}>
          <select value={selectedKey} onChange={(event) => updateRow(index, event.target.value, limit)}>
            {providers.map((provider) => (
              <option key={provider.providerId} value={providerLimitKey(provider)}>
                {providerDisplayName(provider)}
              </option>
            ))}
            {!providerByLimitKey(providers, key) && key && <option value={key}>旧配置: {key}</option>}
          </select>
          <input type="number" min="1" max="100000" value={limit} onChange={(event) => updateRow(index, key, Number(event.target.value))} />
          <button type="button" onClick={() => removeRow(index)}>-</button>
        </div>
      );}) : <p className="model-count">未指定时使用默认提供商并发。</p>}
    </div>
  );
}

function ModelLimitEditor({
  title,
  providers,
  value,
  onChange
}: {
  title: string;
  providers: ProviderDraft[];
  value: Record<string, number>;
  onChange: (value: Record<string, number>) => void;
}) {
  const rows = Object.entries(value);
  const fallbackProvider = providers[0];
  const fallbackModel = fallbackProvider?.models?.[0] ?? "";
  const addRow = () => {
    if (!fallbackProvider || !fallbackModel) return;
    onChange({ ...value, [modelLimitKey(fallbackProvider, fallbackModel)]: 1 });
  };
  const updateRow = (index: number, nextKey: string, nextValue: number) => {
    const next: Record<string, number> = {};
    rows.forEach(([key, limit], rowIndex) => {
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
        <button type="button" disabled={!fallbackProvider || !fallbackModel} onClick={addRow}>+</button>
      </div>
      {rows.length ? rows.map(([key, limit], index) => {
        const selectedProvider = providerByModelLimitKey(providers, key) ?? fallbackProvider;
        const providerModels = selectedProvider?.models?.map(String).filter(Boolean) ?? [];
        const selectedModel = modelNameFromLimitKey(selectedProvider, key);
        const modelOptions = providerModels.includes(selectedModel) ? providerModels : selectedModel ? [selectedModel, ...providerModels] : providerModels;
        return (
          <div className="runtime-limit-row runtime-model-limit-row" key={`${key}-${index}`}>
            <select value={selectedProvider?.providerId ?? ""} onChange={(event) => {
              const provider = providers.find((item) => item.providerId === event.target.value) ?? providers[0];
              const modelName = provider?.models?.[0] ?? "";
              if (provider && modelName) updateRow(index, modelLimitKey(provider, modelName), limit);
            }}>
              {providers.map((provider) => (
                <option key={provider.providerId} value={provider.providerId}>
                  {providerDisplayName(provider)}
                </option>
              ))}
            </select>
            <select value={selectedModel} onChange={(event) => {
              if (selectedProvider) updateRow(index, modelLimitKey(selectedProvider, event.target.value), limit);
            }}>
              {modelOptions.length ? modelOptions.map((modelName) => <option key={modelName} value={modelName}>{modelName}</option>) : <option value="">该提供商未拉取模型</option>}
            </select>
            <input type="number" min="1" max="100000" value={limit} onChange={(event) => updateRow(index, key, Number(event.target.value))} />
            <button type="button" onClick={() => removeRow(index)}>-</button>
          </div>
        );
      }) : <p className="model-count">未指定时按模型默认并发运行。</p>}
    </div>
  );
}
