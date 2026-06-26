import { Download, Plus, RefreshCw, Trash2, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import type { AgentArchiveFieldOptions, AgentConfigDraft, AgentKnowledgeMode, BabyModelDraft, ImageGenerationSettings, LlmGenerationSettings, NarratorConfigDraft, ProviderDraft, TtsConfigDraft, WerewolfRole, WerewolfRoleAssignmentDraft, World } from "../api/types";
import { configHistoryForKind, upsertConfigHistory } from "../configHistory";
import { t } from "../i18n";
import { FileDropZone } from "./FileDropZone";
import { ModelPicker } from "./ModelPicker";
import { WorkflowJsonInput } from "./WorkflowJsonInput";

const DEFAULT_ARCHIVE_OPTIONS: AgentArchiveFieldOptions = {
  names: true,
  imagePrompts: true,
  prompts: true,
  appearances: true,
  avatars: true,
  standingImages: true,
  collectivePrompt: true,
  providerModels: true,
  toolModes: true,
  agentToolsets: true,
  traits: true,
  knowledge: true,
  narrator: true,
  imageGeneration: true,
  babyModels: true,
  providers: true,
  tts: true,
  secrets: false
};

const ARCHIVE_OPTION_LABELS: Array<[keyof AgentArchiveFieldOptions, string]> = [
  ["names", "名字"],
  ["imagePrompts", "生图名"],
  ["prompts", "提示词"],
  ["appearances", "外貌"],
  ["avatars", "头像"],
  ["standingImages", "立绘"],
  ["collectivePrompt", "集体提示词"],
  ["providerModels", "模型"],
  ["toolModes", "工具模式"],
  ["agentToolsets", "特殊工具集"],
  ["traits", "属性"],
  ["knowledge", "初始认识"],
  ["narrator", "解说"],
  ["imageGeneration", "生图配置"],
  ["babyModels", "宝宝模型"],
  ["providers", "提供商"],
  ["tts", "TTS"],
  ["secrets", "密钥/API Key"]
];

const IMAGE_PROMPT_STYLE_OPTIONS: Array<{ value: ImageGenerationSettings["prompt_style"]; label: string }> = [
  { value: "auto", label: "跟随请求方式" },
  { value: "sdxl", label: "SDXL 通用" },
  { value: "flux", label: "Flux 自然语言" },
  { value: "pony", label: "Pony v6/v7" },
  { value: "anima", label: "Anima / Pony v7" },
  { value: "novelai", label: "NovelAI 标签" },
  { value: "danbooru", label: "Danbooru 标签" },
  { value: "illustrious", label: "Illustrious / NoobAI" },
  { value: "stable_diffusion", label: "Stable Diffusion 1.5" },
  { value: "midjourney", label: "Midjourney 风格" },
  { value: "dalle", label: "DALL-E 自然语言" },
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

const AGENT_TRAIT_MODE_OPTIONS: Array<{ value: AgentConfigDraft["traitMode"]; label: string }> = [
  { value: "inherit", label: "跟随世界默认" },
  { value: "agent", label: "Agent 自己加点" },
  { value: "random", label: "随机加点" },
  { value: "player", label: "玩家加点" }
];

const WEREWOLF_WORLDVIEW_ID = "werewolf_game_worldview";
const DEFAULT_WEREWOLF_AUTO_ROLES: WerewolfRole[] = ["villager", "werewolf", "seer", "coroner", "guard"];
const WEREWOLF_ROLE_OPTIONS: Array<{ value: WerewolfRole; label: string; minPlayers: number; core?: boolean }> = [
  { value: "villager", label: "平民", minPlayers: 1, core: true },
  { value: "werewolf", label: "狼人", minPlayers: 3, core: true },
  { value: "seer", label: "预言家", minPlayers: 3 },
  { value: "coroner", label: "验尸官", minPlayers: 4 },
  { value: "guard", label: "守卫", minPlayers: 5 },
  { value: "witch", label: "女巫", minPlayers: 6 },
  { value: "hunter", label: "猎人", minPlayers: 6 },
  { value: "medium", label: "灵媒", minPlayers: 7 },
  { value: "idiot", label: "白痴", minPlayers: 8 }
];

type RandomModelEntry = {
  id: string;
  providerId: string;
  modelName: string;
};

type RandomModelList = {
  id: string;
  name: string;
  entries: RandomModelEntry[];
};

type BulkRuntimeDraft = {
  retryCount: number;
  retryIntervalMs: number;
  requestTimeoutMs: number;
  rpm: number;
};

const DEFAULT_BULK_RUNTIME: BulkRuntimeDraft = {
  retryCount: 2,
  retryIntervalMs: 1500,
  requestTimeoutMs: 300000,
  rpm: 0
};

const RANDOM_MODEL_LISTS_STORAGE_KEY = "tinyworld_random_model_lists_v1";
const DEFAULT_LLM_GENERATION: LlmGenerationSettings = {
  stream: false,
  temperature: 0.7,
  top_p: 1,
  max_tokens: 0,
  presence_penalty: 0,
  frequency_penalty: 0
};

function normalizeLlmGeneration(raw: Partial<LlmGenerationSettings> | undefined | null): LlmGenerationSettings {
  const data = raw ?? {};
  const numberInRange = (value: unknown, min: number, max: number, fallback: number) => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.max(min, Math.min(max, parsed));
  };
  return {
    stream: Boolean(data.stream),
    temperature: numberInRange(data.temperature, 0, 2, DEFAULT_LLM_GENERATION.temperature),
    top_p: numberInRange(data.top_p, 0, 1, DEFAULT_LLM_GENERATION.top_p),
    max_tokens: Math.round(numberInRange(data.max_tokens, 0, 200000, DEFAULT_LLM_GENERATION.max_tokens)),
    presence_penalty: numberInRange(data.presence_penalty, -2, 2, DEFAULT_LLM_GENERATION.presence_penalty),
    frequency_penalty: numberInRange(data.frequency_penalty, -2, 2, DEFAULT_LLM_GENERATION.frequency_penalty)
  };
}


function makeLocalId(prefix: string): string {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function normalizeRandomModelLists(raw: unknown): RandomModelList[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item, index) => {
    const record = item && typeof item === "object" ? item as Record<string, unknown> : {};
    const entries = Array.isArray(record.entries) ? record.entries : [];
    return {
      id: String(record.id || makeLocalId("rml")),
      name: String(record.name || `随机模型列表 ${index + 1}`),
      entries: entries.map((entry, entryIndex) => {
        const entryRecord = entry && typeof entry === "object" ? entry as Record<string, unknown> : {};
        return {
          id: String(entryRecord.id || makeLocalId(`rme_${entryIndex}`)),
          providerId: String(entryRecord.providerId || entryRecord.provider_id || ""),
          modelName: String(entryRecord.modelName || entryRecord.model_name || "")
        };
      }).filter((entry) => entry.providerId || entry.modelName)
    };
  }).filter((item) => item.id && item.name);
}

function loadRandomModelLists(): RandomModelList[] {
  if (typeof window === "undefined") return [];
  try {
    return normalizeRandomModelLists(JSON.parse(window.localStorage.getItem(RANDOM_MODEL_LISTS_STORAGE_KEY) || "[]"));
  } catch {
    return [];
  }
}

function normalizeAgentTraitMode(value: unknown): AgentConfigDraft["traitMode"] {
  return ["inherit", "agent", "random", "player"].includes(String(value)) ? String(value) as AgentConfigDraft["traitMode"] : "inherit";
}

function normalizeAgentKnowledgeMode(value: unknown): AgentKnowledgeMode {
  return ["all", "none", "custom"].includes(String(value)) ? String(value) as AgentKnowledgeMode : "none";
}

function defaultTtsConfig(): TtsConfigDraft {
  return {
    enabled: false,
    provider: "",
    mode: "gptsovits",
    baseUrl: "",
    endpointPath: "/tts",
    apiKey: "",
    model: "",
    voice: "",
    responseFormat: "wav",
    languageType: "Chinese",
    instructions: "",
    refAudioPath: "",
    promptText: "",
    promptLang: "zh",
    textLang: "zh",
    textSplitMethod: "cut5",
    batchSize: 1
  };
}

function normalizeTtsConfig(raw: unknown): TtsConfigDraft {
  const fallback = defaultTtsConfig();
  if (!raw || typeof raw !== "object") return fallback;
  const item = raw as Partial<TtsConfigDraft> & Record<string, unknown>;
  const mode = ["openai", "mimo", "qwen_dashscope", "gptsovits"].includes(String(item.mode)) ? item.mode as TtsConfigDraft["mode"] : "gptsovits";
  const defaultEndpoint = mode === "qwen_dashscope" ? "/services/aigc/multimodal-generation/generation" : mode === "gptsovits" ? "/tts" : "/audio/speech";
  const defaultFormat = mode === "gptsovits" || mode === "qwen_dashscope" ? "wav" : "mp3";
  return {
    enabled: Boolean(item.enabled),
    provider: String(item.provider ?? ""),
    mode,
    baseUrl: String(item.baseUrl ?? item.base_url ?? ""),
    endpointPath: String(item.endpointPath ?? item.endpoint_path ?? defaultEndpoint),
    apiKey: String(item.apiKey ?? item.api_key ?? ""),
    model: String(item.model ?? ""),
    voice: String(item.voice ?? ""),
    responseFormat: String(item.responseFormat ?? item.response_format ?? defaultFormat),
    languageType: String(item.languageType ?? item.language_type ?? "Chinese"),
    instructions: String(item.instructions ?? ""),
    refAudioPath: String(item.refAudioPath ?? item.ref_audio_path ?? ""),
    promptText: String(item.promptText ?? item.prompt_text ?? ""),
    promptLang: String(item.promptLang ?? item.prompt_lang ?? "zh"),
    textLang: String(item.textLang ?? item.text_lang ?? "zh"),
    textSplitMethod: String(item.textSplitMethod ?? item.text_split_method ?? "cut5"),
    batchSize: Number.isFinite(Number(item.batchSize ?? item.batch_size)) ? Math.max(1, Math.min(32, Number(item.batchSize ?? item.batch_size))) : 1
  };
}

function ttsDefaultsForMode(mode: TtsConfigDraft["mode"]): Partial<TtsConfigDraft> {
  if (mode === "qwen_dashscope") {
    return {
      provider: "Qwen TTS",
      baseUrl: "https://dashscope-intl.aliyuncs.com/api/v1",
      endpointPath: "/services/aigc/multimodal-generation/generation",
      model: "qwen3-tts-flash",
      voice: "Cherry",
      responseFormat: "wav",
      languageType: "Chinese"
    };
  }
  if (mode === "mimo") {
    return {
      provider: "Mimo TTS",
      endpointPath: "/audio/speech",
      responseFormat: "mp3"
    };
  }
  if (mode === "openai") {
    return {
      provider: "OpenAI 兼容 TTS",
      endpointPath: "/audio/speech",
      model: "tts-1",
      voice: "alloy",
      responseFormat: "mp3"
    };
  }
  return {
    provider: "GPT-SoVITS",
    baseUrl: "",
    endpointPath: "/tts",
    responseFormat: "wav",
    textLang: "zh",
    promptLang: "zh",
    textSplitMethod: "cut5"
  };
}

