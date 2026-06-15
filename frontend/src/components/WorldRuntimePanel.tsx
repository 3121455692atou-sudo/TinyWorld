import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, BookOpen, Cpu, Gauge, Image, Layers3, MessageSquareText, Sparkles, Users } from "lucide-react";
import type { AgentListItem, ImageGenerationSettings, LlmConcurrencySettings, ModelUsageEntry, PromptSettings, ProviderDraft, World, WorldRuntimeSettingsPayload } from "../api/types";
import { t, type UiLanguage } from "../i18n";
import { ModelPicker } from "./ModelPicker";
import { WorkflowJsonInput } from "./WorkflowJsonInput";
import { configHistoryForKind, upsertConfigHistory } from "../configHistory";

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
  model_options: [],
  image_retry_count: 0,
  request_timeout_seconds: 300,
  comfyui_timeout_seconds: 0,
  use_agent_appearance: true,
  reference_avatar_images: false,
  reference_standing_images: false,
  style_prompt: "",
  negative_prompt: "",
  request_template_json: "",
  custom_headers_json: "",
  nai_action: "generate",
  nai_image_format: "png",
  nai_n_samples: 1,
  nai_uc_preset: 0,
  nai_quality_toggle: true,
  nai_params_version: 3,
  nai_cfg_rescale: 0,
  nai_sm: false,
  nai_sm_dyn: false,
  nai_dynamic_thresholding: false,
  nai_reference_strength: 0.45,
  nai_reference_information_extracted: 1,
  nai_strength: 0.35,
  nai_noise: 0,
  nai_add_original_image: false,
  nai_params_json: "",
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

const NOVELAI_MODEL_OPTIONS = [
  "nai-diffusion-4-5-full",
  "nai-diffusion-4-5-curated",
  "nai-diffusion-4-full",
  "nai-diffusion-4-curated-preview",
  "nai-diffusion-3"
];

const NOVELAI_SAMPLER_OPTIONS = [
  "k_euler_ancestral",
  "k_euler",
  "k_dpmpp_2s_ancestral",
  "k_dpmpp_2m",
  "k_dpmpp_sde",
  "k_dpmpp_2m_sde",
  "ddim"
];

const NOVELAI_RESOLUTION_OPTIONS = [
  { value: "832x1216", label: "832 x 1216 竖图" },
  { value: "1216x832", label: "1216 x 832 横图" },
  { value: "1024x1024", label: "1024 x 1024 方图" },
  { value: "1024x1536", label: "1024 x 1536 大竖图" },
  { value: "1536x1024", label: "1536 x 1024 大横图" },
  { value: "1472x1472", label: "1472 x 1472 大方图" }
];

const DEFAULT_NOVELAI_PATCH: Partial<ImageGenerationSettings> = {
  provider_type: "novelai",
  prompt_style: "novelai",
  base_url: "",
  endpoint_path: "/ai/generate-image",
  model_name: "nai-diffusion-4-5-full",
  width: 832,
  height: 1216,
  sampler: "k_euler_ancestral",
  steps: 28,
  cfg_scale: 5.5
};

type RuntimeSectionKey = "summary" | "models" | "prompt" | "narrator" | "speed" | "batch" | "image" | "concurrency" | "length";
type RuntimeBatchMode = "" | "llm_retry" | "tts";
type AgentBatchUpdate = { agentId: string; payload: Record<string, unknown> };
type BatchLlmRuntimeDraft = {
  retryCount: number;
  retryIntervalMs: number;
  requestTimeoutMs: number;
  rpm: number;
};
type BatchTtsDraft = {
  enabled: boolean;
  mode: "gptsovits" | "openai" | "mimo" | "qwen_dashscope";
  provider: string;
  baseUrl: string;
  endpointPath: string;
  apiKey: string;
  model: string;
  voice: string;
  responseFormat: string;
  languageType: string;
  instructions: string;
  batchSize: number;
};
const DEFAULT_RUNTIME_TAB: RuntimeSectionKey = "summary";
const DEFAULT_BATCH_LLM_RUNTIME: BatchLlmRuntimeDraft = {
  retryCount: 2,
  retryIntervalMs: 1500,
  requestTimeoutMs: 300000,
  rpm: 0
};
const DEFAULT_BATCH_TTS: BatchTtsDraft = {
  enabled: false,
  mode: "gptsovits",
  provider: "GPT-SoVITS",
  baseUrl: "",
  endpointPath: "/tts",
  apiKey: "",
  model: "",
  voice: "",
  responseFormat: "wav",
  languageType: "Chinese",
  instructions: "",
  batchSize: 1
};

