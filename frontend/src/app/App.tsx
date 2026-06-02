import { Component, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import type { CSSProperties, ReactNode } from "react";
import { Trash2 } from "lucide-react";
import JSZip from "jszip";
import { apiClient } from "../api/client";
import { connectWorldSocket } from "../api/websocket";
import type { AgentArchiveFieldOptions, AgentConfigDraft, AgentDetail, AgentListItem, BabyModelDraft, EventFilters, EventItem, IdentityLibraryItem, InterventionAbility, Narration, NarratorConfigDraft, PresetCatalog, PromptSettings, ProviderDraft, TtsConfigDraft, World, WorldLocation, WorldMetrics } from "../api/types";
import { AgentDrawer } from "../components/AgentDrawer";
import { AgentList } from "../components/AgentList";
import { Controls } from "../components/Controls";
import { EventFeed } from "../components/EventFeed";
import { EconomyPanel } from "../components/EconomyPanel";
import { FileDropZone } from "../components/FileDropZone";
import { MapPanel } from "../components/MapPanel";
import { MetricsPanel } from "../components/MetricsPanel";
import { NarratorPanel } from "../components/NarratorPanel";
import { ProviderConfigPanel } from "../components/ProviderConfigPanel";
import { SimulationStatusPanel } from "../components/SimulationStatusPanel";
import { DEFAULT_UI_SETTINGS, UiSettingsPanel, type UiSettings } from "../components/UiSettingsPanel";
import { WorldDashboard } from "../components/WorldDashboard";
import { WorldInterventionPanel } from "../components/WorldInterventionPanel";
import { WorldRuntimePanel } from "../components/WorldRuntimePanel";
import { installI18nMirror, t, type UiLanguage } from "../i18n";
import "../styles/theme.css";

const TRAIT_KEYS = ["openness", "caution", "sociability", "empathy", "curiosity", "discipline", "aggression", "honesty", "creativity", "neuroticism"];
const DEFAULT_AGENT_COUNT = 6;
const MAX_AGENT_COUNT = 64;
const AGENT_ARCHIVE_FORMAT = "tiny-living-world-agent-config-v2";
const LEGACY_AGENT_ARCHIVE_FORMAT = "tiny-living-world-agent-config-v1";
const UI_SETTINGS_KEY = "tiny-living-world-ui-settings";
const UI_LANGUAGE_CHOSEN_KEY = "tiny-living-world-language-chosen";
const LAST_WORLD_ID_KEY = "tiny-living-world-last-world-id";
const PROVIDERS_STORAGE_KEY = "tiny-living-world-providers";
const SETUP_MODE_STORAGE_KEY = "tiny-living-world-setup-mode";
const RECENT_WORLD_PAGE_SIZE = 12;
const DEFAULT_WORLDVIEW_ID = "default_modern_worldview";
const DEFAULT_CORE_TOOLSET_ID = "core_basic_toolset";
const DEFAULT_SURVIVAL_NEEDS_TOOLSET_ID = "survival_needs_toolset";
const DEFAULT_REPRODUCTION_TOOLSET_ID = "reproduction_lifecycle_toolset";
const DEFAULT_FINANCE_INVESTING_TOOLSET_ID = "finance_investing_toolset";
const DEFAULT_WORLD_TOOLSET_ID = "default_modern_world_toolset";
const DEFAULT_LLM_RETRY_COUNT = 2;
const DEFAULT_LLM_RETRY_INTERVAL_MS = 1500;
const DEFAULT_LLM_RPM = 0;
const MAX_LLM_RETRY_COUNT = 100000;
const MAX_LLM_RETRY_INTERVAL_MS = 21600000;
const MAX_LLM_RPM = 100000;
const DEFAULT_PROMPT_SETTINGS: PromptSettings = {
  memory_limit: 10,
  recent_event_limit: 8,
  recent_self_event_limit: 6,
  action_option_limit: 90,
  dream_memory_limit: 24,
  dream_important_limit: 5,
  dream_background_limit: 3
};
const DEFAULT_AGENT_SPECIAL_TOOLSETS = [
  { toolset_id: "agent_social_toolset", name: "特殊社交工具集", description: "细分社交、求助、安慰、边界、赠送、书信和关系记录工具。" },
  { toolset_id: "agent_work_toolset", name: "特殊工作劳动工具集", description: "找工作、打工、加班、休息、抱怨工作或辞职。" },
  { toolset_id: "agent_creative_toolset", name: "特殊创作娱乐工具集", description: "写作、唱歌、讲故事、练技能、拍视频、直播或发布作品。" },
  { toolset_id: "agent_governance_toolset", name: "特殊治理公共事务工具集", description: "会议、规则、投票倾向、指控、提名和公共事务。" },
  { toolset_id: "agent_romance_toolset", name: "特殊恋爱亲密工具集", description: "好感、约会、表白、确认关系、分手、修复关系和抽象成年亲密。" },
  { toolset_id: "agent_caregiving_toolset", name: "特殊照护育儿工具集", description: "照顾孩子、教孩子简单技能和主动照护。" },
  { toolset_id: "agent_crime_toolset", name: "特殊犯罪越界工具集", description: "偷窃、入室盗窃、威胁、抢劫、攻击和越狱等高风险工具。" },
  { toolset_id: "agent_finance_toolset", name: "特殊金融投资工具集", description: "证券账户、行情、股票买卖、保证金和做空。" }
];
const DEFAULT_AGENT_SPECIAL_TOOLSET_IDS = DEFAULT_AGENT_SPECIAL_TOOLSETS.map((item) => item.toolset_id);
const SURVIVAL_DIFFICULTIES = [
  { value: "FAIRY", label: "童话" },
  { value: "NORMAL", label: "普通" },
  { value: "HARD", label: "困难" },
  { value: "HELL", label: "地狱" }
];
const AGENT_TRAIT_MODES = ["inherit", "agent", "random", "player"];
const DEFAULT_ARCHIVE_FIELD_OPTIONS: AgentArchiveFieldOptions = {
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

type SetupMode = "beginner" | "expert";

function loadSetupMode(): SetupMode {
  try {
    return window.localStorage.getItem(SETUP_MODE_STORAGE_KEY) === "expert" ? "expert" : "beginner";
  } catch {
    return "beginner";
  }
}

function needsInitialLanguageChoice(): boolean {
  try {
    return window.localStorage.getItem(UI_LANGUAGE_CHOSEN_KEY) !== "true";
  } catch {
    return false;
  }
}


function compareEvents(a: EventItem, b: EventItem): number {
  const timeDiff = Number(a.world_time ?? 0) - Number(b.world_time ?? 0);
  if (timeDiff !== 0) return timeDiff;
  return Number(a.event_id ?? 0) - Number(b.event_id ?? 0);
}

function sortEventsChronologically(items: EventItem[]): EventItem[] {
  return [...items].sort(compareEvents);
}

function blankTtsConfig(): TtsConfigDraft {
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
const DEFAULT_PRESET_CATALOG: PresetCatalog = {
  worldviews: [
    {
      worldview_id: DEFAULT_WORLDVIEW_ID,
      name: "默认现代世界观",
      name_i18n: { zh: "默认现代世界观", en: "Default Modern Worldview" },
      version: "1.0.0",
      packaged: true,
      description: "当前内置的现代小镇社会模拟世界观。饥渴、金融投资、生育育儿由可选通用工具集控制。",
      description_i18n: { zh: "当前内置的现代小镇社会模拟世界观。饥渴、金融投资、生育育儿由可选通用工具集控制。", en: "Built-in modern town social simulation worldview. Hunger/thirst, finance, reproduction, and childcare are controlled by optional universal toolsets." },
      status: "active"
    }
  ],
  core_toolsets: [
    {
      toolset_id: DEFAULT_CORE_TOOLSET_ID,
      name: "自带基础工具集",
      name_i18n: { zh: "自带基础工具集", en: "Built-in Base Toolset" },
      version: "1.0.0",
      packaged: true,
      scope: "core",
      default_enabled: true,
      description: "独立于世界观的观察、说话、移动、睡眠、赠送、记忆和基础求助工具。吃喝补给由生存需求工具集控制。",
      description_i18n: { zh: "独立于世界观的观察、说话、移动、睡眠、赠送、记忆和基础求助工具。吃喝补给由生存需求工具集控制。", en: "World-independent tools for observing, speaking, moving, sleeping, gifting, memory, and basic help. Eating, drinking, and supplies are controlled by the survival needs toolset." },
      status: "active"
    }
  ],
  optional_toolsets: [
    {
      toolset_id: DEFAULT_SURVIVAL_NEEDS_TOOLSET_ID,
      name: "通用生存需求工具集",
      version: "1.0.0",
      packaged: true,
      scope: "optional",
      default_enabled: true,
      description: "控制饥饿、口渴及对应吃喝/补给/求助工具。关闭后适合不吃不喝的特殊世界观。",
      name_i18n: { zh: "通用生存需求工具集", en: "Universal Survival Needs Toolset" },
      description_i18n: { zh: "控制饥饿、口渴及对应吃喝/补给/求助工具。关闭后适合不吃不喝的特殊世界观。", en: "Controls hunger, thirst, and related eating/drinking/supply/help tools. Disable it for special worlds without eating or drinking." },
      status: "active"
    },
    {
      toolset_id: DEFAULT_REPRODUCTION_TOOLSET_ID,
      name: "通用生育与育儿工具集",
      version: "1.0.0",
      packaged: true,
      scope: "optional",
      default_enabled: true,
      description: "可选生命延续模块，包含抽象成年亲密同意、怀孕/避孕/检测、出生、宝宝模型池、孩子成长与基础育儿工具。",
      name_i18n: { zh: "通用生育与育儿工具集", en: "Universal Reproduction & Childcare Toolset" },
      description_i18n: { zh: "可选生命延续模块，包含抽象成年亲密同意、怀孕/避孕/检测、出生、宝宝模型池、孩子成长与基础育儿工具。", en: "Optional life-continuation module with abstract adult consent, pregnancy/contraception/testing, birth, baby model pools, child growth, and basic childcare tools." },
      status: "active"
    },
    {
      toolset_id: DEFAULT_FINANCE_INVESTING_TOOLSET_ID,
      name: "通用金融投资工具集",
      version: "1.0.0",
      packaged: true,
      scope: "optional",
      default_enabled: true,
      description: "控制游戏内虚构证券账户、股票行情、买卖、保证金、做空与市场新闻。",
      name_i18n: { zh: "通用金融投资工具集", en: "Universal Finance & Investing Toolset" },
      description_i18n: { zh: "控制游戏内虚构证券账户、股票行情、买卖、保证金、做空与市场新闻。", en: "Controls fictional in-game brokerage accounts, stock quotes, trading, margin, short selling, and market news." },
      status: "active"
    }
  ],
  agent_special_toolsets: DEFAULT_AGENT_SPECIAL_TOOLSETS.map((item) => ({
    ...item,
    version: "1.0.0",
    packaged: true,
    scope: "agent_special",
    default_enabled: true,
    status: "active"
  })),
  world_toolsets: [
    {
      toolset_id: DEFAULT_WORLD_TOOLSET_ID,
      legacy_toolset_ids: ["default_modern_toolset"],
      name: "默认现代世界工具集",
      name_i18n: { zh: "默认现代世界工具集", en: "Default Modern World Toolset" },
      version: "1.0.0",
      packaged: true,
      scope: "world",
      worldview_id: DEFAULT_WORLDVIEW_ID,
      description: "默认现代世界观专用工具集，覆盖现代小镇里的工作、住房、普通消费、犯罪、租房、遗体持续存在与本世界特有设施。",
      description_i18n: { zh: "默认现代世界观专用工具集，覆盖现代小镇里的工作、住房、普通消费、犯罪、租房、遗体持续存在与本世界特有设施。", en: "World-specific toolset for the default modern worldview, covering modern town work, housing, consumption, crime, rent, persistent bodies, and local facilities." },
      status: "active"
    }
  ],
  toolsets: [
    {
      toolset_id: DEFAULT_WORLD_TOOLSET_ID,
      legacy_toolset_ids: ["default_modern_toolset"],
      name: "默认现代世界工具集",
      name_i18n: { zh: "默认现代世界工具集", en: "Default Modern World Toolset" },
      version: "1.0.0",
      packaged: true,
      scope: "world",
      worldview_id: DEFAULT_WORLDVIEW_ID,
      description: "默认现代世界观专用工具集。",
      description_i18n: { zh: "默认现代世界观专用工具集。", en: "World-specific toolset for the default modern worldview." },
      status: "active"
    }
  ],
  placeholder_interfaces: [
    {
      interface_id: "identity_model_history",
      name: "历史身份与模型库",
      status: "placeholder",
      description: "保存本地历史 agent 身份、头像、提示词与模型组合。"
    },
    {
      interface_id: "plugin_import",
      name: "插件导入",
      status: "placeholder",
      description: "导入插件 zip/manifest 并挂接扩展点。"
    },
    {
      interface_id: "optional_toolset_import",
      name: "通用工具集导入",
      status: "placeholder",
      description: "导入可跨世界观复用的通用工具集。"
    },
    {
      interface_id: "agent_special_toolset_import",
      name: "特殊工具集导入",
      status: "placeholder",
      description: "导入可分配给单个 agent 的特殊工具集。"
    },
    {
      interface_id: "agent_tts",
      name: "Agent TTS 接口",
      status: "placeholder",
      description: "给单个 agent 绑定本地或云端 TTS。"
    }
  ]
};

function blankAgentConfig(providerId = "default"): AgentConfigDraft {
  return {
    providerId,
    modelName: "",
    toolContextMode: "dynamic",
    agentToolsetIds: [...DEFAULT_AGENT_SPECIAL_TOOLSET_IDS],
    traitMode: "inherit",
    systemPrompt: "",
    chosenName: "",
    appearance: "",
    avatarDataUrl: "",
    traits: Object.fromEntries(TRAIT_KEYS.map((key) => [key, 50])),
    ttsConfig: blankTtsConfig()
  };
}

function clampAgentCount(value: unknown): number {
  const count = Number(value);
  if (!Number.isFinite(count)) return 1;
  return Math.max(1, Math.min(MAX_AGENT_COUNT, Math.floor(count)));
}

function normalizeAgentConfig(config: AgentConfigDraft | undefined, providerId: string): AgentConfigDraft {
  const fallback = blankAgentConfig(providerId);
  if (!config) return fallback;
  const rawTraitMode = String((config as Partial<AgentConfigDraft>).traitMode ?? "inherit");
  return {
    ...fallback,
    ...config,
    providerId: config.providerId || providerId,
    toolContextMode: config.toolContextMode === "all" ? "all" : "dynamic",
    agentToolsetIds: Array.isArray(config.agentToolsetIds) ? config.agentToolsetIds.map(String) : [...DEFAULT_AGENT_SPECIAL_TOOLSET_IDS],
    traitMode: AGENT_TRAIT_MODES.includes(rawTraitMode) ? rawTraitMode as AgentConfigDraft["traitMode"] : "inherit",
    traits: { ...fallback.traits, ...(config.traits ?? {}) },
    ttsConfig: normalizeTtsConfig((config as Partial<AgentConfigDraft>).ttsConfig)
  };
}

function normalizeAgentConfigs(configs: AgentConfigDraft[], count: number, providerId: string): AgentConfigDraft[] {
  return Array.from({ length: clampAgentCount(count) }, (_, index) => normalizeAgentConfig(configs[index], providerId));
}

function normalizeBabyModelConfigs(configs: BabyModelDraft[], providerId: string): BabyModelDraft[] {
  return configs.map((config) => ({ providerId: config.providerId || providerId, modelName: config.modelName || "" }));
}

function normalizeTtsConfig(raw: unknown): TtsConfigDraft {
  const fallback = blankTtsConfig();
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
    batchSize: clampNumber(item.batchSize ?? item.batch_size, 1, 32, 1)
  };
}

function serializeTtsConfig(config: TtsConfigDraft): Record<string, unknown> | undefined {
  const normalized = normalizeTtsConfig(config);
  const hasConfig = normalized.enabled || [
    normalized.provider,
    normalized.baseUrl,
    normalized.endpointPath,
    normalized.apiKey,
    normalized.model,
    normalized.voice,
    normalized.refAudioPath,
    normalized.promptText
  ].some((value) => value.trim());
  if (!hasConfig) return undefined;
  const payload: Record<string, unknown> = {
    enabled: normalized.enabled,
    provider: normalized.provider.trim(),
    mode: normalized.mode,
    base_url: normalized.baseUrl.trim(),
    endpoint_path: normalized.endpointPath.trim(),
    response_format: normalized.responseFormat.trim() || (normalized.mode === "openai" ? "mp3" : "wav"),
    model: normalized.model.trim(),
    voice: normalized.voice.trim(),
    language_type: normalized.languageType.trim() || "Chinese",
    instructions: normalized.instructions.trim(),
    ref_audio_path: normalized.refAudioPath.trim(),
    prompt_text: normalized.promptText.trim(),
    prompt_lang: normalized.promptLang.trim() || "zh",
    text_lang: normalized.textLang.trim() || "zh",
    text_split_method: normalized.textSplitMethod.trim() || "cut5",
    batch_size: normalized.batchSize
  };
  if (normalized.apiKey.trim()) payload.api_key = normalized.apiKey.trim();
  return payload;
}

function normalizeImportedProviders(rawProviders: unknown[], currentProviders: ProviderDraft[]): ProviderDraft[] {
  const currentById = new Map(currentProviders.map((provider) => [provider.providerId, provider]));
  const imported = rawProviders.map((raw, index) => {
    const item = raw as Partial<ProviderDraft>;
    const providerId = String(item.providerId || `imported_${index + 1}`);
    const previous = currentById.get(providerId);
    return {
      providerId,
      name: String(item.name || previous?.name || providerId),
      baseUrl: String(item.baseUrl || previous?.baseUrl || ""),
      apiKey: String(item.apiKey || previous?.apiKey || ""),
      retryCount: clampNumber(item.retryCount ?? (item as Record<string, unknown>).retry_count ?? previous?.retryCount, 0, MAX_LLM_RETRY_COUNT, DEFAULT_LLM_RETRY_COUNT),
      retryIntervalMs: clampNumber(item.retryIntervalMs ?? (item as Record<string, unknown>).retry_interval_ms ?? previous?.retryIntervalMs, 0, MAX_LLM_RETRY_INTERVAL_MS, DEFAULT_LLM_RETRY_INTERVAL_MS),
      rpm: clampNumber(item.rpm ?? previous?.rpm, 0, MAX_LLM_RPM, DEFAULT_LLM_RPM),
      models: Array.isArray(item.models) ? item.models.map(String) : previous?.models ?? []
    };
  });
  const merged = [...currentProviders.filter((provider) => !imported.some((item) => item.providerId === provider.providerId)), ...imported];
  return merged.length ? merged : currentProviders;
}

function defaultProviders(): ProviderDraft[] {
  return [
    {
      providerId: "default",
      name: "Provider",
      baseUrl: "",
      apiKey: "",
      retryCount: DEFAULT_LLM_RETRY_COUNT,
      retryIntervalMs: DEFAULT_LLM_RETRY_INTERVAL_MS,
      rpm: DEFAULT_LLM_RPM,
      models: []
    }
  ];
}

function loadProviders(): ProviderDraft[] {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(PROVIDERS_STORAGE_KEY) || "[]");
    if (Array.isArray(parsed) && parsed.length) {
      return normalizeImportedProviders(parsed, defaultProviders());
    }
  } catch {
    window.localStorage.removeItem(PROVIDERS_STORAGE_KEY);
  }
  return defaultProviders();
}