export function ProviderConfigPanel({
  agentCount,
  allowBirth,
  traitMode,
  traitBudget,
  llmGeneration,
  collectiveCorePrompt,
  providers,
  agentSpecialToolsets,
  narratorConfig,
  imageGeneration,
  babyModelConfigs,
  agentConfigs,
  worldviewId,
  werewolfEnabled = false,
  werewolfRoleAssignment,
  reusableWorlds = [],
  pullingProviderId,
  pullingImageModels = false,
  setupMode = "expert",
  language = "zh",
  onProvidersChange,
  onCollectiveCorePromptChange,
  onLlmGenerationChange,
  onNarratorConfigChange,
  onImageGenerationChange,
  onBabyModelConfigsChange,
  onAgentConfigsChange,
  onWerewolfRoleAssignmentChange,
  onPullModels,
  onPullImageModels,
  onExportAgentArchive,
  onImportAgentArchive,
  onReuseWorldConfig
}: {
  agentCount: number;
  allowBirth: boolean;
  traitMode: string;
  traitBudget: number;
  llmGeneration: LlmGenerationSettings;
  collectiveCorePrompt: string;
  providers: ProviderDraft[];
  agentSpecialToolsets: Array<{ toolset_id: string; name: string; description: string }>;
  narratorConfig: NarratorConfigDraft;
  imageGeneration: ImageGenerationSettings;
  babyModelConfigs: BabyModelDraft[];
  agentConfigs: AgentConfigDraft[];
  worldviewId?: string;
  werewolfEnabled?: boolean;
  werewolfRoleAssignment?: WerewolfRoleAssignmentDraft;
  reusableWorlds?: World[];
  pullingProviderId: string | null;
  pullingImageModels?: boolean;
  setupMode?: "beginner" | "expert";
  language?: "zh" | "en";
  onProvidersChange: (providers: ProviderDraft[]) => void;
  onCollectiveCorePromptChange: (value: string) => void;
  onLlmGenerationChange: (value: LlmGenerationSettings) => void;
  onNarratorConfigChange: (config: NarratorConfigDraft) => void;
  onImageGenerationChange: (config: ImageGenerationSettings) => void;
  onBabyModelConfigsChange: (configs: BabyModelDraft[]) => void;
  onAgentConfigsChange: (configs: AgentConfigDraft[]) => void;
  onWerewolfRoleAssignmentChange?: (config: WerewolfRoleAssignmentDraft) => void;
  onPullModels: (providerId: string, override?: { baseUrl?: string; apiKey?: string }) => void | Promise<string[] | void>;
  onPullImageModels?: (payload: { baseUrl: string; apiKey?: string }) => Promise<string[] | void> | string[] | void;
  onExportAgentArchive: (options: AgentArchiveFieldOptions) => void | Promise<void>;
  onImportAgentArchive: (file: File, options: AgentArchiveFieldOptions) => void | Promise<void>;
  onReuseWorldConfig?: (worldId: string) => void | Promise<void>;
}) {
  const traitLabels: Record<string, string> = {
    openness: "开放",
    caution: "警惕",
    sociability: "社交",
    empathy: "共情",
    curiosity: "好奇",
    discipline: "自律",
    aggression: "攻击",
    honesty: "诚实",
    creativity: "创造",
    neuroticism: "敏感"
  };
  const traitHelp: Record<string, string> = {
    openness: "探索、接受新关系、尝试世界观机制；通过探索/学习提升，长期回避新事物会下降。",
    caution: "边界、风险、投资/犯罪避险；通过预算/研究/设边界提升，冲动冒险会下降。",
    sociability: "聊天、邀约、会议、关系维护；通过社交提升，长期孤立或忽视别人会下降。",
    empathy: "帮助、安慰、照护、哀悼；通过照护/分享提升，伤害别人或见死不救会下降。",
    curiosity: "观察、调查、阅读、市场研究；通过探索/研究提升，长期机械重复会下降。",
    discipline: "睡觉、清洁、工作、预算、还债；通过规律生活提升，熬夜/违约/冲动消费会下降。",
    aggression: "冲突、威胁、强制、攻击；通过暴力/犯罪提升，冥想/道歉/和解会下降。",
    honesty: "自我介绍、守约、报告、还债；通过承认和兑现提升，偷骗/隐瞒/违约会下降。",
    creativity: "创作、提出规则、解决问题；通过写作/艺术/视频/提案提升，疲劳和机械重复会压低。",
    neuroticism: "焦虑、应激、危机警觉；创伤/债务/尸臭会提升，睡眠/冥想/稳定生活会下降。"
  };
  const safeAgentCount = Number.isFinite(agentCount) ? Math.max(0, Math.floor(agentCount)) : 0;
  const fallbackProviderId = providers[0]?.providerId ?? "default";
  const providerDisplaySignature = providers.map((provider) => `${provider.providerId}:${provider.name}`).join("|");
  const expertMode = setupMode === "expert";
  const [bulkProviderId, setBulkProviderId] = useState("");
  const [bulkModelName, setBulkModelName] = useState("");
  const [bulkRandomListId, setBulkRandomListId] = useState("");
  const [bulkToolContextMode, setBulkToolContextMode] = useState<"dynamic" | "all">("dynamic");
  const [bulkTraitMode, setBulkTraitMode] = useState<AgentConfigDraft["traitMode"]>("inherit");
  const [bulkRuntime, setBulkRuntime] = useState<BulkRuntimeDraft>(DEFAULT_BULK_RUNTIME);
  const [bulkTargetIndexes, setBulkTargetIndexes] = useState<number[]>(() => Array.from({ length: safeAgentCount }, (_, index) => index));
  const [reuseWorldId, setReuseWorldId] = useState("");
  const [randomModelLists, setRandomModelLists] = useState<RandomModelList[]>(loadRandomModelLists);
  const [archiveExportOptions, setArchiveExportOptions] = useState<AgentArchiveFieldOptions>(DEFAULT_ARCHIVE_OPTIONS);
  const [archiveImportOptions, setArchiveImportOptions] = useState<AgentArchiveFieldOptions>(DEFAULT_ARCHIVE_OPTIONS);
  const [imageHistory, setImageHistory] = useState(() => configHistoryForKind("imageGeneration"));
  const [narratorHistory, setNarratorHistory] = useState(() => configHistoryForKind("narrator"));
  const [providerHistory, setProviderHistory] = useState(() => configHistoryForKind("providers"));
  const [runtimeHistory, setRuntimeHistory] = useState(() => configHistoryForKind("runtime"));
  const [llmHistory, setLlmHistory] = useState(() => configHistoryForKind("llmGeneration"));
  const [activeAgentConfigIndex, setActiveAgentConfigIndex] = useState(0);
  const [activeAgentConfigOpen, setActiveAgentConfigOpen] = useState(true);
  const [bulkTtsConfig, setBulkTtsConfig] = useState<TtsConfigDraft>(() => defaultTtsConfig());
  const fallbackAgentConfig = (): AgentConfigDraft => ({
    providerId: fallbackProviderId,
    modelName: "",
    toolContextMode: "dynamic",
    agentToolsetIds: agentSpecialToolsets.map((item) => item.toolset_id),
    systemPrompt: "",
    chosenName: "",
    imagePromptName: "",
    appearance: "",
    avatarDataUrl: "",
    standingImageDataUrl: "",
    traitMode: "inherit",
    traits: Object.fromEntries(Object.keys(traitLabels).map((key) => [key, 50])),
    knowledgeMode: "none",
    knownAgents: {},
    llmGeneration: undefined,
    ttsConfig: defaultTtsConfig()
  });
  const normalizedAgentConfigs = Array.from({ length: safeAgentCount }, (_, index) => {
    const fallback = fallbackAgentConfig();
    const config = agentConfigs[index];
    return config ? {
      ...fallback,
      ...config,
      traitMode: normalizeAgentTraitMode(config.traitMode),
      knowledgeMode: normalizeAgentKnowledgeMode(config.knowledgeMode),
      knownAgents: config.knownAgents && typeof config.knownAgents === "object" ? Object.fromEntries(
        Object.entries(config.knownAgents).map(([key, value]) => [
          String(key),
          {
            knows: Boolean(value?.knows),
            affection: Math.max(-100, Math.min(100, Number(value?.affection ?? 0) || 0))
          }
        ])
      ) : {},
      agentToolsetIds: Array.isArray(config.agentToolsetIds) ? config.agentToolsetIds : fallback.agentToolsetIds,
      imagePromptName: String((config as Record<string, unknown>).imagePromptName ?? (config as Record<string, unknown>).image_prompt_name ?? ""),
      standingImageDataUrl: String((config as Record<string, unknown>).standingImageDataUrl ?? (config as Record<string, unknown>).standing_image_data_url ?? ""),
      traits: { ...fallback.traits, ...(config.traits ?? {}) },
      llmGeneration: config.llmGeneration ? normalizeLlmGeneration(config.llmGeneration) : undefined,
      ttsConfig: normalizeTtsConfig(config.ttsConfig)
    } : fallback;
  });
  const allAgentIndexes = Array.from({ length: safeAgentCount }, (_, index) => index);
  const selectedBulkTargetIndexes = bulkTargetIndexes.filter((index) => index >= 0 && index < safeAgentCount);
  const selectedBulkTargetSet = new Set(selectedBulkTargetIndexes);
  useEffect(() => {
    setBulkTargetIndexes((current) => current.filter((index) => index >= 0 && index < safeAgentCount));
    setActiveAgentConfigIndex((current) => Math.max(0, Math.min(current, Math.max(0, safeAgentCount - 1))));
  }, [safeAgentCount]);
  const werewolfConfig: WerewolfRoleAssignmentDraft = {
    mode: werewolfRoleAssignment?.mode === "counts" || werewolfRoleAssignment?.mode === "manual" ? werewolfRoleAssignment.mode : "auto",
    counts: Object.fromEntries(WEREWOLF_ROLE_OPTIONS.map((role) => [role.value, Math.max(0, Number(werewolfRoleAssignment?.counts?.[role.value] ?? 0) || 0)])) as Record<WerewolfRole, number>,
    manualRoles: Array.from({ length: safeAgentCount }, (_, index) => {
      const value = werewolfRoleAssignment?.manualRoles?.[index];
      return WEREWOLF_ROLE_OPTIONS.some((role) => role.value === value) ? value as WerewolfRole : "villager";
    }),
    autoRoles: Array.from(new Set((werewolfRoleAssignment?.autoRoles?.length ? werewolfRoleAssignment.autoRoles : DEFAULT_WEREWOLF_AUTO_ROLES).filter((value) => WEREWOLF_ROLE_OPTIONS.some((role) => role.value === value)))) as WerewolfRole[]
  };
  const normalizedBabyConfigs = babyModelConfigs.map((config) => ({
    providerId: config.providerId || fallbackProviderId,
    modelName: config.modelName || ""
  }));
  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(RANDOM_MODEL_LISTS_STORAGE_KEY, JSON.stringify(randomModelLists));
  }, [randomModelLists]);
  const updateProvider = (providerId: string, patch: Partial<ProviderDraft>) => {
    const nextProviders = providers.map((provider) => provider.providerId === providerId ? { ...provider, ...patch } : provider);
    onProvidersChange(nextProviders);
    if (patch.name !== undefined && imageGeneration.prompt_llm_provider_id === providerId) {
      const nextProvider = nextProviders.find((provider) => provider.providerId === providerId);
      onImageGenerationChange({
        ...imageGeneration,
        prompt_llm_provider_name: nextProvider?.name ?? "",
      });
    }
  };
  const pullProviderModels = async (providerId: string) => {
    const provider = providers.find((item) => item.providerId === providerId);
    await onPullModels(providerId, provider ? { baseUrl: provider.baseUrl, apiKey: provider.apiKey } : undefined);
  };
  const addProvider = () => {
    const next = `${Date.now()}`;
    onProvidersChange([...providers, { providerId: next, name: "新提供商", baseUrl: "", apiKey: "", retryCount: 2, retryIntervalMs: 1500, requestTimeoutMs: 300000, rpm: 0, models: [] }]);
  };
  const removeProvider = (providerId: string) => {
    if (providers.length <= 1) return;
    const fallback = providers.find((provider) => provider.providerId !== providerId)?.providerId ?? "default";
    onProvidersChange(providers.filter((provider) => provider.providerId !== providerId));
    onAgentConfigsChange(normalizedAgentConfigs.map((config) => config.providerId === providerId ? { ...config, providerId: fallback } : config));
    onBabyModelConfigsChange(normalizedBabyConfigs.map((config) => config.providerId === providerId ? { ...config, providerId: fallback, modelName: "" } : config));
    if (narratorConfig.providerId === providerId) {
      onNarratorConfigChange({ ...narratorConfig, providerId: fallback, modelName: "" });
    }
  };
  const updateImageGeneration = (patch: Partial<ImageGenerationSettings>) => {
    onImageGenerationChange({ ...imageGeneration, ...patch });
  };
  const applyImageHistory = (id: string) => {
    const item = imageHistory.find((entry) => entry.id === id);
    if (!item) return;
    onImageGenerationChange({ ...imageGeneration, ...item.data });
  };
  const saveImageHistory = () => {
    upsertConfigHistory("imageGeneration", `${imageGeneration.provider_type} · ${imageGeneration.model_name || "默认模型"} · ${new Date().toLocaleString()}`, imageGeneration as unknown as Record<string, unknown>);
    setImageHistory(configHistoryForKind("imageGeneration"));
  };
  const applyNarratorHistory = (id: string) => {
    const item = narratorHistory.find((entry) => entry.id === id);
    if (!item) return;
    onNarratorConfigChange({ ...narratorConfig, ...item.data });
  };
  const saveNarratorHistory = () => {
    const providerName = providers.find((provider) => provider.providerId === narratorConfig.providerId)?.name || "解说";
    upsertConfigHistory("narrator", `${providerName} · ${narratorConfig.modelName || "默认模型"} · ${new Date().toLocaleString()}`, narratorConfig as unknown as Record<string, unknown>);
    setNarratorHistory(configHistoryForKind("narrator"));
  };
  const applyProviderHistory = (id: string) => {
    const item = providerHistory.find((entry) => entry.id === id);
    const savedProviders = item?.data.providers;
    if (!Array.isArray(savedProviders)) return;
    onProvidersChange(savedProviders as ProviderDraft[]);
  };
  const saveProviderHistory = () => {
    upsertConfigHistory("providers", `提供商 · ${providers.length} 个 · ${new Date().toLocaleString()}`, { providers: providers as unknown as Record<string, unknown>[] });
    setProviderHistory(configHistoryForKind("providers"));
  };
  const applyRuntimeHistory = (id: string) => {
    const item = runtimeHistory.find((entry) => entry.id === id);
    if (!item) return;
    const data = item.data;
    if (typeof data.providerId === "string") setBulkProviderId(data.providerId);
    if (typeof data.modelName === "string") setBulkModelName(data.modelName);
    if (typeof data.randomListId === "string") setBulkRandomListId(data.randomListId);
    if (data.toolContextMode === "dynamic" || data.toolContextMode === "all") setBulkToolContextMode(data.toolContextMode);
    if (["inherit", "agent", "random", "player"].includes(String(data.traitMode))) setBulkTraitMode(data.traitMode as AgentConfigDraft["traitMode"]);
    setBulkRuntime({
      retryCount: Number.isFinite(Number(data.retryCount)) ? Number(data.retryCount) : DEFAULT_BULK_RUNTIME.retryCount,
      retryIntervalMs: Number.isFinite(Number(data.retryIntervalMs)) ? Number(data.retryIntervalMs) : DEFAULT_BULK_RUNTIME.retryIntervalMs,
      requestTimeoutMs: Number.isFinite(Number(data.requestTimeoutMs)) ? Number(data.requestTimeoutMs) : DEFAULT_BULK_RUNTIME.requestTimeoutMs,
      rpm: Number.isFinite(Number(data.rpm)) ? Number(data.rpm) : DEFAULT_BULK_RUNTIME.rpm
    });
  };
  const saveRuntimeHistory = () => {
    upsertConfigHistory("runtime", `一键模型 · ${bulkProvider?.name || "提供商"} · ${bulkModelName || selectedRandomModelList?.name || "默认"} · ${new Date().toLocaleString()}`, {
      providerId: effectiveBulkProviderId,
      modelName: bulkModelName,
      randomListId: selectedRandomModelList?.id ?? "",
      toolContextMode: bulkToolContextMode,
      traitMode: bulkTraitMode,
      retryCount: bulkRuntime.retryCount,
      retryIntervalMs: bulkRuntime.retryIntervalMs,
      requestTimeoutMs: bulkRuntime.requestTimeoutMs,
      rpm: bulkRuntime.rpm
    });
    setRuntimeHistory(configHistoryForKind("runtime"));
  };
  const pullImageModelOptions = async () => {
    if (!onPullImageModels) return;
    const models = await onPullImageModels({ baseUrl: imageGeneration.base_url, apiKey: imageGeneration.api_key });
    const normalizedModels = Array.isArray(models) ? models.map(String).filter(Boolean) : [];
    if (!normalizedModels.length) return;
    updateImageGeneration({
      model_options: normalizedModels,
      model_name: imageGeneration.model_name || normalizedModels[0] || ""
    });
  };
  const updateAgent = (index: number, patch: Partial<AgentConfigDraft>) => {
    onAgentConfigsChange(normalizedAgentConfigs.map((config, idx) => idx === index ? { ...config, ...patch } : config));
  };
  const updateAgentsAtIndexes = (indexes: number[], mapper: (config: AgentConfigDraft, index: number) => AgentConfigDraft) => {
    const targets = new Set(indexes.filter((index) => index >= 0 && index < safeAgentCount));
    if (!targets.size) return;
    onAgentConfigsChange(normalizedAgentConfigs.map((config, idx) => targets.has(idx) ? mapper(config, idx) : config));
  };
  const setBulkTarget = (index: number, enabled: boolean) => {
    setBulkTargetIndexes((current) => {
      const next = new Set(current);
      if (enabled) next.add(index);
      else next.delete(index);
      return Array.from(next).filter((item) => item >= 0 && item < safeAgentCount).sort((a, b) => a - b);
    });
  };
  const updateAgentKnowledgeMode = (index: number, mode: AgentKnowledgeMode) => {
    const config = normalizedAgentConfigs[index] ?? fallbackAgentConfig();
    updateAgent(index, {
      knowledgeMode: mode,
      knownAgents: mode === "custom" ? config.knownAgents : {},
    });
  };
  const updateAgentKnownTarget = (observerIndex: number, targetIndex: number, patch: { knows?: boolean; affection?: number }) => {
    const config = normalizedAgentConfigs[observerIndex] ?? fallbackAgentConfig();
    const key = String(targetIndex);
    const current = config.knownAgents[key] ?? { knows: false, affection: 0 };
    updateAgent(observerIndex, {
      knowledgeMode: "custom",
      knownAgents: {
        ...config.knownAgents,
        [key]: {
          knows: patch.knows ?? current.knows,
          affection: Math.max(-100, Math.min(100, Number(patch.affection ?? current.affection ?? 0) || 0)),
        },
      },
    });
  };
  const globalLlmGeneration = normalizeLlmGeneration(llmGeneration);
  const updateGlobalLlmGeneration = (patch: Partial<LlmGenerationSettings>) => {
    onLlmGenerationChange(normalizeLlmGeneration({ ...globalLlmGeneration, ...patch }));
  };
  const applyLlmHistory = (id: string) => {
    const item = llmHistory.find((entry) => entry.id === id);
    if (!item) return;
    onLlmGenerationChange(normalizeLlmGeneration(item.data as Partial<LlmGenerationSettings>));
  };
  const saveLlmHistory = () => {
    upsertConfigHistory("llmGeneration", `LLM 输出参数 · temp ${globalLlmGeneration.temperature} · ${new Date().toLocaleString()}`, globalLlmGeneration as unknown as Record<string, unknown>);
    setLlmHistory(configHistoryForKind("llmGeneration"));
  };
  const updateAgentLlmGeneration = (index: number, patch: Partial<LlmGenerationSettings>) => {
    const config = normalizedAgentConfigs[index] ?? fallbackAgentConfig();
    updateAgent(index, { llmGeneration: normalizeLlmGeneration({ ...globalLlmGeneration, ...(config.llmGeneration ?? {}), ...patch }) });
  };
  const clearAgentLlmGeneration = (index: number) => {
    updateAgent(index, { llmGeneration: undefined });
  };
  const updateTrait = (index: number, key: string, value: number) => {
    const config = normalizedAgentConfigs[index] ?? fallbackAgentConfig();
    updateAgent(index, { traits: { ...config.traits, [key]: value } });
  };
  const updateAgentTts = (index: number, patch: Partial<TtsConfigDraft>) => {
    const config = normalizedAgentConfigs[index] ?? fallbackAgentConfig();
    const modePatch = patch.mode ? ttsDefaultsForMode(patch.mode) : {};
    const next = normalizeTtsConfig({ ...config.ttsConfig, ...modePatch, ...patch });
    updateAgent(index, { ttsConfig: next });
  };
  const updateBulkTts = (patch: Partial<TtsConfigDraft>) => {
    const modePatch = patch.mode ? ttsDefaultsForMode(patch.mode) : {};
    setBulkTtsConfig((current) => normalizeTtsConfig({ ...current, ...modePatch, ...patch }));
  };
  const loadBulkTtsFromActiveAgent = () => {
    setBulkTtsConfig(normalizeTtsConfig(normalizedAgentConfigs[activeAgentConfigIndex]?.ttsConfig));
  };
  const applyBulkTtsToIndexes = (indexes: number[]) => {
    const next = normalizeTtsConfig(bulkTtsConfig);
    updateAgentsAtIndexes(indexes, (config) => ({
      ...config,
      ttsConfig: { ...next },
    }));
  };
  const clearBulkTtsForIndexes = (indexes: number[]) => {
    updateAgentsAtIndexes(indexes, (config) => ({
      ...config,
      ttsConfig: defaultTtsConfig(),
    }));
  };
  const toggleAgentToolset = (index: number, toolsetId: string, enabled: boolean) => {
    const config = normalizedAgentConfigs[index] ?? fallbackAgentConfig();
    const current = new Set(config.agentToolsetIds);
    if (enabled) current.add(toolsetId);
    else current.delete(toolsetId);
    updateAgent(index, { agentToolsetIds: Array.from(current) });
  };
  const readAvatarFile = (index: number, file: File | undefined) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => updateAgent(index, { avatarDataUrl: String(reader.result || "") });
    reader.readAsDataURL(file);
  };
  const readStandingFile = (index: number, file: File | undefined) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => updateAgent(index, { standingImageDataUrl: String(reader.result || "") });
    reader.readAsDataURL(file);
  };
  const narratorProvider = providers.find((item) => item.providerId === narratorConfig.providerId) ?? providers[0];
  const promptLlmProviderId = providers.some((item) => item.providerId === imageGeneration.prompt_llm_provider_id)
    ? imageGeneration.prompt_llm_provider_id
    : narratorConfig.providerId || fallbackProviderId;
  const promptLlmProvider = providers.find((item) => item.providerId === promptLlmProviderId) ?? providers[0];
  const imageProviderType = imageGeneration.provider_type === "anima" ? "sdxl" : imageGeneration.provider_type;
  const isOpenAiImageProvider = imageProviderType === "sdxl";
  const isNovelAiImageProvider = imageProviderType === "novelai";
  const isComfyUiImageProvider = imageProviderType === "comfyui";
  const imageHasComfyWorkflow = isComfyUiImageProvider && Boolean(imageGeneration.workflow_json.trim());
  const showImageBaseUrl = !isNovelAiImageProvider;
  const showImageEndpointPath = !isNovelAiImageProvider && !imageHasComfyWorkflow;
  const showImageModelField = !imageHasComfyWorkflow;
  const showImageSizeFields = !imageHasComfyWorkflow;
  const showImageRequestTemplate = !imageHasComfyWorkflow;
  const showImageSamplingFields = isNovelAiImageProvider || (isComfyUiImageProvider && !imageHasComfyWorkflow);
  const novelAiResolutionValue = `${imageGeneration.width}x${imageGeneration.height}`;
  const addBabyModel = () => onBabyModelConfigsChange([...normalizedBabyConfigs, { providerId: fallbackProviderId, modelName: "" }]);
  const updateBabyModel = (index: number, patch: Partial<BabyModelDraft>) => {
    onBabyModelConfigsChange(normalizedBabyConfigs.map((config, idx) => idx === index ? { ...config, ...patch } : config));
  };
  const removeBabyModel = (index: number) => {
    onBabyModelConfigsChange(normalizedBabyConfigs.filter((_, idx) => idx !== index));
  };
  const effectiveBulkProviderId = providers.some((provider) => provider.providerId === bulkProviderId) ? bulkProviderId : fallbackProviderId;
  const bulkProvider = providers.find((provider) => provider.providerId === effectiveBulkProviderId) ?? providers[0];
  const allPulledModelEntries = providers.flatMap((provider) => (
    (provider.models ?? [])
      .map((modelName) => ({ providerId: provider.providerId, modelName: String(modelName ?? "").trim() }))
      .filter((entry) => entry.modelName)
  ));
  const validRandomModelLists = randomModelLists.map((list) => ({
    ...list,
    entries: list.entries.filter((entry) => providers.some((provider) => provider.providerId === entry.providerId) && entry.modelName.trim())
  }));
  const defaultRandomModelList = validRandomModelLists.find((list) => list.entries.length) ?? validRandomModelLists[0];
  const selectedRandomModelList = validRandomModelLists.find((list) => list.id === bulkRandomListId) ?? defaultRandomModelList;
  const pickModelEntry = (entries: Array<{ providerId: string; modelName: string }>) => {
    const validEntries = entries.filter((entry) => entry.providerId && entry.modelName.trim());
    if (!validEntries.length) return null;
    return validEntries[Math.floor(Math.random() * validEntries.length)];
  };
  const usableRandomModelEntries = (list: RandomModelList | undefined) => (list?.entries ?? [])
    .filter((entry) => providers.some((provider) => provider.providerId === entry.providerId) && entry.modelName.trim());
  const addRandomModelList = () => {
    const nextProviderId = fallbackProviderId;
    const nextModelName = providers.find((provider) => provider.providerId === nextProviderId)?.models?.[0] ?? "";
    const nextList: RandomModelList = {
      id: makeLocalId("rml"),
      name: `随机模型列表 ${randomModelLists.length + 1}`,
      entries: [{ id: makeLocalId("rme"), providerId: nextProviderId, modelName: nextModelName }]
    };
    setRandomModelLists([...randomModelLists, nextList]);
    setBulkRandomListId(nextList.id);
  };
  const updateRandomModelList = (listId: string, patch: Partial<RandomModelList>) => {
    setRandomModelLists(randomModelLists.map((list) => list.id === listId ? { ...list, ...patch } : list));
  };
  const removeRandomModelList = (listId: string) => {
    const nextLists = randomModelLists.filter((list) => list.id !== listId);
    setRandomModelLists(nextLists);
    if (bulkRandomListId === listId) setBulkRandomListId(nextLists[0]?.id ?? "");
  };
  const addRandomModelEntry = (listId: string) => {
    setRandomModelLists(randomModelLists.map((list) => {
      if (list.id !== listId) return list;
      const providerId = fallbackProviderId;
      const modelName = providers.find((provider) => provider.providerId === providerId)?.models?.[0] ?? "";
      return { ...list, entries: [...list.entries, { id: makeLocalId("rme"), providerId, modelName }] };
    }));
  };
  const updateRandomModelEntry = (listId: string, entryId: string, patch: Partial<RandomModelEntry>) => {
    setRandomModelLists(randomModelLists.map((list) => list.id === listId
      ? { ...list, entries: list.entries.map((entry) => entry.id === entryId ? { ...entry, ...patch } : entry) }
      : list));
  };
  const removeRandomModelEntry = (listId: string, entryId: string) => {
    setRandomModelLists(randomModelLists.map((list) => list.id === listId
      ? { ...list, entries: list.entries.filter((entry) => entry.id !== entryId) }
      : list));
  };
  const effectiveReuseWorldId = reusableWorlds.some((item) => item.world_id === reuseWorldId) ? reuseWorldId : (reusableWorlds[0]?.world_id ?? "");
  const effectiveReuseWorld = reusableWorlds.find((item) => item.world_id === effectiveReuseWorldId);
  const effectiveReuseWorldTitle = effectiveReuseWorld
    ? `复用历史配置: ${effectiveReuseWorld.save_name || effectiveReuseWorld.name || "未命名存档"} · 世界名 ${effectiveReuseWorld.name || "未命名世界"} · ${effectiveReuseWorld.world_time_label || "无时间"}`
    : "暂无可复用的历史存档";
  const applyBulkModelToIndexes = (indexes: number[], includeNarrator = false) => {
    if (!bulkModelName) {
      const pool = allPulledModelEntries;
      if (pool.length) {
        updateAgentsAtIndexes(indexes, (config) => {
          const picked = pickModelEntry(pool);
          return picked ? { ...config, providerId: picked.providerId, modelName: picked.modelName } : config;
        });
        if (includeNarrator) {
          const pickedNarrator = pickModelEntry(pool);
          if (pickedNarrator) {
            onNarratorConfigChange({
              ...narratorConfig,
              enabled: true,
              providerId: pickedNarrator.providerId,
              modelName: pickedNarrator.modelName,
            });
          }
        }
        return;
      }
    }
    updateAgentsAtIndexes(indexes, (config) => ({
      ...config,
      providerId: effectiveBulkProviderId,
      modelName: bulkModelName,
    }));
    if (includeNarrator) {
      onNarratorConfigChange({
        ...narratorConfig,
        enabled: true,
        providerId: effectiveBulkProviderId,
        modelName: bulkModelName,
      });
    }
  };
  const applyBulkModel = () => {
    applyBulkModelToIndexes(allAgentIndexes, !expertMode);
  };
  const loadBulkRuntimeFromProvider = () => {
    if (!bulkProvider) return;
    setBulkRuntime({
      retryCount: bulkProvider.retryCount,
      retryIntervalMs: bulkProvider.retryIntervalMs,
      requestTimeoutMs: bulkProvider.requestTimeoutMs,
      rpm: bulkProvider.rpm
    });
  };
  const normalizedBulkRuntime = (): Pick<ProviderDraft, "retryCount" | "retryIntervalMs" | "requestTimeoutMs" | "rpm"> => ({
    retryCount: Math.max(0, Math.min(100000, Math.floor(Number(bulkRuntime.retryCount) || 0))),
    retryIntervalMs: Math.max(0, Math.min(21600000, Math.floor(Number(bulkRuntime.retryIntervalMs) || 0))),
    requestTimeoutMs: Math.max(0, Math.min(86400000, Math.floor(Number(bulkRuntime.requestTimeoutMs) || 0))),
    rpm: Math.max(0, Math.min(100000, Math.floor(Number(bulkRuntime.rpm) || 0)))
  });
  const applyBulkRuntimeToProviders = (providerIds: string[]) => {
    const targets = new Set(providerIds);
    if (!targets.size) return;
    const runtime = normalizedBulkRuntime();
    onProvidersChange(providers.map((provider) => targets.has(provider.providerId) ? { ...provider, ...runtime } : provider));
  };
  const applyBulkRandomModelListToIndexes = (list: RandomModelList | undefined, indexes: number[], includeNarrator = false) => {
    const entries = usableRandomModelEntries(list);
    if (!entries.length) return;
    updateAgentsAtIndexes(indexes, (config) => {
      const picked = pickModelEntry(entries);
      return picked ? { ...config, providerId: picked.providerId, modelName: picked.modelName } : config;
    });
    if (includeNarrator) {
      const pickedNarrator = pickModelEntry(entries);
      if (pickedNarrator) {
        onNarratorConfigChange({
          ...narratorConfig,
          enabled: true,
          providerId: pickedNarrator.providerId,
          modelName: pickedNarrator.modelName,
        });
      }
    }
  };
  const applyBulkToolContextToIndexes = (indexes: number[]) => {
    updateAgentsAtIndexes(indexes, (config) => ({
      ...config,
      toolContextMode: bulkToolContextMode,
    }));
  };
  const applyBulkToolContext = () => {
    applyBulkToolContextToIndexes(allAgentIndexes);
  };
  const applyBulkTraitModeToIndexes = (indexes: number[]) => {
    updateAgentsAtIndexes(indexes, (config) => ({
      ...config,
      traitMode: bulkTraitMode,
    }));
  };
  const applyBulkTraitMode = () => {
    applyBulkTraitModeToIndexes(allAgentIndexes);
  };
  const setAgentToolsetsForIndexes = (mode: "all" | "none", indexes: number[]) => {
    const allToolsetIds = agentSpecialToolsets.map((toolset) => toolset.toolset_id);
    updateAgentsAtIndexes(indexes, (config) => ({
      ...config,
      agentToolsetIds: mode === "all" ? allToolsetIds : [],
    }));
  };
  const setAllAgentToolsets = (mode: "all" | "none") => {
    setAgentToolsetsForIndexes(mode, allAgentIndexes);
  };
  const updateNovelAiResolution = (value: string) => {
    const [width, height] = value.split("x").map((part) => Number(part));
    if (!Number.isFinite(width) || !Number.isFinite(height)) return;
    updateImageGeneration({ width, height });
  };
  const setAgentKnowledgeForIndexes = (mode: "all" | "none", indexes: number[]) => {
    updateAgentsAtIndexes(indexes, (config) => ({
      ...config,
      knowledgeMode: mode,
      knownAgents: {},
    }));
  };
  const normalizedGlobalTraitMode = ["agent", "random", "player"].includes(String(traitMode)) ? String(traitMode) as "agent" | "random" | "player" : "agent";
  const effectiveTraitMode = (config: AgentConfigDraft) => config.traitMode === "inherit" ? normalizedGlobalTraitMode : config.traitMode;
  const toggleOption = (options: AgentArchiveFieldOptions, key: keyof AgentArchiveFieldOptions, value: boolean): AgentArchiveFieldOptions => ({ ...options, [key]: value });
  const english = language === "en";
  const text = (zh: string, en: string) => english ? en : zh;
  const tr = (value: string) => t(value, language);
  const renderArchiveReuseControls = (variant: "default" | "overview" = "default") => (
    <div className={`archive-reuse-controls ${variant === "overview" ? "archive-reuse-controls-compact" : ""}`}>
      <div className="archive-actions">
        <button type="button" onClick={() => onExportAgentArchive(archiveExportOptions)}>
          <Download size={15} /> 导出人员配置
        </button>
        <FileDropZone
          accept="application/json,.json,.tlwagents,.zip,application/zip"
          onFile={(file) => onImportAgentArchive(file, archiveImportOptions)}
          hint="可拖入 zip/json"
        >
          <Upload size={15} /> 导入人员配置
        </FileDropZone>
      </div>
      <div className="reuse-config-row">
        <label>
          复用历史配置
          {!expertMode && <em className="beginner-marker marker-reuse">{text("靛色: 复用旧存档人员", "Indigo: reuse saved residents")}</em>}
          <select data-auto-title="false" title={effectiveReuseWorldTitle} value={effectiveReuseWorldId} onChange={(event) => setReuseWorldId(event.target.value)}>
            {reusableWorlds.length ? reusableWorlds.map((item) => {
              const saveName = item.save_name || item.name || "未命名存档";
              const timeLabel = item.world_time_label || "无时间";
              const statusLabel = item.status === "running" ? "运行中" : item.status === "paused" ? "暂停" : item.status === "ended" ? "已结束" : item.status;
              return (
                <option key={item.world_id} value={item.world_id}>
                  {saveName} · {item.name} · {timeLabel} · {statusLabel}
                </option>
              );
            }) : <option value="">暂无历史存档</option>}
          </select>
        </label>
        <button type="button" disabled={!effectiveReuseWorldId || !onReuseWorldConfig} onClick={() => onReuseWorldConfig?.(effectiveReuseWorldId)}>
          复用历史配置
          {!expertMode && <em className="beginner-marker marker-reuse">靛色</em>}
        </button>
      </div>
      {expertMode && (
        <details className="archive-options-details">
          <summary>字段选项</summary>
          <div className="archive-option-grid">
            <fieldset className="archive-option-row">
              <legend>导出包含</legend>
              {ARCHIVE_OPTION_LABELS.map(([key, label]) => (
                <label key={`export-${variant}-${key}`}>
                  <input type="checkbox" checked={archiveExportOptions[key] !== false} onChange={(event) => setArchiveExportOptions(toggleOption(archiveExportOptions, key, event.target.checked))} />
                  {label}
                </label>
              ))}
            </fieldset>
            <fieldset className="archive-option-row">
              <legend>导入覆盖</legend>
              {ARCHIVE_OPTION_LABELS.map(([key, label]) => (
                <label key={`import-${variant}-${key}`}>
                  <input type="checkbox" checked={archiveImportOptions[key] !== false} onChange={(event) => setArchiveImportOptions(toggleOption(archiveImportOptions, key, event.target.checked))} />
                  {label}
                </label>
              ))}
            </fieldset>
          </div>
        </details>
      )}
    </div>
  );
  const traitModeLabel = (value: AgentConfigDraft["traitMode"]) => {
    if (value === "agent") return tr("Agent 自己加点");
    if (value === "random") return tr("随机加点");
    if (value === "player") return tr("玩家加点");
    return tr("跟随世界默认");
  };
  const updateWerewolfConfig = (patch: Partial<WerewolfRoleAssignmentDraft>) => {
    onWerewolfRoleAssignmentChange?.({
      ...werewolfConfig,
      ...patch,
      counts: { ...werewolfConfig.counts, ...(patch.counts ?? {}) },
      manualRoles: patch.manualRoles ?? werewolfConfig.manualRoles,
      autoRoles: patch.autoRoles ?? werewolfConfig.autoRoles
    });
  };
  const updateWerewolfRoleCount = (role: WerewolfRole, value: number) => {
    const current = Math.max(0, Math.floor(Number(werewolfConfig.counts[role]) || 0));
    const usedByOthers = Object.entries(werewolfConfig.counts).reduce((sum, [key, count]) => key === role ? sum : sum + Number(count || 0), 0);
    const maxForRole = Math.max(0, safeAgentCount - usedByOthers);
    updateWerewolfConfig({
      counts: {
        ...werewolfConfig.counts,
        [role]: Math.max(0, Math.min(maxForRole, Math.floor(Number.isFinite(value) ? value : current)))
      }
    });
  };
  const updateWerewolfManualRole = (index: number, role: WerewolfRole) => {
    updateWerewolfConfig({ manualRoles: werewolfConfig.manualRoles.map((current, idx) => idx === index ? role : current) });
  };
  const werewolfCountTotal = Object.values(werewolfConfig.counts).reduce((sum, value) => sum + Number(value || 0), 0);
  const selectedAutoRoles = new Set<WerewolfRole>([...DEFAULT_WEREWOLF_AUTO_ROLES.filter((role) => role === "villager" || role === "werewolf"), ...werewolfConfig.autoRoles]);
  const selectedAutoOptions = WEREWOLF_ROLE_OPTIONS.filter((role) => selectedAutoRoles.has(role.value));
  const selectedAutoRequiredSlots = Math.min(
    safeAgentCount,
    safeAgentCount <= 5 ? 1 : safeAgentCount <= 8 ? 2 : safeAgentCount <= 12 ? 3 : 4,
  ) + selectedAutoOptions.filter((role) => !role.core && safeAgentCount >= role.minPlayers).length;
  const updateWerewolfAutoRole = (role: WerewolfRole, enabled: boolean) => {
    const option = WEREWOLF_ROLE_OPTIONS.find((item) => item.value === role);
    if (!option || option.core) return;
    const next = new Set(selectedAutoRoles);
    if (enabled) next.add(role);
    else next.delete(role);
    updateWerewolfConfig({ autoRoles: Array.from(next) });
  };
  const canAddAutoRole = (role: WerewolfRole) => {
    const option = WEREWOLF_ROLE_OPTIONS.find((item) => item.value === role);
    if (!option) return false;
    if (safeAgentCount < option.minPlayers) return false;
    if (selectedAutoRoles.has(role)) return true;
    return selectedAutoRequiredSlots + 1 <= safeAgentCount;
  };

  return (
    <div className="create-config">
      <div className="model-config-grid">
        <section className="setup-provider-section provider-config-section section-accent-provider">
          <div className="setup-provider-heading">
            <h2>{text("提供商", "Providers")} {!expertMode && <em className="beginner-marker marker-provider">{text("蓝色: 先填这里", "Blue: fill this first")}</em>}</h2>
            <span>{text(`${providers.length} 个连接配置`, `${providers.length} provider configs`)}</span>
            <button type="button" title={text("添加提供商", "Add provider")} onClick={addProvider}><Plus size={15} /></button>
          </div>
          <div className="history-picker-row">
            <label>
              {text("历史配置", "History")}
              <select value="" onChange={(event) => applyProviderHistory(event.target.value)}>
                <option value="">{text("选择历史提供商配置", "Choose saved provider config")}</option>
                {providerHistory.map((item) => <option key={item.id} value={item.id}>{item.pinned ? "★ " : ""}{item.name}</option>)}
              </select>
            </label>
            <button type="button" onClick={saveProviderHistory}>{text("保存当前提供商配置", "Save current providers")}</button>
          </div>
          <div className="provider-list">
            {providers.map((provider) => (
              <div className="provider-row" key={provider.providerId}>
                <label>
                  <span>{text("名称", "Name")}</span>
                  {!expertMode && <em className="beginner-marker marker-provider">{text("蓝色: 随便起名", "Blue: any name is fine")}</em>}
                  <input value={provider.name} onChange={(event) => updateProvider(provider.providerId, { name: event.target.value })} />
                </label>
                <label>
                  <span>URL</span>
                  {!expertMode && <em className="beginner-marker marker-provider">{text("蓝色: 结尾带 /v1", "Blue: must end with /v1")}</em>}
                  <input value={provider.baseUrl} onChange={(event) => updateProvider(provider.providerId, { baseUrl: event.target.value })} />
                </label>
                <label>
                  <span>API Key</span>
                  {!expertMode && <em className="beginner-marker marker-provider">{text("蓝色: 填模型网站密钥", "Blue: enter model API key")}</em>}
                  <input type="password" value={provider.apiKey} placeholder={text("留空则使用后端 .env", "Leave blank to use backend .env")} onChange={(event) => updateProvider(provider.providerId, { apiKey: event.target.value })} />
                </label>
                {expertMode && (
                  <div className="provider-runtime-grid">
                    <label title={text("模型请求失败后最多重试多少次。", "Maximum retry count after a model request fails.")}>
                      {text("重试次数", "Retries")}
                      <input type="number" min="0" max="100000" value={provider.retryCount} onChange={(event) => updateProvider(provider.providerId, { retryCount: Number(event.target.value) })} />
                    </label>
                    <label title={text("每次 LLM 重试之间等待的毫秒数。", "Milliseconds to wait between LLM retries.")}>
                      {text("重试间隔 ms", "Retry interval ms")}
                      <input type="number" min="0" max="21600000" step="100" value={provider.retryIntervalMs} onChange={(event) => updateProvider(provider.providerId, { retryIntervalMs: Number(event.target.value) })} />
                    </label>
                    <label title={text("单次模型请求等待完整响应的毫秒数。0 表示不主动超时，适合很慢的本地模型。", "Milliseconds to wait for one full model response. 0 disables client-side timeout, useful for slow local models.")}>
                      {text("请求超时 ms", "Request timeout ms")}
                      <input type="number" min="0" max="86400000" step="1000" value={provider.requestTimeoutMs} onChange={(event) => updateProvider(provider.providerId, { requestTimeoutMs: Number(event.target.value) })} />
                    </label>
                    <label title={text("每分钟请求上限。0 表示不按 RPM 限速，只使用并发限制。", "Requests per minute limit. 0 means no RPM throttling, only concurrency limits.")}>
                      RPM
                      <input type="number" min="0" max="100000" value={provider.rpm} onChange={(event) => updateProvider(provider.providerId, { rpm: Number(event.target.value) })} />
                    </label>
                  </div>
                )}
                <div className="provider-actions">
                  <button type="button" onClick={() => pullProviderModels(provider.providerId)} disabled={pullingProviderId === provider.providerId}>
                    <RefreshCw size={15} /> {pullingProviderId === provider.providerId ? text("拉取中", "Fetching") : text("拉取模型", "Fetch models")}
                  </button>
                  <button type="button" title={text("删除", "Delete")} onClick={() => removeProvider(provider.providerId)} disabled={providers.length <= 1}>
                    <Trash2 size={15} />
                  </button>
                </div>
                <p className="model-count">{provider.models.length ? text(`已拉取 ${provider.models.length} 个模型`, `Fetched ${provider.models.length} models`) : text("尚未拉取模型", "No models fetched yet")}</p>
              </div>
            ))}
          </div>
        </section>
        {!expertMode && (
          <section className="setup-collapsible-section beginner-guide-panel section-accent-guide">
            <div className="setup-section-summary static-section-summary">
              <h2>{text("快速上手", "Quick Start")}</h2>
              <span>{text("步骤说明", "Steps")}</span>
              <span className="beginner-summary-markers">
                <em className="beginner-marker marker-provider">{text("蓝色: 提供商", "Blue: provider")}</em>
                <em className="beginner-marker marker-model">{text("紫色: 模型", "Purple: model")}</em>
                <em className="beginner-marker marker-world">{text("绿色: 世界/人数", "Green: world/count")}</em>
                <em className="beginner-marker marker-agent">{text("橙色: 角色", "Orange: character")}</em>
                <em className="beginner-marker marker-start">{text("红色: 创建", "Red: create")}</em>
              </span>
            </div>
            <ol>
              <li><span className="guide-chip marker-provider">{text("蓝色", "Blue")}</span> {text("先填标着蓝色的“提供商”: 名称随便写，URL 要以", "First fill the blue-marked Providers area: the name can be anything, and the URL must end with")} <code>/v1</code>{text("结尾，例如", ", for example")} <code>https://api.deepseek.com/v1</code>{text("，再填 API Key 并点“拉取模型”。", ". Then enter your API Key and click Fetch models.")}</li>
              <li><span className="guide-chip marker-model">{text("紫色", "Purple")}</span> {text("到标着紫色的“一键配置模型”选择刚才的提供商和模型，再点“应用到全部”。优先选 flash、mini 或其他便宜模型。", "In the purple-marked One-click model setup, choose the provider and model you just added, then click Apply to all. Prefer flash, mini, or other inexpensive models.")}</li>
              <li><span className="guide-chip marker-world">{text("绿色", "Green")}</span> {text("顶部可以改 Agent 数量（角色数量）和生存难度；右侧边栏可以切换世界观。", "At the top you can change Agent count (character count) and survival difficulty; the right sidebar switches worldviews.")}</li>
              <li><span className="guide-chip marker-agent">{text("橙色", "Orange")}</span> {text("下面可以手动填角色名字、外貌、提示词和头像；不填也可以，AI 会自动生成。", "Below you can manually set character names, appearance, prompts, and avatars. Leaving them blank is fine; AI will generate them.")}</li>
              <li>
                <span className="guide-chip marker-start">{text("红色", "Red")}</span> {text("点“创建世界”进入游戏后，还要点右上角“继续”按钮，世界才会运行。", "After clicking Create world and entering the game, click the Continue button in the upper-right toolbar to start the simulation.")}
                <img className="beginner-guide-image" src="/beginner-continue-button.png" alt={text("右上角继续按钮示意图", "Upper-right Continue button example")} />
              </li>
              <li><span className="guide-chip marker-record">{text("灰色", "Gray")}</span> {text("玩过的存档在右侧“本地游玩记录”里，双击或点开即可继续。", "Saved games are listed in Local play records on the right. Double-click or open one to continue.")}</li>
              <li><span className="guide-chip marker-history">{text("青色", "Cyan")}</span> {text("左边“历史身份库”是以前存档里用过的角色身份。点“应用”会把那个角色的名字、外貌、头像、提示词和模型配置填到某个 Agent 上。", "The left Identity history contains character identities used in previous saves. Apply fills a target Agent with that character's name, appearance, avatar, prompt, and model setup.")}</li>
              <li><span className="guide-chip marker-target">{text("玫红", "Pink")}</span> {text("历史身份库里的“目标”是在选择要把这个角色应用到哪个 Agent，例如 Agent 1 或 Agent 2。", "The Target selector in Identity history chooses which Agent receives that character, such as Agent 1 or Agent 2.")}</li>
              <li><span className="guide-chip marker-reuse">{text("靛色", "Indigo")}</span> {text("想复用以前整个存档的人员配置，就在“复用历史配置”选择旧存档，再点“复用历史配置”。", "To reuse a previous save's full resident setup, choose it in Reuse history config, then click Reuse history config.")}</li>
              <li>
                {text("想要更深入配置时，可以把顶部“配置模式”从新手模式改成专家模式，并访问", "For deeper configuration, switch the top Setup mode from Beginner to Expert, then visit")}{" "}
                <a href="https://docs.galbands.com" target="_blank" rel="noreferrer">docs.galbands.com</a>
                {text("查看相关文档。", " for the documentation.")}
              </li>
            </ol>
          </section>
        )}
        {expertMode && <div className="model-config-side">
          <details className="setup-collapsible-section narrator-config-section section-accent-narrator">
            <summary className="setup-section-summary">
              <h2>解说 Agent</h2>
              <span>{narratorConfig.enabled ? "已启用" : "关闭"}</span>
            </summary>
            <div className="section-heading section-heading-actions-only">
              <label className="toggle-inline">
                <input
                  type="checkbox"
                  checked={narratorConfig.enabled}
                  onChange={(event) => onNarratorConfigChange({ ...narratorConfig, enabled: event.target.checked })}
                />
                启用解说
              </label>
            </div>
            <div className="history-picker-row">
              <label>
                历史配置
                <select value="" onChange={(event) => applyNarratorHistory(event.target.value)}>
                  <option value="">选择历史解说配置</option>
                  {narratorHistory.map((item) => <option key={item.id} value={item.id}>{item.pinned ? "★ " : ""}{item.name}</option>)}
                </select>
              </label>
              <button type="button" onClick={saveNarratorHistory}>保存当前解说配置</button>
            </div>
            <div className={`narrator-config-row ${narratorConfig.enabled ? "" : "disabled-row"}`}>
              <label>
                提供商
                <select
                  key={`narrator-provider-${providerDisplaySignature}`}
                  disabled={!narratorConfig.enabled}
                  value={narratorConfig.providerId}
                  onChange={(event) => onNarratorConfigChange({ ...narratorConfig, providerId: event.target.value, modelName: "" })}
                >
                  {providers.map((item) => <option key={item.providerId} value={item.providerId} title={item.name}>{item.name}</option>)}
                </select>
              </label>
              <label>
                模型
                <ModelPicker
                  disabled={!narratorConfig.enabled}
                  value={narratorConfig.modelName}
                  models={narratorProvider?.models ?? []}
                  emptyLabel="默认 pro 解说"
                  searchPlaceholder="搜索解说模型"
                  onChange={(modelName) => onNarratorConfigChange({ ...narratorConfig, modelName })}
                />
              </label>
              <label>
                解说频率
                <select
                  disabled={!narratorConfig.enabled}
                  value={narratorConfig.autoFrequency ?? "normal"}
                  onChange={(event) => onNarratorConfigChange({ ...narratorConfig, autoFrequency: event.target.value as NarratorConfigDraft["autoFrequency"] })}
                >
                  <option value="low">较少</option>
                  <option value="normal">普通</option>
                  <option value="high">较多</option>
                </select>
              </label>
              <label>
                解说提示词
                <textarea
                  disabled={!narratorConfig.enabled}
                  value={narratorConfig.systemPrompt}
                  placeholder={narratorConfig.enabled ? "可选。解说只做场外旁白，不参与世界。" : "关闭后不会生成解说，世界照常运行。"}
                  onChange={(event) => onNarratorConfigChange({ ...narratorConfig, systemPrompt: event.target.value })}
                />
              </label>
            </div>
          </details>
          <details className="setup-collapsible-section image-config-section section-accent-image" open={imageGeneration.enabled}>
            <summary className="setup-section-summary">
              <h2>生图功能</h2>
              <span>{imageGeneration.enabled ? `${imageProviderType} · ${imageGeneration.prompt_style === "auto" ? "自动风格" : imageGeneration.prompt_style} · ${imageGeneration.display_mode === "wait" ? "等待图片" : "占位替换"}` : "关闭"}</span>
            </summary>
            <div className="image-config-grid">
              <label className="toggle-inline">
                <input
                  type="checkbox"
                  checked={imageGeneration.enabled}
                  onChange={(event) => updateImageGeneration({ enabled: event.target.checked })}
                />
                启用解说生图
              </label>
              <label>
                生图模式
                <select value={imageGeneration.source_mode} onChange={(event) => updateImageGeneration({ source_mode: event.target.value as ImageGenerationSettings["source_mode"] })}>
                  <option value="narration">根据解说生图</option>
                  <option value="auto_summary">自动总结生图</option>
                </select>
              </label>
              {imageGeneration.source_mode === "auto_summary" && (
                <label>
                  自动频率
                  <select value={imageGeneration.auto_frequency} onChange={(event) => updateImageGeneration({ auto_frequency: event.target.value as ImageGenerationSettings["auto_frequency"] })}>
                    <option value="low">较少</option>
                    <option value="normal">普通</option>
                    <option value="high">较多</option>
                  </select>
                </label>
              )}
              <label>
                请求方式
                <select value={imageProviderType} onChange={(event) => {
                  const provider_type = event.target.value as ImageGenerationSettings["provider_type"];
                  updateImageGeneration(provider_type === "novelai"
                    ? DEFAULT_NOVELAI_PATCH
                    : { provider_type, prompt_style: imageGeneration.prompt_style });
                }}>
                  <option value="sdxl">OpenAI 兼容图片 API</option>
                  <option value="novelai">NovelAI</option>
                  <option value="comfyui">ComfyUI workflow / API</option>
                </select>
              </label>
              <label>
                历史配置
                <select value="" onChange={(event) => applyImageHistory(event.target.value)}>
                  <option value="">{imageHistory.length ? "选择生图历史配置" : "暂无历史配置"}</option>
                  {imageHistory.map((item) => <option key={item.id} value={item.id}>{item.pinned ? "★ " : ""}{item.name}</option>)}
                </select>
              </label>
              <button type="button" className="image-model-fetch-button" onClick={saveImageHistory}>
                存为历史配置
              </button>
              {isNovelAiImageProvider ? (
                <label>
                  提示词风格
                  <input value="NovelAI 标签" disabled />
                </label>
              ) : (
                <label>
                  提示词风格
                  <select value={imageGeneration.prompt_style} onChange={(event) => updateImageGeneration({ prompt_style: event.target.value as ImageGenerationSettings["prompt_style"] })}>
                    {IMAGE_PROMPT_STYLE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                  </select>
                </label>
              )}
              {imageGeneration.prompt_style === "custom" && (
                <label className="image-config-wide">
                  自定义提示词风格
                  <textarea value={imageGeneration.custom_prompt_style} placeholder="告诉生图提示词 LLM 应该怎么写正负提示词，例如使用哪些质量词、角色标签、构图描述、禁止哪些格式。" onChange={(event) => updateImageGeneration({ custom_prompt_style: event.target.value })} />
                </label>
              )}
              <label>
                提示词 LLM
                <select value={imageGeneration.prompt_llm_mode} onChange={(event) => updateImageGeneration({
                  prompt_llm_mode: event.target.value as ImageGenerationSettings["prompt_llm_mode"],
                  prompt_llm_provider_id: event.target.value === "custom" ? promptLlmProviderId : imageGeneration.prompt_llm_provider_id
                })}>
                  <option value="narrator">沿用解说 AI</option>
                  <option value="custom">单独配置</option>
                </select>
              </label>
              {imageGeneration.prompt_llm_mode === "custom" && (
                <>
                  <label>
                    提示词提供商
                    <select key={`prompt-llm-provider-${providerDisplaySignature}`} value={promptLlmProviderId} onChange={(event) => {
                      const provider = providers.find((item) => item.providerId === event.target.value);
                      updateImageGeneration({ prompt_llm_provider_id: event.target.value, prompt_llm_provider_name: provider?.name ?? "", prompt_llm_model_name: "" });
                    }}>
                      {providers.map((provider) => <option key={provider.providerId} value={provider.providerId}>{provider.name}</option>)}
                    </select>
                  </label>
                  <label>
                    提示词模型
                    <ModelPicker
                      value={imageGeneration.prompt_llm_model_name}
                      models={promptLlmProvider?.models ?? []}
                      emptyLabel="使用默认提示词模型"
                      searchPlaceholder="搜索提示词模型"
                      onChange={(prompt_llm_model_name) => updateImageGeneration({ prompt_llm_provider_id: promptLlmProviderId, prompt_llm_model_name })}
                    />
                  </label>
                  <label className="image-config-wide">
                    提示词 LLM 附加提示
                    <textarea value={imageGeneration.prompt_llm_system_prompt} placeholder="可选。只影响把剧情改写成绘图 prompt 的 LLM，不影响角色行动。" onChange={(event) => updateImageGeneration({ prompt_llm_system_prompt: event.target.value })} />
                  </label>
                </>
              )}
              <label>
                显示方式
                <select value={imageGeneration.display_mode} onChange={(event) => updateImageGeneration({ display_mode: event.target.value as ImageGenerationSettings["display_mode"] })}>
                  <option value="placeholder">占位图，剧情继续显示</option>
                  <option value="wait">等图片生成，再显示后续剧情</option>
                </select>
              </label>
              {showImageBaseUrl && (
                <label>
                  Base URL
                  <input value={imageGeneration.base_url} placeholder={isComfyUiImageProvider ? "http://127.0.0.1:8188" : "https://example.com/v1"} onChange={(event) => updateImageGeneration({ base_url: event.target.value })} />
                </label>
              )}
              {showImageEndpointPath && (
                <label>
                  接口路径
                  <input
                    value={imageGeneration.endpoint_path}
                    placeholder={isComfyUiImageProvider ? "无 workflow 时才使用，例如 /api/generate" : "/images/generations"}
                    onChange={(event) => updateImageGeneration({ endpoint_path: event.target.value })}
                  />
                </label>
              )}
              <label>
                API Key
                <input type="password" value={imageGeneration.api_key || ""} placeholder="本地服务可留空" onChange={(event) => updateImageGeneration({ api_key: event.target.value })} />
              </label>
              {showImageModelField && (
                <label>
                  模型
                  {isNovelAiImageProvider ? (
                    <select value={imageGeneration.model_name || "nai-diffusion-4-5-full"} onChange={(event) => updateImageGeneration({ model_name: event.target.value })}>
                      {NOVELAI_MODEL_OPTIONS.map((model) => <option key={model} value={model}>{model}</option>)}
                    </select>
                  ) : (
                    <ModelPicker
                      value={imageGeneration.model_name}
                      models={imageGeneration.model_options ?? []}
                      emptyLabel="不指定模型"
                      manualPlaceholder="模型名，可留空"
                      searchPlaceholder="搜索图片模型"
                      onChange={(model_name) => updateImageGeneration({ model_name })}
                    />
                  )}
                </label>
              )}
              {isOpenAiImageProvider && showImageModelField && (
                <button type="button" className="image-model-fetch-button" disabled={pullingImageModels || !imageGeneration.base_url.trim()} onClick={pullImageModelOptions}>
                  <RefreshCw size={15} /> {pullingImageModels ? "拉取中" : "拉取图片模型"}
                </button>
              )}
              <label>
                失败重试次数
                <input type="number" min="0" max="100" value={imageGeneration.image_retry_count} onChange={(event) => updateImageGeneration({ image_retry_count: Number(event.target.value) })} />
              </label>
              <label>
                请求超时秒
                <input type="number" min="0" max="86400" value={imageGeneration.request_timeout_seconds} onChange={(event) => updateImageGeneration({ request_timeout_seconds: Number(event.target.value) })} />
              </label>
              {isComfyUiImageProvider && (
                <label>
                  ComfyUI 等待秒
                  <input type="number" min="0" max="86400" value={imageGeneration.comfyui_timeout_seconds} onChange={(event) => updateImageGeneration({ comfyui_timeout_seconds: Number(event.target.value) })} />
                </label>
              )}
              {showImageSizeFields && (
                isNovelAiImageProvider ? (
                  <label>
                    尺寸
                    <select value={NOVELAI_RESOLUTION_OPTIONS.some((option) => option.value === novelAiResolutionValue) ? novelAiResolutionValue : "832x1216"} onChange={(event) => updateNovelAiResolution(event.target.value)}>
                      {NOVELAI_RESOLUTION_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                    </select>
                  </label>
                ) : (
                  <label>
                    尺寸
                    <span className="image-size-inputs">
                      <input type="number" min="256" max="2048" step="64" value={imageGeneration.width} onChange={(event) => updateImageGeneration({ width: Number(event.target.value) })} />
                      <input type="number" min="256" max="2048" step="64" value={imageGeneration.height} onChange={(event) => updateImageGeneration({ height: Number(event.target.value) })} />
                    </span>
                  </label>
                )
              )}
              <label className="toggle-inline">
                <input
                  type="checkbox"
                  checked={imageGeneration.use_agent_appearance}
                  onChange={(event) => updateImageGeneration({ use_agent_appearance: event.target.checked })}
                />
                参考角色外貌文本
              </label>
              <label className="toggle-inline">
                <input
                  type="checkbox"
                  checked={imageGeneration.reference_avatar_images}
                  onChange={(event) => updateImageGeneration({ reference_avatar_images: event.target.checked })}
                />
                参考头像图
              </label>
              <label className="toggle-inline">
                <input
                  type="checkbox"
                  checked={imageGeneration.reference_standing_images}
                  onChange={(event) => updateImageGeneration({ reference_standing_images: event.target.checked })}
                />
                参考立绘图
              </label>
              <details className="image-config-advanced image-config-wide">
                <summary>高级请求参数</summary>
                <div className="image-config-advanced-grid">
              {showImageSamplingFields && (
                <>
                  <label>
                    Steps
                    <input type="number" min="1" max="150" value={imageGeneration.steps} onChange={(event) => updateImageGeneration({ steps: Number(event.target.value) })} />
                  </label>
                  <label>
                    CFG
                    <input type="number" min="1" max="30" step="0.5" value={imageGeneration.cfg_scale} onChange={(event) => updateImageGeneration({ cfg_scale: Number(event.target.value) })} />
                  </label>
                  <label>
                    采样器
                    {isNovelAiImageProvider ? (
                      <select value={imageGeneration.sampler || "k_euler_ancestral"} onChange={(event) => updateImageGeneration({ sampler: event.target.value })}>
                        {NOVELAI_SAMPLER_OPTIONS.map((sampler) => <option key={sampler} value={sampler}>{sampler}</option>)}
                      </select>
                    ) : (
                      <input value={imageGeneration.sampler} placeholder="可选" onChange={(event) => updateImageGeneration({ sampler: event.target.value })} />
                    )}
                  </label>
                  <label>
                    Seed
                    <input type="number" min="-1" value={imageGeneration.seed} onChange={(event) => updateImageGeneration({ seed: Number(event.target.value) })} />
                  </label>
                </>
              )}
              <label className="image-config-wide">
                固定画风提示词
                <textarea value={imageGeneration.style_prompt} placeholder="例如 anime illustration, cinematic lighting，或 score_9, score_8_up 等固定风格词" onChange={(event) => updateImageGeneration({ style_prompt: event.target.value })} />
              </label>
              <label className="image-config-wide">
                负面提示词
                <textarea value={imageGeneration.negative_prompt} placeholder="例如 low quality, bad anatomy, extra fingers" onChange={(event) => updateImageGeneration({ negative_prompt: event.target.value })} />
              </label>
              {showImageRequestTemplate && (
                <label className="image-config-wide">
                  请求体模板 JSON
                  <textarea
                    value={imageGeneration.request_template_json}
                    placeholder={'留空使用默认字段映射。自定义 API 可填 JSON，例如 {"prompt":"{{prompt}}","negative_prompt":"{{negative_prompt}}","width":"{{width}}"}；也支持 %prompt% 和 %negative_prompt%。'}
                    onChange={(event) => updateImageGeneration({ request_template_json: event.target.value })}
                  />
                </label>
              )}
              <label className="image-config-wide">
                固定请求头 JSON
                <textarea
                  value={imageGeneration.custom_headers_json}
                  placeholder={'例如 {"x-correlation-id":"tlw-local-test"}。API Key 会自动写入 Authorization。'}
                  onChange={(event) => updateImageGeneration({ custom_headers_json: event.target.value })}
                />
              </label>
              {isNovelAiImageProvider && (
                <>
                  <label>
                    NAI Action
                    <select value={imageGeneration.nai_action} onChange={(event) => updateImageGeneration({ nai_action: event.target.value as ImageGenerationSettings["nai_action"] })}>
                      <option value="generate">generate</option>
                      <option value="img2img">img2img</option>
                      <option value="infill">infill</option>
                    </select>
                  </label>
                  <label>
                    NAI Format
                    <select value={imageGeneration.nai_image_format} onChange={(event) => updateImageGeneration({ nai_image_format: event.target.value as ImageGenerationSettings["nai_image_format"] })}>
                      <option value="png">png</option>
                      <option value="webp">webp</option>
                    </select>
                  </label>
                  <label>
                    NAI samples
                    <input type="number" min="1" max="4" value={imageGeneration.nai_n_samples} onChange={(event) => updateImageGeneration({ nai_n_samples: Number(event.target.value) })} />
                  </label>
                  <label>
                    ucPreset
                    <input type="number" min="0" max="10" value={imageGeneration.nai_uc_preset} onChange={(event) => updateImageGeneration({ nai_uc_preset: Number(event.target.value) })} />
                  </label>
                  <label>
                    cfg_rescale
                    <input type="number" min="0" max="20" step="0.1" value={imageGeneration.nai_cfg_rescale} onChange={(event) => updateImageGeneration({ nai_cfg_rescale: Number(event.target.value) })} />
                  </label>
                  <label>
                    params_version
                    <input type="number" min="1" max="10" value={imageGeneration.nai_params_version} onChange={(event) => updateImageGeneration({ nai_params_version: Number(event.target.value) })} />
                  </label>
                  <label>
                    参考强度
                    <input type="number" min="0" max="1" step="0.05" value={imageGeneration.nai_reference_strength} onChange={(event) => updateImageGeneration({ nai_reference_strength: Number(event.target.value) })} />
                  </label>
                  <label>
                    参考提取量
                    <input type="number" min="0" max="1" step="0.05" value={imageGeneration.nai_reference_information_extracted} onChange={(event) => updateImageGeneration({ nai_reference_information_extracted: Number(event.target.value) })} />
                  </label>
                  <label>
                    img2img strength
                    <input type="number" min="0" max="1" step="0.05" value={imageGeneration.nai_strength} onChange={(event) => updateImageGeneration({ nai_strength: Number(event.target.value) })} />
                  </label>
                  <label>
                    img2img noise
                    <input type="number" min="0" max="1" step="0.05" value={imageGeneration.nai_noise} onChange={(event) => updateImageGeneration({ nai_noise: Number(event.target.value) })} />
                  </label>
                  <label className="toggle-inline">
                    <input type="checkbox" checked={imageGeneration.nai_quality_toggle} onChange={(event) => updateImageGeneration({ nai_quality_toggle: event.target.checked })} />
                    NAI qualityToggle
                  </label>
                  <label className="toggle-inline">
                    <input type="checkbox" checked={imageGeneration.nai_sm_dyn} onChange={(event) => updateImageGeneration({ nai_sm_dyn: event.target.checked })} />
                    sm_dyn
                  </label>
                  <label className="toggle-inline">
                    <input type="checkbox" checked={imageGeneration.nai_dynamic_thresholding} onChange={(event) => updateImageGeneration({ nai_dynamic_thresholding: event.target.checked })} />
                    dynamic_thresholding
                  </label>
                  <label className="toggle-inline">
                    <input type="checkbox" checked={imageGeneration.nai_add_original_image} onChange={(event) => updateImageGeneration({ nai_add_original_image: event.target.checked })} />
                    add_original_image
                  </label>
                  <label className="image-config-wide">
                    NAI parameters JSON
                    <textarea
                      value={imageGeneration.nai_params_json}
                      placeholder={'直接合并到 NovelAI parameters，例如 {"noise_schedule":"native","skip_cfg_above_sigma":19}。同名字段会覆盖上面的表单值。'}
                      onChange={(event) => updateImageGeneration({ nai_params_json: event.target.value })}
                    />
                  </label>
                </>
              )}
              {isComfyUiImageProvider && (
                <WorkflowJsonInput
                  className="image-config-wide"
                  label="ComfyUI workflow JSON"
                  value={imageGeneration.workflow_json}
                  placeholder={'有 workflow JSON 时请求固定走 ComfyUI /prompt；只有写成占位符的节点才会被外面的宽高、steps、CFG 替换。可用 {{prompt}}、{{negative_prompt}}、{{width}}、{{height}}、{{steps}}、{{cfg_scale}}。'}
                  onChange={(workflow_json) => updateImageGeneration({ workflow_json })}
                />
              )}
                </div>
              </details>
            </div>
          </details>
          <details className="setup-collapsible-section collective-prompt-section section-accent-prompt">
            <summary className="setup-section-summary">
              <h2>集体核心提示词</h2>
              <span>{collectiveCorePrompt.trim() ? "已填写" : "未填写"}</span>
            </summary>
            <label className="collective-prompt-field">
              <span>所有 Agent 的提示词最前面</span>
              <textarea
                value={collectiveCorePrompt}
                placeholder="可选。这里的内容会注入到每个居民每次行动的系统提示词最前面；单个 agent 的个人提示词仍然会在各自配置里追加。"
                onChange={(event) => onCollectiveCorePromptChange(event.target.value)}
              />
            </label>
          </details>
          <details className="setup-collapsible-section bulk-overview-section section-accent-model">
            <summary className="setup-section-summary">
              <h2>一键配置总览</h2>
              <span>{selectedBulkTargetIndexes.length ? `已选 ${selectedBulkTargetIndexes.length}/${safeAgentCount} 个 Agent` : "未选择目标 Agent"}</span>
            </summary>
            <div className="bulk-overview-panel">
              <div className="bulk-target-panel">
                <div className="bulk-overview-heading">
                  <strong>目标 Agent</strong>
                  <span>下面的“应用到选中”只改这里勾选的人。</span>
                </div>
                <div className="bulk-target-actions">
                  <button type="button" onClick={() => setBulkTargetIndexes(allAgentIndexes)}>全选目标</button>
                  <button type="button" onClick={() => setBulkTargetIndexes([])}>清空目标</button>
                </div>
                <div className="bulk-target-grid">
                  {normalizedAgentConfigs.map((config, index) => (
                    <label key={`bulk-target-${index}`}>
                      <input
                        type="checkbox"
                        checked={selectedBulkTargetSet.has(index)}
                        onChange={(event) => setBulkTarget(index, event.target.checked)}
                      />
                      {config.chosenName.trim() || `Agent ${index + 1}`}
                    </label>
                  ))}
                </div>
              </div>
              <div className="bulk-overview-actions">
                <section>
                  <h3>模型</h3>
                  <label>
                    提供商
                    <select key={`bulk-provider-${providerDisplaySignature}`} value={effectiveBulkProviderId} title={bulkProvider?.name ?? ""} onChange={(event) => {
                      setBulkProviderId(event.target.value);
                      setBulkModelName("");
                    }}>
                      {providers.map((item) => <option key={item.providerId} value={item.providerId} title={item.name}>{item.name}</option>)}
                    </select>
                  </label>
                  <label>
                    模型
                    <ModelPicker
                      value={bulkModelName}
                      models={bulkProvider?.models ?? []}
                      emptyLabel={allPulledModelEntries.length ? "默认混用: 随机抽真实模型" : "默认混用"}
                      searchPlaceholder="搜索模型名"
                      onChange={setBulkModelName}
                    />
                  </label>
                  <div className="bulk-overview-button-row">
                    <button type="button" onClick={() => applyBulkModelToIndexes(allAgentIndexes, false)}>应用到全部</button>
                    <button type="button" disabled={!selectedBulkTargetIndexes.length} onClick={() => applyBulkModelToIndexes(selectedBulkTargetIndexes, false)}>应用到选中</button>
                  </div>
                </section>
                <section>
                  <h3>运行参数</h3>
                  <div className="bulk-overview-button-row">
                    <button type="button" onClick={loadBulkRuntimeFromProvider}>读取当前提供商参数</button>
                  </div>
                  <div className="bulk-runtime-grid">
                    <label>
                      重试次数
                      <input type="number" min="0" max="100000" value={bulkRuntime.retryCount} onChange={(event) => setBulkRuntime({ ...bulkRuntime, retryCount: Number(event.target.value) })} />
                    </label>
                    <label>
                      重试间隔 ms
                      <input type="number" min="0" max="21600000" step="100" value={bulkRuntime.retryIntervalMs} onChange={(event) => setBulkRuntime({ ...bulkRuntime, retryIntervalMs: Number(event.target.value) })} />
                    </label>
                    <label>
                      请求超时 ms
                      <input type="number" min="0" max="86400000" step="1000" value={bulkRuntime.requestTimeoutMs} onChange={(event) => setBulkRuntime({ ...bulkRuntime, requestTimeoutMs: Number(event.target.value) })} />
                    </label>
                    <label>
                      RPM
                      <input type="number" min="0" max="100000" value={bulkRuntime.rpm} onChange={(event) => setBulkRuntime({ ...bulkRuntime, rpm: Number(event.target.value) })} />
                    </label>
                  </div>
                  <div className="bulk-overview-button-row">
                    <button type="button" onClick={() => applyBulkRuntimeToProviders([effectiveBulkProviderId])}>运行参数到当前提供商</button>
                    <button type="button" onClick={() => applyBulkRuntimeToProviders(providers.map((provider) => provider.providerId))}>运行参数到全部提供商</button>
                  </div>
                </section>
                <section>
                  <h3>随机模型</h3>
                  <div className="bulk-random-list-actions">
                    {validRandomModelLists.length ? validRandomModelLists.map((list) => (
                      <div className="bulk-random-list-action-row" key={`bulk-random-action-${list.id}`}>
                        <span>{list.name} · {list.entries.length} 个模型</span>
                        <button type="button" disabled={!list.entries.length} onClick={() => applyBulkRandomModelListToIndexes(list, allAgentIndexes, false)}>应用到全部</button>
                        <button type="button" disabled={!list.entries.length || !selectedBulkTargetIndexes.length} onClick={() => applyBulkRandomModelListToIndexes(list, selectedBulkTargetIndexes, false)}>应用到选中</button>
                      </div>
                    )) : <p className="model-count">还没有随机模型列表。</p>}
                  </div>
                </section>
                <section>
                  <h3>工具与加点</h3>
                  <label>
                    工具上下文
                    <select value={bulkToolContextMode} onChange={(event) => setBulkToolContextMode(event.target.value === "all" ? "all" : "dynamic")}>
                      <option value="dynamic">动态工具</option>
                      <option value="all">固定工具集</option>
                    </select>
                  </label>
                  <label>
                    加点方式
                    <select value={bulkTraitMode} onChange={(event) => setBulkTraitMode(normalizeAgentTraitMode(event.target.value))}>
                      {AGENT_TRAIT_MODE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                    </select>
                  </label>
                  <div className="bulk-overview-button-row">
                    <button type="button" onClick={() => applyBulkToolContextToIndexes(allAgentIndexes)}>工具模式到全部</button>
                    <button type="button" disabled={!selectedBulkTargetIndexes.length} onClick={() => applyBulkToolContextToIndexes(selectedBulkTargetIndexes)}>工具模式到选中</button>
                    <button type="button" onClick={() => applyBulkTraitModeToIndexes(allAgentIndexes)}>加点到全部</button>
                    <button type="button" disabled={!selectedBulkTargetIndexes.length} onClick={() => applyBulkTraitModeToIndexes(selectedBulkTargetIndexes)}>加点到选中</button>
                  </div>
                </section>
                <section>
                  <h3>特殊工具集</h3>
                  <div className="bulk-overview-button-row">
                    <button type="button" onClick={() => setAgentToolsetsForIndexes("all", allAgentIndexes)}>全员全选工具集</button>
                    <button type="button" onClick={() => setAgentToolsetsForIndexes("none", allAgentIndexes)}>全员清空工具集</button>
                    <button type="button" disabled={!selectedBulkTargetIndexes.length} onClick={() => setAgentToolsetsForIndexes("all", selectedBulkTargetIndexes)}>选中全选工具集</button>
                    <button type="button" disabled={!selectedBulkTargetIndexes.length} onClick={() => setAgentToolsetsForIndexes("none", selectedBulkTargetIndexes)}>选中清空工具集</button>
                  </div>
                </section>
                <section>
                  <h3>初始认识</h3>
                  <div className="bulk-overview-button-row">
                    <button type="button" onClick={() => setAgentKnowledgeForIndexes("all", allAgentIndexes)}>全员认识所有人</button>
                    <button type="button" onClick={() => setAgentKnowledgeForIndexes("none", allAgentIndexes)}>全员不认识任何人</button>
                    <button type="button" disabled={!selectedBulkTargetIndexes.length} onClick={() => setAgentKnowledgeForIndexes("all", selectedBulkTargetIndexes)}>选中认识所有人</button>
                    <button type="button" disabled={!selectedBulkTargetIndexes.length} onClick={() => setAgentKnowledgeForIndexes("none", selectedBulkTargetIndexes)}>选中不认识任何人</button>
                  </div>
                </section>
                <section>
                  <h3>一键 TTS</h3>
                  <label className="toggle-inline">
                    <input type="checkbox" checked={bulkTtsConfig.enabled} onChange={(event) => updateBulkTts({ enabled: event.target.checked })} />
                    启用 TTS
                  </label>
                  <label>
                    类型
                    <select value={bulkTtsConfig.mode} onChange={(event) => updateBulkTts({ mode: event.target.value as TtsConfigDraft["mode"] })}>
                      <option value="gptsovits">GPT-SoVITS</option>
                      <option value="openai">{tr("OpenAI 兼容")}</option>
                      <option value="mimo">Mimo TTS</option>
                      <option value="qwen_dashscope">Qwen / DashScope</option>
                    </select>
                  </label>
                  <label>
                    名称
                    <input value={bulkTtsConfig.provider} placeholder="例如 GPT-SoVITS 本地" onChange={(event) => updateBulkTts({ provider: event.target.value })} />
                  </label>
                  <label>
                    Base URL
                    <input value={bulkTtsConfig.baseUrl} placeholder="填写 TTS 服务地址" onChange={(event) => updateBulkTts({ baseUrl: event.target.value })} />
                  </label>
                  <label>
                    接口路径
                    <input value={bulkTtsConfig.endpointPath} placeholder={bulkTtsConfig.mode === "openai" ? "/audio/speech" : "/tts"} onChange={(event) => updateBulkTts({ endpointPath: event.target.value })} />
                  </label>
                  <label>
                    API Key
                    <input type="password" value={bulkTtsConfig.apiKey} placeholder="本地服务可留空" onChange={(event) => updateBulkTts({ apiKey: event.target.value })} />
                  </label>
                  <label>
                    模型
                    <input value={bulkTtsConfig.model} placeholder={bulkTtsConfig.mode === "qwen_dashscope" ? "qwen3-tts-flash" : bulkTtsConfig.mode === "openai" ? "tts-1" : ""} onChange={(event) => updateBulkTts({ model: event.target.value })} />
                  </label>
                  <label>
                    音色
                    <input value={bulkTtsConfig.voice} placeholder={bulkTtsConfig.mode === "qwen_dashscope" ? "Cherry" : "alloy / voice id"} onChange={(event) => updateBulkTts({ voice: event.target.value })} />
                  </label>
                  <div className="bulk-overview-button-row">
                    <button type="button" onClick={loadBulkTtsFromActiveAgent}>读取当前 Agent TTS</button>
                    <button type="button" onClick={() => applyBulkTtsToIndexes(allAgentIndexes)}>TTS 到全部</button>
                    <button type="button" disabled={!selectedBulkTargetIndexes.length} onClick={() => applyBulkTtsToIndexes(selectedBulkTargetIndexes)}>TTS 到选中</button>
                    <button type="button" onClick={() => clearBulkTtsForIndexes(allAgentIndexes)}>全员关闭 TTS</button>
                    <button type="button" disabled={!selectedBulkTargetIndexes.length} onClick={() => clearBulkTtsForIndexes(selectedBulkTargetIndexes)}>选中关闭 TTS</button>
                  </div>
                </section>
                {expertMode && (
                  <section>
                    <h3>LLM 输出参数</h3>
                    <label>
                      历史配置
                      <select value="" onChange={(event) => applyLlmHistory(event.target.value)}>
                        <option value="">选择历史 LLM 输出参数</option>
                        {llmHistory.map((item) => <option key={item.id} value={item.id}>{item.pinned ? "★ " : ""}{item.name}</option>)}
                      </select>
                    </label>
                    <label className="toggle-inline">
                      <input type="checkbox" checked={globalLlmGeneration.stream} onChange={(event) => updateGlobalLlmGeneration({ stream: event.target.checked })} />
                      {text("流式输出", "Streaming output")}
                    </label>
                    <div className="bulk-llm-compact-grid">
                      <label>
                        Temperature
                        <input type="number" min="0" max="2" step="0.05" value={globalLlmGeneration.temperature} onChange={(event) => updateGlobalLlmGeneration({ temperature: Number(event.target.value) })} />
                      </label>
                      <label>
                        Top P
                        <input type="number" min="0" max="1" step="0.05" value={globalLlmGeneration.top_p} onChange={(event) => updateGlobalLlmGeneration({ top_p: Number(event.target.value) })} />
                      </label>
                      <label>
                        Max tokens
                        <input type="number" min="0" max="200000" step="128" value={globalLlmGeneration.max_tokens} onChange={(event) => updateGlobalLlmGeneration({ max_tokens: Number(event.target.value) })} />
                      </label>
                      <label>
                        Presence penalty
                        <input type="number" min="-2" max="2" step="0.1" value={globalLlmGeneration.presence_penalty} onChange={(event) => updateGlobalLlmGeneration({ presence_penalty: Number(event.target.value) })} />
                      </label>
                      <label>
                        Frequency penalty
                        <input type="number" min="-2" max="2" step="0.1" value={globalLlmGeneration.frequency_penalty} onChange={(event) => updateGlobalLlmGeneration({ frequency_penalty: Number(event.target.value) })} />
                      </label>
                    </div>
                    <div className="bulk-overview-button-row">
                      <button type="button" onClick={saveLlmHistory}>保存当前 LLM 参数</button>
                    </div>
                  </section>
                )}
                <section className="bulk-archive-reuse-section">
                  <h3>{text("导入、导出与复用", "Import, export, reuse")}</h3>
                  {renderArchiveReuseControls("overview")}
                </section>
              </div>
            </div>
          </details>
          {(werewolfEnabled || worldviewId === WEREWOLF_WORLDVIEW_ID) && (
            <details className="setup-collapsible-section werewolf-role-section section-accent-werewolf" open>
              <summary className="setup-section-summary">
                <h2>狼人杀身份分配</h2>
                <span>{werewolfConfig.mode === "auto" ? "自动分配" : werewolfConfig.mode === "counts" ? `决定身份数 · ${werewolfCountTotal}/${safeAgentCount}` : "手动分配"}</span>
              </summary>
              <div className="werewolf-role-config">
                <div className="werewolf-role-heading">
                  <strong>分配方式</strong>
                  <span>
                    {werewolfConfig.mode === "auto" ? "从勾选角色池自动分配" : werewolfConfig.mode === "counts" ? "按你指定的身份数量随机分配给居民" : "逐个 Agent 指定身份"}
                  </span>
                </div>
                <div className="segmented-control werewolf-role-mode">
                  <button type="button" className={werewolfConfig.mode === "auto" ? "active" : ""} onClick={() => updateWerewolfConfig({ mode: "auto" })}>自动分配</button>
                  <button type="button" className={werewolfConfig.mode === "counts" ? "active" : ""} onClick={() => updateWerewolfConfig({ mode: "counts" })}>决定身份数</button>
                  <button type="button" className={werewolfConfig.mode === "manual" ? "active" : ""} onClick={() => updateWerewolfConfig({ mode: "manual" })}>手动分配</button>
                </div>
                {werewolfConfig.mode === "auto" && (
                  <div className="werewolf-auto-role-list">
                    {WEREWOLF_ROLE_OPTIONS.map((role) => {
                      const checked = selectedAutoRoles.has(role.value);
                      const disabled = role.core || (!checked && !canAddAutoRole(role.value));
                      const reason = role.core ? "核心身份" : safeAgentCount < role.minPlayers ? `至少 ${role.minPlayers} 人` : (!checked && selectedAutoRequiredSlots + 1 > safeAgentCount ? "人数已满" : "可选");
                      return (
                        <label key={role.value} className={disabled ? "disabled" : ""}>
                          <input
                            type="checkbox"
                            checked={checked}
                            disabled={disabled}
                            onChange={(event) => updateWerewolfAutoRole(role.value, event.target.checked)}
                          />
                          <span>{role.label}</span>
                          <em>{reason}</em>
                        </label>
                      );
                    })}
                    <p className="model-count">
                      自动分配只会从已勾选且人数足够的职业中抽取；默认角色池为平民、狼人、预言家、验尸官、守卫。
                    </p>
                  </div>
                )}
                {werewolfConfig.mode === "counts" && (
                  <div className="werewolf-role-count-grid">
                    {WEREWOLF_ROLE_OPTIONS.map((role) => {
                      const value = werewolfConfig.counts[role.value];
                      const usedByOthers = werewolfCountTotal - value;
                      const maxForRole = Math.max(0, safeAgentCount - usedByOthers);
                      return (
                        <label key={role.value} className="werewolf-role-slider">
                          <span>{role.label}</span>
                          <input
                            type="range"
                            min="0"
                            max={maxForRole}
                            value={Math.min(value, maxForRole)}
                            onChange={(event) => updateWerewolfRoleCount(role.value, Number(event.target.value))}
                          />
                          <output>{Math.min(value, maxForRole)}</output>
                        </label>
                      );
                    })}
                    <p className="model-count">
                      已分配 {Math.min(werewolfCountTotal, safeAgentCount)}/{safeAgentCount}；剩余 {Math.max(0, safeAgentCount - werewolfCountTotal)} 人会自动补平民。人数满时滑条会停住。
                    </p>
                  </div>
                )}
                {werewolfConfig.mode === "manual" && (
                  <div className="werewolf-manual-role-list">
                    {Array.from({ length: safeAgentCount }, (_, index) => (
                      <label key={index}>
                        <span>{normalizedAgentConfigs[index]?.chosenName.trim() || `Agent ${index + 1}`}</span>
                        <select value={werewolfConfig.manualRoles[index] ?? "villager"} onChange={(event) => updateWerewolfManualRole(index, event.target.value as WerewolfRole)}>
                          {WEREWOLF_ROLE_OPTIONS.map((role) => <option key={role.value} value={role.value}>{role.label}</option>)}
                        </select>
                      </label>
                    ))}
                  </div>
                )}
              </div>
            </details>
          )}
          {allowBirth && (
            <details className="setup-collapsible-section baby-config-section section-accent-baby">
              <summary className="setup-section-summary">
                <h2>宝宝 Agent 模型池</h2>
                <span>{normalizedBabyConfigs.length ? `${normalizedBabyConfigs.length} 个模型` : "继承居民模型"}</span>
              </summary>
              <div className="section-heading section-heading-actions-only">
                <button type="button" title="添加宝宝模型" onClick={addBabyModel}><Plus size={15} /></button>
              </div>
              <div className="baby-model-list">
                {normalizedBabyConfigs.length ? normalizedBabyConfigs.map((config, index) => {
                  const provider = providers.find((item) => item.providerId === config.providerId) ?? providers[0];
                  return (
                    <div className="baby-model-row" key={`${config.providerId}-${index}`}>
                      <label>
                        提供商
                        <select key={`baby-provider-${index}-${providerDisplaySignature}`} value={config.providerId} title={provider?.name ?? ""} onChange={(event) => updateBabyModel(index, { providerId: event.target.value, modelName: "" })}>
                          {providers.map((item) => <option key={item.providerId} value={item.providerId} title={item.name}>{item.name}</option>)}
                        </select>
                      </label>
                      <label>
                        模型
                        <ModelPicker
                          value={config.modelName}
                          models={provider?.models ?? []}
                          emptyLabel="不指定"
                          searchPlaceholder="搜索宝宝模型"
                          onChange={(modelName) => updateBabyModel(index, { modelName })}
                        />
                      </label>
                      <button type="button" title="删除" onClick={() => removeBabyModel(index)}>
                        <Trash2 size={15} />
                      </button>
                    </div>
                  );
                }) : <p className="model-count">未指定时，出生会继承现有居民模型。</p>}
              </div>
            </details>
          )}
        </div>}
      </div>
      {expertMode && (
        <section className="setup-collapsible-section archive-reuse-standalone section-accent-reuse">
          <div className="setup-section-summary archive-reuse-heading">
            <h2>{text("导入、导出与复用", "Import, export, reuse")}</h2>
            <span>{text("人员配置文件和历史存档复用", "Agent archives and saved-world reuse")}</span>
          </div>
          {renderArchiveReuseControls()}
        </section>
      )}
      {expertMode && (
        <details className="setup-collapsible-section llm-generation-section section-accent-llm">
          <summary className="setup-section-summary">
            <h2>LLM 输出参数 · 全局默认</h2>
            <span>高级参数</span>
          </summary>
          <div className="history-picker-row">
            <label>
              历史配置
              <select value="" onChange={(event) => applyLlmHistory(event.target.value)}>
                <option value="">选择历史 LLM 输出参数</option>
                {llmHistory.map((item) => <option key={item.id} value={item.id}>{item.pinned ? "★ " : ""}{item.name}</option>)}
              </select>
            </label>
            <button type="button" onClick={saveLlmHistory}>保存当前 LLM 参数</button>
          </div>
          <div className="llm-generation-grid">
            <label className="toggle-inline">
              <input type="checkbox" checked={globalLlmGeneration.stream} onChange={(event) => updateGlobalLlmGeneration({ stream: event.target.checked })} />
              {text("流式输出", "Streaming output")}
            </label>
            <label>
              Temperature
              <input type="number" min="0" max="2" step="0.05" value={globalLlmGeneration.temperature} onChange={(event) => updateGlobalLlmGeneration({ temperature: Number(event.target.value) })} />
            </label>
            <label>
              Top P
              <input type="number" min="0" max="1" step="0.05" value={globalLlmGeneration.top_p} onChange={(event) => updateGlobalLlmGeneration({ top_p: Number(event.target.value) })} />
            </label>
            <label>
              Max tokens
              <input type="number" min="0" max="200000" step="128" value={globalLlmGeneration.max_tokens} onChange={(event) => updateGlobalLlmGeneration({ max_tokens: Number(event.target.value) })} />
            </label>
            <label>
              Presence penalty
              <input type="number" min="-2" max="2" step="0.1" value={globalLlmGeneration.presence_penalty} onChange={(event) => updateGlobalLlmGeneration({ presence_penalty: Number(event.target.value) })} />
            </label>
            <label>
              Frequency penalty
              <input type="number" min="-2" max="2" step="0.1" value={globalLlmGeneration.frequency_penalty} onChange={(event) => updateGlobalLlmGeneration({ frequency_penalty: Number(event.target.value) })} />
            </label>
          </div>
          <p className="model-count">{text("这些是全体 Agent 默认值；每个 Agent 下面可以单独覆盖，默认收起以免设置界面继续变乱。", "These are global defaults; each agent can override them below. The panel stays collapsed to keep the setup screen readable.")}</p>
        </details>
      )}

      <details className="setup-collapsible-section agent-identity-section section-accent-agent" open>
        <summary className="setup-section-summary">
          <h2>Agent 模型与身份</h2>
          <span>{safeAgentCount} 个居民</span>
          {!expertMode && (
            <span className="beginner-summary-markers">
              <em className="beginner-marker marker-model">{text("紫色: 批量模型", "Purple: bulk model")}</em>
              <em className="beginner-marker marker-agent">{text("橙色: 逐个角色", "Orange: per character")}</em>
              <em className="beginner-marker marker-reuse">{text("靛色: 复用", "Indigo: reuse")}</em>
            </span>
          )}
        </summary>
        <details className="setup-subsection section-accent-model" open>
          <summary className="setup-subsection-summary">
            <h3>{text("批量与一键配置", "Bulk setup")}</h3>
            <span>{text("模型、随机模型、工具集批量按钮", "Models, random models, bulk buttons")}</span>
            {!expertMode && (
              <span className="beginner-summary-markers">
                <em className="beginner-marker marker-model">{text("紫色: 给全部居民选模型", "Purple: choose all models")}</em>
              </span>
            )}
          </summary>
          <div className="bulk-setup-workspace">
            {expertMode && (
              <section className="bulk-setup-card bulk-target-card">
                <div className="bulk-setup-card-head">
                  <div className="bulk-card-title">
                    <div>
                      <h4>应用范围</h4>
                      <span>{selectedBulkTargetIndexes.length}/{safeAgentCount} 个 Agent</span>
                    </div>
                  </div>
                  <div className="bulk-action-group">
                    <button type="button" onClick={() => setBulkTargetIndexes(allAgentIndexes)}>全选</button>
                    <button type="button" onClick={() => setBulkTargetIndexes([])}>清空</button>
                  </div>
                </div>
                <div className="bulk-target-grid bulk-target-grid-compact">
                  {normalizedAgentConfigs.map((config, index) => (
                    <label key={`identity-bulk-target-${index}`}>
                      <input
                        type="checkbox"
                        checked={selectedBulkTargetSet.has(index)}
                        onChange={(event) => setBulkTarget(index, event.target.checked)}
                      />
                      <span>{config.chosenName.trim() || `Agent ${index + 1}`}</span>
                    </label>
                  ))}
                </div>
              </section>
            )}
            <section className="bulk-setup-card bulk-setup-card-primary">
              <div className="bulk-setup-card-head">
                <div className="bulk-card-title">
                  <div>
                    <h4>{text("统一模型", "Same model")}</h4>
                    <span>{bulkProvider?.name || text("未选提供商", "No provider")} · {bulkModelName || (allPulledModelEntries.length ? "默认混用" : "未指定")}</span>
                  </div>
                </div>
                <div className="bulk-action-group">
                  <button type="button" className="bulk-primary-action" onClick={() => applyBulkModelToIndexes(allAgentIndexes, !expertMode)}>
                    应用到全部
                  </button>
                  {expertMode && (
                    <button type="button" disabled={!selectedBulkTargetIndexes.length} onClick={() => applyBulkModelToIndexes(selectedBulkTargetIndexes, false)}>
                      应用到选中
                    </button>
                  )}
                </div>
              </div>
              <div className="bulk-field-grid">
                <label>
                  <span>提供商</span>
                  <select key={`identity-bulk-provider-${providerDisplaySignature}`} value={effectiveBulkProviderId} title={bulkProvider?.name ?? ""} onChange={(event) => {
                    setBulkProviderId(event.target.value);
                    setBulkModelName("");
                  }}>
                    {providers.map((item) => <option key={item.providerId} value={item.providerId} title={item.name}>{item.name}</option>)}
                  </select>
                </label>
                <label>
                  <span>模型</span>
                  <ModelPicker
                    value={bulkModelName}
                    models={bulkProvider?.models ?? []}
                    emptyLabel={allPulledModelEntries.length ? "默认混用: 随机抽真实模型" : "默认混用"}
                    searchPlaceholder="搜索模型名"
                    onChange={setBulkModelName}
                  />
                </label>
              </div>
              <div className="bulk-history-strip">
                <label>
                  <span>{text("历史配置", "History")}</span>
                  <select value="" onChange={(event) => applyRuntimeHistory(event.target.value)}>
                    <option value="">{text("选择历史一键模型配置", "Choose saved bulk model setup")}</option>
                    {runtimeHistory.map((item) => <option key={item.id} value={item.id}>{item.pinned ? "★ " : ""}{item.name}</option>)}
                  </select>
                </label>
                <button type="button" onClick={saveRuntimeHistory}>{text("保存当前配置", "Save setup")}</button>
              </div>
            </section>

            {expertMode && (
              <section className="bulk-setup-card bulk-random-card">
                <div className="bulk-setup-card-head">
                  <div className="bulk-card-title">
                    <div>
                      <h4>随机模型池</h4>
                      <span>{validRandomModelLists.length ? `${validRandomModelLists.length} 个列表` : "无列表"}</span>
                    </div>
                  </div>
                  <button type="button" title="创建随机模型列表" onClick={addRandomModelList}><Plus size={15} /> 新建列表</button>
                </div>
                <div className="random-model-list">
                {randomModelLists.length ? randomModelLists.map((list) => {
                    const usableEntryCount = usableRandomModelEntries(list).length;
                    return (
                    <details className="random-model-card" key={list.id}>
                      <summary className="random-model-card-heading">
                      <label>
                        <span>列表名称</span>
                        <input
                          value={list.name}
                          onClick={(event) => event.stopPropagation()}
                          onChange={(event) => updateRandomModelList(list.id, { name: event.target.value })}
                        />
                      </label>
                      <span className="random-model-card-count">{usableEntryCount}/{list.entries.length} 可用</span>
                      <div className="random-model-card-actions">
                        <button type="button" className="bulk-primary-action" disabled={!usableEntryCount} onClick={(event) => {
                          event.stopPropagation();
                          applyBulkRandomModelListToIndexes(list, allAgentIndexes, false);
                        }}>应用到全部</button>
                        <button type="button" disabled={!usableEntryCount || !selectedBulkTargetIndexes.length} onClick={(event) => {
                          event.stopPropagation();
                          applyBulkRandomModelListToIndexes(list, selectedBulkTargetIndexes, false);
                        }}>应用到选中</button>
                      </div>
                      <button type="button" title="添加模型" onClick={(event) => {
                        event.stopPropagation();
                        addRandomModelEntry(list.id);
                      }}><Plus size={15} /></button>
                      <button type="button" title="删除列表" onClick={(event) => {
                        event.stopPropagation();
                        removeRandomModelList(list.id);
                      }}><Trash2 size={15} /></button>
                    </summary>
                      <div className="random-model-entry-list">
                        {list.entries.length ? list.entries.map((entry) => {
                          const entryProvider = providers.find((provider) => provider.providerId === entry.providerId) ?? providers[0];
                          return (
                            <div className="random-model-entry-row" key={entry.id}>
                              <label>
                                <span>提供商</span>
                                <select
                                  key={`random-entry-provider-${entry.id}-${providerDisplaySignature}`}
                                  value={entry.providerId || fallbackProviderId}
                                  title={entryProvider?.name ?? ""}
                                  onChange={(event) => updateRandomModelEntry(list.id, entry.id, { providerId: event.target.value, modelName: "" })}
                                >
                                  {providers.map((provider) => <option key={provider.providerId} value={provider.providerId} title={provider.name}>{provider.name}</option>)}
                                </select>
                              </label>
                              <label>
                                <span>模型</span>
                                <ModelPicker
                                  value={entry.modelName}
                                  models={entryProvider?.models ?? []}
                                  emptyLabel="选择模型"
                                  searchPlaceholder="搜索模型名"
                                  onChange={(modelName) => updateRandomModelEntry(list.id, entry.id, { modelName })}
                                />
                              </label>
                              <button type="button" title="删除模型" onClick={() => removeRandomModelEntry(list.id, entry.id)}>
                                <Trash2 size={15} />
                              </button>
                            </div>
                          );
                        }) : <p className="model-count">这个列表还没有模型。</p>}
                      </div>
                    </details>
                  );
                  }) : <p className="model-count">还没有随机模型列表。</p>}
                </div>
              </section>
            )}

            {expertMode && (
              <section className="bulk-setup-card bulk-advanced-card">
                <div className="bulk-setup-card-head">
                  <div className="bulk-card-title">
                    <div>
                      <h4>其他批量设置</h4>
                      <span>工具、加点、运行参数</span>
                    </div>
                  </div>
                </div>
                <div className="bulk-advanced-grid">
                  <label>
                    <span>工具上下文</span>
                    <select value={bulkToolContextMode} onChange={(event) => setBulkToolContextMode(event.target.value === "all" ? "all" : "dynamic")}>
                      <option value="dynamic">动态工具</option>
                      <option value="all">固定工具集</option>
                    </select>
                  </label>
                  <div className="bulk-action-group">
                    <button type="button" onClick={() => applyBulkToolContextToIndexes(allAgentIndexes)}>到全部</button>
                    <button type="button" disabled={!selectedBulkTargetIndexes.length} onClick={() => applyBulkToolContextToIndexes(selectedBulkTargetIndexes)}>到选中</button>
                  </div>
                  <label>
                    <span>加点方式</span>
                    <select value={bulkTraitMode} onChange={(event) => setBulkTraitMode(normalizeAgentTraitMode(event.target.value))}>
                      {AGENT_TRAIT_MODE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                    </select>
                  </label>
                  <div className="bulk-action-group">
                    <button type="button" onClick={() => applyBulkTraitModeToIndexes(allAgentIndexes)}>到全部</button>
                    <button type="button" disabled={!selectedBulkTargetIndexes.length} onClick={() => applyBulkTraitModeToIndexes(selectedBulkTargetIndexes)}>到选中</button>
                  </div>
                  <label>
                    <span>重试次数</span>
                    <input type="number" min="0" max="100000" value={bulkRuntime.retryCount} onChange={(event) => setBulkRuntime({ ...bulkRuntime, retryCount: Number(event.target.value) })} />
                  </label>
                  <div className="bulk-action-group">
                    <button type="button" onClick={loadBulkRuntimeFromProvider}>读取参数</button>
                    <button type="button" onClick={() => applyBulkRuntimeToProviders([effectiveBulkProviderId])}>到当前提供商</button>
                    <button type="button" onClick={() => applyBulkRuntimeToProviders(providers.map((provider) => provider.providerId))}>到全部提供商</button>
                  </div>
                  <div className="bulk-action-group bulk-advanced-full">
                    <button type="button" onClick={() => setAgentToolsetsForIndexes("all", allAgentIndexes)}>全员全选工具集</button>
                    <button type="button" onClick={() => setAgentToolsetsForIndexes("none", allAgentIndexes)}>全员清空工具集</button>
                    <button type="button" disabled={!selectedBulkTargetIndexes.length} onClick={() => setAgentToolsetsForIndexes("all", selectedBulkTargetIndexes)}>选中全选工具集</button>
                    <button type="button" disabled={!selectedBulkTargetIndexes.length} onClick={() => setAgentToolsetsForIndexes("none", selectedBulkTargetIndexes)}>选中清空工具集</button>
                  </div>
                </div>
              </section>
            )}
          </div>
        </details>
        {!expertMode && <details className="setup-subsection section-accent-reuse">
          <summary className="setup-subsection-summary">
            <h3>{text("导入、导出与复用", "Import, export, reuse")}</h3>
            <span>{text("人员配置文件和历史存档复用", "Agent archives and saved-world reuse")}</span>
            {!expertMode && (
              <span className="beginner-summary-markers">
                <em className="beginner-marker marker-reuse">{text("靛色: 复用旧存档人员", "Indigo: reuse saved residents")}</em>
              </span>
            )}
          </summary>
          {renderArchiveReuseControls()}
        </details>}
        <section className="agent-config-inline-section section-accent-agent-detail">
          <div className="agent-config-inline-heading">
            <h3>{text("逐个 Agent 配置", "Per-agent setup")}</h3>
            <span>{text("姓名、外貌、头像、个人提示词", "Names, appearances, avatars, prompts")}</span>
            {!expertMode && (
              <span className="beginner-summary-markers">
                <em className="beginner-marker marker-agent">{text("橙色: 可选角色信息", "Orange: optional character info")}</em>
              </span>
            )}
          </div>
        <div className="agent-config-tabs" role="tablist" aria-label={text("逐个 Agent 配置", "Per-agent setup")}>
          {normalizedAgentConfigs.map((config, index) => {
            const provider = providers.find((item) => item.providerId === config.providerId) ?? providers[0];
            const active = activeAgentConfigIndex === index;
            const expanded = active && activeAgentConfigOpen;
            const title = [
              config.chosenName.trim() || `Agent ${index + 1}`,
              provider?.name || text("未选提供商", "No provider"),
              config.modelName.trim() || text("默认混用", "Default mix")
            ].join(" · ");
            return (
              <button
                key={`agent-tab-${index}`}
                type="button"
                className={`agent-config-tab${active ? " active" : ""}`}
                role="tab"
                aria-selected={active}
                aria-expanded={expanded}
                title={title}
                onClick={() => {
                  if (active) {
                    setActiveAgentConfigOpen((open) => !open);
                    return;
                  }
                  setActiveAgentConfigIndex(index);
                  setActiveAgentConfigOpen(true);
                }}
              >
                <strong>Agent {index + 1}</strong>
                <span>{config.chosenName.trim() || provider?.name || text("默认混用", "Default mix")}</span>
              </button>
            );
          })}
        </div>
        <div className={`agent-config-list ${expertMode ? "" : "beginner-agent-config-list"}`}>
          {normalizedAgentConfigs.map((config, index) => {
            if (index !== activeAgentConfigIndex || !activeAgentConfigOpen) return null;
            const provider = providers.find((item) => item.providerId === config.providerId) ?? providers[0];
            const agentTraitMode = effectiveTraitMode(config);
            const agentSummary = [
              config.chosenName.trim() || `Agent ${index + 1}`,
              provider?.name || text("未选提供商", "No provider"),
              config.modelName.trim() || text("默认混用", "Default mix")
            ].join(" · ");
            return (
              <details className="agent-config-row agent-config-active-row" key={index} open={activeAgentConfigOpen} onToggle={(event) => setActiveAgentConfigOpen(event.currentTarget.open)}>
                <summary className="agent-config-summary">
                  <h4>Agent {index + 1}</h4>
                  <span>{agentSummary}</span>
                  {!expertMode && <em className="beginner-marker marker-agent">{text("橙色: 可选角色信息", "Orange: optional character info")}</em>}
                </summary>
                <div className="agent-config-body">
                <div className="agent-config-main-column">
                {expertMode && <label>
                  提供商
                  <select key={`agent-provider-${index}-${providerDisplaySignature}`} value={config.providerId} title={provider?.name ?? ""} onChange={(event) => updateAgent(index, { providerId: event.target.value, modelName: "" })}>
                    {providers.map((item) => <option key={item.providerId} value={item.providerId} title={item.name}>{item.name}</option>)}
                  </select>
                </label>}
                {expertMode && <label>
                  模型
                  <ModelPicker
                    value={config.modelName}
                    models={provider?.models ?? []}
                    emptyLabel="默认混用"
                    searchPlaceholder="搜索模型名"
                    onChange={(modelName) => updateAgent(index, { modelName })}
                  />
                </label>}
                {expertMode && <label>
                  工具上下文
                  <select value={config.toolContextMode} onChange={(event) => updateAgent(index, { toolContextMode: event.target.value === "all" ? "all" : "dynamic" })}>
                    <option value="dynamic">动态工具</option>
                    <option value="all">固定工具集</option>
                  </select>
                </label>}
                {expertMode && <label>
                  加点方式
                  <select value={config.traitMode} onChange={(event) => updateAgent(index, { traitMode: normalizeAgentTraitMode(event.target.value) })}>
                    {AGENT_TRAIT_MODE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.value === "inherit" ? `${traitModeLabel("inherit")} (${traitModeLabel(normalizedGlobalTraitMode)})` : traitModeLabel(option.value)}
                      </option>
                    ))}
                  </select>
                </label>}
                {expertMode && <div className="agent-toolset-picker">
                  <span>特殊工具集</span>
                  <div>
                    {agentSpecialToolsets.map((toolset) => (
                      <label key={`${index}-${toolset.toolset_id}`} title={toolset.description}>
                        <input
                          type="checkbox"
                          checked={config.agentToolsetIds.includes(toolset.toolset_id)}
                          onChange={(event) => toggleAgentToolset(index, toolset.toolset_id, event.target.checked)}
                        />
                        {tr(toolset.name.replace(/^特殊/, ""))}
                      </label>
                    ))}
                  </div>
                </div>}
                <label title={text("可选。留空时由 Agent 自己起名。", "Optional. Leave blank and the agent will name themselves.")}>
                  <span>{text("名字", "Name")}</span>
                  {!expertMode && <em className="beginner-marker marker-agent">{text("橙色: 不填会自动起名", "Orange: leave blank for auto name")}</em>}
                  <input value={config.chosenName} placeholder={text("留空则 agent 自己起名", "Leave blank for agent to name themselves")} onChange={(event) => updateAgent(index, { chosenName: event.target.value })} />
                </label>
                {imageGeneration.enabled && <label title="可选。给生图模型使用的角色标签或英文名；填写后，解说 AI 写绘图提示词时会用这里而不是显示名。">
                  <span>生图角色名</span>
                  <input value={config.imagePromptName} placeholder="例如 saki / character tag" onChange={(event) => updateAgent(index, { imagePromptName: event.target.value })} />
                </label>}
                <label title={text("可选。留空时由 Agent 自己生成外貌。", "Optional. Leave blank and the agent will generate their appearance.")}>
                  <span>{text("外貌", "Appearance")}</span>
                  {!expertMode && <em className="beginner-marker marker-agent">{text("橙色: 不填会自动生成", "Orange: leave blank for auto generation")}</em>}
                  <textarea value={config.appearance} placeholder={text("留空则 agent 自己生成外貌", "Leave blank for agent to generate appearance")} onChange={(event) => updateAgent(index, { appearance: event.target.value })} />
                </label>
                <div className="avatar-upload-row">
                  {config.avatarDataUrl ? <img src={config.avatarDataUrl} alt="" /> : <span>{(config.chosenName || `A${index + 1}`).slice(0, 1)}</span>}
                  <FileDropZone
                    accept="image/*"
                    className="avatar-drop-zone"
                    buttonClassName="avatar-upload-button"
                    onFile={(file) => readAvatarFile(index, file)}
                    hint={text("可拖入图片", "Drop image here")}
                  >
                    {text("上传头像", "Upload avatar")}
                  </FileDropZone>
                  <button type="button" onClick={() => updateAgent(index, { avatarDataUrl: "" })} disabled={!config.avatarDataUrl}>
                    {text("移除", "Remove")}
                  </button>
                </div>
                <div className="avatar-upload-row standing-upload-row">
                  {config.standingImageDataUrl ? <img src={config.standingImageDataUrl} alt="" /> : <span>{text("立绘", "Full")}</span>}
                  <FileDropZone
                    accept="image/*"
                    className="avatar-drop-zone"
                    buttonClassName="avatar-upload-button"
                    onFile={(file) => readStandingFile(index, file)}
                    hint={text("可拖入图片", "Drop image here")}
                  >
                    {text("上传立绘", "Upload standing")}
                  </FileDropZone>
                  <button type="button" onClick={() => updateAgent(index, { standingImageDataUrl: "" })} disabled={!config.standingImageDataUrl}>
                    {text("移除", "Remove")}
                  </button>
                </div>
                <label className="agent-system-prompt-field" title={text("可选。只影响这个居民的长期行为、说话方式和角色设定。", "Optional. Only affects this resident's long-term behavior, speaking style, and role definition.")}>
                  <span>{text("系统提示词", "System prompt")}</span>
                  {!expertMode && <em className="beginner-marker marker-agent">{text("橙色: 可选角色设定", "Orange: optional character setting")}</em>}
                  <textarea value={config.systemPrompt} placeholder={text("可给这个 agent 单独添加长期行为约束", "Optional long-term behavior constraints for this agent")} onChange={(event) => updateAgent(index, { systemPrompt: event.target.value })} />
                </label>
                </div>
                <div className="agent-config-side-column">
                {expertMode && <details className="agent-knowledge-config" open={config.knowledgeMode === "custom"}>
                  <summary>
                    初始认识与好感 · {config.knowledgeMode === "all" ? "认识所有人" : config.knowledgeMode === "custom" ? "手动设置" : "不认识任何人"}
                  </summary>
                  <div className="agent-knowledge-mode-row">
                    <button type="button" className={config.knowledgeMode === "all" ? "active" : ""} onClick={() => updateAgentKnowledgeMode(index, "all")}>认识所有人</button>
                    <button type="button" className={config.knowledgeMode === "none" ? "active" : ""} onClick={() => updateAgentKnowledgeMode(index, "none")}>不认识任何人</button>
                    <button type="button" className={config.knowledgeMode === "custom" ? "active" : ""} onClick={() => updateAgentKnowledgeMode(index, "custom")}>手动设置</button>
                  </div>
                  {config.knowledgeMode === "custom" && (
                    <div className="agent-knowledge-target-list">
                      {normalizedAgentConfigs.map((targetConfig, targetIndex) => {
                        if (targetIndex === index) return null;
                        const targetEntry = config.knownAgents[String(targetIndex)] ?? { knows: false, affection: 0 };
                        return (
                          <div className="agent-knowledge-target-row" key={`${index}-${targetIndex}`}>
                            <label className="toggle-inline">
                              <input
                                type="checkbox"
                                checked={targetEntry.knows}
                                onChange={(event) => updateAgentKnownTarget(index, targetIndex, { knows: event.target.checked })}
                              />
                              认识 {targetConfig.chosenName.trim() || `Agent ${targetIndex + 1}`}
                            </label>
                            <label>
                              初始好感
                              <input
                                type="number"
                                min="-100"
                                max="100"
                                step="1"
                                disabled={!targetEntry.knows}
                                value={targetEntry.affection}
                                onChange={(event) => updateAgentKnownTarget(index, targetIndex, { affection: Number(event.target.value) })}
                              />
                            </label>
                          </div>
                        );
                      })}
                    </div>
                  )}
                  <p className="model-count">被设置为认识的人，开局就知道名字和外貌，不需要先自我介绍才知道名字。</p>
                </details>}
                {expertMode && <details className="agent-llm-generation-config" open={Boolean(config.llmGeneration)}>
                  <summary>{config.llmGeneration ? "LLM 输出参数 · 单独覆盖" : "LLM 输出参数 · 跟随全局"}</summary>
                  {(() => {
                    const generation = normalizeLlmGeneration({ ...globalLlmGeneration, ...(config.llmGeneration ?? {}) });
                    return (
                      <div className="llm-generation-grid">
                        <label className="toggle-inline">
                          <input type="checkbox" checked={generation.stream} onChange={(event) => updateAgentLlmGeneration(index, { stream: event.target.checked })} />
                          流式输出
                        </label>
                        <label>Temperature<input type="number" min="0" max="2" step="0.05" value={generation.temperature} onChange={(event) => updateAgentLlmGeneration(index, { temperature: Number(event.target.value) })} /></label>
                        <label>Top P<input type="number" min="0" max="1" step="0.05" value={generation.top_p} onChange={(event) => updateAgentLlmGeneration(index, { top_p: Number(event.target.value) })} /></label>
                        <label>Max tokens<input type="number" min="0" max="200000" step="128" value={generation.max_tokens} onChange={(event) => updateAgentLlmGeneration(index, { max_tokens: Number(event.target.value) })} /></label>
                        <label>Presence penalty<input type="number" min="-2" max="2" step="0.1" value={generation.presence_penalty} onChange={(event) => updateAgentLlmGeneration(index, { presence_penalty: Number(event.target.value) })} /></label>
                        <label>Frequency penalty<input type="number" min="-2" max="2" step="0.1" value={generation.frequency_penalty} onChange={(event) => updateAgentLlmGeneration(index, { frequency_penalty: Number(event.target.value) })} /></label>
                        <button type="button" onClick={() => clearAgentLlmGeneration(index)} disabled={!config.llmGeneration}>恢复全局默认</button>
                      </div>
                    );
                  })()}
                </details>}
                {expertMode && <details className="agent-tts-config" open={config.ttsConfig.enabled}>
                  <summary>{tr(config.ttsConfig.enabled ? "Agent TTS 接口 · 已启用" : "Agent TTS 接口 · 可选")}</summary>
                  <div className="agent-tts-grid">
                    <label className="toggle-inline">
                      <input type="checkbox" checked={config.ttsConfig.enabled} onChange={(event) => updateAgentTts(index, { enabled: event.target.checked })} />
                      {tr("启用 TTS")}
                    </label>
                    <label>
                      {tr("类型")}
                      <select value={config.ttsConfig.mode} onChange={(event) => updateAgentTts(index, { mode: event.target.value as TtsConfigDraft["mode"] })}>
                        <option value="gptsovits">GPT-SoVITS</option>
                        <option value="openai">{tr("OpenAI 兼容")}</option>
                        <option value="mimo">Mimo TTS</option>
                        <option value="qwen_dashscope">Qwen / DashScope</option>
                      </select>
                    </label>
                    <label>
                      {tr("名称")}
                      <input value={config.ttsConfig.provider} placeholder={tr("例如 GPT-SoVITS 本地")} onChange={(event) => updateAgentTts(index, { provider: event.target.value })} />
                    </label>
                    <label>
                      Base URL
                      <input value={config.ttsConfig.baseUrl} placeholder={tr("填写 TTS 服务地址")} onChange={(event) => updateAgentTts(index, { baseUrl: event.target.value })} />
                    </label>
                    <label>
                      {tr("接口路径")}
                      <input value={config.ttsConfig.endpointPath} placeholder={config.ttsConfig.mode === "openai" ? "/audio/speech" : "/tts"} onChange={(event) => updateAgentTts(index, { endpointPath: event.target.value })} />
                    </label>
                    <label>
                      API Key
                      <input type="password" value={config.ttsConfig.apiKey} placeholder={tr("本地服务可留空")} onChange={(event) => updateAgentTts(index, { apiKey: event.target.value })} />
                    </label>
                    {["openai", "mimo"].includes(config.ttsConfig.mode) ? (
                      <>
                        <label>
                          {tr("模型")}
                          <input value={config.ttsConfig.model} placeholder={config.ttsConfig.mode === "mimo" ? "mimo-tts" : "tts-1"} onChange={(event) => updateAgentTts(index, { model: event.target.value })} />
                        </label>
                        <label>
                          {tr("音色")}
                          <input value={config.ttsConfig.voice} placeholder="alloy / voice id" onChange={(event) => updateAgentTts(index, { voice: event.target.value })} />
                        </label>
                        <label>
                          {tr("格式")}
                          <input value={config.ttsConfig.responseFormat} placeholder="mp3" onChange={(event) => updateAgentTts(index, { responseFormat: event.target.value })} />
                        </label>
                      </>
                    ) : config.ttsConfig.mode === "qwen_dashscope" ? (
                      <>
                        <label>
                          {tr("模型")}
                          <input value={config.ttsConfig.model} placeholder="qwen3-tts-flash" onChange={(event) => updateAgentTts(index, { model: event.target.value })} />
                        </label>
                        <label>
                          {tr("音色")}
                          <input value={config.ttsConfig.voice} placeholder="Cherry" onChange={(event) => updateAgentTts(index, { voice: event.target.value })} />
                        </label>
                        <label>
                          {tr("语言")}
                          <input value={config.ttsConfig.languageType} placeholder="Chinese / English / Auto" onChange={(event) => updateAgentTts(index, { languageType: event.target.value })} />
                        </label>
                        <label>
                          {tr("格式")}
                          <input value={config.ttsConfig.responseFormat} placeholder="wav" onChange={(event) => updateAgentTts(index, { responseFormat: event.target.value })} />
                        </label>
                        <label className="agent-tts-wide-field">
                          {tr("指令")}
                          <input value={config.ttsConfig.instructions} placeholder={tr("可选。仅 instruct 模型支持语速、情绪等控制。")} onChange={(event) => updateAgentTts(index, { instructions: event.target.value })} />
                        </label>
                      </>
                    ) : (
                      <>
                        <label className="agent-tts-wide-field">
                          {tr("参考音频路径")}
                          <input value={config.ttsConfig.refAudioPath} placeholder={tr("填写本机参考音频路径，例如 /path/to/reference.wav")} onChange={(event) => updateAgentTts(index, { refAudioPath: event.target.value })} />
                        </label>
                        <label className="agent-tts-wide-field">
                          {tr("参考音频文字")}
                          <input value={config.ttsConfig.promptText} placeholder={tr("参考音频里说的原文")} onChange={(event) => updateAgentTts(index, { promptText: event.target.value })} />
                        </label>
                        <label>
                          {tr("文本语言")}
                          <input value={config.ttsConfig.textLang} placeholder="zh" onChange={(event) => updateAgentTts(index, { textLang: event.target.value })} />
                        </label>
                        <label>
                          {tr("参考语言")}
                          <input value={config.ttsConfig.promptLang} placeholder="zh" onChange={(event) => updateAgentTts(index, { promptLang: event.target.value })} />
                        </label>
                        <label>
                          {tr("切分")}
                          <input value={config.ttsConfig.textSplitMethod} placeholder="cut5" onChange={(event) => updateAgentTts(index, { textSplitMethod: event.target.value })} />
                        </label>
                        <label>
                          {tr("格式")}
                          <input value={config.ttsConfig.responseFormat} placeholder="wav" onChange={(event) => updateAgentTts(index, { responseFormat: event.target.value })} />
                        </label>
                        <label>
                          {tr("批量")}
                          <input type="number" min="1" max="32" value={config.ttsConfig.batchSize} onChange={(event) => updateAgentTts(index, { batchSize: Number(event.target.value) })} />
                        </label>
                      </>
                    )}
                  </div>
                </details>}
                {expertMode && agentTraitMode === "player" && (
                  <div className="player-traits">
                    <p>玩家加点: 当前 {Object.values(config.traits).reduce((sum, value) => sum + Number(value || 0), 0)} / 固定参考 {traitBudget}，允许超出。点数会影响候选工具排序、风险判定、自动回应和长期成长。</p>
                    <div className="player-trait-grid">
                      {Object.entries(config.traits).map(([key, value]) => (
                        <label key={key} title={traitHelp[key] ?? key}>
                          {traitLabels[key] ?? key}
                          <input type="number" min="0" value={value} onChange={(event) => updateTrait(index, key, Number(event.target.value))} />
                          <small>{traitHelp[key] ?? ""}</small>
                        </label>
                      ))}
                    </div>
                  </div>
                )}
                </div>
                </div>
              </details>
            );
          })}
        </div>
        </section>
      </details>
    </div>
  );
}