export function WorldRuntimePanel({
  world,
  agents = [],
  providers = [],
  modelUsageEntries = [],
  busy,
  onSave,
  pullingImageModels = false,
  onPullImageModels,
  onBatchUpdateAgentLlm,
  onBatchUpdateAgentProfile,
  language = "zh"
}: {
  world: World;
  agents?: AgentListItem[];
  providers?: ProviderDraft[];
  modelUsageEntries?: ModelUsageEntry[];
  busy: boolean;
  onSave: (payload: WorldRuntimeSettingsPayload) => Promise<void>;
  pullingImageModels?: boolean;
  onPullImageModels?: (payload: { baseUrl: string; apiKey?: string }) => Promise<string[] | void> | string[] | void;
  onBatchUpdateAgentLlm?: (updates: AgentBatchUpdate[]) => Promise<void>;
  onBatchUpdateAgentProfile?: (updates: AgentBatchUpdate[]) => Promise<void>;
  language?: UiLanguage;
}) {
  const settings = world.settings ?? {};
  const [promptDraft, setPromptDraft] = useState(String(settings.collective_core_prompt ?? ""));
  const [speedDraft, setSpeedDraft] = useState<"slow" | "fast">(settings.speed === "fast" ? "fast" : "slow");
  const [requestModeDraft, setRequestModeDraft] = useState<"serial" | "parallel">(settings.agent_request_mode === "parallel" ? "parallel" : "serial");
  const [displayModeDraft, setDisplayModeDraft] = useState<"batch" | "per_agent">(settings.event_display_mode === "per_agent" ? "per_agent" : "batch");
  const [narratorFrequencyDraft, setNarratorFrequencyDraft] = useState<"low" | "normal" | "high">(() => normalizeFrequency(settings.narrator_frequency ?? (settings.narrator_config as Record<string, unknown> | undefined)?.auto_frequency));
  const [promptSettingsDraft, setPromptSettingsDraft] = useState<PromptSettings>(() => normalizePromptSettings(settings.prompt_settings));
  const [concurrencyDraft, setConcurrencyDraft] = useState<LlmConcurrencySettings>(() => normalizeConcurrency(settings.llm_concurrency));
  const [imageDraft, setImageDraft] = useState<ImageGenerationSettings>(() => normalizeImageGeneration(settings.image_generation, agents));
  const [imageHistory, setImageHistory] = useState(() => configHistoryForKind("imageGeneration"));
  const [activeRuntimeTab, setActiveRuntimeTab] = useState<RuntimeSectionKey>(DEFAULT_RUNTIME_TAB);
  const [batchMode, setBatchMode] = useState<RuntimeBatchMode>("");
  const [batchAgentIds, setBatchAgentIds] = useState<string[]>([]);
  const [batchLlmRuntimeDraft, setBatchLlmRuntimeDraft] = useState<BatchLlmRuntimeDraft>(DEFAULT_BATCH_LLM_RUNTIME);
  const [batchTtsDraft, setBatchTtsDraft] = useState<BatchTtsDraft>(DEFAULT_BATCH_TTS);
  const [batchSaving, setBatchSaving] = useState(false);
  const [saving, setSaving] = useState(false);
  const imageDraftDirtyRef = useRef(false);
  const imageDraftWorldIdRef = useRef(world.world_id);
  const agentsSignature = useMemo(
    () => agents.map((agent) => `${agent.agent_id}:${agent.display_name}:${agent.image_prompt_name ?? ""}`).join("|"),
    [agents]
  );

  useEffect(() => {
    const sameWorld = imageDraftWorldIdRef.current === world.world_id;
    if (!sameWorld) {
      imageDraftWorldIdRef.current = world.world_id;
      imageDraftDirtyRef.current = false;
    }
    setPromptDraft(String(world.settings?.collective_core_prompt ?? ""));
    setSpeedDraft(world.settings?.speed === "fast" ? "fast" : "slow");
    setRequestModeDraft(world.settings?.agent_request_mode === "parallel" ? "parallel" : "serial");
    setDisplayModeDraft(world.settings?.event_display_mode === "per_agent" ? "per_agent" : "batch");
    setNarratorFrequencyDraft(normalizeFrequency(world.settings?.narrator_frequency ?? (world.settings?.narrator_config as Record<string, unknown> | undefined)?.auto_frequency));
    setPromptSettingsDraft(normalizePromptSettings(world.settings?.prompt_settings));
    setConcurrencyDraft(normalizeConcurrency(world.settings?.llm_concurrency));
    if (!imageDraftDirtyRef.current) {
      setImageDraft((current) => {
        const incoming = world.settings?.image_generation && typeof world.settings.image_generation === "object"
          ? world.settings.image_generation as Partial<ImageGenerationSettings> & Record<string, unknown>
          : {};
        const merged = { ...current, ...incoming };
        if (sameWorld && current.image_retry_count !== DEFAULT_IMAGE_GENERATION_SETTINGS.image_retry_count && Number(incoming.image_retry_count ?? DEFAULT_IMAGE_GENERATION_SETTINGS.image_retry_count) === DEFAULT_IMAGE_GENERATION_SETTINGS.image_retry_count) {
          merged.image_retry_count = current.image_retry_count;
        }
        return normalizeImageGeneration(sameWorld ? merged : incoming, agents);
      });
    } else {
      setImageDraft((current) => {
        const nextAliases = { ...current.agent_aliases };
        let changed = false;
        for (const agent of agents) {
          if (!nextAliases[agent.agent_id] && agent.image_prompt_name) {
            nextAliases[agent.agent_id] = agent.image_prompt_name;
            changed = true;
          }
        }
        return changed ? { ...current, agent_aliases: nextAliases } : current;
      });
    }
  }, [world.world_id, world.settings?.collective_core_prompt, world.settings?.speed, world.settings?.agent_request_mode, world.settings?.event_display_mode, world.settings?.narrator_frequency, world.settings?.narrator_config, world.settings?.prompt_settings, world.settings?.llm_concurrency, world.settings?.image_generation, agentsSignature]);

  const worldviewName = t(String(settings.worldview_name ?? "未命名世界观"), language);
  const worldToolsetName = t(String(settings.world_toolset_name ?? settings.toolset_name ?? "未指定世界工具集"), language);
  const optionalNames = Array.isArray(settings.optional_toolset_names) ? settings.optional_toolset_names.map(String) : [];
  const survivalLabel = settings.survival_needs_enabled ? "生存需求开启" : "无吃喝生存压力";
  const narratorConfig = settings.narrator_config && typeof settings.narrator_config === "object" ? settings.narrator_config as Record<string, unknown> : {};
  const narratorEnabled = Boolean(narratorConfig.enabled ?? Object.keys(narratorConfig).length);
  const narratorProviderName = String(narratorConfig.provider_name ?? narratorConfig.providerName ?? narratorConfig.provider_id ?? narratorConfig.providerId ?? "");
  const narratorModelName = String(narratorConfig.model_name ?? narratorConfig.modelName ?? "");
  const narratorPrompt = String(narratorConfig.system_prompt ?? narratorConfig.systemPrompt ?? "");
  const providerOptions = providers.filter((provider) => provider.baseUrl || provider.name || provider.providerId);
  const promptLlmProviderId = providerOptions.some((provider) => provider.providerId === imageDraft.prompt_llm_provider_id)
    ? imageDraft.prompt_llm_provider_id
    : providerOptions[0]?.providerId ?? "";
  const promptLlmProvider = providerOptions.find((provider) => provider.providerId === promptLlmProviderId) ?? providerOptions[0];
  const batchSelectedAgentIds = useMemo(() => new Set(batchAgentIds), [batchAgentIds]);
  const batchTargetAgents = batchAgentIds.length ? agents.filter((agent) => batchSelectedAgentIds.has(agent.agent_id)) : agents;
  const batchTargetText = batchAgentIds.length ? `已选 ${batchTargetAgents.length} 人` : `全部 ${agents.length} 人`;
  const imageProviderType = imageDraft.provider_type === "anima" ? "sdxl" : imageDraft.provider_type;
  const isOpenAiImageProvider = imageProviderType === "sdxl";
  const isNovelAiImageProvider = imageProviderType === "novelai";
  const isComfyUiImageProvider = imageProviderType === "comfyui";
  const showImageBaseUrl = !isNovelAiImageProvider;
  const showImageEndpointPath = !isNovelAiImageProvider;
  const showImageSamplingFields = isNovelAiImageProvider || isComfyUiImageProvider;
  const novelAiResolutionValue = `${imageDraft.width}x${imageDraft.height}`;

  const save = async () => {
    setSaving(true);
    try {
      await onSave({
        collective_core_prompt: promptDraft,
        speed: speedDraft,
        narrator_frequency: narratorFrequencyDraft,
        prompt_settings: promptSettingsDraft,
        agent_request_mode: requestModeDraft,
        event_display_mode: requestModeDraft === "parallel" ? "batch" : displayModeDraft,
        llm_concurrency: concurrencyDraft,
        image_generation: serializeImageGeneration(imageDraft)
      });
      imageDraftDirtyRef.current = false;
    } finally {
      setSaving(false);
    }
  };
  const updatePromptSetting = (key: keyof PromptSettings, value: number) => {
    setPromptSettingsDraft((current) => ({ ...current, [key]: value }));
  };
  const keepDetailsOpen = (event: React.SyntheticEvent<HTMLDetailsElement>) => {
    if (!event.currentTarget.open) event.currentTarget.open = true;
  };
  const updateImageDraft = (patch: Partial<ImageGenerationSettings>) => {
    imageDraftDirtyRef.current = true;
    setImageDraft((current) => ({ ...current, ...patch }));
  };
  const toggleBatchAgent = (agentId: string, checked: boolean) => {
    setBatchAgentIds((current) => {
      const next = new Set(current);
      if (checked) next.add(agentId);
      else next.delete(agentId);
      return Array.from(next);
    });
  };
  const setBatchTtsMode = (mode: BatchTtsDraft["mode"]) => {
    const patch: Partial<BatchTtsDraft> = mode === "qwen_dashscope"
      ? { provider: "Qwen TTS", baseUrl: "https://dashscope-intl.aliyuncs.com/api/v1", endpointPath: "/services/aigc/multimodal-generation/generation", model: "qwen3-tts-flash", voice: "Cherry", responseFormat: "wav", languageType: "Chinese" }
      : mode === "mimo"
        ? { provider: "Mimo TTS", endpointPath: "/audio/speech", responseFormat: "mp3" }
        : mode === "openai"
          ? { provider: "OpenAI 兼容 TTS", endpointPath: "/audio/speech", model: "tts-1", voice: "alloy", responseFormat: "mp3" }
          : { provider: "GPT-SoVITS", baseUrl: "", endpointPath: "/tts", responseFormat: "wav", languageType: "Chinese" };
    setBatchTtsDraft((current) => ({ ...current, ...patch, mode }));
  };
  const applyBatchSettings = async () => {
    if (!batchMode || !batchTargetAgents.length) return;
    setBatchSaving(true);
    try {
      if (batchMode === "llm_retry") {
        const payload = {
          retry_count: Math.max(0, Math.round(Number(batchLlmRuntimeDraft.retryCount) || 0)),
          retry_interval_ms: Math.max(0, Math.round(Number(batchLlmRuntimeDraft.retryIntervalMs) || 0)),
          request_timeout_ms: Math.max(0, Math.round(Number(batchLlmRuntimeDraft.requestTimeoutMs) || 0)),
          rpm: Math.max(0, Math.round(Number(batchLlmRuntimeDraft.rpm) || 0))
        };
        await onBatchUpdateAgentLlm?.(batchTargetAgents.map((agent) => ({ agentId: agent.agent_id, payload })));
      } else if (batchMode === "tts") {
        const ttsConfig: Record<string, unknown> = {
          enabled: batchTtsDraft.enabled,
          mode: batchTtsDraft.mode,
          provider: batchTtsDraft.provider.trim(),
          base_url: batchTtsDraft.baseUrl.trim(),
          endpoint_path: batchTtsDraft.endpointPath.trim(),
          model: batchTtsDraft.model.trim(),
          voice: batchTtsDraft.voice.trim(),
          response_format: batchTtsDraft.responseFormat.trim(),
          language_type: batchTtsDraft.languageType.trim(),
          instructions: batchTtsDraft.instructions.trim(),
          batch_size: Math.max(1, Math.min(32, Math.round(Number(batchTtsDraft.batchSize) || 1)))
        };
        if (batchTtsDraft.apiKey.trim()) ttsConfig.api_key = batchTtsDraft.apiKey.trim();
        await onBatchUpdateAgentProfile?.(batchTargetAgents.map((agent) => ({ agentId: agent.agent_id, payload: { tts_config: ttsConfig } })));
        setBatchTtsDraft((current) => ({ ...current, apiKey: "" }));
      }
    } finally {
      setBatchSaving(false);
    }
  };
  const saveImageDraftHistory = () => {
    upsertConfigHistory("imageGeneration", `${imageDraft.provider_type} · ${imageDraft.model_name || "默认模型"} · ${new Date().toLocaleString()}`, serializeImageGeneration(imageDraft) as Record<string, unknown>);
    setImageHistory(configHistoryForKind("imageGeneration"));
  };
  const applyImageHistory = (id: string) => {
    const item = imageHistory.find((entry) => entry.id === id);
    if (!item) return;
    imageDraftDirtyRef.current = true;
    setImageDraft(normalizeImageGeneration(item.data, agents));
  };
  const updateImageAlias = (agentId: string, value: string) => {
    imageDraftDirtyRef.current = true;
    setImageDraft((current) => ({
      ...current,
      agent_aliases: { ...current.agent_aliases, [agentId]: value }
    }));
  };
  const updateNovelAiResolution = (value: string) => {
    const [width, height] = value.split("x").map((part) => Number(part));
    if (!Number.isFinite(width) || !Number.isFinite(height)) return;
    updateImageDraft({ width, height });
  };
  const pullImageModelOptions = async () => {
    if (!onPullImageModels) return;
    const models = await onPullImageModels({ baseUrl: imageDraft.base_url, apiKey: imageDraft.api_key });
    const normalizedModels = Array.isArray(models) ? models.map(String).filter(Boolean) : [];
    if (!normalizedModels.length) return;
    imageDraftDirtyRef.current = true;
    setImageDraft((current) => ({
      ...current,
      model_options: normalizedModels,
      model_name: current.model_name || normalizedModels[0] || ""
    }));
  };

  return (
    <section className="panel world-runtime-panel">
      <div className="panel-heading">
        <h2>{t("世界运行设置", language)}</h2>
        <button type="button" disabled={busy || saving} onClick={save}>{saving ? t("保存中", language) : t("保存", language)}</button>
      </div>
      <div className="world-runtime-body">
        <nav className="runtime-icon-tabs" aria-label={t("世界运行设置分类", language)}>
          {runtimeTabItems(language).map((tab) => {
            const active = activeRuntimeTab === tab.key;
            return (
              <button
                key={tab.key}
                type="button"
                className={`runtime-icon-tab runtime-section-${tab.key}${active ? " active" : ""}`}
                title={tab.title}
                aria-label={tab.title}
                aria-pressed={active}
                onClick={() => setActiveRuntimeTab(tab.key)}
              >
                {tab.icon}
              </button>
            );
          })}
        </nav>
        {activeRuntimeTab === "summary" && <details className="runtime-section runtime-section-summary runtime-tab-panel" open onToggle={keepDetailsOpen}>
          <summary>{t("当前世界", language)}</summary>
          <dl>
            <dt>{t("世界观", language)}</dt><dd title={worldviewName}>{worldviewName}</dd>
            <dt>{t("工具集", language)}</dt><dd title={worldToolsetName}>{worldToolsetName}</dd>
            <dt>{t("生存", language)}</dt><dd>{t(survivalLabel, language)}</dd>
            <dt>{t("可选", language)}</dt><dd title={optionalNames.map((item) => t(item, language)).join("、")}>{optionalNames.length ? optionalNames.map((item) => t(item, language)).join(language === "en" ? ", " : "、") : t("无", language)}</dd>
          </dl>
        </details>}
        {activeRuntimeTab === "models" && <details className="runtime-section runtime-section-models runtime-tab-panel" open onToggle={keepDetailsOpen}>
          <summary>{t("模型使用", language)}</summary>
          <div className="runtime-model-usage-list">
            {modelUsageEntries.length ? modelUsageEntries.map((entry) => {
              const providerLabel = [entry.provider_name, entry.model_name].filter(Boolean).join(" · ") || t("未配置模型", language);
              const baseUrlLabel = entry.base_url || t("无 Base URL", language);
              const lastRunLabel = modelUsageLastRunLabel(entry, language);
              const warning = entry.warning || entry.last_llm_error;
              return (
                <div className={`runtime-model-usage-row ${warning ? "has-warning" : ""}`} key={`${entry.source_type}:${entry.source_id}`}>
                  <div>
                    <strong title={entry.label}>{entry.label}</strong>
                    <span title={entry.note || modelUsageSourceLabel(entry, language)}>{entry.note || modelUsageSourceLabel(entry, language)}</span>
                  </div>
                  <div>
                    <b title={providerLabel}>{providerLabel}</b>
                    <span title={baseUrlLabel}>{baseUrlLabel}</span>
                    {lastRunLabel && <span title={lastRunLabel}>{lastRunLabel}</span>}
                  </div>
                  {warning && <em title={warning}>{warning}</em>}
                </div>
              );
            }) : <p className="model-count">{t("暂无模型使用数据。", language)}</p>}
          </div>
        </details>}
        {activeRuntimeTab === "prompt" && <details className="runtime-section runtime-section-prompt runtime-tab-panel" open onToggle={keepDetailsOpen}>
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
        </details>}
        {activeRuntimeTab === "narrator" && <details className="runtime-section runtime-section-narrator runtime-tab-panel" open onToggle={keepDetailsOpen}>
          <summary>{t("解说 Agent", language)}</summary>
          <div className="runtime-prompt-settings runtime-narrator-settings">
            <label>
              <span>{t("解说频率", language)}</span>
              <select value={narratorFrequencyDraft} onChange={(event) => setNarratorFrequencyDraft(event.target.value as typeof narratorFrequencyDraft)}>
                <option value="low">{t("较少", language)}</option>
                <option value="normal">{t("普通", language)}</option>
                <option value="high">{t("较多", language)}</option>
              </select>
            </label>
            <label>
              <span>{t("启用状态", language)}</span>
              <input value={narratorEnabled ? t("已启用", language) : t("未启用", language)} disabled readOnly />
            </label>
            <label>
              <span>{t("提供商", language)}</span>
              <input value={narratorProviderName || t("未配置", language)} disabled readOnly />
            </label>
            <label>
              <span>{t("模型", language)}</span>
              <input value={narratorModelName || t("未配置", language)} disabled readOnly />
            </label>
            <label className="runtime-image-wide">
              <span>{t("额外提示词", language)}</span>
              <textarea value={narratorPrompt} disabled readOnly placeholder={t("未填写", language)} />
            </label>
            <p className="runtime-image-wide runtime-narrator-note">
              {t("当前后端只支持在运行中保存解说频率；解说 Agent 的提供商、模型和提示词需要在创建世界时配置，或升级后端接口后修改。", language)}
            </p>
          </div>
        </details>}
        {activeRuntimeTab === "speed" && <details className="runtime-section runtime-section-speed runtime-tab-panel" open onToggle={keepDetailsOpen}>
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
        </details>}
        {activeRuntimeTab === "batch" && <details className="runtime-section runtime-section-batch runtime-tab-panel" open onToggle={keepDetailsOpen}>
          <summary>{t("批量配置", language)}</summary>
          <div className="runtime-batch-settings">
            <div className="runtime-batch-mode-row">
              <button type="button" className={batchMode === "llm_retry" ? "active" : ""} onClick={() => setBatchMode((current) => current === "llm_retry" ? "" : "llm_retry")}>
                {t("模型重试参数", language)}
              </button>
              <button type="button" className={batchMode === "tts" ? "active" : ""} onClick={() => setBatchMode((current) => current === "tts" ? "" : "tts")}>
                {t("TTS 接口", language)}
              </button>
            </div>
            {!batchMode && <p className="runtime-batch-note">{t("先选择要批量配置的内容，再选择角色；不选择角色时默认应用到全部 Agent。", language)}</p>}
            {batchMode && (
              <>
                {batchMode === "llm_retry" && (
                  <div className="runtime-prompt-settings runtime-batch-form">
                    <label>
                      <span>{t("重试次数", language)}</span>
                      <input type="number" min="0" max="100000" value={batchLlmRuntimeDraft.retryCount} onChange={(event) => setBatchLlmRuntimeDraft((current) => ({ ...current, retryCount: Number(event.target.value) }))} />
                    </label>
                    <label>
                      <span>{t("重试间隔 ms", language)}</span>
                      <input type="number" min="0" max="21600000" step="100" value={batchLlmRuntimeDraft.retryIntervalMs} onChange={(event) => setBatchLlmRuntimeDraft((current) => ({ ...current, retryIntervalMs: Number(event.target.value) }))} />
                    </label>
                    <label>
                      <span>{t("请求超时 ms", language)}</span>
                      <input type="number" min="0" max="86400000" step="1000" value={batchLlmRuntimeDraft.requestTimeoutMs} onChange={(event) => setBatchLlmRuntimeDraft((current) => ({ ...current, requestTimeoutMs: Number(event.target.value) }))} />
                    </label>
                    <label>
                      <span>RPM</span>
                      <input type="number" min="0" max="100000" value={batchLlmRuntimeDraft.rpm} onChange={(event) => setBatchLlmRuntimeDraft((current) => ({ ...current, rpm: Number(event.target.value) }))} />
                    </label>
                  </div>
                )}
                {batchMode === "tts" && (
                  <div className="runtime-prompt-settings runtime-batch-form">
                    <label className="toggle-inline">
                      <input type="checkbox" checked={batchTtsDraft.enabled} onChange={(event) => setBatchTtsDraft((current) => ({ ...current, enabled: event.target.checked }))} />
                      {t("启用 TTS", language)}
                    </label>
                    <label>
                      <span>{t("类型", language)}</span>
                      <select value={batchTtsDraft.mode} onChange={(event) => setBatchTtsMode(event.target.value as BatchTtsDraft["mode"])}>
                        <option value="gptsovits">GPT-SoVITS</option>
                        <option value="openai">OpenAI 兼容</option>
                        <option value="mimo">Mimo TTS</option>
                        <option value="qwen_dashscope">Qwen / DashScope</option>
                      </select>
                    </label>
                    <label>
                      <span>{t("提供商", language)}</span>
                      <input value={batchTtsDraft.provider} onChange={(event) => setBatchTtsDraft((current) => ({ ...current, provider: event.target.value }))} />
                    </label>
                    <label>
                      <span>Base URL</span>
                      <input value={batchTtsDraft.baseUrl} onChange={(event) => setBatchTtsDraft((current) => ({ ...current, baseUrl: event.target.value }))} />
                    </label>
                    <label>
                      <span>{t("接口路径", language)}</span>
                      <input value={batchTtsDraft.endpointPath} onChange={(event) => setBatchTtsDraft((current) => ({ ...current, endpointPath: event.target.value }))} />
                    </label>
                    <label>
                      <span>API Key</span>
                      <input type="password" value={batchTtsDraft.apiKey} placeholder={t("留空不修改密钥", language)} onChange={(event) => setBatchTtsDraft((current) => ({ ...current, apiKey: event.target.value }))} />
                    </label>
                    <label>
                      <span>{t("模型", language)}</span>
                      <input value={batchTtsDraft.model} onChange={(event) => setBatchTtsDraft((current) => ({ ...current, model: event.target.value }))} />
                    </label>
                    <label>
                      <span>{t("音色", language)}</span>
                      <input value={batchTtsDraft.voice} onChange={(event) => setBatchTtsDraft((current) => ({ ...current, voice: event.target.value }))} />
                    </label>
                    <label>
                      <span>{t("格式", language)}</span>
                      <input value={batchTtsDraft.responseFormat} onChange={(event) => setBatchTtsDraft((current) => ({ ...current, responseFormat: event.target.value }))} />
                    </label>
                    <label>
                      <span>{t("语言", language)}</span>
                      <input value={batchTtsDraft.languageType} onChange={(event) => setBatchTtsDraft((current) => ({ ...current, languageType: event.target.value }))} />
                    </label>
                    <label>
                      <span>{t("批量大小", language)}</span>
                      <input type="number" min="1" max="32" value={batchTtsDraft.batchSize} onChange={(event) => setBatchTtsDraft((current) => ({ ...current, batchSize: Number(event.target.value) }))} />
                    </label>
                    <label className="runtime-image-wide">
                      <span>{t("指令", language)}</span>
                      <textarea value={batchTtsDraft.instructions} onChange={(event) => setBatchTtsDraft((current) => ({ ...current, instructions: event.target.value }))} />
                    </label>
                  </div>
                )}
                <details className="runtime-batch-agent-picker">
                  <summary>{t("作用角色", language)} · {batchTargetText}</summary>
                  <div className="runtime-batch-agent-grid">
                    {agents.map((agent) => (
                      <label key={agent.agent_id} title={agent.display_name}>
                        <input
                          type="checkbox"
                          checked={batchSelectedAgentIds.has(agent.agent_id)}
                          onChange={(event) => toggleBatchAgent(agent.agent_id, event.target.checked)}
                        />
                        <span>{agent.display_name}</span>
                      </label>
                    ))}
                  </div>
                  <div className="runtime-batch-agent-actions">
                    <button type="button" onClick={() => setBatchAgentIds(agents.map((agent) => agent.agent_id))}>{t("全选", language)}</button>
                    <button type="button" onClick={() => setBatchAgentIds([])}>{t("清空选择", language)}</button>
                    <span>{t("不选择角色时应用到全部 Agent", language)}</span>
                  </div>
                </details>
                <div className="runtime-batch-actions">
                  <button
                    type="button"
                    disabled={batchSaving || busy || !batchTargetAgents.length || (batchMode === "llm_retry" ? !onBatchUpdateAgentLlm : !onBatchUpdateAgentProfile)}
                    onClick={applyBatchSettings}
                  >
                    {batchSaving ? t("应用中", language) : `${t("应用到", language)} ${batchTargetText}`}
                  </button>
                </div>
              </>
            )}
          </div>
        </details>}
        {activeRuntimeTab === "image" && <details className="runtime-section runtime-section-image runtime-tab-panel" open onToggle={keepDetailsOpen}>
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
                  <select value={imageProviderType} onChange={(event) => {
                    const provider_type = event.target.value as ImageGenerationSettings["provider_type"];
                    updateImageDraft(provider_type === "novelai"
                      ? DEFAULT_NOVELAI_PATCH
                      : { provider_type, prompt_style: imageDraft.prompt_style });
                  }}>
                    <option value="sdxl">{t("OpenAI 兼容图片 API", language)}</option>
                    <option value="novelai">NovelAI</option>
                    <option value="comfyui">ComfyUI workflow / API</option>
                  </select>
                </label>
                <label>
                  <span>{t("历史配置", language)}</span>
                  <select value="" onChange={(event) => applyImageHistory(event.target.value)}>
                    <option value="">{imageHistory.length ? t("选择生图历史配置", language) : t("暂无历史配置", language)}</option>
                    {imageHistory.map((item) => <option key={item.id} value={item.id}>{item.pinned ? "★ " : ""}{item.name}</option>)}
                  </select>
                </label>
                <button type="button" className="image-model-fetch-button" onClick={saveImageDraftHistory}>
                  {t("存为历史配置", language)}
                </button>
                <button type="button" className="image-model-fetch-button" disabled={busy || saving} onClick={save}>
                  {saving ? t("保存中", language) : t("保存到当前世界", language)}
                </button>
                {isNovelAiImageProvider ? (
                  <label>
                    <span>{t("提示词风格", language)}</span>
                    <input value="NovelAI 标签" disabled />
                  </label>
                ) : (
                  <label>
                    <span>{t("提示词风格", language)}</span>
                    <select value={imageDraft.prompt_style} onChange={(event) => updateImageDraft({ prompt_style: event.target.value as ImageGenerationSettings["prompt_style"] })}>
                      {IMAGE_PROMPT_STYLE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{t(option.label, language)}</option>)}
                    </select>
                  </label>
                )}
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
                {showImageBaseUrl && (
                  <label>
                    <span>Base URL</span>
                    <input value={imageDraft.base_url} placeholder={isComfyUiImageProvider ? "http://127.0.0.1:8188" : "https://example.com/v1"} onChange={(event) => updateImageDraft({ base_url: event.target.value })} />
                  </label>
                )}
                {showImageEndpointPath && (
                  <label>
                    <span>{t("接口路径", language)}</span>
                    <input
                      value={imageDraft.endpoint_path}
                      placeholder={isComfyUiImageProvider && imageDraft.workflow_json.trim() ? t("已填 workflow JSON 时忽略，实际请求 /prompt", language) : isComfyUiImageProvider ? t("无 workflow 时才使用，例如 /api/generate", language) : "/images/generations"}
                      disabled={isComfyUiImageProvider && Boolean(imageDraft.workflow_json.trim())}
                      onChange={(event) => updateImageDraft({ endpoint_path: event.target.value })}
                    />
                  </label>
                )}
                <label>
                  <span>API Key</span>
                  <input
                    type="password"
                    value={imageDraft.api_key === "***" ? "" : imageDraft.api_key || ""}
                    placeholder={imageDraft.api_key === "***" ? t("已保存密钥；输入新密钥可替换", language) : t("留空保持现有密钥，本地服务可留空", language)}
                    onChange={(event) => updateImageDraft({ api_key: event.target.value })}
                  />
                </label>
                <label>
                  <span>{t("模型", language)}</span>
                  {isNovelAiImageProvider ? (
                    <select value={imageDraft.model_name || "nai-diffusion-4-5-full"} onChange={(event) => updateImageDraft({ model_name: event.target.value })}>
                      {NOVELAI_MODEL_OPTIONS.map((model) => <option key={model} value={model}>{model}</option>)}
                    </select>
                  ) : (
                    <ModelPicker
                      value={imageDraft.model_name}
                      models={imageDraft.model_options ?? []}
                      emptyLabel={t("不指定模型", language)}
                      manualPlaceholder={t("模型名，可留空", language)}
                      searchPlaceholder={t("搜索图片模型", language)}
                      onChange={(model_name) => updateImageDraft({ model_name })}
                    />
                  )}
                </label>
                {isOpenAiImageProvider && (
                  <button type="button" className="image-model-fetch-button" disabled={pullingImageModels || !imageDraft.base_url.trim()} onClick={pullImageModelOptions}>
                    {pullingImageModels ? t("拉取中", language) : t("拉取图片模型", language)}
                  </button>
                )}
                <label>
                  <span>{t("失败重试次数", language)}</span>
                  <input type="number" min="0" max="100" value={imageDraft.image_retry_count} onChange={(event) => updateImageDraft({ image_retry_count: Number(event.target.value) })} />
                </label>
                <label>
                  <span>{t("请求超时秒", language)}</span>
                  <input type="number" min="0" max="86400" value={imageDraft.request_timeout_seconds} onChange={(event) => updateImageDraft({ request_timeout_seconds: Number(event.target.value) })} />
                </label>
                {isComfyUiImageProvider && (
                  <label>
                    <span>{t("ComfyUI 等待秒", language)}</span>
                    <input type="number" min="0" max="86400" value={imageDraft.comfyui_timeout_seconds} onChange={(event) => updateImageDraft({ comfyui_timeout_seconds: Number(event.target.value) })} />
                  </label>
                )}
                {isNovelAiImageProvider ? (
                  <label>
                    <span>{t("尺寸", language)}</span>
                    <select value={NOVELAI_RESOLUTION_OPTIONS.some((option) => option.value === novelAiResolutionValue) ? novelAiResolutionValue : "832x1216"} onChange={(event) => updateNovelAiResolution(event.target.value)}>
                      {NOVELAI_RESOLUTION_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                    </select>
                  </label>
                ) : (
                  <>
                    <label>
                      <span>{t("宽度", language)}</span>
                      <input type="number" min="256" max="2048" step="64" value={imageDraft.width} onChange={(event) => updateImageDraft({ width: Number(event.target.value) })} />
                    </label>
                    <label>
                      <span>{t("高度", language)}</span>
                      <input type="number" min="256" max="2048" step="64" value={imageDraft.height} onChange={(event) => updateImageDraft({ height: Number(event.target.value) })} />
                    </label>
                  </>
                )}
                <label className="toggle-inline">
                  <input
                    type="checkbox"
                    checked={imageDraft.use_agent_appearance}
                    onChange={(event) => updateImageDraft({ use_agent_appearance: event.target.checked })}
                  />
                  {t("参考角色外貌文本", language)}
                </label>
                <label className="toggle-inline">
                  <input
                    type="checkbox"
                    checked={imageDraft.reference_avatar_images}
                    onChange={(event) => updateImageDraft({ reference_avatar_images: event.target.checked })}
                  />
                  {t("参考头像图", language)}
                </label>
                <label className="toggle-inline">
                  <input
                    type="checkbox"
                    checked={imageDraft.reference_standing_images}
                    onChange={(event) => updateImageDraft({ reference_standing_images: event.target.checked })}
                  />
                  {t("参考立绘图", language)}
                </label>
                <details className="runtime-image-advanced runtime-image-wide">
                  <summary>{t("高级请求参数", language)}</summary>
                  <div className="runtime-image-advanced-grid">
                {showImageSamplingFields && (
                  <>
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
                      {isNovelAiImageProvider ? (
                        <select value={imageDraft.sampler || "k_euler_ancestral"} onChange={(event) => updateImageDraft({ sampler: event.target.value })}>
                          {NOVELAI_SAMPLER_OPTIONS.map((sampler) => <option key={sampler} value={sampler}>{sampler}</option>)}
                        </select>
                      ) : (
                        <input value={imageDraft.sampler} placeholder={t("可选", language)} onChange={(event) => updateImageDraft({ sampler: event.target.value })} />
                      )}
                    </label>
                    <label>
                      <span>Seed</span>
                      <input type="number" min="-1" value={imageDraft.seed} onChange={(event) => updateImageDraft({ seed: Number(event.target.value) })} />
                    </label>
                  </>
                )}
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
                <label className="runtime-image-wide">
                  <span>{t("固定请求头 JSON", language)}</span>
                  <textarea
                    value={imageDraft.custom_headers_json}
                    placeholder={'例如 {"x-correlation-id":"tlw-local-test"}。API Key 会自动写入 Authorization。'}
                    onChange={(event) => updateImageDraft({ custom_headers_json: event.target.value })}
                  />
                </label>
                {isNovelAiImageProvider && (
                  <>
                    <label>
                      <span>NAI Action</span>
                      <select value={imageDraft.nai_action} onChange={(event) => updateImageDraft({ nai_action: event.target.value as ImageGenerationSettings["nai_action"] })}>
                        <option value="generate">generate</option>
                        <option value="img2img">img2img</option>
                        <option value="infill">infill</option>
                      </select>
                    </label>
                    <label>
                      <span>NAI Format</span>
                      <select value={imageDraft.nai_image_format} onChange={(event) => updateImageDraft({ nai_image_format: event.target.value as ImageGenerationSettings["nai_image_format"] })}>
                        <option value="png">png</option>
                        <option value="webp">webp</option>
                      </select>
                    </label>
                    <label>
                      <span>NAI samples</span>
                      <input type="number" min="1" max="4" value={imageDraft.nai_n_samples} onChange={(event) => updateImageDraft({ nai_n_samples: Number(event.target.value) })} />
                    </label>
                    <label>
                      <span>ucPreset</span>
                      <input type="number" min="0" max="10" value={imageDraft.nai_uc_preset} onChange={(event) => updateImageDraft({ nai_uc_preset: Number(event.target.value) })} />
                    </label>
                    <label>
                      <span>cfg_rescale</span>
                      <input type="number" min="0" max="20" step="0.1" value={imageDraft.nai_cfg_rescale} onChange={(event) => updateImageDraft({ nai_cfg_rescale: Number(event.target.value) })} />
                    </label>
                    <label>
                      <span>params_version</span>
                      <input type="number" min="1" max="10" value={imageDraft.nai_params_version} onChange={(event) => updateImageDraft({ nai_params_version: Number(event.target.value) })} />
                    </label>
                    <label>
                      <span>参考强度</span>
                      <input type="number" min="0" max="1" step="0.05" value={imageDraft.nai_reference_strength} onChange={(event) => updateImageDraft({ nai_reference_strength: Number(event.target.value) })} />
                    </label>
                    <label>
                      <span>参考提取量</span>
                      <input type="number" min="0" max="1" step="0.05" value={imageDraft.nai_reference_information_extracted} onChange={(event) => updateImageDraft({ nai_reference_information_extracted: Number(event.target.value) })} />
                    </label>
                    <label>
                      <span>img2img strength</span>
                      <input type="number" min="0" max="1" step="0.05" value={imageDraft.nai_strength} onChange={(event) => updateImageDraft({ nai_strength: Number(event.target.value) })} />
                    </label>
                    <label>
                      <span>img2img noise</span>
                      <input type="number" min="0" max="1" step="0.05" value={imageDraft.nai_noise} onChange={(event) => updateImageDraft({ nai_noise: Number(event.target.value) })} />
                    </label>
                    <label className="toggle-inline">
                      <input type="checkbox" checked={imageDraft.nai_quality_toggle} onChange={(event) => updateImageDraft({ nai_quality_toggle: event.target.checked })} />
                      NAI qualityToggle
                    </label>
                    <label className="toggle-inline">
                      <input type="checkbox" checked={imageDraft.nai_sm_dyn} onChange={(event) => updateImageDraft({ nai_sm_dyn: event.target.checked })} />
                      sm_dyn
                    </label>
                    <label className="toggle-inline">
                      <input type="checkbox" checked={imageDraft.nai_dynamic_thresholding} onChange={(event) => updateImageDraft({ nai_dynamic_thresholding: event.target.checked })} />
                      dynamic_thresholding
                    </label>
                    <label className="toggle-inline">
                      <input type="checkbox" checked={imageDraft.nai_add_original_image} onChange={(event) => updateImageDraft({ nai_add_original_image: event.target.checked })} />
                      add_original_image
                    </label>
                    <label className="runtime-image-wide">
                      <span>NAI parameters JSON</span>
                      <textarea
                        value={imageDraft.nai_params_json}
                        placeholder={'直接合并到 NovelAI parameters，例如 {"noise_schedule":"native","skip_cfg_above_sigma":19}。同名字段会覆盖上面的表单值。'}
                        onChange={(event) => updateImageDraft({ nai_params_json: event.target.value })}
                      />
                    </label>
                  </>
                )}
                {isComfyUiImageProvider && (
                  <WorkflowJsonInput
                    className="runtime-image-wide"
                    label="ComfyUI workflow JSON"
                    value={imageDraft.workflow_json}
                    placeholder={'有 workflow JSON 时请求固定走 ComfyUI /prompt；只有写成占位符的节点才会被外面的宽高、steps、CFG 替换。可用 {{prompt}}、{{negative_prompt}}、{{width}}、{{height}}、{{steps}}、{{cfg_scale}}。'}
                    onChange={(workflow_json) => updateImageDraft({ workflow_json })}
                  />
                )}
                  </div>
                </details>
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
        </details>}
        {activeRuntimeTab === "concurrency" && <details className="runtime-section runtime-section-concurrency runtime-tab-panel" open onToggle={keepDetailsOpen}>
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
        </details>}
        {activeRuntimeTab === "length" && <details className="runtime-section runtime-section-length runtime-tab-panel" open onToggle={keepDetailsOpen}>
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
        </details>}
      </div>
    </section>
  );
}