function safeArchiveName(value: string, fallback: string): string {
  const cleaned = value.trim().replace(/[\\/:*?"<>|]/g, "_").replace(/\s+/g, "_");
  return cleaned || fallback;
}

function mimeFromPath(path: string): string {
  const lower = path.toLowerCase();
  if (lower.endsWith(".webp")) return "image/webp";
  if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image/jpeg";
  if (lower.endsWith(".gif")) return "image/gif";
  return "image/png";
}

function extensionFromMime(mime: string): string {
  if (mime.includes("webp")) return "webp";
  if (mime.includes("jpeg") || mime.includes("jpg")) return "jpg";
  if (mime.includes("gif")) return "gif";
  return "png";
}

function dataUrlToBytes(dataUrl: string): { bytes: Uint8Array; extension: string } | null {
  const match = /^data:([^;,]+);base64,(.*)$/s.exec(dataUrl);
  if (!match) return null;
  const binary = window.atob(match[2]);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return { bytes, extension: extensionFromMime(match[1]) };
}

async function zipFileToDataUrl(zip: JSZip, path: string): Promise<string> {
  const file = zip.file(path);
  if (!file) return "";
  const base64 = await file.async("base64");
  return `data:${mimeFromPath(path)};base64,${base64}`;
}

function clampNumber(value: unknown, min: number, max: number, fallback: number): number {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(min, Math.min(max, Math.round(number)));
}

function loadUiSettings(): UiSettings {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(UI_SETTINGS_KEY) || "{}") as Partial<UiSettings>;
    return {
      theme: parsed.theme === "dark" ? "dark" : "light",
      language: parsed.language === "en" ? "en" : "zh",
      leftWidth: clampNumber(parsed.leftWidth, 220, 460, DEFAULT_UI_SETTINGS.leftWidth),
      rightWidth: clampNumber(parsed.rightWidth, 260, 560, DEFAULT_UI_SETTINGS.rightWidth),
      eventFontSize: clampNumber(parsed.eventFontSize, 12, 20, DEFAULT_UI_SETTINGS.eventFontSize),
      eventAvatarSize: clampNumber(parsed.eventAvatarSize, 30, 64, DEFAULT_UI_SETTINGS.eventAvatarSize)
    };
  } catch {
    return DEFAULT_UI_SETTINGS;
  }
}

function isSpeechEvent(event: EventItem): boolean {
  return event.event_type === "dialogue" || typeof event.payload?.speech === "string" || typeof event.payload?.message === "string" || typeof event.payload?.content === "string";
}

function worldDifficultyLabel(world: World): string {
  return String(world.settings?.survival_difficulty_label || world.settings?.survival_difficulty || "普通");
}

function worldviewIdForWorld(world: World): string {
  return String(world.settings?.worldview_id || DEFAULT_WORLDVIEW_ID);
}

type LocalizedPreset = {
  packaged?: boolean;
  name: string;
  name_i18n?: Record<string, string>;
  description?: string;
  description_i18n?: Record<string, string>;
};

