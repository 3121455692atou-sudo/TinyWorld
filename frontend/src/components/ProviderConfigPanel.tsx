import { Download, Plus, RefreshCw, Trash2, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import type { AgentArchiveFieldOptions, AgentConfigDraft, BabyModelDraft, LlmGenerationSettings, NarratorConfigDraft, ProviderDraft, TtsConfigDraft, World } from "../api/types";
import { t } from "../i18n";
import { FileDropZone } from "./FileDropZone";
import { ModelPicker } from "./ModelPicker";

const DEFAULT_ARCHIVE_OPTIONS: AgentArchiveFieldOptions = {
  names: true,
  prompts: true,
  appearances: true,
  avatars: true,
  collectivePrompt: true,
  providerModels: true,
  toolModes: true,
  agentToolsets: true,
  traits: true,
  narrator: true,
  babyModels: true,
  providers: true,
  tts: true
};

const ARCHIVE_OPTION_LABELS: Array<[keyof AgentArchiveFieldOptions, string]> = [
  ["names", "名字"],
  ["prompts", "提示词"],
  ["appearances", "外貌"],
  ["avatars", "头像"],
  ["collectivePrompt", "集体提示词"],
  ["providerModels", "模型"],
  ["toolModes", "工具模式"],
  ["agentToolsets", "特殊工具集"],
  ["traits", "属性"],
  ["narrator", "解说"],
  ["babyModels", "宝宝模型"],
  ["providers", "提供商"],
  ["tts", "TTS"]
];

const AGENT_TRAIT_MODE_OPTIONS: Array<{ value: AgentConfigDraft["traitMode"]; label: string }> = [
  { value: "inherit", label: "跟随世界默认" },
  { value: "agent", label: "Agent 自己加点" },
  { value: "random", label: "随机加点" },
  { value: "player", label: "玩家加点" }
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
  babyModelConfigs,
  agentConfigs,
  reusableWorlds = [],
  pullingProviderId,
  setupMode = "expert",
  language = "zh",
  onProvidersChange,
  onCollectiveCorePromptChange,
  onLlmGenerationChange,
  onNarratorConfigChange,
  onBabyModelConfigsChange,
  onAgentConfigsChange,
  onPullModels,
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
  babyModelConfigs: BabyModelDraft[];
  agentConfigs: AgentConfigDraft[];
  reusableWorlds?: World[];
  pullingProviderId: string | null;
  setupMode?: "beginner" | "expert";
  language?: "zh" | "en";
  onProvidersChange: (providers: ProviderDraft[]) => void;
  onCollectiveCorePromptChange: (value: string) => void;
  onLlmGenerationChange: (value: LlmGenerationSettings) => void;
  onNarratorConfigChange: (config: NarratorConfigDraft) => void;
  onBabyModelConfigsChange: (configs: BabyModelDraft[]) => void;
  onAgentConfigsChange: (configs: AgentConfigDraft[]) => void;
  onPullModels: (providerId: string, override?: { baseUrl?: string; apiKey?: string }) => void | Promise<string[] | void>;
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
  const expertMode = setupMode === "expert";
  const [bulkProviderId, setBulkProviderId] = useState("");
  const [bulkModelName, setBulkModelName] = useState("");
  const [bulkRandomListId, setBulkRandomListId] = useState("");
  const [bulkToolContextMode, setBulkToolContextMode] = useState<"dynamic" | "all">("dynamic");
  const [bulkTraitMode, setBulkTraitMode] = useState<AgentConfigDraft["traitMode"]>("inherit");
  const [reuseWorldId, setReuseWorldId] = useState("");
  const [randomModelLists, setRandomModelLists] = useState<RandomModelList[]>(loadRandomModelLists);
  const [archiveExportOptions, setArchiveExportOptions] = useState<AgentArchiveFieldOptions>(DEFAULT_ARCHIVE_OPTIONS);
  const [archiveImportOptions, setArchiveImportOptions] = useState<AgentArchiveFieldOptions>(DEFAULT_ARCHIVE_OPTIONS);
  const fallbackAgentConfig = (): AgentConfigDraft => ({
    providerId: fallbackProviderId,
    modelName: "",
    toolContextMode: "dynamic",
    agentToolsetIds: agentSpecialToolsets.map((item) => item.toolset_id),
    systemPrompt: "",
    chosenName: "",
    appearance: "",
    avatarDataUrl: "",
    traitMode: "inherit",
    traits: Object.fromEntries(Object.keys(traitLabels).map((key) => [key, 50])),
    llmGeneration: undefined,
    ttsConfig: defaultTtsConfig()
  });
  const normalizedAgentConfigs = Array.from({ length: safeAgentCount }, (_, index) => {
    const fallback = fallbackAgentConfig();
    const config = agentConfigs[index];
    return config ? { ...fallback, ...config, traitMode: normalizeAgentTraitMode(config.traitMode), agentToolsetIds: Array.isArray(config.agentToolsetIds) ? config.agentToolsetIds : fallback.agentToolsetIds, traits: { ...fallback.traits, ...(config.traits ?? {}) }, llmGeneration: config.llmGeneration ? normalizeLlmGeneration(config.llmGeneration) : undefined, ttsConfig: normalizeTtsConfig(config.ttsConfig) } : fallback;
  });
  const normalizedBabyConfigs = babyModelConfigs.map((config) => ({
    providerId: config.providerId || fallbackProviderId,
    modelName: config.modelName || ""
  }));
  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(RANDOM_MODEL_LISTS_STORAGE_KEY, JSON.stringify(randomModelLists));
  }, [randomModelLists]);
  const updateProvider = (providerId: string, patch: Partial<ProviderDraft>) => {
    onProvidersChange(providers.map((provider) => provider.providerId === providerId ? { ...provider, ...patch } : provider));
  };
  const pullProviderModels = async (provider: ProviderDraft) => {
    // App.tsx owns provider state. Do not write a second stale provider snapshot here;
    // otherwise an immediate “rename provider -> fetch models” click can overwrite the
    // edited name back to the old default label such as “新提供商”.
    await onPullModels(provider.providerId, { baseUrl: provider.baseUrl, apiKey: provider.apiKey });
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
  const updateAgent = (index: number, patch: Partial<AgentConfigDraft>) => {
    onAgentConfigsChange(normalizedAgentConfigs.map((config, idx) => idx === index ? { ...config, ...patch } : config));
  };
  const globalLlmGeneration = normalizeLlmGeneration(llmGeneration);
  const updateGlobalLlmGeneration = (patch: Partial<LlmGenerationSettings>) => {
    onLlmGenerationChange(normalizeLlmGeneration({ ...globalLlmGeneration, ...patch }));
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
  const narratorProvider = providers.find((item) => item.providerId === narratorConfig.providerId) ?? providers[0];
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
  const applyBulkModel = () => {
    if (!bulkModelName) {
      const pool = allPulledModelEntries;
      if (pool.length) {
        onAgentConfigsChange(normalizedAgentConfigs.map((config) => {
          const picked = pickModelEntry(pool);
          return picked ? { ...config, providerId: picked.providerId, modelName: picked.modelName } : config;
        }));
        if (!expertMode) {
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
    onAgentConfigsChange(normalizedAgentConfigs.map((config) => ({
      ...config,
      providerId: effectiveBulkProviderId,
      modelName: bulkModelName,
    })));
    if (!expertMode) {
      onNarratorConfigChange({
        ...narratorConfig,
        enabled: true,
        providerId: effectiveBulkProviderId,
        modelName: bulkModelName,
      });
    }
  };
  const applyBulkRandomModelList = () => {
    if (!selectedRandomModelList?.entries.length) return;
    onAgentConfigsChange(normalizedAgentConfigs.map((config) => {
      const picked = pickModelEntry(selectedRandomModelList.entries);
      return picked ? { ...config, providerId: picked.providerId, modelName: picked.modelName } : config;
    }));
    if (!expertMode) {
      const pickedNarrator = pickModelEntry(selectedRandomModelList.entries);
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
  const applyBulkToolContext = () => {
    onAgentConfigsChange(normalizedAgentConfigs.map((config) => ({
      ...config,
      toolContextMode: bulkToolContextMode,
    })));
  };
  const applyBulkTraitMode = () => {
    onAgentConfigsChange(normalizedAgentConfigs.map((config) => ({
      ...config,
      traitMode: bulkTraitMode,
    })));
  };
  const setAllAgentToolsets = (mode: "all" | "none") => {
    const allToolsetIds = agentSpecialToolsets.map((toolset) => toolset.toolset_id);
    onAgentConfigsChange(normalizedAgentConfigs.map((config) => ({
      ...config,
      agentToolsetIds: mode === "all" ? allToolsetIds : [],
    })));
  };
  const normalizedGlobalTraitMode = ["agent", "random", "player"].includes(String(traitMode)) ? String(traitMode) as "agent" | "random" | "player" : "agent";
  const effectiveTraitMode = (config: AgentConfigDraft) => config.traitMode === "inherit" ? normalizedGlobalTraitMode : config.traitMode;
  const toggleOption = (options: AgentArchiveFieldOptions, key: keyof AgentArchiveFieldOptions, value: boolean): AgentArchiveFieldOptions => ({ ...options, [key]: value });
  const english = language === "en";
  const text = (zh: string, en: string) => english ? en : zh;
  const tr = (value: string) => t(value, language);
  const traitModeLabel = (value: AgentConfigDraft["traitMode"]) => {
    if (value === "agent") return tr("Agent 自己加点");
    if (value === "random") return tr("随机加点");
    if (value === "player") return tr("玩家加点");
    return tr("跟随世界默认");
  };

  return (
    <div className="create-config">
      <div className="model-config-grid">
        <section className="provider-config-section">
          <div className="section-heading">
            <h2>{text("提供商", "Providers")} {!expertMode && <em className="beginner-marker marker-provider">{text("蓝色: 先填这里", "Blue: fill this first")}</em>}</h2>
            <button type="button" title={text("添加提供商", "Add provider")} onClick={addProvider}><Plus size={15} /></button>
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
                  <button type="button" onClick={() => pullProviderModels(provider)} disabled={pullingProviderId === provider.providerId}>
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
          <section className="beginner-guide-panel">
            <div className="section-heading">
              <h2>{text("快速上手", "Quick Start")}</h2>
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
          <section className="narrator-config-section">
            <div className="section-heading">
              <h2>解说 Agent</h2>
              <label className="toggle-inline">
                <input
                  type="checkbox"
                  checked={narratorConfig.enabled}
                  onChange={(event) => onNarratorConfigChange({ ...narratorConfig, enabled: event.target.checked })}
                />
                启用解说
              </label>
            </div>
            <div className={`narrator-config-row ${narratorConfig.enabled ? "" : "disabled-row"}`}>
              <label>
                提供商
                <select
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
                解说提示词
                <textarea
                  disabled={!narratorConfig.enabled}
                  value={narratorConfig.systemPrompt}
                  placeholder={narratorConfig.enabled ? "可选。解说只做场外旁白，不参与世界。" : "关闭后不会生成解说，世界照常运行。"}
                  onChange={(event) => onNarratorConfigChange({ ...narratorConfig, systemPrompt: event.target.value })}
                />
              </label>
            </div>
          </section>
          <section className="collective-prompt-section">
            <div className="section-heading">
              <h2>集体核心提示词</h2>
            </div>
            <label className="collective-prompt-field">
              <span>所有 Agent 的提示词最前面</span>
              <textarea
                value={collectiveCorePrompt}
                placeholder="可选。这里的内容会注入到每个居民每次行动的系统提示词最前面；单个 agent 的个人提示词仍然会在各自配置里追加。"
                onChange={(event) => onCollectiveCorePromptChange(event.target.value)}
              />
            </label>
          </section>
          {allowBirth && (
            <section className="baby-config-section">
              <div className="section-heading">
                <h2>宝宝 Agent 模型池</h2>
                <button type="button" title="添加宝宝模型" onClick={addBabyModel}><Plus size={15} /></button>
              </div>
              <div className="baby-model-list">
                {normalizedBabyConfigs.length ? normalizedBabyConfigs.map((config, index) => {
                  const provider = providers.find((item) => item.providerId === config.providerId) ?? providers[0];
                  return (
                    <div className="baby-model-row" key={`${config.providerId}-${index}`}>
                      <label>
                        提供商
                        <select value={config.providerId} title={provider?.name ?? ""} onChange={(event) => updateBabyModel(index, { providerId: event.target.value, modelName: "" })}>
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
            </section>
          )}
        </div>}
      </div>
      {expertMode && (
        <details className="llm-generation-section">
          <summary>LLM 输出参数 · 全局默认</summary>
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

      <section>
        <h2>Agent 模型与身份</h2>
        <div className="bulk-model-row">
          <strong>{text("一键配置模型", "One-click model setup")} {!expertMode && <em className="beginner-marker marker-model">{text("紫色: 给全部居民选模型", "Purple: choose model for all residents")}</em>}</strong>
          <label>
            <span>提供商</span>
            {!expertMode && <em className="beginner-marker marker-model">{text("紫色: 选刚才填写的提供商", "Purple: choose the provider above")}</em>}
            <select value={effectiveBulkProviderId} title={bulkProvider?.name ?? ""} onChange={(event) => {
              setBulkProviderId(event.target.value);
              setBulkModelName("");
            }}>
              {providers.map((item) => <option key={item.providerId} value={item.providerId} title={item.name}>{item.name}</option>)}
            </select>
          </label>
          <label>
            <span>模型</span>
            {!expertMode && <em className="beginner-marker marker-model">{text("紫色: 推荐便宜模型", "Purple: cheap model recommended")}</em>}
            <ModelPicker
              value={bulkModelName}
              models={bulkProvider?.models ?? []}
              emptyLabel={allPulledModelEntries.length ? "默认混用: 随机抽真实模型" : "默认混用"}
              searchPlaceholder="搜索模型名"
              onChange={setBulkModelName}
            />
          </label>
          <button type="button" onClick={applyBulkModel} title={text("紫色步骤: 把这个提供商和模型应用到所有居民。", "Purple step: apply this provider and model to every resident.")}>{text("应用到全部", "Apply to all")}</button>
        </div>
        {expertMode && <section className="random-model-section">
          <div className="section-heading">
            <h3>随机模型列表</h3>
            <button type="button" title="创建随机模型列表" onClick={addRandomModelList}><Plus size={15} /></button>
          </div>
          <div className="bulk-random-model-row">
            <label>
              <span>选择随机列表</span>
              <select value={selectedRandomModelList?.id ?? ""} onChange={(event) => setBulkRandomListId(event.target.value)}>
                {validRandomModelLists.length ? validRandomModelLists.map((list) => (
                  <option key={list.id} value={list.id} title={`${list.name} · ${list.entries.length} 个可用模型`}>
                    {list.name} · {list.entries.length} 个模型
                  </option>
                )) : <option value="">还没有随机模型列表</option>}
              </select>
            </label>
            <button type="button" disabled={!selectedRandomModelList?.entries.length} onClick={applyBulkRandomModelList}>
              随机应用到全部
            </button>
          </div>
          <div className="random-model-list">
            {randomModelLists.length ? randomModelLists.map((list) => (
              <div className="random-model-card" key={list.id}>
                <div className="random-model-card-heading">
                  <label>
                    <span>列表名称</span>
                    <input value={list.name} onChange={(event) => updateRandomModelList(list.id, { name: event.target.value })} />
                  </label>
                  <button type="button" title="添加模型" onClick={() => addRandomModelEntry(list.id)}><Plus size={15} /></button>
                  <button type="button" title="删除列表" onClick={() => removeRandomModelList(list.id)}><Trash2 size={15} /></button>
                </div>
                <div className="random-model-entry-list">
                  {list.entries.length ? list.entries.map((entry) => {
                    const entryProvider = providers.find((provider) => provider.providerId === entry.providerId) ?? providers[0];
                    return (
                      <div className="random-model-entry-row" key={entry.id}>
                        <label>
                          <span>提供商</span>
                          <select
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
              </div>
            )) : <p className="model-count">可以创建多个随机模型列表；应用时会给每个 Agent 写入抽到的真实模型。</p>}
          </div>
        </section>}
        {expertMode && <div className="bulk-settings-row">
          <strong>批量设置</strong>
          <label>
            工具上下文
            <select value={bulkToolContextMode} onChange={(event) => setBulkToolContextMode(event.target.value === "all" ? "all" : "dynamic")}>
              <option value="dynamic">动态工具</option>
              <option value="all">固定工具集</option>
            </select>
          </label>
          <button type="button" onClick={applyBulkToolContext}>应用工具模式</button>
          <label>
            加点方式
            <select value={bulkTraitMode} onChange={(event) => setBulkTraitMode(normalizeAgentTraitMode(event.target.value))}>
              {AGENT_TRAIT_MODE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
          <button type="button" onClick={applyBulkTraitMode}>应用加点</button>
          <button type="button" onClick={() => setAllAgentToolsets("all")}>全选工具集</button>
          <button type="button" onClick={() => setAllAgentToolsets("none")}>清空工具集</button>
        </div>}
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
        {expertMode && <div className="archive-option-grid">
          <div className="archive-option-row">
            <span>导出包含</span>
            {ARCHIVE_OPTION_LABELS.map(([key, label]) => (
              <label key={`export-${key}`}>
                <input type="checkbox" checked={archiveExportOptions[key]} onChange={(event) => setArchiveExportOptions(toggleOption(archiveExportOptions, key, event.target.checked))} />
                {label}
              </label>
            ))}
          </div>
          <div className="archive-option-row">
            <span>导入覆盖</span>
            {ARCHIVE_OPTION_LABELS.map(([key, label]) => (
              <label key={`import-${key}`}>
                <input type="checkbox" checked={archiveImportOptions[key]} onChange={(event) => setArchiveImportOptions(toggleOption(archiveImportOptions, key, event.target.checked))} />
                {label}
              </label>
            ))}
          </div>
        </div>}
        <div className={`agent-config-list ${expertMode ? "" : "beginner-agent-config-list"}`}>
          {normalizedAgentConfigs.map((config, index) => {
            const provider = providers.find((item) => item.providerId === config.providerId) ?? providers[0];
            const agentTraitMode = effectiveTraitMode(config);
            return (
              <div className="agent-config-row" key={index}>
                <strong>Agent {index + 1} {!expertMode && <em className="beginner-marker marker-agent">{text("橙色: 可选角色信息", "Orange: optional character info")}</em>}</strong>
                {expertMode && <label>
                  提供商
                  <select value={config.providerId} title={provider?.name ?? ""} onChange={(event) => updateAgent(index, { providerId: event.target.value, modelName: "" })}>
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
                <label className="agent-system-prompt-field" title={text("可选。只影响这个居民的长期行为、说话方式和角色设定。", "Optional. Only affects this resident's long-term behavior, speaking style, and role definition.")}>
                  <span>{text("系统提示词", "System prompt")}</span>
                  {!expertMode && <em className="beginner-marker marker-agent">{text("橙色: 可选角色设定", "Orange: optional character setting")}</em>}
                  <textarea value={config.systemPrompt} placeholder={text("可给这个 agent 单独添加长期行为约束", "Optional long-term behavior constraints for this agent")} onChange={(event) => updateAgent(index, { systemPrompt: event.target.value })} />
                </label>
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
            );
          })}
        </div>
      </section>
    </div>
  );
}