function runtimeTabItems(language: UiLanguage): Array<{ key: RuntimeSectionKey; title: string; icon: React.ReactNode }> {
  return [
    { key: "summary", title: t("当前世界", language), icon: <Activity size={18} /> },
    { key: "models", title: t("模型使用", language), icon: <Cpu size={18} /> },
    { key: "prompt", title: t("共享提示词", language), icon: <MessageSquareText size={18} /> },
    { key: "narrator", title: t("解说 Agent", language), icon: <Sparkles size={18} /> },
    { key: "speed", title: t("运行节奏", language), icon: <Gauge size={18} /> },
    { key: "batch", title: t("批量配置", language), icon: <Users size={18} /> },
    { key: "image", title: t("生图设置", language), icon: <Image size={18} /> },
    { key: "concurrency", title: t("并发限制", language), icon: <Layers3 size={18} /> },
    { key: "length", title: t("记忆设置", language), icon: <BookOpen size={18} /> },
  ];
}

function modelUsageSourceLabel(entry: ModelUsageEntry, language: UiLanguage): string {
  if (entry.source_type === "agent") return t("居民 Agent", language);
  if (entry.source_type === "narrator") return t("解说 Agent", language);
  if (entry.source_type === "image_prompt") return t("生图提示词 LLM", language);
  if (entry.source_type === "image_provider") return t("生图接口模型", language);
  if (entry.source_type === "baby_model") return t("宝宝 Agent 模型", language);
  return entry.source_type || t("模型配置", language);
}