function localizedPresetName(item: LocalizedPreset, language: UiLanguage): string {
  return String((item.packaged ? item.name_i18n?.[language] : "") || item.name);
}

function localizedPresetDescription(item: LocalizedPreset, language: UiLanguage): string {
  return String((item.packaged ? item.description_i18n?.[language] : "") || item.description || "");
}

function worldviewLabelForWorld(world: World, catalog: PresetCatalog, language: UiLanguage): string {
  const worldviewId = worldviewIdForWorld(world);
  const preset = catalog.worldviews.find((item) => item.worldview_id === worldviewId);
  if (preset) return localizedPresetName(preset, language);
  return String(world.settings?.worldview_name || "默认现代世界观");
}

function saveNameForWorld(world: World): string {
  return String(world.save_name || world.settings?.save_name || world.name || "未命名存档");
}

function reproductionEnabledForCreateSettings(settings: { optionalToolsetIds: string[] }): boolean {
  return settings.optionalToolsetIds.includes(DEFAULT_REPRODUCTION_TOOLSET_ID);
}

type WorldUiFeatures = {
  showEconomyPanel: boolean;
  showAgentEconomy: boolean;
  showWork: boolean;
  showLaw: boolean;
  showFamily: boolean;
  showNarrator: boolean;
  showMetrics: boolean;
};

function worldUiFeatures(world: World): WorldUiFeatures {
  const settings = world.settings ?? {};
  const ui = asPlainRecord(settings.worldview_ui);
  const panels = asPlainRecord(ui.panels);
  const worldviewId = String(settings.worldview_id ?? "");
  const toolsetId = String(settings.world_toolset_id ?? settings.toolset_id ?? "");
  const defaultModern = worldviewId === DEFAULT_WORLDVIEW_ID || toolsetId === DEFAULT_WORLD_TOOLSET_ID || toolsetId === "default_modern_toolset";
  const financeEnabled = boolFromUnknown(settings.finance_investing_enabled, false);
  const reproductionEnabled = boolFromUnknown(settings.reproduction_enabled, false);
  const economyFallback = defaultModern || financeEnabled;
  return {
    showEconomyPanel: boolFromUnknown(panels.economy, economyFallback),
    showAgentEconomy: boolFromUnknown(panels.agent_economy, economyFallback),
    showWork: boolFromUnknown(panels.work, defaultModern),
    showLaw: boolFromUnknown(panels.law, true),
    showFamily: boolFromUnknown(panels.reproduction, reproductionEnabled),
    showNarrator: boolFromUnknown(panels.narrator, true),
    showMetrics: boolFromUnknown(panels.metrics, true),
  };
}

function asPlainRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function boolFromUnknown(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

class AppErrorBoundary extends Component<{ children: ReactNode }, { error: string | null }> {
  state: { error: string | null } = { error: null };

  static getDerivedStateFromError(error: unknown) {
    return { error: error instanceof Error ? error.message : String(error) };
  }

  componentDidCatch(error: unknown) {
    console.error(error);
  }

  render() {
    if (this.state.error) {
      return (
        <main className="empty-shell">
          <section className="create-panel">
            <h1>微世界</h1>
            <p className="error-line">前端渲染出错: {this.state.error}</p>
            <button className="primary-action" type="button" onClick={() => window.location.reload()}>重新加载</button>
          </section>
        </main>
      );
    }
    return this.props.children;
  }
}

function App() {
  const [world, setWorld] = useState<World | null>(null);
  const [agents, setAgents] = useState<AgentListItem[]>([]);
  const [locations, setLocations] = useState<WorldLocation[]>([]);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [narrations, setNarrations] = useState<Narration[]>([]);
  const [metrics, setMetrics] = useState<WorldMetrics | null>(null);
  const [interventionAbilities, setInterventionAbilities] = useState<InterventionAbility[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<AgentDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [replacingLlm, setReplacingLlm] = useState(false);
  const [restoringWorld, setRestoringWorld] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [recentWorlds, setRecentWorlds] = useState<World[]>([]);
  const [reusableWorlds, setReusableWorlds] = useState<World[]>([]);
  const [recentWorldTotal, setRecentWorldTotal] = useState(0);
  const [recentWorldPage, setRecentWorldPage] = useState(1);
  const [renamingWorldId, setRenamingWorldId] = useState<string | null>(null);
  const [renamingSaveName, setRenamingSaveName] = useState("");
  const [deletingWorldId, setDeletingWorldId] = useState<string | null>(null);
  const [filters, setFilters] = useState<EventFilters>({ minImportance: 0, dialogueOnly: false, showNarrator: true, exportAvatars: true, exportAudio: false, agentId: "", locationId: "", renderLimit: 2000, startEventId: "", endEventId: "" });
  const [createSettings, setCreateSettings] = useState({
    name: "微世界",
    agentCount: DEFAULT_AGENT_COUNT,
    collectiveCorePrompt: "",
    seed: Date.now() % 100000000,
    speed: "slow",
    survivalDifficulty: "NORMAL",
    worldviewId: DEFAULT_WORLDVIEW_ID,
    coreToolsetEnabled: true,
    coreToolsetId: DEFAULT_CORE_TOOLSET_ID,
    optionalToolsetIds: [DEFAULT_SURVIVAL_NEEDS_TOOLSET_ID, DEFAULT_REPRODUCTION_TOOLSET_ID, DEFAULT_FINANCE_INVESTING_TOOLSET_ID],
    worldToolsetId: DEFAULT_WORLD_TOOLSET_ID,
    pregnancyMode: "any_gender",
    traitMode: "agent",
    traitBudget: 500
  });
  const [providers, setProviders] = useState<ProviderDraft[]>(() => loadProviders());
  const [narratorConfig, setNarratorConfig] = useState<NarratorConfigDraft>({
    enabled: true,
    providerId: "default",
    modelName: "",
    systemPrompt: ""
  });
  const [babyModelConfigs, setBabyModelConfigs] = useState<BabyModelDraft[]>([]);
  const [agentConfigs, setAgentConfigs] = useState<AgentConfigDraft[]>(Array.from({ length: DEFAULT_AGENT_COUNT }, () => blankAgentConfig()));
  const [pullingProviderId, setPullingProviderId] = useState<string | null>(null);
  const [uiSettings, setUiSettings] = useState<UiSettings>(() => loadUiSettings());
  const [languageGateOpen, setLanguageGateOpen] = useState(() => needsInitialLanguageChoice());
  const [setupMode, setSetupMode] = useState<SetupMode>(() => loadSetupMode());
  const [setupLeftOpen, setSetupLeftOpen] = useState(false);
  const [setupRightOpen, setSetupRightOpen] = useState(false);
  const [presetCatalog, setPresetCatalog] = useState<PresetCatalog>(DEFAULT_PRESET_CATALOG);
  const [worldPackImporting, setWorldPackImporting] = useState(false);
  const [worldPackImportMessage, setWorldPackImportMessage] = useState("");
  const [pluginInstalling, setPluginInstalling] = useState(false);
  const [pluginInstallUrl, setPluginInstallUrl] = useState("");
  const [pluginInstallMessage, setPluginInstallMessage] = useState("");
  const [identityLibrary, setIdentityLibrary] = useState<IdentityLibraryItem[]>([]);
  const [identitySearch, setIdentitySearch] = useState("");
  const [identityTargetIndex, setIdentityTargetIndex] = useState(0);
  const [deletingIdentityId, setDeletingIdentityId] = useState<string | null>(null);
  const [interventionBusy, setInterventionBusy] = useState(false);

  const loadRecentWorlds = async (page = recentWorldPage) => {
    const safePage = Math.max(1, Math.floor(page));
    const result = await apiClient.worlds({ limit: RECENT_WORLD_PAGE_SIZE, offset: (safePage - 1) * RECENT_WORLD_PAGE_SIZE });
    setRecentWorlds(result.worlds);
    setRecentWorldTotal(Number(result.total ?? result.worlds.length));
    setRecentWorldPage(safePage);
    return result.worlds;
  };

  const loadReusableWorlds = async () => {
    const result = await apiClient.worlds({ limit: 200, offset: 0 });
    setReusableWorlds(result.worlds);
    return result.worlds;
  };

  const refresh = async (worldId = world?.world_id) => {
    if (!worldId) return;
    const eventQuery = new URLSearchParams({
      min_importance: String(filters.minImportance),
      limit: String(filters.renderLimit),
      latest: "true"
    });
    if (filters.locationId) eventQuery.set("location_id", filters.locationId);
    if (filters.agentId) eventQuery.set("agent_id", filters.agentId);
    if (filters.startEventId) eventQuery.set("start_event_id", filters.startEventId);
    if (filters.endEventId) eventQuery.set("end_event_id", filters.endEventId);
    if (filters.dialogueOnly) eventQuery.set("dialogue_only", "true");
    if (!filters.showNarrator) eventQuery.set("show_narrator", "false");
    const [worldData, agentData, locationData, eventData, narrationData, metricsData] = await Promise.all([
      apiClient.getWorld(worldId),
      apiClient.agents(worldId),
      apiClient.locations(worldId),
      apiClient.events(worldId, `?${eventQuery.toString()}`),
      apiClient.narrations(worldId),
      apiClient.metrics(worldId)
    ]);
    setWorld(worldData);
    window.localStorage.setItem(LAST_WORLD_ID_KEY, worldData.world_id);
    setAgents(agentData.agents);
    setLocations(locationData.locations);
    setEvents(sortEventsChronologically(eventData.events));
    setNarrations(narrationData.narrations);
    setMetrics(metricsData);
    const latestEvent = eventData.events[eventData.events.length - 1];
    if (latestEvent?.event_type === "llm_stalled" && worldData.status === "paused") {
      setError(latestEvent.viewer_text);
    }
  };

  useEffect(() => {
    let cancelled = false;
    const restoreWorld = async () => {
      setRestoringWorld(true);
      try {
        const [recent] = await Promise.all([
          loadRecentWorlds(),
          loadReusableWorlds()
        ]);
        const storedWorldId = window.localStorage.getItem(LAST_WORLD_ID_KEY);
        if (storedWorldId && !recent.some((item) => item.world_id === storedWorldId)) {
          window.localStorage.removeItem(LAST_WORLD_ID_KEY);
        }
      } catch (err) {
        window.localStorage.removeItem(LAST_WORLD_ID_KEY);
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setRestoringWorld(false);
      }
    };
    restoreWorld();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!world?.world_id) return;
    const ws = connectWorldSocket(world.world_id, () => {
      refresh(world.world_id).catch((err) => setError(String(err)));
    });
    return () => ws.close();
  }, [world?.world_id, filters.minImportance, filters.renderLimit, filters.locationId, filters.agentId, filters.startEventId, filters.endEventId, filters.dialogueOnly, filters.showNarrator]);

  useEffect(() => {
    if (!world?.world_id) return;
    const timer = window.setInterval(() => {
      refresh(world.world_id).catch((err) => setError(String(err)));
    }, world.status === "running" ? 3000 : 6000);
    return () => window.clearInterval(timer);
  }, [world?.world_id, world?.status, filters.minImportance, filters.renderLimit, filters.locationId, filters.agentId, filters.startEventId, filters.endEventId, filters.dialogueOnly, filters.showNarrator]);

  useEffect(() => {
    if (!world || !selectedAgentId) {
      setSelectedAgent(null);
      return;
    }
    apiClient.agent(world.world_id, selectedAgentId).then(setSelectedAgent).catch((err) => setError(String(err)));
  }, [world, selectedAgentId, agents]);

  useEffect(() => {
  }, []);

  useEffect(() => {
    apiClient.presets().then(setPresetCatalog).catch(() => setPresetCatalog(DEFAULT_PRESET_CATALOG));
  }, []);

  useEffect(() => {
    apiClient.interventionAbilities().then((data) => setInterventionAbilities(data.abilities)).catch(() => setInterventionAbilities([]));
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(SETUP_MODE_STORAGE_KEY, setupMode);
    } catch {
      // localStorage may be unavailable in unusual browser contexts.
    }
  }, [setupMode]);

  useEffect(() => {
    const elements = document.querySelectorAll<HTMLElement>(
      "button, input, select, textarea, summary, label, [role='button'], .preset-tags span, .recent-world-row em"
    );
    elements.forEach((element) => {
      if (element.dataset.autoTitle === "false") return;
      if (element.title && element.dataset.autoTitle !== "true") return;
      const placeholder = element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement ? element.placeholder : "";
      const selectedText = element instanceof HTMLSelectElement ? element.selectedOptions[0]?.textContent?.trim() ?? "" : "";
      const text = (element.getAttribute("aria-label") || placeholder || selectedText || element.textContent || "").trim().replace(/\s+/g, " ");
      if (text) {
        element.title = text.length > 160 ? `${text.slice(0, 157)}...` : text;
        element.dataset.autoTitle = "true";
      }
    });
  });

  const loadIdentityLibrary = async () => {
    const result = await apiClient.identityLibrary(300);
    setIdentityLibrary(result.items);
  };

  useEffect(() => {
    loadIdentityLibrary().catch(() => undefined);
  }, []);

  const applyWorldviewSelection = (worldviewId: string, catalog: PresetCatalog = presetCatalog) => {
    const worldview = catalog.worldviews.find((item) => item.worldview_id === worldviewId);
    const defaults = worldview?.default_create_settings ?? {};
    const matchingWorldToolset = catalog.world_toolsets.find((item) => item.worldview_id === worldviewId);
    const defaultOptional = Array.isArray(defaults.optional_toolset_ids) ? defaults.optional_toolset_ids.map(String) : undefined;
    const defaultWorldToolsetId = typeof defaults.world_toolset_id === "string" ? defaults.world_toolset_id : matchingWorldToolset?.toolset_id;
    setCreateSettings((current) => ({
      ...current,
      worldviewId,
      survivalDifficulty: ["FAIRY", "NORMAL", "HARD", "HELL"].includes(String(defaults.survival_difficulty)) ? String(defaults.survival_difficulty) : current.survivalDifficulty,
      coreToolsetEnabled: typeof defaults.core_toolset_enabled === "boolean" ? defaults.core_toolset_enabled : current.coreToolsetEnabled,
      coreToolsetId: typeof defaults.core_toolset_id === "string" ? defaults.core_toolset_id : current.coreToolsetId,
      optionalToolsetIds: defaultOptional ?? current.optionalToolsetIds,
      worldToolsetId: defaultWorldToolsetId ?? current.worldToolsetId
    }));
  };

  const importWorldPack = async (file: File) => {
    setWorldPackImporting(true);
    setWorldPackImportMessage("");
    setError(null);
    try {
      const result = await apiClient.importWorldPack(file);
      setPresetCatalog(result.catalog);
      const firstWorldviewId = result.pack.worldviews[0]?.worldview_id;
      if (firstWorldviewId) applyWorldviewSelection(firstWorldviewId, result.catalog);
      setWorldPackImportMessage(`已导入 ${result.pack.name}，新增/刷新 ${result.registered_tool_count} 个工具。`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setWorldPackImporting(false);
    }
  };

  const importPluginPack = async (file: File) => {
    setPluginInstalling(true);
    setPluginInstallMessage("");
    setError(null);
    try {
      const result = await apiClient.importPlugin(file);
      setPresetCatalog(result.catalog);
      setPluginInstallMessage(`已安装插件 ${result.plugin.name}，新增/刷新 ${result.registered_tool_count} 个工具。`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPluginInstalling(false);
    }
  };

  const installPluginFromUrl = async () => {
    const url = pluginInstallUrl.trim();
    if (!url) return;
    setPluginInstalling(true);
    setPluginInstallMessage("");
    setError(null);
    try {
      const result = await apiClient.installPluginFromUrl(url);
      setPresetCatalog(result.catalog);
      setPluginInstallMessage(`已安装插件 ${result.plugin.name}，新增/刷新 ${result.registered_tool_count} 个工具。`);
      setPluginInstallUrl("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPluginInstalling(false);
    }
  };

  useEffect(() => {
    window.localStorage.setItem(UI_SETTINGS_KEY, JSON.stringify(uiSettings));
  }, [uiSettings]);

  useEffect(() => installI18nMirror(uiSettings.language), [uiSettings.language]);

  const chooseLanguage = (language: UiSettings["language"]) => {
    setUiSettings((current) => ({ ...current, language }));
    try {
      window.localStorage.setItem(UI_LANGUAGE_CHOSEN_KEY, "true");
    } catch {
      // localStorage may be unavailable in unusual browser contexts.
    }
    setLanguageGateOpen(false);
  };

  useEffect(() => {
    window.localStorage.setItem(PROVIDERS_STORAGE_KEY, JSON.stringify(providers));
  }, [providers]);

  useEffect(() => {
    setAgentConfigs((current) => {
      return normalizeAgentConfigs(current, createSettings.agentCount, providers[0]?.providerId ?? "default");
    });
    setBabyModelConfigs((current) => normalizeBabyModelConfigs(current, providers[0]?.providerId ?? "default"));
  }, [createSettings.agentCount, providers]);

  const pullModels = async (providerId: string, override?: { baseUrl?: string; apiKey?: string }) => {
    const provider = providers.find((item) => item.providerId === providerId);
    if (!provider) return;
    setPullingProviderId(providerId);
    setError(null);
    try {
      const baseUrl = override?.baseUrl?.trim() || provider.baseUrl;
      const apiKey = override?.apiKey?.trim() || provider.apiKey;
      const result = await apiClient.pullModels({ base_url: baseUrl, api_key: apiKey || undefined });
      setProviders((current) => current.map((item) => item.providerId === providerId ? { ...item, baseUrl, apiKey, models: result.models } : item));
      return result.models;
    } catch (err) {
      setError(String(err));
      return [];
    } finally {
      setPullingProviderId(null);
    }
  };

  const exportAgentArchive = async (options: AgentArchiveFieldOptions = DEFAULT_ARCHIVE_FIELD_OPTIONS) => {
    const activeAgentConfigs = normalizeAgentConfigs(agentConfigs, createSettings.agentCount, providers[0]?.providerId ?? "default");
    const allowBirth = reproductionEnabledForCreateSettings(createSettings);
    const activeBabyModelConfigs = allowBirth
      ? normalizeBabyModelConfigs(babyModelConfigs, providers[0]?.providerId ?? "default").filter((config) => config.modelName.trim())
      : [];
    const zip = new JSZip();
    const payload = {
      format: AGENT_ARCHIVE_FORMAT,
      exportedAt: new Date().toISOString(),
      agentCount: createSettings.agentCount,
      collectiveCorePrompt: options.collectivePrompt ? createSettings.collectiveCorePrompt : "",
      pregnancyMode: createSettings.pregnancyMode,
      survivalDifficulty: createSettings.survivalDifficulty,
      worldviewId: createSettings.worldviewId,
      coreToolsetEnabled: createSettings.coreToolsetEnabled,
      coreToolsetId: createSettings.coreToolsetId,
      optionalToolsetIds: createSettings.optionalToolsetIds,
      worldToolsetId: createSettings.worldToolsetId,
      traitMode: createSettings.traitMode,
      traitBudget: createSettings.traitBudget,
      exportOptions: options,
      providers: options.providers ? providers : [],
      narratorConfig: options.narrator ? narratorConfig : undefined,
      babyModelConfigs: options.babyModels ? activeBabyModelConfigs : [],
      agents: activeAgentConfigs.map((config, index) => ({
        index,
        providerId: options.providerModels ? config.providerId : "",
        modelName: options.providerModels ? config.modelName : "",
        toolContextMode: options.toolModes ? config.toolContextMode : "dynamic",
        agentToolsetIds: options.agentToolsets ? config.agentToolsetIds : [],
        traitMode: options.traits ? config.traitMode : "inherit",
        systemPrompt: options.prompts ? config.systemPrompt : "",
        chosenName: options.names ? config.chosenName : "",
        appearance: options.appearances ? config.appearance : "",
        traits: options.traits ? config.traits : {},
        ttsConfig: options.tts ? config.ttsConfig : undefined
      }))
    };
    if (options.avatars) payload.agents.forEach((agent, index) => {
      const avatar = dataUrlToBytes(activeAgentConfigs[index].avatarDataUrl);
      if (!avatar) return;
      const baseName = safeArchiveName(agent.chosenName, `agent_${index + 1}`);
      const avatarPath = `avatars/${String(index + 1).padStart(2, "0")}_${baseName}.${avatar.extension}`;
      zip.file(avatarPath, avatar.bytes);
      Object.assign(agent, { avatarPath });
    });
    zip.file("manifest.json", JSON.stringify(payload, null, 2));
    const blob = await zip.generateAsync({ type: "blob", compression: "DEFLATE", compressionOptions: { level: 6 } });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `tiny-living-world-agents-${Date.now()}.tlwagents.zip`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const applyImportedAgentArchive = (parsed: Record<string, unknown>, importedAgents: AgentConfigDraft[], options: AgentArchiveFieldOptions, nextProviders: ProviderDraft[] = providers) => {
    if (![AGENT_ARCHIVE_FORMAT, LEGACY_AGENT_ARCHIVE_FORMAT].includes(String(parsed.format)) || !Array.isArray(parsed.agents)) {
      throw new Error("人员配置文件格式不正确");
    }
    const providerIds = new Set(nextProviders.map((provider) => provider.providerId));
    const count = clampAgentCount(Number(parsed.agentCount) || importedAgents.length || 1);
    setCreateSettings((current) => ({
      ...current,
      agentCount: count,
      collectiveCorePrompt: options.collectivePrompt ? String(parsed.collectiveCorePrompt ?? current.collectiveCorePrompt) : current.collectiveCorePrompt,
      pregnancyMode: ["any_gender", "heterosexual"].includes(String(parsed.pregnancyMode)) ? String(parsed.pregnancyMode) : current.pregnancyMode,
      survivalDifficulty: ["FAIRY", "NORMAL", "HARD", "HELL"].includes(String(parsed.survivalDifficulty)) ? String(parsed.survivalDifficulty) : current.survivalDifficulty,
      worldviewId: String(parsed.worldviewId || current.worldviewId),
      coreToolsetEnabled: typeof parsed.coreToolsetEnabled === "boolean" ? parsed.coreToolsetEnabled : current.coreToolsetEnabled,
      coreToolsetId: String(parsed.coreToolsetId || current.coreToolsetId),
      optionalToolsetIds: Array.isArray(parsed.optionalToolsetIds) ? parsed.optionalToolsetIds.map(String) : current.optionalToolsetIds,
      worldToolsetId: String(parsed.worldToolsetId || parsed.toolsetId || current.worldToolsetId),
      traitMode: ["agent", "player", "random"].includes(String(parsed.traitMode)) ? String(parsed.traitMode) : current.traitMode,
      traitBudget: Number.isFinite(Number(parsed.traitBudget)) ? Number(parsed.traitBudget) : current.traitBudget
    }));
    setAgentConfigs(() => {
      return normalizeAgentConfigs(importedAgents, count, nextProviders[0]?.providerId ?? "default");
    });
    const narrator = parsed.narratorConfig as Partial<NarratorConfigDraft> | undefined;
    if (options.narrator && narrator) {
      setNarratorConfig((current) => ({
        enabled: typeof narrator.enabled === "boolean" ? narrator.enabled : current.enabled,
        providerId: narrator.providerId && providerIds.has(narrator.providerId) ? narrator.providerId : current.providerId,
        modelName: String(narrator.modelName ?? current.modelName),
        systemPrompt: String(narrator.systemPrompt ?? "")
      }));
    }
    const babyConfigs = Array.isArray(parsed.babyModelConfigs) ? parsed.babyModelConfigs : [];
    if (options.babyModels) {
      setBabyModelConfigs(
        normalizeBabyModelConfigs(
          babyConfigs.map((raw) => {
            const item = raw as Partial<BabyModelDraft>;
            return {
              providerId: options.providerModels && item.providerId && providerIds.has(item.providerId) ? item.providerId : nextProviders[0]?.providerId ?? "default",
              modelName: options.providerModels ? String(item.modelName ?? "") : "",
            };
          }),
          nextProviders[0]?.providerId ?? "default",
        ),
      );
    }
  };

  const importAgentArchive = async (file: File, options: AgentArchiveFieldOptions = DEFAULT_ARCHIVE_FIELD_OPTIONS) => {
    try {
      let parsed: Record<string, unknown>;
      let nextProviders = providers;
      let importedAgents: AgentConfigDraft[];
      if (file.name.toLowerCase().endsWith(".zip")) {
        const zip = await JSZip.loadAsync(file);
        const manifestFile = zip.file("manifest.json");
        if (!manifestFile) throw new Error("压缩包中缺少 manifest.json");
        parsed = JSON.parse(await manifestFile.async("text"));
        if (options.providers && Array.isArray(parsed.providers)) {
          nextProviders = normalizeImportedProviders(parsed.providers, providers);
          setProviders(nextProviders);
        }
        const providerIds = new Set(nextProviders.map((provider) => provider.providerId));
        const agents = Array.isArray(parsed.agents) ? parsed.agents : [];
        importedAgents = await Promise.all(agents.map(async (raw) => {
          const item = raw as Partial<AgentConfigDraft> & { avatarPath?: string };
          const avatarDataUrl = options.avatars && item.avatarPath ? await zipFileToDataUrl(zip, item.avatarPath) : "";
          return {
              providerId: options.providerModels && item.providerId && providerIds.has(item.providerId) ? item.providerId : nextProviders[0]?.providerId ?? "default",
              modelName: options.providerModels ? String(item.modelName ?? "") : "",
              toolContextMode: options.toolModes && item.toolContextMode === "all" ? "all" : "dynamic",
              agentToolsetIds: options.agentToolsets && Array.isArray(item.agentToolsetIds) ? item.agentToolsetIds.map(String) : [...DEFAULT_AGENT_SPECIAL_TOOLSET_IDS],
              traitMode: options.traits && AGENT_TRAIT_MODES.includes(String(item.traitMode)) ? String(item.traitMode) as AgentConfigDraft["traitMode"] : "inherit",
              systemPrompt: options.prompts ? String(item.systemPrompt ?? "") : "",
            chosenName: options.names ? String(item.chosenName ?? "") : "",
            appearance: options.appearances ? String(item.appearance ?? "") : "",
            avatarDataUrl,
            traits: options.traits ? { ...blankAgentConfig().traits, ...(typeof item.traits === "object" && item.traits ? item.traits : {}) } : blankAgentConfig().traits,
            ttsConfig: options.tts ? normalizeTtsConfig((item as Record<string, unknown>).ttsConfig ?? (item as Record<string, unknown>).tts_config) : blankTtsConfig()
          };
        }));
      } else {
        parsed = JSON.parse(await file.text());
        if (options.providers && Array.isArray(parsed.providers)) {
          nextProviders = normalizeImportedProviders(parsed.providers, providers);
          setProviders(nextProviders);
        }
        const providerIds = new Set(nextProviders.map((provider) => provider.providerId));
        const agents = Array.isArray(parsed.agents) ? parsed.agents : [];
        importedAgents = agents.map((raw) => {
          const item = raw as Partial<AgentConfigDraft>;
          return {
            providerId: options.providerModels && item.providerId && providerIds.has(item.providerId) ? item.providerId : nextProviders[0]?.providerId ?? "default",
            modelName: options.providerModels ? String(item.modelName ?? "") : "",
            toolContextMode: options.toolModes && item.toolContextMode === "all" ? "all" : "dynamic",
            agentToolsetIds: options.agentToolsets && Array.isArray(item.agentToolsetIds) ? item.agentToolsetIds.map(String) : [...DEFAULT_AGENT_SPECIAL_TOOLSET_IDS],
            traitMode: options.traits && AGENT_TRAIT_MODES.includes(String(item.traitMode)) ? String(item.traitMode) as AgentConfigDraft["traitMode"] : "inherit",
            systemPrompt: options.prompts ? String(item.systemPrompt ?? "") : "",
            chosenName: options.names ? String(item.chosenName ?? "") : "",
            appearance: options.appearances ? String(item.appearance ?? "") : "",
            avatarDataUrl: options.avatars ? String(item.avatarDataUrl ?? "") : "",
            traits: options.traits ? { ...blankAgentConfig().traits, ...(typeof item.traits === "object" && item.traits ? item.traits : {}) } : blankAgentConfig().traits,
            ttsConfig: options.tts ? normalizeTtsConfig((item as Record<string, unknown>).ttsConfig ?? (item as Record<string, unknown>).tts_config) : blankTtsConfig()
          };
        });
      }
      applyImportedAgentArchive(parsed, importedAgents, options, nextProviders);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const reuseWorldAgentConfig = async (sourceWorldId: string) => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(apiClient.agentPresetsExportUrl(sourceWorldId));
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || response.statusText);
      }
      const blob = await response.blob();
      const file = new File([blob], `${sourceWorldId}-agent-config.tlwagents.zip`, { type: "application/zip" });
      await importAgentArchive(file, DEFAULT_ARCHIVE_FIELD_OPTIONS);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const applyIdentityLibraryItem = (item: IdentityLibraryItem, targetIndex = identityTargetIndex) => {
    const activeConfigs = normalizeAgentConfigs(agentConfigs, createSettings.agentCount, providers[0]?.providerId ?? "default");
    const safeIndex = Math.max(0, Math.min(activeConfigs.length - 1, Math.floor(targetIndex)));
    const matchedProvider = providers.find((provider) => provider.name === item.providerName || provider.baseUrl === item.baseUrl);
    const current = activeConfigs[safeIndex] ?? blankAgentConfig(providers[0]?.providerId ?? "default");
    activeConfigs[safeIndex] = {
      ...current,
      providerId: matchedProvider?.providerId ?? current.providerId,
      modelName: item.modelName || current.modelName,
      toolContextMode: item.toolContextMode === "all" ? "all" : "dynamic",
      agentToolsetIds: item.agentToolsetIds.length ? item.agentToolsetIds : current.agentToolsetIds,
      systemPrompt: item.systemPrompt || "",
      chosenName: item.name || "",
      appearance: item.appearance || item.appearanceShort || "",
      avatarDataUrl: item.avatarDataUrl || "",
      traits: { ...current.traits, ...(item.traits ?? {}) },
      ttsConfig: normalizeTtsConfig(item.ttsConfig),
    };
    setAgentConfigs(activeConfigs);
  };

  const deleteIdentityLibraryItem = async (item: IdentityLibraryItem) => {
    const label = item.name || item.agentId;
    if (!window.confirm(`从历史身份库删除「${label}」？这会删除来源存档里的这个居民身份和直接相关关系/记忆，不能撤销。`)) return;
    setDeletingIdentityId(item.agentId);
    setError(null);
    try {
      await apiClient.deleteIdentityLibraryItem(item.agentId);
      await loadIdentityLibrary();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeletingIdentityId(null);
    }
  };

  const createWorld = async () => {
    setBusy(true);
    setError(null);
    try {
      const activeAgentConfigs = normalizeAgentConfigs(agentConfigs, createSettings.agentCount, providers[0]?.providerId ?? "default");
      const allowBirth = reproductionEnabledForCreateSettings(createSettings);
      const activeBabyModelConfigs = allowBirth
        ? normalizeBabyModelConfigs(babyModelConfigs, providers[0]?.providerId ?? "default").filter((config) => config.modelName.trim())
        : [];
      const created = await apiClient.createWorld({
        name: createSettings.name,
        agent_count: clampAgentCount(createSettings.agentCount),
        collective_core_prompt: createSettings.collectiveCorePrompt || undefined,
        seed: createSettings.seed,
        language: uiSettings.language,
        speed: createSettings.speed,
        prompt_settings: DEFAULT_PROMPT_SETTINGS,
        survival_difficulty: createSettings.survivalDifficulty,
        worldview_id: createSettings.worldviewId,
        core_toolset_enabled: createSettings.coreToolsetEnabled,
        core_toolset_id: createSettings.coreToolsetId,
        optional_toolset_ids: createSettings.optionalToolsetIds,
        world_toolset_id: createSettings.worldToolsetId,
        toolset_id: createSettings.worldToolsetId,
        pregnancy_mode: createSettings.pregnancyMode,
        providers: providers.map((provider) => ({
          provider_id: provider.providerId,
          name: provider.name,
          base_url: provider.baseUrl,
          api_key: provider.apiKey || undefined,
          retry_count: provider.retryCount,
          retry_interval_ms: provider.retryIntervalMs,
          rpm: provider.rpm
        })),
        narrator_config: narratorConfig.enabled ? {
          enabled: true,
          provider_id: narratorConfig.providerId,
          model_name: narratorConfig.modelName || undefined,
          system_prompt: narratorConfig.systemPrompt || undefined
        } : { enabled: false },
        baby_model_configs: activeBabyModelConfigs.map((config) => ({
          provider_id: config.providerId,
          model_name: config.modelName
        })),
        trait_mode: createSettings.traitMode,
        trait_budget: createSettings.traitBudget,
        agent_configs: activeAgentConfigs.map((config) => ({
          provider_id: config.providerId,
          model_name: config.modelName || undefined,
          tool_context_mode: config.toolContextMode,
          agent_toolset_ids: config.agentToolsetIds,
          system_prompt: config.systemPrompt || undefined,
          chosen_name: config.chosenName || undefined,
          appearance: config.appearance || undefined,
          avatar_data_url: config.avatarDataUrl || undefined,
          trait_mode: config.traitMode === "inherit" ? undefined : config.traitMode,
          trait_sliders: config.traits,
          tts_config: serializeTtsConfig(config.ttsConfig)
        }))
      });
      setWorld(created);
      window.localStorage.setItem(LAST_WORLD_ID_KEY, created.world_id);
      await refresh(created.world_id);
      await loadRecentWorlds();
      await loadReusableWorlds();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  const runAction = async (action: "start" | "pause" | "step" | "end" | "summarize") => {
    if (!world) return;
    setBusy(true);
    setError(null);
    try {
      if (action === "start") await apiClient.start(world.world_id);
      if (action === "pause") await apiClient.pause(world.world_id);
      if (action === "step") await apiClient.step(world.world_id);
      if (action === "end") await apiClient.end(world.world_id);
      if (action === "summarize") await apiClient.summarize(world.world_id);
      await refresh(world.world_id);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  const replaceAgentLlm = async (agentId: string, payload: Record<string, unknown>) => {
    if (!world) return;
    setReplacingLlm(true);
    setError(null);
    try {
      const updated = await apiClient.updateAgentLlm(world.world_id, agentId, payload);
      setSelectedAgent(updated);
      await refresh(world.world_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setReplacingLlm(false);
    }
  };

  const updateAgentProfile = async (agentId: string, payload: Record<string, unknown>) => {
    if (!world) return;
    setError(null);
    try {
      const updated = await apiClient.updateAgentProfile(world.world_id, agentId, payload);
      setSelectedAgent(updated);
      await refresh(world.world_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const applyWorldIntervention = async (payload: Record<string, unknown>) => {
    if (!world) return;
    setInterventionBusy(true);
    setError(null);
    try {
      const result = await apiClient.applyIntervention(world.world_id, payload);
      setWorld(result.world);
      await refresh(world.world_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setInterventionBusy(false);
    }
  };

  const importInterventionPack = async (file: File) => {
    setInterventionBusy(true);
    setError(null);
    try {
      const result = await apiClient.importInterventionPack(file);
      setInterventionAbilities(result.abilities);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setInterventionBusy(false);
    }
  };

  const requestEventTts = async (eventId: number) => {
    if (!world) return "";
    const result = await apiClient.eventTts(world.world_id, eventId);
    setEvents((current) => sortEventsChronologically(current.map((event) => event.event_id === eventId ? { ...event, payload: { ...event.payload, tts_audio_data_url: result.audio_data_url } } : event)));
    return result.audio_data_url;
  };

  const updateWorldRuntimeSettings = async (payload: { collective_core_prompt?: string; speed?: "slow" | "fast"; prompt_settings?: Record<string, number> }) => {
    if (!world) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await apiClient.updateWorldRuntimeSettings(world.world_id, payload);
      setWorld(updated);
      await refresh(updated.world_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const eventExportUrl = useMemo(() => {
    if (!world?.world_id) return "";
    const query = new URLSearchParams({
      min_importance: String(filters.minImportance),
      dialogue_only: String(filters.dialogueOnly),
      show_narrator: String(filters.showNarrator),
      include_avatars: String(filters.exportAvatars),
      include_audio: String(filters.exportAudio)
    });
    if (filters.agentId) query.set("agent_id", filters.agentId);
    if (filters.locationId) query.set("location_id", filters.locationId);
    if (filters.startEventId) query.set("start_event_id", filters.startEventId);
    if (filters.endEventId) query.set("end_event_id", filters.endEventId);
    return apiClient.eventsExportUrl(world.world_id, `?${query.toString()}`);
  }, [world?.world_id, filters]);

  const resetToSetup = () => {
    window.localStorage.removeItem(LAST_WORLD_ID_KEY);
    setWorld(null);
    setAgents([]);
    setLocations([]);
    setEvents([]);
    setNarrations([]);
    setMetrics(null);
    setSelectedAgentId(null);
    setSelectedAgent(null);
    setError(null);
    setFilters({ minImportance: 0, dialogueOnly: false, showNarrator: true, exportAvatars: true, exportAudio: false, agentId: "", locationId: "", renderLimit: 2000, startEventId: "", endEventId: "" });
    loadRecentWorlds().catch(() => undefined);
    loadReusableWorlds().catch(() => undefined);
  };

  const openRecentWorld = async (worldId: string) => {
    setBusy(true);
    setError(null);
    try {
      await refresh(worldId);
      window.localStorage.setItem(LAST_WORLD_ID_KEY, worldId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const updateRecentWorldSaveName = async (worldId: string) => {
    setBusy(true);
    setError(null);
    try {
      const updated = await apiClient.updateWorldSaveName(worldId, { save_name: renamingSaveName });
      if (world?.world_id === updated.world_id) setWorld(updated);
      setRenamingWorldId(null);
      setRenamingSaveName("");
      await loadRecentWorlds(recentWorldPage);
      await loadReusableWorlds();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const deleteWorldSave = async (item: World) => {
    const saveName = saveNameForWorld(item);
    if (!window.confirm(`删除存档「${saveName}」？这会删除这个世界的居民、事件、记忆和本地记录，不能撤销。`)) return;
    setBusy(true);
    setDeletingWorldId(item.world_id);
    setError(null);
    try {
      await apiClient.deleteWorld(item.world_id);
      if (window.localStorage.getItem(LAST_WORLD_ID_KEY) === item.world_id) {
        window.localStorage.removeItem(LAST_WORLD_ID_KEY);
      }
      if (world?.world_id === item.world_id) {
        resetToSetup();
      }
      if (renamingWorldId === item.world_id) {
        setRenamingWorldId(null);
        setRenamingSaveName("");
      }
      const nextItems = await loadRecentWorlds(recentWorldPage);
      if (!nextItems.length && recentWorldPage > 1) {
        await loadRecentWorlds(recentWorldPage - 1);
      }
      await loadReusableWorlds();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeletingWorldId(null);
      setBusy(false);
    }
  };

  const filteredEvents = useMemo(() => {
    return events.filter((event) => {
      if (filters.dialogueOnly && !isSpeechEvent(event)) return false;
      if (!filters.showNarrator && event.color_class === "narrator") return false;
      if (filters.agentId && event.actor_agent_id !== filters.agentId && event.target_agent_id !== filters.agentId) return false;
      if (filters.locationId && event.location_id !== filters.locationId) return false;
      if (filters.startEventId && event.event_id < Number(filters.startEventId)) return false;
      if (filters.endEventId && event.event_id > Number(filters.endEventId)) return false;
      return true;
    });
  }, [events, filters]);

  const setupStyle = useMemo(() => ({
    "--left-rail-width": `${uiSettings.leftWidth}px`,
    "--right-rail-width": `${uiSettings.rightWidth}px`
  }) as CSSProperties, [uiSettings]);

  const recentWorldGroups = useMemo(() => {
    const groups = new Map<string, { worldviewId: string; label: string; worlds: World[] }>();
    for (const item of recentWorlds) {
      const worldviewId = worldviewIdForWorld(item);
      const label = worldviewLabelForWorld(item, presetCatalog, uiSettings.language);
      const group = groups.get(worldviewId) ?? { worldviewId, label, worlds: [] };
      group.worlds.push(item);
      groups.set(worldviewId, group);
    }
    return Array.from(groups.values());
  }, [presetCatalog, recentWorlds, uiSettings.language]);

  const recentWorldPageCount = Math.max(1, Math.ceil(recentWorldTotal / RECENT_WORLD_PAGE_SIZE));
  const filteredIdentityLibrary = identityLibrary.filter((item) => {
    const q = identitySearch.trim().toLowerCase();
    if (!q) return true;
    return [item.name, item.appearanceShort, item.worldName, item.saveName, item.modelName, item.providerName, item.worldviewName]
      .join(" ")
      .toLowerCase()
      .includes(q);
  });

  if (languageGateOpen) {
    return (
      <main className={`language-gate theme-${uiSettings.theme}`}>
        <section className="language-gate-card">
          <img src="/tiny-living-world-icon-transparent.png" alt="" />
          <div>
            <p>语言 language</p>
            <h1>Choose Language / 选择语言</h1>
          </div>
          <div className="language-gate-actions">
            <button type="button" onClick={() => chooseLanguage("en")}>
              <strong>English</strong>
              <span>Use English UI and ask agents to speak English.</span>
            </button>
            <button type="button" onClick={() => chooseLanguage("zh")}>
              <strong>中文</strong>
              <span>使用中文界面，并要求角色、身份生成和解说使用中文。</span>
            </button>
          </div>
        </section>
      </main>
    );
  }

  if (!world) {
    const coreToolsets = presetCatalog.core_toolsets?.length ? presetCatalog.core_toolsets : DEFAULT_PRESET_CATALOG.core_toolsets;
    const optionalToolsets = presetCatalog.optional_toolsets?.length ? presetCatalog.optional_toolsets : DEFAULT_PRESET_CATALOG.optional_toolsets;
    const agentSpecialToolsets = presetCatalog.agent_special_toolsets?.length ? presetCatalog.agent_special_toolsets : (DEFAULT_PRESET_CATALOG.agent_special_toolsets ?? []);
    const worldToolsets = presetCatalog.world_toolsets?.length ? presetCatalog.world_toolsets : (presetCatalog.toolsets?.length ? presetCatalog.toolsets : DEFAULT_PRESET_CATALOG.world_toolsets);
    const selectedWorldview = presetCatalog.worldviews.find((item) => item.worldview_id === createSettings.worldviewId) ?? presetCatalog.worldviews[0] ?? DEFAULT_PRESET_CATALOG.worldviews[0];
    const selectedCoreToolset = coreToolsets.find((item) => item.toolset_id === createSettings.coreToolsetId) ?? coreToolsets[0] ?? DEFAULT_PRESET_CATALOG.core_toolsets[0];
    const selectedWorldToolset = worldToolsets.find((item) => item.toolset_id === createSettings.worldToolsetId || item.legacy_toolset_ids?.includes(createSettings.worldToolsetId)) ?? worldToolsets[0] ?? DEFAULT_PRESET_CATALOG.world_toolsets[0];
    const selectedWorldviewName = localizedPresetName(selectedWorldview, uiSettings.language);
    const selectedWorldviewDescription = localizedPresetDescription(selectedWorldview, uiSettings.language);
    const selectedWorldToolsetName = localizedPresetName(selectedWorldToolset, uiSettings.language);
    const selectedWorldToolsetDescription = localizedPresetDescription(selectedWorldToolset, uiSettings.language);
    const allowBirth = reproductionEnabledForCreateSettings(createSettings);
    const tr = (value: string) => t(value, uiSettings.language);
    const setupDifficultyLabel = SURVIVAL_DIFFICULTIES.find((item) => item.value === createSettings.survivalDifficulty)?.label ?? "普通";
    const setupSummary = `${selectedWorldToolsetName} · ${tr(createSettings.coreToolsetEnabled ? "自带工具开启" : "自带工具关闭")} · ${tr(allowBirth ? "生育开启" : "生育关闭")} · ${tr(`${setupDifficultyLabel}难度`)}`;
    return (
      <main className={`setup-shell theme-${uiSettings.theme} ${setupLeftOpen ? "setup-left-open" : ""} ${setupRightOpen ? "setup-right-open" : ""}`} style={setupStyle}>
        <button
          type="button"
          className="setup-drawer-toggle setup-drawer-toggle-left"
          onClick={() => setSetupLeftOpen((value) => !value)}
          title={setupLeftOpen ? "收起左侧栏 / Hide left sidebar" : "拉出左侧栏 / Show left sidebar"}
        >
          {setupLeftOpen ? "‹" : "›"}
        </button>
        <button
          type="button"
          className="setup-drawer-toggle setup-drawer-toggle-right"
          onClick={() => setSetupRightOpen((value) => !value)}
          title={setupRightOpen ? "收起右侧栏 / Hide right sidebar" : "拉出右侧栏 / Show right sidebar"}
        >
          {setupRightOpen ? "›" : "‹"}
        </button>
        {(setupLeftOpen || setupRightOpen) && <button type="button" className="setup-drawer-scrim" aria-label="关闭侧栏 / Close sidebars" onClick={() => {
          setSetupLeftOpen(false);
          setSetupRightOpen(false);
        }} />}
        <aside className="setup-left">
          <section className="panel setup-brand-panel">
            <div className="setup-brand-copy">
              <h1>{tr("微世界")}</h1>
              <p>{restoringWorld ? tr("正在读取本地游玩记录...") : tr("本地中文多 agent 生存互动观察器")}</p>
            </div>
            <img className="setup-brand-icon" src="/tiny-living-world-icon-transparent.png" alt="" />
          </section>
          <UiSettingsPanel settings={uiSettings} onChange={setUiSettings} />
          <section id="setup-identity-library" className="panel identity-library-panel">
            <div className="panel-heading">
              <h2>{tr("历史身份库")}</h2>
              <button type="button" className="icon-button text-icon-button" onClick={() => loadIdentityLibrary().catch((err) => setError(String(err)))}>{tr("刷新")}</button>
            </div>
            <div className="identity-library-controls">
              <input value={identitySearch} placeholder={tr("搜索姓名、世界、模型")} onChange={(event) => setIdentitySearch(event.target.value)} />
              <label>
                {tr("目标")}
                <select value={identityTargetIndex} onChange={(event) => setIdentityTargetIndex(Number(event.target.value))}>
                  {Array.from({ length: createSettings.agentCount }, (_, index) => (
                    <option key={index} value={index}>Agent {index + 1}</option>
                  ))}
                </select>
              </label>
            </div>
            <div className="identity-library-list">
              {filteredIdentityLibrary.length ? filteredIdentityLibrary.slice(0, 80).map((item) => (
                <div className="identity-library-row" key={item.agentId}>
                  <div className="identity-library-avatar">
                    {item.avatarDataUrl ? <img src={item.avatarDataUrl} alt="" /> : <span>{(item.name || "?").slice(0, 1)}</span>}
                  </div>
                  <button type="button" className="identity-library-main" onClick={() => applyIdentityLibraryItem(item)}>
                    <strong>{item.name || tr("未命名身份")}</strong>
                    <span>{item.saveName || item.worldName} · {item.modelName || tr("未指定模型")}</span>
                    <small>{item.appearanceShort || item.appearance.slice(0, 48) || tr("无外貌摘要")}</small>
                  </button>
                  <div className="identity-library-actions">
                    <button type="button" onClick={() => applyIdentityLibraryItem(item)}>{tr("应用")}</button>
                    <button type="button" className="danger-button" disabled={deletingIdentityId === item.agentId} onClick={() => deleteIdentityLibraryItem(item)}>
                      {deletingIdentityId === item.agentId ? tr("删除中") : tr("删除")}
                    </button>
                  </div>
                </div>
              )) : <p className="muted">{tr("还没有可用历史身份。创建或导入人员配置后会出现在这里。")}</p>}
            </div>
          </section>
        </aside>

        <section className="setup-main">
          <div className="setup-main-heading">
            <div className="setup-heading-copy">
              <span>当前预设</span>
              <h1 title={selectedWorldviewName}>{selectedWorldviewName}</h1>
              <p title={setupSummary}>{setupSummary}</p>
            </div>
            <div className="setup-heading-actions">
              <label className="heading-world-name">
                <span>世界名</span>
                {setupMode === "beginner" && <em className="beginner-marker marker-world">绿色: 世界名</em>}
                <input
                  title="这次游玩的世界名称。存档名不是这里改，创建后可在右侧本地游玩记录里修改。"
                  value={createSettings.name}
                  placeholder="给这次世界起个名字"
                  onChange={(event) => setCreateSettings({ ...createSettings, name: event.target.value })}
                />
              </label>
              <label className="heading-setup-mode">
                <span>配置模式</span>
                {setupMode === "beginner" && <em className="beginner-marker marker-world">绿色: 新手/专家</em>}
                <select
                  title="新手模式隐藏复杂选项，适合快速开局；专家模式显示完整世界观、工具、模型、加点和导入导出配置。"
                  value={setupMode}
                  onChange={(event) => setSetupMode(event.target.value === "expert" ? "expert" : "beginner")}
                >
                  <option value="beginner">新手模式</option>
                  <option value="expert">专家模式</option>
                </select>
              </label>
              <label className="heading-agent-count">
                <span>Agent 数量（角色数量）</span>
                {setupMode === "beginner" && <em className="beginner-marker marker-world">绿色: 居民数量</em>}
                <input
                  title="这次开局创建的居民数量。"
                  type="number"
                  min="1"
                  max={MAX_AGENT_COUNT}
                  value={createSettings.agentCount}
                  onChange={(event) => setCreateSettings({ ...createSettings, agentCount: clampAgentCount(event.target.value) })}
                />
              </label>
              <label className="heading-difficulty-select">
                <span>生存难度</span>
                {setupMode === "beginner" && <em className="beginner-marker marker-world">绿色: 生存压力</em>}
                <select
                  title="控制饥饿、口渴、睡眠、疾病和生存压力的强度。"
                  value={createSettings.survivalDifficulty}
                  onChange={(event) => setCreateSettings({ ...createSettings, survivalDifficulty: event.target.value })}
                >
                  {SURVIVAL_DIFFICULTIES.map((difficulty) => (
                    <option key={difficulty.value} value={difficulty.value}>{tr(difficulty.label)}</option>
                  ))}
                </select>
              </label>
              <button className="primary-action" data-auto-title="false" disabled={busy} onClick={createWorld} title="红色步骤: 配置完成后点击这里创建世界。进入游戏后还要点右上角继续按钮。">
                {busy ? tr("正在创建居民...") : tr("创建世界")}
                {setupMode === "beginner" && <em className="beginner-marker marker-start">红色: 创建世界</em>}
              </button>
            </div>
          </div>

          {setupMode === "expert" && (
            <section id="setup-world-config" className="panel create-panel setup-card">
              <div className="panel-heading setup-card-heading">
                <h2>世界配置</h2>
                <span>{createSettings.agentCount} 个居民</span>
              </div>
              <div className="create-fields">
                <label title="相同种子会让部分随机结果更接近，适合复现实验。">
                  种子
                  <input
                    type="number"
                    value={createSettings.seed}
                    onChange={(event) => setCreateSettings({ ...createSettings, seed: Number(event.target.value) })}
                  />
                </label>
                <label title="控制后端自动推进频率。快节奏世界观推荐快速，真实模拟推荐慢速。">
                  速度
                  <select
                    value={createSettings.speed}
                    onChange={(event) => setCreateSettings({ ...createSettings, speed: event.target.value })}
                  >
                    <option value="slow">慢速</option>
                    <option value="fast">快速</option>
                  </select>
                </label>
                {allowBirth && (
                  <label title="控制正常怀孕规则。默认模式任意性别都可怀孕；异性恋模式只有女性可怀孕且伴侣需为男性。">
                    怀孕规则
                    <select
                      value={createSettings.pregnancyMode}
                      onChange={(event) => setCreateSettings({ ...createSettings, pregnancyMode: event.target.value })}
                    >
                      <option value="any_gender">默认：任意性别</option>
                      <option value="heterosexual">异性恋：女方怀孕</option>
                    </select>
                  </label>
                )}
                <label title="决定居民初始人格属性如何分配。玩家加点允许超过固定点数。">
                  属性加点
                  <select
                    value={createSettings.traitMode}
                    onChange={(event) => setCreateSettings({ ...createSettings, traitMode: event.target.value })}
                  >
                    <option value="agent">{tr("Agent 自己加点")}</option>
                    <option value="random">{tr("随机加点")}</option>
                    <option value="player">{tr("玩家加点")}</option>
                  </select>
                </label>
                <label title={tr("Agent 自己加点和随机加点使用的固定总点数参考。")}>
                  固定点数
                  <input
                    type="number"
                    min="0"
                    value={createSettings.traitBudget}
                    onChange={(event) => setCreateSettings({ ...createSettings, traitBudget: Number(event.target.value) })}
                  />
                </label>
              </div>
            </section>
          )}

          <div id="setup-agent-config">
            <ProviderConfigPanel
              agentCount={createSettings.agentCount}
              allowBirth={allowBirth}
              traitMode={createSettings.traitMode}
              traitBudget={createSettings.traitBudget}
              collectiveCorePrompt={createSettings.collectiveCorePrompt}
              providers={providers}
              agentSpecialToolsets={agentSpecialToolsets}
              narratorConfig={narratorConfig}
              babyModelConfigs={babyModelConfigs}
              agentConfigs={agentConfigs}
              reusableWorlds={reusableWorlds.length ? reusableWorlds : recentWorlds}
              pullingProviderId={pullingProviderId}
              setupMode={setupMode}
              language={uiSettings.language}
              onProvidersChange={setProviders}
              onCollectiveCorePromptChange={(value) => setCreateSettings({ ...createSettings, collectiveCorePrompt: value })}
              onNarratorConfigChange={setNarratorConfig}
              onBabyModelConfigsChange={setBabyModelConfigs}
              onAgentConfigsChange={setAgentConfigs}
              onPullModels={pullModels}
              onExportAgentArchive={exportAgentArchive}
              onImportAgentArchive={importAgentArchive}
              onReuseWorldConfig={reuseWorldAgentConfig}
            />
          </div>
          {busy && <p className="muted create-hint">{tr("已有姓名和外貌的居民会直接使用配置；缺少身份时才调用模型补全。")}</p>}
          {error && <p className="error-line">{error}</p>}
        </section>

        <aside className="setup-right">
          <section id="setup-worldpacks" className="panel preset-panel">
            <h2>世界观与工具集</h2>
            <div className="archive-actions worldpack-import-actions">
              <FileDropZone
                accept="application/json,.json,.aiworld,.aiworld.json,.zip,application/zip"
                disabled={worldPackImporting}
                onFile={importWorldPack}
                hint="可拖入世界包"
              >
                导入世界观文件
              </FileDropZone>
              <button type="button" disabled={worldPackImporting} onClick={() => apiClient.presets().then(setPresetCatalog).catch((err) => setError(String(err)))}>
                刷新目录
              </button>
            </div>
            {worldPackImportMessage && <p className="muted">{worldPackImportMessage}</p>}
            {presetCatalog.content_pack_errors?.length ? (
              <div className="error-line">
                世界包有 {presetCatalog.content_pack_errors.length} 个校验错误：{presetCatalog.content_pack_errors[0]?.error || "未知错误"}
              </div>
            ) : null}
            <div className="preset-body">
              <label>
                世界观
                {setupMode === "beginner" && <em className="beginner-marker marker-world">绿色: 选择世界观</em>}
                <select
                  title="选择这次游戏使用的世界观。世界观会决定地点、规则、变量和默认工具集。"
                  value={createSettings.worldviewId}
                  onChange={(event) => applyWorldviewSelection(event.target.value)}
                >
                  {presetCatalog.worldviews.map((item) => (
                    <option key={item.worldview_id} value={item.worldview_id}>{localizedPresetName(item, uiSettings.language)}</option>
                  ))}
                </select>
              </label>
              <p>{selectedWorldviewDescription}</p>
              {setupMode === "expert" && (
                <>
                  <label className="toggle-inline preset-toggle" title="自带基础工具包含观察、说话、移动、睡眠等跨世界通用能力。关闭后需要世界观自己提供足够工具。">
                    <input
                      type="checkbox"
                      checked={createSettings.coreToolsetEnabled}
                      onChange={(event) => setCreateSettings({ ...createSettings, coreToolsetEnabled: event.target.checked })}
                    />
                    启用自带基础工具集
                  </label>
                  <label title="选择跨世界通用的基础行动工具集。">
                    自带工具集
                    <select
                      disabled={!createSettings.coreToolsetEnabled}
                      value={createSettings.coreToolsetId}
                      onChange={(event) => setCreateSettings({ ...createSettings, coreToolsetId: event.target.value })}
                    >
                      {coreToolsets.map((item) => (
                        <option key={item.toolset_id} value={item.toolset_id}>{localizedPresetName(item, uiSettings.language)}</option>
                      ))}
                    </select>
                  </label>
                  <p>{createSettings.coreToolsetEnabled ? localizedPresetDescription(selectedCoreToolset, uiSettings.language) : "已关闭自带工具集。只有当前世界观提供的工具和必要兜底会进入候选工具，特殊世界观可用这种方式完全接管行动体系。"}</p>
                  <div className="optional-toolset-list">
                    <strong title="可选通用工具集可以跨世界观复用，例如生存、生育、金融。">可选通用工具集</strong>
                    {optionalToolsets.map((item) => {
                      const checked = createSettings.optionalToolsetIds.includes(item.toolset_id);
                      const toolsetName = localizedPresetName(item, uiSettings.language);
                      const toolsetDescription = localizedPresetDescription(item, uiSettings.language);
                      return (
                        <label key={item.toolset_id} className="toggle-inline preset-toggle optional-toolset-row" title={toolsetDescription}>
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(event) => {
                              const nextIds = event.target.checked
                                ? Array.from(new Set([...createSettings.optionalToolsetIds, item.toolset_id]))
                                : createSettings.optionalToolsetIds.filter((id) => id !== item.toolset_id);
                              setCreateSettings({ ...createSettings, optionalToolsetIds: nextIds });
                            }}
                          />
                          <span>
                            {toolsetName}
                            <small>{toolsetDescription}</small>
                          </span>
                        </label>
                      );
                    })}
                    {!allowBirth && <p>通用生育与育儿工具集未勾选，所以不会开放怀孕、生子和宝宝模型配置。</p>}
                  </div>
                  <label title="选择当前世界观专属的地点、住房、工作、消费、犯罪等工具集。">
                    世界工具集
                    <select
                      value={selectedWorldToolset.toolset_id}
                      onChange={(event) => setCreateSettings({ ...createSettings, worldToolsetId: event.target.value })}
                    >
                      {worldToolsets.map((item) => (
                        <option key={item.toolset_id} value={item.toolset_id}>{localizedPresetName(item, uiSettings.language)}</option>
                      ))}
                    </select>
                  </label>
                  <p>{selectedWorldToolsetDescription}</p>
                </>
              )}
              <div className="preset-tags">
                <span title={selectedWorldview.packaged ? "这个世界观包随项目内置，不需要额外导入。" : "这个世界观来自你导入的外部世界包。"}>{selectedWorldview.packaged ? "内置包" : "外部包"}</span>
                <span title={`当前世界观版本：${selectedWorldview.version}`}>世界观 v{selectedWorldview.version}</span>
                <span title={createSettings.coreToolsetEnabled ? `自带基础工具集版本：${selectedCoreToolset.version}` : "自带基础工具集已关闭。"}>{createSettings.coreToolsetEnabled ? `自带 v${selectedCoreToolset.version}` : "自带已关闭"}</span>
                <span title={`当前启用 ${createSettings.optionalToolsetIds.length} 个可选通用工具集。`}>可选 {createSettings.optionalToolsetIds.length} 个</span>
                <span title={`世界观专属工具集版本：${selectedWorldToolset.version}。`}>世界工具 v{selectedWorldToolset.version}</span>
              </div>
            </div>
          </section>
          <section id="setup-plugins" className="panel plugin-panel">
            <h2>项目插件</h2>
            <div className="plugin-install-body">
              <FileDropZone
                accept="application/json,.json,.aiworld,.aiworld.json,.zip,application/zip"
                disabled={pluginInstalling}
                onFile={importPluginPack}
                hint="可拖入插件包"
              >
                导入插件包
              </FileDropZone>
              <label>
                GitHub / URL
                <input
                  value={pluginInstallUrl}
                  placeholder="https://github.com/user/repo 或插件 zip/json URL"
                  onChange={(event) => setPluginInstallUrl(event.target.value)}
                />
              </label>
              <button type="button" disabled={pluginInstalling || !pluginInstallUrl.trim()} onClick={installPluginFromUrl}>
                {pluginInstalling ? "安装中" : "安装插件"}
              </button>
              <p>
                插件使用 aiworld.plugin_pack.v1 或世界包格式；安装后会写入本地 worldpacks/imported，并刷新世界观、工具集和工具目录。
              </p>
              {pluginInstallMessage && <p className="muted">{pluginInstallMessage}</p>}
            </div>
          </section>
          <section id="setup-recent-worlds" className="panel recent-worlds">
            <div className="panel-heading">
              <h2>{tr("本地游玩记录")}</h2>
              <button type="button" className="icon-button text-icon-button" onClick={() => loadRecentWorlds(recentWorldPage).catch((err) => setError(String(err)))}>{tr("刷新")}</button>
            </div>
            {recentWorldGroups.length ? (
              <>
                <div className="recent-world-list grouped">
                  {recentWorldGroups.map((group) => (
                    <div key={group.worldviewId} className="recent-world-group">
                      <h3>{group.label}</h3>
                      {group.worlds.map((item) => {
                        const editing = renamingWorldId === item.world_id;
                        return (
                          <div key={item.world_id} className="recent-world-row">
                            <button type="button" className="recent-world-open" disabled={busy} onClick={() => openRecentWorld(item.world_id)}>
                              <strong>{saveNameForWorld(item)}</strong>
                              <span>世界名: {item.name}</span>
                              <span>{item.world_time_label} · {item.status === "running" ? "运行中" : item.status === "paused" ? "暂停" : item.status === "ended" ? "已结束" : item.status}</span>
                            </button>
                            <em>{worldDifficultyLabel(item)}</em>
                            {editing ? (
                              <form className="recent-rename-form" onSubmit={(event) => {
                                event.preventDefault();
                                updateRecentWorldSaveName(item.world_id);
                              }}>
                                <input value={renamingSaveName} placeholder="存档名" onChange={(event) => setRenamingSaveName(event.target.value)} />
                                <button type="submit" disabled={busy}>保存</button>
                                <button type="button" disabled={busy} onClick={() => {
                                  setRenamingWorldId(null);
                                  setRenamingSaveName("");
                                }}>取消</button>
                              </form>
                            ) : (
                              <div className="recent-world-actions">
                                <button type="button" disabled={busy} onClick={() => {
                                  setRenamingWorldId(item.world_id);
                                  setRenamingSaveName(saveNameForWorld(item));
                                }}>改存档名</button>
                                <button
                                  type="button"
                                  className="danger-button"
                                  disabled={busy}
                                  onClick={() => deleteWorldSave(item)}
                                >
                                  <Trash2 size={14} />
                                  <span>{deletingWorldId === item.world_id ? "删除中" : "删除"}</span>
                                </button>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  ))}
                </div>
                <div className="recent-pagination">
                  <button type="button" disabled={busy || recentWorldPage <= 1} onClick={() => loadRecentWorlds(recentWorldPage - 1).catch((err) => setError(String(err)))}>上一页</button>
                  <span>{recentWorldPage} / {recentWorldPageCount} · 共 {recentWorldTotal} 个</span>
                  <button type="button" disabled={busy || recentWorldPage >= recentWorldPageCount} onClick={() => loadRecentWorlds(recentWorldPage + 1).catch((err) => setError(String(err)))}>下一页</button>
                </div>
              </>
            ) : (
              <p className="muted">{tr("还没有本地游玩记录。")}</p>
            )}
          </section>
        </aside>
      </main>
    );
  }

  const agentSpecialToolsets = presetCatalog.agent_special_toolsets?.length ? presetCatalog.agent_special_toolsets : (DEFAULT_PRESET_CATALOG.agent_special_toolsets ?? []);
  const runtimeFeatures = worldUiFeatures(world);

  return (
    <WorldDashboard
      uiSettings={uiSettings}
      controls={
        <Controls
          world={world}
          busy={busy}
          exportUrl={apiClient.exportUrl(world.world_id)}
          presetExportUrl={apiClient.agentPresetsExportUrl(world.world_id)}
          onStart={() => runAction("start")}
          onPause={() => runAction("pause")}
          onStep={() => runAction("step")}
	          onEnd={() => runAction("end")}
	          onSummarize={() => runAction("summarize")}
	          onRefresh={() => refresh()}
	          onNewWorld={resetToSetup}
	          onDeleteWorld={() => deleteWorldSave(world)}
	        />
      }
      left={
        <>
          <UiSettingsPanel settings={uiSettings} onChange={setUiSettings} />
          <MapPanel agents={agents} locations={locations} language={uiSettings.language} />
          <AgentList agents={agents} selectedAgentId={selectedAgentId} onSelect={setSelectedAgentId} language={uiSettings.language} />
          <NarratorPanel narrations={narrations} />
          <SimulationStatusPanel world={world} agents={agents} language={uiSettings.language} />
          {runtimeFeatures.showMetrics && <MetricsPanel world={world} metrics={metrics} />}
        </>
      }
      center={
        <>
          <EventFeed
            agents={agents}
            locations={locations}
            events={filteredEvents}
            filters={filters}
            onFiltersChange={setFilters}
            onRefresh={() => refresh()}
            onRequestTts={requestEventTts}
            exportUrl={eventExportUrl}
            language={uiSettings.language}
          />
          <WorldInterventionPanel agents={agents} locations={locations} busy={interventionBusy} abilities={interventionAbilities} onApply={applyWorldIntervention} onImportPack={importInterventionPack} language={uiSettings.language} />
        </>
      }
      right={
        <>
          <AgentDrawer
            detail={selectedAgent}
            uiFeatures={runtimeFeatures}
            providers={providers}
            agentSpecialToolsets={agentSpecialToolsets}
            pullingProviderId={pullingProviderId}
            replacingLlm={replacingLlm}
            onPullModels={pullModels}
            onReplaceLlm={replaceAgentLlm}
            onUpdateProfile={updateAgentProfile}
          />
          <WorldRuntimePanel world={world} busy={busy} onSave={updateWorldRuntimeSettings} language={uiSettings.language} />
          {runtimeFeatures.showEconomyPanel && <EconomyPanel world={world} metrics={metrics} language={uiSettings.language} />}
        </>
      }
      error={error}
    />
  );
}

export default App;

createRoot(document.getElementById("root") as HTMLElement).render(
  <AppErrorBoundary>
    <App />
  </AppErrorBoundary>
);