function modelUsageLastRunLabel(entry: ModelUsageEntry, language: UiLanguage): string {
  const parts: string[] = [];
  if (entry.last_llm_phase) parts.push(entry.last_llm_phase);
  if (typeof entry.last_llm_world_time === "number") parts.push(`${t("世界时", language)} ${entry.last_llm_world_time}`);
  if (typeof entry.last_llm_latency_ms === "number") parts.push(`${Math.round(entry.last_llm_latency_ms)}ms`);
  const tokenLabel = tokenUsageLabel(entry.last_llm_token_usage);
  if (tokenLabel) parts.push(tokenLabel);
  if (entry.llm_consecutive_failures > 0) parts.push(`${entry.llm_consecutive_failures} ${t("次连续失败", language)}`);
  return parts.join(" · ");
}

function tokenUsageLabel(raw: Record<string, unknown>): string {
  const input = usageNumber(raw, ["prompt_tokens", "input_tokens"]);
  const output = usageNumber(raw, ["completion_tokens", "output_tokens"]);
  const total = usageNumber(raw, ["total_tokens", "total"]);
  if (total !== null) return `tokens ${total}`;
  if (input !== null || output !== null) return `tokens ${(input ?? 0) + (output ?? 0)}`;
  return "";
}

function usageNumber(raw: Record<string, unknown>, keys: string[]): number | null {
  for (const key of keys) {
    const value = raw[key];
    const parsed = typeof value === "number" ? value : typeof value === "string" ? Number(value) : Number.NaN;
    if (Number.isFinite(parsed)) return Math.max(0, Math.round(parsed));
  }
  return null;
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

function normalizeStringList(raw: unknown, limit: number): string[] {
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  const result: string[] = [];
  for (const item of raw.slice(0, limit)) {
    const value = String(item ?? "").trim();
    if (!value || seen.has(value)) continue;
    seen.add(value);
    result.push(value);
  }
  return result;
}

function normalizeFrequency(raw: unknown): "low" | "normal" | "high" {
  const value = String(raw ?? "").trim();
  return value === "low" || value === "high" ? value : "normal";
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
  const normalizedProviderType = providerType === "anima" ? "sdxl" : providerType;
  const normalizedPromptStyle = normalizedProviderType === "novelai" ? "novelai" : providerType === "anima" && promptStyle === "auto" ? "anima" : promptStyle;
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
    provider_type: ["novelai", "comfyui", "sdxl"].includes(normalizedProviderType) ? normalizedProviderType as ImageGenerationSettings["provider_type"] : "sdxl",
    prompt_style: IMAGE_PROMPT_STYLE_VALUES.includes(normalizedPromptStyle as ImageGenerationSettings["prompt_style"]) ? normalizedPromptStyle as ImageGenerationSettings["prompt_style"] : "auto",
    custom_prompt_style: String(data.custom_prompt_style ?? data.customPromptStyle ?? ""),
    prompt_llm_mode: ["narrator", "custom"].includes(promptLlmMode) ? promptLlmMode as ImageGenerationSettings["prompt_llm_mode"] : "narrator",
    prompt_llm_provider_id: String(data.prompt_llm_provider_id ?? data.promptLlmProviderId ?? ""),
    prompt_llm_provider_name: String(data.prompt_llm_provider_name ?? data.promptLlmProviderName ?? ""),
    prompt_llm_base_url: String(data.prompt_llm_base_url ?? data.promptLlmBaseUrl ?? ""),
    prompt_llm_api_key: String(data.prompt_llm_api_key === "***" ? "***" : data.prompt_llm_api_key ?? data.promptLlmApiKey ?? ""),
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
    api_key: String(data.api_key === "***" ? "***" : data.api_key ?? data.apiKey ?? ""),
    model_name: String(data.model_name ?? data.modelName ?? ""),
    model_options: normalizeStringList(data.model_options ?? data.modelOptions, 500),
    image_retry_count: numberOrDefault(data.image_retry_count ?? data.imageRetryCount, DEFAULT_IMAGE_GENERATION_SETTINGS.image_retry_count),
    request_timeout_seconds: numberOrDefault(data.request_timeout_seconds ?? data.requestTimeoutSeconds, DEFAULT_IMAGE_GENERATION_SETTINGS.request_timeout_seconds),
    comfyui_timeout_seconds: numberOrDefault(data.comfyui_timeout_seconds ?? data.comfyuiTimeoutSeconds, DEFAULT_IMAGE_GENERATION_SETTINGS.comfyui_timeout_seconds),
    use_agent_appearance: data.use_agent_appearance ?? data.useAgentAppearance ?? true ? true : false,
    reference_avatar_images: Boolean(data.reference_avatar_images ?? data.referenceAvatarImages),
    reference_standing_images: Boolean(data.reference_standing_images ?? data.referenceStandingImages),
    style_prompt: String(data.style_prompt ?? data.stylePrompt ?? ""),
    negative_prompt: String(data.negative_prompt ?? data.negativePrompt ?? ""),
    request_template_json: String(data.request_template_json ?? data.requestTemplateJson ?? ""),
    custom_headers_json: String(data.custom_headers_json ?? data.customHeadersJson ?? ""),
    nai_action: ["generate", "img2img", "infill"].includes(String(data.nai_action ?? data.naiAction)) ? String(data.nai_action ?? data.naiAction) as ImageGenerationSettings["nai_action"] : "generate",
    nai_image_format: ["png", "webp"].includes(String(data.nai_image_format ?? data.naiImageFormat)) ? String(data.nai_image_format ?? data.naiImageFormat) as ImageGenerationSettings["nai_image_format"] : "png",
    nai_n_samples: numberOrDefault(data.nai_n_samples ?? data.naiNSamples, DEFAULT_IMAGE_GENERATION_SETTINGS.nai_n_samples),
    nai_uc_preset: numberOrDefault(data.nai_uc_preset ?? data.naiUcPreset, DEFAULT_IMAGE_GENERATION_SETTINGS.nai_uc_preset),
    nai_quality_toggle: data.nai_quality_toggle ?? data.naiQualityToggle ?? true ? true : false,
    nai_params_version: numberOrDefault(data.nai_params_version ?? data.naiParamsVersion, DEFAULT_IMAGE_GENERATION_SETTINGS.nai_params_version),
    nai_cfg_rescale: numberOrDefault(data.nai_cfg_rescale ?? data.naiCfgRescale, DEFAULT_IMAGE_GENERATION_SETTINGS.nai_cfg_rescale),
    nai_sm: Boolean(data.nai_sm ?? data.naiSm),
    nai_sm_dyn: Boolean(data.nai_sm_dyn ?? data.naiSmDyn),
    nai_dynamic_thresholding: Boolean(data.nai_dynamic_thresholding ?? data.naiDynamicThresholding),
    nai_reference_strength: numberOrDefault(data.nai_reference_strength ?? data.naiReferenceStrength, DEFAULT_IMAGE_GENERATION_SETTINGS.nai_reference_strength),
    nai_reference_information_extracted: numberOrDefault(data.nai_reference_information_extracted ?? data.naiReferenceInformationExtracted, DEFAULT_IMAGE_GENERATION_SETTINGS.nai_reference_information_extracted),
    nai_strength: numberOrDefault(data.nai_strength ?? data.naiStrength, DEFAULT_IMAGE_GENERATION_SETTINGS.nai_strength),
    nai_noise: numberOrDefault(data.nai_noise ?? data.naiNoise, DEFAULT_IMAGE_GENERATION_SETTINGS.nai_noise),
    nai_add_original_image: Boolean(data.nai_add_original_image ?? data.naiAddOriginalImage),
    nai_params_json: String(data.nai_params_json ?? data.naiParamsJson ?? ""),
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
    model_options: config.model_options,
    image_retry_count: config.image_retry_count,
    request_timeout_seconds: config.request_timeout_seconds,
    comfyui_timeout_seconds: config.comfyui_timeout_seconds,
    use_agent_appearance: config.use_agent_appearance,
    reference_avatar_images: config.reference_avatar_images,
    reference_standing_images: config.reference_standing_images,
    style_prompt: config.style_prompt,
    negative_prompt: config.negative_prompt,
    request_template_json: config.request_template_json,
    custom_headers_json: config.custom_headers_json,
    nai_action: config.nai_action,
    nai_image_format: config.nai_image_format,
    nai_n_samples: config.nai_n_samples,
    nai_uc_preset: config.nai_uc_preset,
    nai_quality_toggle: config.nai_quality_toggle,
    nai_params_version: config.nai_params_version,
    nai_cfg_rescale: config.nai_cfg_rescale,
    nai_sm: config.nai_sm,
    nai_sm_dyn: config.nai_sm_dyn,
    nai_dynamic_thresholding: config.nai_dynamic_thresholding,
    nai_reference_strength: config.nai_reference_strength,
    nai_reference_information_extracted: config.nai_reference_information_extracted,
    nai_strength: config.nai_strength,
    nai_noise: config.nai_noise,
    nai_add_original_image: config.nai_add_original_image,
    nai_params_json: config.nai_params_json,
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
