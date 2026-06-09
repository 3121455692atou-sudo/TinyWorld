import { Component, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import type { CSSProperties, ReactNode } from "react";
import { Trash2 } from "lucide-react";
import JSZip from "jszip";
import { apiClient } from "../api/client";
import { connectWorldSocket } from "../api/websocket";
import type {
  AgentArchiveFieldOptions,
  AgentConfigDraft,
  AgentDetail,
  AgentListItem,
  BabyModelDraft,
  EventFilters,
  EventItem,
  ImageGenerationSettings,
  IdentityLibraryItem,
  InterventionAbility,
  LeftSnapshot,
  LlmGenerationSettings,
  Narration,
  NarratorConfigDraft,
  PresetCatalog,
  PromptSettings,
  ProviderDraft,
  TtsConfigDraft,
  WerewolfRoleAssignmentDraft,
  World,
  WorldLocation,
  WorldMetrics,
  WorldRuntimeSettingsPayload,
} from "../api/types";
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
import {
  DEFAULT_UI_SETTINGS,
  UiSettingsPanel,
  type UiSettings,
} from "../components/UiSettingsPanel";
import { WorldDashboard } from "../components/WorldDashboard";
import { WorldInterventionPanel } from "../components/WorldInterventionPanel";
import { WorldRuntimePanel } from "../components/WorldRuntimePanel";
import { installI18nMirror, t, type UiLanguage } from "../i18n";
import "../styles/theme.css";

const TRAIT_KEYS = [
  "openness",
  "caution",
  "sociability",
  "empathy",
  "curiosity",
  "discipline",
  "aggression",
  "honesty",
  "creativity",
  "neuroticism",
];
const DEFAULT_AGENT_COUNT = 6;
const MAX_AGENT_COUNT = 64;
const BUNDLE_ARCHIVE_FORMAT = "aiworld.bundle_manifest.v1";
const WORLD_CONFIG_FORMAT = "aiworld.world_config.v1";
const AGENT_ARCHIVE_FORMAT = "tiny-living-world-agent-config-v2";
const LEGACY_AGENT_ARCHIVE_FORMAT = "tiny-living-world-agent-config-v1";
const EXPORT_NAME_COUNTER_KEY = "tiny-living-world-export-name-counter";
const UI_SETTINGS_KEY = "tiny-living-world-ui-settings";
const UI_LANGUAGE_CHOSEN_KEY = "tiny-living-world-language-chosen";
const LAST_WORLD_ID_KEY = "tiny-living-world-last-world-id";
const PROVIDERS_STORAGE_KEY = "tiny-living-world-providers";
const SETUP_MODE_STORAGE_KEY = "tiny-living-world-setup-mode";
const RECENT_WORLD_PAGE_SIZE = 12;
const RESTORE_WORLD_TIMEOUT_MS = 15000;
const DEFAULT_WORLDVIEW_ID = "fast_modern_worldview";
const REALISTIC_WORLDVIEW_ID = "default_modern_worldview";

const DEFAULT_WEREWOLF_ROLE_ASSIGNMENT: WerewolfRoleAssignmentDraft = {
  mode: "auto",
  counts: { villager: 0, werewolf: 0, seer: 0, coroner: 0, guard: 0 },
  manualRoles: [],
};
const DEFAULT_CORE_TOOLSET_ID = "core_basic_toolset";
const DEFAULT_SURVIVAL_NEEDS_TOOLSET_ID = "survival_needs_toolset";
const DEFAULT_REPRODUCTION_TOOLSET_ID = "reproduction_lifecycle_toolset";
const DEFAULT_FINANCE_INVESTING_TOOLSET_ID = "finance_investing_toolset";
const DEFAULT_WORLD_TOOLSET_ID = "fast_modern_world_toolset";
const REALISTIC_WORLD_TOOLSET_ID = "default_modern_world_toolset";
const DEFAULT_LLM_RETRY_COUNT = 2;
const DEFAULT_LLM_RETRY_INTERVAL_MS = 1500;
const DEFAULT_LLM_REQUEST_TIMEOUT_MS = 300000;
const DEFAULT_LLM_RPM = 0;
const MAX_LLM_RETRY_COUNT = 100000;
const MAX_LLM_RETRY_INTERVAL_MS = 21600000;
const MAX_LLM_REQUEST_TIMEOUT_MS = 86400000;
const MAX_LLM_RPM = 100000;
const DEFAULT_PROMPT_SETTINGS: PromptSettings = {
  memory_limit: 40,
  recent_event_limit: 18,
  recent_self_event_limit: 12,
  action_option_limit: 60,
  dream_memory_limit: 64,
  dream_important_limit: 10,
  dream_background_limit: 5,
};
const DEFAULT_LLM_GENERATION_SETTINGS = {
  stream: false,
  temperature: 0.7,
  top_p: 1,
  max_tokens: 0,
  presence_penalty: 0,
  frequency_penalty: 0,
};
const DEFAULT_AGENT_SPECIAL_TOOLSETS = [
  {
    toolset_id: "agent_social_toolset",
    name: "特殊社交工具集",
    description: "细分社交、求助、安慰、边界、赠送、书信和关系记录工具。",
  },
  {
    toolset_id: "agent_work_toolset",
    name: "特殊工作劳动工具集",
    description: "找工作、打工、加班、休息、抱怨工作或辞职。",
  },
  {
    toolset_id: "agent_creative_toolset",
    name: "特殊创作娱乐工具集",
    description: "写作、唱歌、讲故事、练技能、拍视频、直播或发布作品。",
  },
  {
    toolset_id: "agent_governance_toolset",
    name: "特殊治理公共事务工具集",
    description: "会议、规则、投票倾向、指控、提名和公共事务。",
  },
  {
    toolset_id: "agent_romance_toolset",
    name: "特殊恋爱亲密工具集",
    description: "好感、约会、表白、确认关系、分手、修复关系和抽象成年亲密。",
  },
  {
    toolset_id: "agent_caregiving_toolset",
    name: "特殊照护育儿工具集",
    description: "照顾孩子、教孩子简单技能和主动照护。",
  },
  {
    toolset_id: "agent_crime_toolset",
    name: "特殊犯罪越界工具集",
    description: "偷窃、入室盗窃、威胁、抢劫、攻击和越狱等高风险工具。",
  },
  {
    toolset_id: "agent_finance_toolset",
    name: "特殊金融投资工具集",
    description: "证券账户、行情、股票买卖、保证金和做空。",
  },
];
const DEFAULT_AGENT_SPECIAL_TOOLSET_IDS = DEFAULT_AGENT_SPECIAL_TOOLSETS.map(
  (item) => item.toolset_id,
);
const SURVIVAL_DIFFICULTIES = [
  { value: "FAIRY", label: "童话" },
  { value: "NORMAL", label: "普通" },
  { value: "HARD", label: "困难" },
  { value: "HELL", label: "地狱" },
];
const AGENT_TRAIT_MODES = ["inherit", "agent", "random", "player"];
const DEFAULT_ARCHIVE_FIELD_OPTIONS: AgentArchiveFieldOptions = {
  names: true,
  imagePrompts: true,
  prompts: true,
  appearances: true,
  avatars: true,
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
  prompt_llm_generation: { ...DEFAULT_LLM_GENERATION_SETTINGS, temperature: 0.35, max_tokens: 1600 },
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
  agent_aliases: {},
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

function hasCustomTraitSliders(config: AgentConfigDraft): boolean {
  return TRAIT_KEYS.some((key) => Number(config.traits?.[key] ?? 50) !== 50);
}

function traitModeForCreatePayload(
  config: AgentConfigDraft,
  globalTraitMode: string,
): "agent" | "random" | "player" | undefined {
  if (config.traitMode !== "inherit") return config.traitMode;
  if (globalTraitMode === "player" && !hasCustomTraitSliders(config))
    return "agent";
  return undefined;
}

type SetupMode = "beginner" | "expert";

function loadSetupMode(): SetupMode {
  try {
    return window.localStorage.getItem(SETUP_MODE_STORAGE_KEY) === "expert"
      ? "expert"
      : "beginner";
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

function latestEventByWorldTime(items: EventItem[]): EventItem | null {
  if (!items.length) return null;
  return items.reduce(
    (best, item) => (compareEvents(best, item) <= 0 ? item : best),
    items[0],
  );
}

function worldWithFreshEventClock(world: World, items: EventItem[]): World {
  const latest = latestEventByWorldTime(items);
  if (!latest) return world;
  const worldMinutes = Number(world.current_world_time_minutes ?? 0);
  const eventMinutes = Number(latest.world_time ?? 0);
  if (!Number.isFinite(eventMinutes) || eventMinutes <= worldMinutes)
    return world;
  return {
    ...world,
    current_world_time_minutes: eventMinutes,
    world_time_label: latest.world_time_label || world.world_time_label,
  };
}

function mergeSnapshotAgents(currentAgents: AgentListItem[], snapshotAgents: AgentListItem[]): AgentListItem[] {
  const currentById = new Map(currentAgents.map((agent) => [agent.agent_id, agent]));
  return snapshotAgents.map((agent) => {
    const current = currentById.get(agent.agent_id);
    const currentImage = current?.avatar_hint?.image_data_url;
    if (!currentImage || agent.avatar_hint?.image_data_url) return agent;
    return {
      ...agent,
      avatar_hint: {
        ...(agent.avatar_hint ?? {}),
        image_data_url: currentImage,
      },
    };
  });
}

function hasAnyAgentImage(agents: AgentListItem[]): boolean {
  return agents.some((agent) => Boolean(agent.avatar_hint?.image_data_url));
}

function isRecordValue(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function locationByIdOrSuffix(
  locations: WorldLocation[],
  idOrSuffix: string | null | undefined,
): WorldLocation | null {
  if (!idOrSuffix) return null;
  const direct = locations.find(
    (location) => location.location_id === idOrSuffix,
  );
  if (direct) return direct;
  return (
    locations.find((location) =>
      location.location_id.endsWith(`:${idOrSuffix}`),
    ) ?? null
  );
}

function agentLocationDisplayFromEvents(
  agents: AgentListItem[],
  locations: WorldLocation[],
  items: EventItem[],
): AgentListItem[] {
  if (!agents.length || !items.length) return agents;
  const byId = new Map(agents.map((agent) => [agent.agent_id, { ...agent }]));
  const applyLocation = (
    agentId: string | null | undefined,
    locationId: string | null | undefined,
    locationName?: string | null,
    locationColor?: string | null,
  ) => {
    if (!agentId || !locationId) return;
    const agent = byId.get(agentId);
    if (!agent) return;
    const location = locationByIdOrSuffix(locations, locationId);
    agent.location_id = location?.location_id ?? locationId;
    agent.location_name = location?.name ?? locationName ?? agent.location_name;
    agent.location_color =
      location?.color ?? locationColor ?? agent.location_color;
  };
  const sorted = sortEventsChronologically(items);
  for (const event of sorted) {
    const locationDelta = isRecordValue(event.state_delta?.location)
      ? event.state_delta.location
      : null;
    const deltaAfter =
      typeof locationDelta?.after === "string" ? locationDelta.after : null;
    if (event.actor_agent_id && (deltaAfter || event.event_type === "move")) {
      applyLocation(
        event.actor_agent_id,
        deltaAfter || event.location_id || undefined,
        event.location_name,
        event.location_color,
      );
    }
    if (event.event_type === "werewolf_phase" && isRecordValue(event.payload)) {
      const phase =
        typeof event.payload.phase === "string" ? event.payload.phase : "";
      const localLocation =
        phase === "morning"
          ? "village_square"
          : phase === "discussion"
            ? "discussion_hall"
            : phase === "voting"
              ? "voting_room"
              : "";
      const location = locationByIdOrSuffix(locations, localLocation);
      if (location) {
        for (const agent of byId.values()) {
          if (agent.lifecycle_state === "dead") continue;
          agent.location_id = location.location_id;
          agent.location_name = location.name;
          agent.location_color = location.color ?? agent.location_color;
        }
      }
    }
  }
  return agents.map((agent) => byId.get(agent.agent_id) ?? agent);
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
    batchSize: 1,
  };
}

function normalizeImageGenerationSettings(raw: unknown): ImageGenerationSettings {
  const data = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  const sourceMode = String(data.source_mode ?? data.sourceMode ?? DEFAULT_IMAGE_GENERATION_SETTINGS.source_mode);
  const providerType = String(data.provider_type ?? data.providerType ?? DEFAULT_IMAGE_GENERATION_SETTINGS.provider_type);
  const promptStyle = String(data.prompt_style ?? data.promptStyle ?? DEFAULT_IMAGE_GENERATION_SETTINGS.prompt_style);
  const promptLlmMode = String(data.prompt_llm_mode ?? data.promptLlmMode ?? DEFAULT_IMAGE_GENERATION_SETTINGS.prompt_llm_mode);
  const autoFrequency = String(data.auto_frequency ?? data.autoFrequency ?? DEFAULT_IMAGE_GENERATION_SETTINGS.auto_frequency);
  const displayMode = String(data.display_mode ?? data.displayMode ?? DEFAULT_IMAGE_GENERATION_SETTINGS.display_mode);
  const aliases = data.agent_aliases ?? data.agentAliases;
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
    prompt_llm_generation: normalizeLlmGenerationForImagePrompt(data.prompt_llm_generation ?? data.promptLlmGeneration ?? { ...DEFAULT_LLM_GENERATION_SETTINGS, temperature: 0.35, max_tokens: 1600 }),
    prompt_llm_retry_count: clampNumber(data.prompt_llm_retry_count ?? data.promptLlmRetryCount, 0, 100000, 2),
    prompt_llm_retry_interval_ms: clampNumber(data.prompt_llm_retry_interval_ms ?? data.promptLlmRetryIntervalMs, 0, 21600000, 1500),
    prompt_llm_request_timeout_ms: clampNumber(data.prompt_llm_request_timeout_ms ?? data.promptLlmRequestTimeoutMs, 0, 86400000, 300000),
    prompt_llm_rpm: clampNumber(data.prompt_llm_rpm ?? data.promptLlmRpm, 0, 100000, 0),
    auto_frequency: ["low", "normal", "high"].includes(autoFrequency) ? autoFrequency as ImageGenerationSettings["auto_frequency"] : "normal",
    display_mode: ["placeholder", "wait"].includes(displayMode) ? displayMode as ImageGenerationSettings["display_mode"] : "placeholder",
    base_url: String(data.base_url ?? data.baseUrl ?? ""),
    endpoint_path: String(data.endpoint_path ?? data.endpointPath ?? ""),
    api_key: String(data.api_key === "***" ? "" : data.api_key ?? data.apiKey ?? ""),
    model_name: String(data.model_name ?? data.modelName ?? ""),
    style_prompt: String(data.style_prompt ?? data.stylePrompt ?? ""),
    negative_prompt: String(data.negative_prompt ?? data.negativePrompt ?? ""),
    request_template_json: String(data.request_template_json ?? data.requestTemplateJson ?? ""),
    width: clampNumber(data.width, 256, 2048, 1024),
    height: clampNumber(data.height, 256, 2048, 1024),
    steps: clampNumber(data.steps, 1, 150, 28),
    cfg_scale: clampFloat(data.cfg_scale ?? data.cfgScale, 1, 30, 7),
    sampler: String(data.sampler ?? ""),
    seed: clampNumber(data.seed, -1, 2147483647, -1),
    workflow_json: String(data.workflow_json ?? data.workflowJson ?? ""),
    agent_aliases: aliases && typeof aliases === "object"
      ? Object.fromEntries(Object.entries(aliases as Record<string, unknown>).map(([key, value]) => [key, String(value ?? "")]).filter(([, value]) => value.trim()))
      : {},
  };
}

function serializeImageGenerationSettings(config: ImageGenerationSettings): Record<string, unknown> {
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
    agent_aliases: config.agent_aliases,
  };
}

function isDefaultDisabledImageGenerationSettings(
  config: ImageGenerationSettings,
): boolean {
  return (
    !config.enabled &&
    JSON.stringify(serializeImageGenerationSettings(config)) ===
      JSON.stringify(
        serializeImageGenerationSettings(DEFAULT_IMAGE_GENERATION_SETTINGS),
      )
  );
}

function normalizeLlmGenerationForImagePrompt(raw: unknown): LlmGenerationSettings {
  const data = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  return {
    stream: Boolean(data.stream ?? DEFAULT_LLM_GENERATION_SETTINGS.stream),
    temperature: clampFloat(data.temperature, 0, 2, 0.35),
    top_p: clampFloat(data.top_p, 0, 1, DEFAULT_LLM_GENERATION_SETTINGS.top_p),
    max_tokens: clampNumber(data.max_tokens, 0, 200000, 1600),
    presence_penalty: clampFloat(data.presence_penalty, -2, 2, DEFAULT_LLM_GENERATION_SETTINGS.presence_penalty),
    frequency_penalty: clampFloat(data.frequency_penalty, -2, 2, DEFAULT_LLM_GENERATION_SETTINGS.frequency_penalty),
  };
}

function clampFloat(value: unknown, min: number, max: number, fallback: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, parsed));
}

const DEFAULT_PRESET_CATALOG: PresetCatalog = {
  worldviews: [
    {
      worldview_id: DEFAULT_WORLDVIEW_ID,
      name: "快节奏现代世界观",
      name_i18n: { zh: "快节奏现代世界观", en: "Fast-Paced Modern Worldview" },
      version: "1.1.0",
      packaged: true,
      description:
        "默认推荐的快节奏现代小镇社会模拟世界观。饥渴、金融投资、生育育儿由可选通用工具集控制。",
      description_i18n: {
        zh: "默认推荐的快节奏现代小镇社会模拟世界观。饥渴、金融投资、生育育儿由可选通用工具集控制。",
        en: "Recommended fast-paced modern town simulation worldview. Hunger/thirst, finance, reproduction, and childcare are controlled by optional universal toolsets.",
      },
      status: "active",
    },
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
      description:
        "独立于世界观的观察、说话、移动、睡眠、赠送、记忆和基础求助工具。吃喝补给由生存需求工具集控制。",
      description_i18n: {
        zh: "独立于世界观的观察、说话、移动、睡眠、赠送、记忆和基础求助工具。吃喝补给由生存需求工具集控制。",
        en: "World-independent tools for observing, speaking, moving, sleeping, gifting, memory, and basic help. Eating, drinking, and supplies are controlled by the survival needs toolset.",
      },
      status: "active",
    },
  ],
  optional_toolsets: [
    {
      toolset_id: DEFAULT_SURVIVAL_NEEDS_TOOLSET_ID,
      name: "通用生存需求工具集",
      version: "1.0.0",
      packaged: true,
      scope: "optional",
      default_enabled: true,
      description:
        "控制饥饿、口渴及对应吃喝/补给/求助工具。关闭后适合不吃不喝的特殊世界观。",
      name_i18n: {
        zh: "通用生存需求工具集",
        en: "Universal Survival Needs Toolset",
      },
      description_i18n: {
        zh: "控制饥饿、口渴及对应吃喝/补给/求助工具。关闭后适合不吃不喝的特殊世界观。",
        en: "Controls hunger, thirst, and related eating/drinking/supply/help tools. Disable it for special worlds without eating or drinking.",
      },
      status: "active",
    },
    {
      toolset_id: DEFAULT_REPRODUCTION_TOOLSET_ID,
      name: "通用生育与育儿工具集",
      version: "1.0.0",
      packaged: true,
      scope: "optional",
      default_enabled: true,
      description:
        "可选生命延续模块，包含抽象成年亲密同意、怀孕/避孕/检测、出生、宝宝模型池、孩子成长与基础育儿工具。",
      name_i18n: {
        zh: "通用生育与育儿工具集",
        en: "Universal Reproduction & Childcare Toolset",
      },
      description_i18n: {
        zh: "可选生命延续模块，包含抽象成年亲密同意、怀孕/避孕/检测、出生、宝宝模型池、孩子成长与基础育儿工具。",
        en: "Optional life-continuation module with abstract adult consent, pregnancy/contraception/testing, birth, baby model pools, child growth, and basic childcare tools.",
      },
      status: "active",
    },
    {
      toolset_id: DEFAULT_FINANCE_INVESTING_TOOLSET_ID,
      name: "通用金融投资工具集",
      version: "1.0.0",
      packaged: true,
      scope: "optional",
      default_enabled: true,
      description:
        "控制游戏内虚构证券账户、股票行情、买卖、保证金、做空与市场新闻。",
      name_i18n: {
        zh: "通用金融投资工具集",
        en: "Universal Finance & Investing Toolset",
      },
      description_i18n: {
        zh: "控制游戏内虚构证券账户、股票行情、买卖、保证金、做空与市场新闻。",
        en: "Controls fictional in-game brokerage accounts, stock quotes, trading, margin, short selling, and market news.",
      },
      status: "active",
    },
  ],
  agent_special_toolsets: DEFAULT_AGENT_SPECIAL_TOOLSETS.map((item) => ({
    ...item,
    version: "1.0.0",
    packaged: true,
    scope: "agent_special",
    default_enabled: true,
    status: "active",
  })),
  world_toolsets: [
    {
      toolset_id: DEFAULT_WORLD_TOOLSET_ID,
      legacy_toolset_ids: ["default_modern_toolset"],
      name: "快节奏现代世界工具集",
      name_i18n: {
        zh: "快节奏现代世界工具集",
        en: "Fast-Paced Modern World Toolset",
      },
      version: "1.0.0",
      packaged: true,
      scope: "world",
      worldview_id: DEFAULT_WORLDVIEW_ID,
      description:
        "快节奏现代世界观专用工具集，覆盖现代小镇里的工作、住房、普通消费、犯罪、租房、遗体持续存在与本世界特有设施。",
      description_i18n: {
        zh: "快节奏现代世界观专用工具集，覆盖现代小镇里的工作、住房、普通消费、犯罪、租房、遗体持续存在与本世界特有设施。",
        en: "World-specific toolset for the fast-paced modern worldview, covering modern town work, housing, consumption, crime, rent, persistent bodies, and local facilities.",
      },
      status: "active",
    },
  ],
  toolsets: [
    {
      toolset_id: DEFAULT_WORLD_TOOLSET_ID,
      legacy_toolset_ids: ["default_modern_toolset"],
      name: "快节奏现代世界工具集",
      name_i18n: {
        zh: "快节奏现代世界工具集",
        en: "Fast-Paced Modern World Toolset",
      },
      version: "1.0.0",
      packaged: true,
      scope: "world",
      worldview_id: DEFAULT_WORLDVIEW_ID,
      description: "快节奏现代世界观专用工具集。",
      description_i18n: {
        zh: "快节奏现代世界观专用工具集。",
        en: "World-specific toolset for the fast-paced modern worldview.",
      },
      status: "active",
    },
  ],
  placeholder_interfaces: [
    {
      interface_id: "identity_model_history",
      name: "历史身份与模型库",
      status: "placeholder",
      description: "保存本地历史 agent 身份、头像、提示词与模型组合。",
    },
    {
      interface_id: "plugin_import",
      name: "插件导入",
      status: "placeholder",
      description: "导入插件 zip/manifest 并挂接扩展点。",
    },
    {
      interface_id: "optional_toolset_import",
      name: "通用工具集导入",
      status: "placeholder",
      description: "导入可跨世界观复用的通用工具集。",
    },
    {
      interface_id: "agent_special_toolset_import",
      name: "特殊工具集导入",
      status: "placeholder",
      description: "导入可分配给单个 agent 的特殊工具集。",
    },
    {
      interface_id: "agent_tts",
      name: "Agent TTS 接口",
      status: "placeholder",
      description: "给单个 agent 绑定本地或云端 TTS。",
    },
  ],
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
    imagePromptName: "",
    appearance: "",
    avatarDataUrl: "",
    traits: Object.fromEntries(TRAIT_KEYS.map((key) => [key, 50])),
    knowledgeMode: "none",
    knownAgents: {},
    ttsConfig: blankTtsConfig(),
  };
}

function clampAgentCount(value: unknown): number {
  const count = Number(value);
  if (!Number.isFinite(count)) return 1;
  return Math.max(1, Math.min(MAX_AGENT_COUNT, Math.floor(count)));
}

function normalizeAgentConfig(
  config: AgentConfigDraft | undefined,
  providerId: string,
): AgentConfigDraft {
  const fallback = blankAgentConfig(providerId);
  if (!config) return fallback;
  const rawTraitMode = String(
    (config as Partial<AgentConfigDraft>).traitMode ?? "inherit",
  );
  return {
    ...fallback,
    ...config,
    providerId: config.providerId || providerId,
    toolContextMode: config.toolContextMode === "all" ? "all" : "dynamic",
    agentToolsetIds: Array.isArray(config.agentToolsetIds)
      ? config.agentToolsetIds.map(String)
      : [...DEFAULT_AGENT_SPECIAL_TOOLSET_IDS],
    traitMode: AGENT_TRAIT_MODES.includes(rawTraitMode)
      ? (rawTraitMode as AgentConfigDraft["traitMode"])
      : "inherit",
    traits: { ...fallback.traits, ...(config.traits ?? {}) },
    imagePromptName: String((config as Record<string, unknown>).imagePromptName ?? (config as Record<string, unknown>).image_prompt_name ?? ""),
    knowledgeMode: ["all", "none", "custom"].includes(String((config as Partial<AgentConfigDraft>).knowledgeMode))
      ? ((config as Partial<AgentConfigDraft>).knowledgeMode as AgentConfigDraft["knowledgeMode"])
      : "none",
    knownAgents:
      config.knownAgents && typeof config.knownAgents === "object"
        ? Object.fromEntries(
            Object.entries(config.knownAgents).map(([key, value]) => [
              String(key),
              {
                knows: Boolean(value?.knows),
                affection: Math.max(-100, Math.min(100, Number(value?.affection ?? 0) || 0)),
              },
            ]),
          )
        : {},
    ttsConfig: normalizeTtsConfig(
      (config as Partial<AgentConfigDraft>).ttsConfig,
    ),
  };
}

function normalizeAgentConfigs(
  configs: AgentConfigDraft[],
  count: number,
  providerId: string,
): AgentConfigDraft[] {
  return Array.from({ length: clampAgentCount(count) }, (_, index) =>
    normalizeAgentConfig(configs[index], providerId),
  );
}

function normalizeBabyModelConfigs(
  configs: BabyModelDraft[],
  providerId: string,
): BabyModelDraft[] {
  return configs.map((config) => ({
    providerId: config.providerId || providerId,
    modelName: config.modelName || "",
  }));
}

function normalizeWerewolfRoleAssignment(
  config: WerewolfRoleAssignmentDraft | undefined,
  count: number,
): WerewolfRoleAssignmentDraft {
  const validRoles = new Set(["villager", "werewolf", "seer", "coroner", "guard"]);
  const safeCount = clampAgentCount(count);
  const mode = config?.mode === "counts" || config?.mode === "manual" ? config.mode : "auto";
  return {
    mode,
    counts: {
      villager: Math.max(0, Math.floor(Number(config?.counts?.villager ?? 0) || 0)),
      werewolf: Math.max(0, Math.floor(Number(config?.counts?.werewolf ?? 0) || 0)),
      seer: Math.max(0, Math.floor(Number(config?.counts?.seer ?? 0) || 0)),
      coroner: Math.max(0, Math.floor(Number(config?.counts?.coroner ?? 0) || 0)),
      guard: Math.max(0, Math.floor(Number(config?.counts?.guard ?? 0) || 0)),
    },
    manualRoles: Array.from({ length: safeCount }, (_, index) => {
      const role = String(config?.manualRoles?.[index] ?? "villager");
      return validRoles.has(role) ? role as WerewolfRoleAssignmentDraft["manualRoles"][number] : "villager";
    }),
  };
}

function normalizeTtsConfig(raw: unknown): TtsConfigDraft {
  const fallback = blankTtsConfig();
  if (!raw || typeof raw !== "object") return fallback;
  const item = raw as Partial<TtsConfigDraft> & Record<string, unknown>;
  const mode = ["openai", "mimo", "qwen_dashscope", "gptsovits"].includes(
    String(item.mode),
  )
    ? (item.mode as TtsConfigDraft["mode"])
    : "gptsovits";
  const defaultEndpoint =
    mode === "qwen_dashscope"
      ? "/services/aigc/multimodal-generation/generation"
      : mode === "gptsovits"
        ? "/tts"
        : "/audio/speech";
  const defaultFormat =
    mode === "gptsovits" || mode === "qwen_dashscope" ? "wav" : "mp3";
  return {
    enabled: Boolean(item.enabled),
    provider: String(item.provider ?? ""),
    mode,
    baseUrl: String(item.baseUrl ?? item.base_url ?? ""),
    endpointPath: String(
      item.endpointPath ?? item.endpoint_path ?? defaultEndpoint,
    ),
    apiKey: String(item.apiKey ?? item.api_key ?? ""),
    model: String(item.model ?? ""),
    voice: String(item.voice ?? ""),
    responseFormat: String(
      item.responseFormat ?? item.response_format ?? defaultFormat,
    ),
    languageType: String(item.languageType ?? item.language_type ?? "Chinese"),
    instructions: String(item.instructions ?? ""),
    refAudioPath: String(item.refAudioPath ?? item.ref_audio_path ?? ""),
    promptText: String(item.promptText ?? item.prompt_text ?? ""),
    promptLang: String(item.promptLang ?? item.prompt_lang ?? "zh"),
    textLang: String(item.textLang ?? item.text_lang ?? "zh"),
    textSplitMethod: String(
      item.textSplitMethod ?? item.text_split_method ?? "cut5",
    ),
    batchSize: clampNumber(item.batchSize ?? item.batch_size, 1, 32, 1),
  };
}

function serializeTtsConfig(
  config: TtsConfigDraft,
): Record<string, unknown> | undefined {
  const normalized = normalizeTtsConfig(config);
  const hasConfig =
    normalized.enabled ||
    [
      normalized.provider,
      normalized.baseUrl,
      normalized.endpointPath,
      normalized.apiKey,
      normalized.model,
      normalized.voice,
      normalized.refAudioPath,
      normalized.promptText,
    ].some((value) => value.trim());
  if (!hasConfig) return undefined;
  const payload: Record<string, unknown> = {
    enabled: normalized.enabled,
    provider: normalized.provider.trim(),
    mode: normalized.mode,
    base_url: normalized.baseUrl.trim(),
    endpoint_path: normalized.endpointPath.trim(),
    response_format:
      normalized.responseFormat.trim() ||
      (normalized.mode === "openai" ? "mp3" : "wav"),
    model: normalized.model.trim(),
    voice: normalized.voice.trim(),
    language_type: normalized.languageType.trim() || "Chinese",
    instructions: normalized.instructions.trim(),
    ref_audio_path: normalized.refAudioPath.trim(),
    prompt_text: normalized.promptText.trim(),
    prompt_lang: normalized.promptLang.trim() || "zh",
    text_lang: normalized.textLang.trim() || "zh",
    text_split_method: normalized.textSplitMethod.trim() || "cut5",
    batch_size: normalized.batchSize,
  };
  if (normalized.apiKey.trim()) payload.api_key = normalized.apiKey.trim();
  return payload;
}

function normalizeImportedProviders(
  rawProviders: unknown[],
  currentProviders: ProviderDraft[],
): ProviderDraft[] {
  const currentById = new Map(
    currentProviders.map((provider) => [provider.providerId, provider]),
  );
  const imported = rawProviders.map((raw, index) => {
    const item = raw as Partial<ProviderDraft>;
    const providerId = String(item.providerId || `imported_${index + 1}`);
    const previous = currentById.get(providerId);
    return {
      providerId,
      name: String(item.name || previous?.name || providerId),
      baseUrl: String(item.baseUrl || previous?.baseUrl || ""),
      apiKey: String(item.apiKey || previous?.apiKey || ""),
      retryCount: clampNumber(
        item.retryCount ??
          (item as Record<string, unknown>).retry_count ??
          previous?.retryCount,
        0,
        MAX_LLM_RETRY_COUNT,
        DEFAULT_LLM_RETRY_COUNT,
      ),
      retryIntervalMs: clampNumber(
        item.retryIntervalMs ??
          (item as Record<string, unknown>).retry_interval_ms ??
          previous?.retryIntervalMs,
        0,
        MAX_LLM_RETRY_INTERVAL_MS,
        DEFAULT_LLM_RETRY_INTERVAL_MS,
      ),
      requestTimeoutMs: clampNumber(
        item.requestTimeoutMs ??
          (item as Record<string, unknown>).request_timeout_ms ??
          previous?.requestTimeoutMs,
        0,
        MAX_LLM_REQUEST_TIMEOUT_MS,
        DEFAULT_LLM_REQUEST_TIMEOUT_MS,
      ),
      rpm: clampNumber(
        item.rpm ?? previous?.rpm,
        0,
        MAX_LLM_RPM,
        DEFAULT_LLM_RPM,
      ),
      models: Array.isArray(item.models)
        ? item.models.map(String)
        : (previous?.models ?? []),
    };
  });
  const merged = [
    ...currentProviders.filter(
      (provider) =>
        !imported.some((item) => item.providerId === provider.providerId),
    ),
    ...imported,
  ];
  return merged.length ? merged : currentProviders;
}

function historyProviderIdForIdentity(item: IdentityLibraryItem): string {
  const source =
    `${item.providerName || "history"}|${item.baseUrl || ""}`.trim() ||
    item.agentId;
  let hash = 0;
  for (let index = 0; index < source.length; index += 1) {
    hash = ((hash << 5) - hash + source.charCodeAt(index)) | 0;
  }
  return `history_${Math.abs(hash).toString(36)}`;
}

function upsertIdentityProvider(
  current: ProviderDraft[],
  item: IdentityLibraryItem,
): { providers: ProviderDraft[]; providerId: string | null } {
  const providerName = item.providerName.trim();
  const baseUrl = item.baseUrl.trim();
  const matched = current.find(
    (provider) =>
      (providerName && provider.name === providerName) ||
      (baseUrl && provider.baseUrl === baseUrl),
  );
  if (matched) {
    const modelName = item.modelName.trim();
    if (!modelName || matched.models.includes(modelName))
      return { providers: current, providerId: matched.providerId };
    return {
      providers: current.map((provider) =>
        provider.providerId === matched.providerId
          ? { ...provider, models: [...provider.models, modelName] }
          : provider,
      ),
      providerId: matched.providerId,
    };
  }
  if (!providerName && !baseUrl)
    return { providers: current, providerId: null };
  const providerId = historyProviderIdForIdentity(item);
  const existing = current.find(
    (provider) => provider.providerId === providerId,
  );
  const modelName = item.modelName.trim();
  if (existing) {
    return {
      providers: current.map((provider) =>
        provider.providerId === providerId &&
        modelName &&
        !provider.models.includes(modelName)
          ? { ...provider, models: [...provider.models, modelName] }
          : provider,
      ),
      providerId,
    };
  }
  const runtime = item.llmRuntime ?? {};
  return {
    providers: [
      ...current,
      {
        providerId,
        name: providerName || "历史提供商",
        baseUrl,
        apiKey: "",
        retryCount: clampNumber(
          runtime.retry_count,
          0,
          MAX_LLM_RETRY_COUNT,
          DEFAULT_LLM_RETRY_COUNT,
        ),
        retryIntervalMs: clampNumber(
          runtime.retry_interval_ms,
          0,
          MAX_LLM_RETRY_INTERVAL_MS,
          DEFAULT_LLM_RETRY_INTERVAL_MS,
        ),
        requestTimeoutMs: clampNumber(
          runtime.request_timeout_ms,
          0,
          MAX_LLM_REQUEST_TIMEOUT_MS,
          DEFAULT_LLM_REQUEST_TIMEOUT_MS,
        ),
        rpm: clampNumber(runtime.rpm, 0, MAX_LLM_RPM, DEFAULT_LLM_RPM),
        models: modelName ? [modelName] : [],
      },
    ],
    providerId,
  };
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
      requestTimeoutMs: DEFAULT_LLM_REQUEST_TIMEOUT_MS,
      rpm: DEFAULT_LLM_RPM,
      models: [],
    },
  ];
}

function loadProviders(): ProviderDraft[] {
  try {
    const parsed = JSON.parse(
      window.localStorage.getItem(PROVIDERS_STORAGE_KEY) || "[]",
    );
    if (Array.isArray(parsed) && parsed.length) {
      return normalizeImportedProviders(parsed, defaultProviders());
    }
  } catch {
    window.localStorage.removeItem(PROVIDERS_STORAGE_KEY);
  }
  return defaultProviders();
}

function safeArchiveName(value: string, fallback: string): string {
  const cleaned = value
    .trim()
    .replace(/[\\/:*?"<>|]/g, "_")
    .replace(/\s+/g, "_");
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

function dataUrlToBytes(
  dataUrl: string,
): { bytes: Uint8Array; extension: string } | null {
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

async function isZipLikeFile(file: File): Promise<boolean> {
  const lowerName = file.name.toLowerCase();
  if (lowerName.endsWith(".zip") || lowerName.includes(".zip.")) return true;
  const header = new Uint8Array(await file.slice(0, 4).arrayBuffer());
  return (
    header[0] === 0x50 &&
    header[1] === 0x4b &&
    (header[2] === 0x03 || header[2] === 0x05 || header[2] === 0x07) &&
    (header[3] === 0x04 || header[3] === 0x06 || header[3] === 0x08)
  );
}

function clampNumber(
  value: unknown,
  min: number,
  max: number,
  fallback: number,
): number {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(min, Math.min(max, Math.round(number)));
}

function loadUiSettings(): UiSettings {
  try {
    const parsed = JSON.parse(
      window.localStorage.getItem(UI_SETTINGS_KEY) || "{}",
    ) as Partial<UiSettings>;
    return {
      theme: parsed.theme === "dark" ? "dark" : "light",
      language: parsed.language === "en" ? "en" : "zh",
      leftWidth: clampNumber(
        parsed.leftWidth,
        220,
        460,
        DEFAULT_UI_SETTINGS.leftWidth,
      ),
      rightWidth: clampNumber(
        parsed.rightWidth,
        260,
        560,
        DEFAULT_UI_SETTINGS.rightWidth,
      ),
      eventFontSize: clampNumber(
        parsed.eventFontSize,
        12,
        20,
        DEFAULT_UI_SETTINGS.eventFontSize,
      ),
      eventAvatarSize: clampNumber(
        parsed.eventAvatarSize,
        30,
        64,
        DEFAULT_UI_SETTINGS.eventAvatarSize,
      ),
      ttsGenerationMode:
        parsed.ttsGenerationMode === "on_speech" ? "on_speech" : "on_demand",
    };
  } catch {
    return DEFAULT_UI_SETTINGS;
  }
}

function isSpeechEvent(event: EventItem): boolean {
  return Boolean(speechTextFromEvent(event));
}

function speechTextFromEvent(event: EventItem): string {
  const lines = event.payload?.dialogue_lines;
  if (Array.isArray(lines)) {
    for (const line of lines) {
      if (!line || typeof line !== "object") continue;
      const record = line as Record<string, unknown>;
      for (const key of ["text", "speech"] as const) {
        const value = record[key];
        if (typeof value === "string") {
          const cleaned = sanitizeSpeechText(value);
          if (cleaned) return cleaned;
        }
      }
    }
  }
  const speech = event.payload?.speech;
  return typeof speech === "string" ? sanitizeSpeechText(speech) : "";
}

function sanitizeSpeechText(value: string): string {
  const trimmed = value.trim();
  if (!trimmed || containsMechanicalBackendLanguage(trimmed)) return "";
  return trimmed;
}

function containsMechanicalBackendLanguage(text: string): boolean {
  return /工具调用格式错误|当前尝试的工具|请重新选择|failure_reason_code|llm_feedback|state_delta|payload|validation\.message|后端|硬规则|基础饱腹规则|数值变化|机制词|抽象结果|EffectEngine|RuleEngine|参数完整且符合|工具失败|这个行动需要第二行|这个行动需要台词|当前生命状态不能执行这个行为/iu.test(
    text,
  );
}

function findBundleComponent(
  bundle: Record<string, unknown>,
  type: string,
): Record<string, unknown> {
  const components = Array.isArray(bundle.components) ? bundle.components : [];
  const component = components.find(
    (item) =>
      item &&
      typeof item === "object" &&
      String((item as Record<string, unknown>).type) === type,
  );
  if (!component || typeof component !== "object") {
    throw new Error(`bundle manifest 缺少 ${type} 组件`);
  }
  return component as Record<string, unknown>;
}

function findOptionalBundleComponent(
  bundle: Record<string, unknown>,
  type: string,
): Record<string, unknown> | null {
  const components = Array.isArray(bundle.components) ? bundle.components : [];
  const component = components.find(
    (item) =>
      item &&
      typeof item === "object" &&
      String((item as Record<string, unknown>).type) === type,
  );
  return component && typeof component === "object"
    ? (component as Record<string, unknown>)
    : null;
}

function mergeImportedWorldAndAgentConfig(
  worldConfig: Record<string, unknown> | null,
  agentConfig: Record<string, unknown>,
): Record<string, unknown> {
  if (!worldConfig) return agentConfig;
  const merged = { ...worldConfig, ...agentConfig };
  if (
    !(
      agentConfig.imageGeneration &&
      typeof agentConfig.imageGeneration === "object"
    ) &&
    worldConfig.imageGeneration &&
    typeof worldConfig.imageGeneration === "object"
  ) {
    merged.imageGeneration = worldConfig.imageGeneration;
  }
  return merged;
}

function worldDifficultyLabel(world: World): string {
  return String(
    world.settings?.survival_difficulty_label ||
      world.settings?.survival_difficulty ||
      "普通",
  );
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

function localizedPresetName(
  item: LocalizedPreset,
  language: UiLanguage,
): string {
  return String((item.packaged ? item.name_i18n?.[language] : "") || item.name);
}

function localizedPresetDescription(
  item: LocalizedPreset,
  language: UiLanguage,
): string {
  return String(
    (item.packaged ? item.description_i18n?.[language] : "") ||
      item.description ||
      "",
  );
}

function nextTinyWorldExportName(extension: string): string {
  const current = Number(
    window.localStorage.getItem(EXPORT_NAME_COUNTER_KEY) || "0",
  );
  const next = Number.isFinite(current) ? current + 1 : 1;
  window.localStorage.setItem(EXPORT_NAME_COUNTER_KEY, String(next));
  return `TinyWorld-${next}.${extension}`;
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function worldviewLabelForWorld(
  world: World,
  catalog: PresetCatalog,
  language: UiLanguage,
): string {
  const worldviewId = worldviewIdForWorld(world);
  const preset = catalog.worldviews.find(
    (item) => item.worldview_id === worldviewId,
  );
  if (preset) return localizedPresetName(preset, language);
  return String(world.settings?.worldview_name || "默认现代世界观");
}

function saveNameForWorld(world: World): string {
  return String(
    world.save_name || world.settings?.save_name || world.name || "未命名存档",
  );
}

function reproductionEnabledForCreateSettings(settings: {
  optionalToolsetIds: string[];
}): boolean {
  return settings.optionalToolsetIds.includes(DEFAULT_REPRODUCTION_TOOLSET_ID);
}

function financeEnabledFromWorldSettings(
  settings: Record<string, unknown>,
): boolean {
  const optionalIds = Array.isArray(settings.enabled_optional_toolset_ids)
    ? settings.enabled_optional_toolset_ids.map(String)
    : [];
  const market = asPlainRecord(settings.v6_market);
  const stocks = asPlainRecord(market.stocks);
  return boolFromUnknown(
    settings.finance_investing_enabled,
    optionalIds.includes(DEFAULT_FINANCE_INVESTING_TOOLSET_ID) ||
      Object.keys(stocks).length > 0,
  );
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
  const toolsetId = String(
    settings.world_toolset_id ?? settings.toolset_id ?? "",
  );
  const defaultModern =
    [DEFAULT_WORLDVIEW_ID, REALISTIC_WORLDVIEW_ID].includes(worldviewId) ||
    [
      DEFAULT_WORLD_TOOLSET_ID,
      REALISTIC_WORLD_TOOLSET_ID,
      "default_modern_toolset",
    ].includes(toolsetId);
  const financeEnabled = financeEnabledFromWorldSettings(settings);
  const reproductionEnabled = boolFromUnknown(
    settings.reproduction_enabled,
    false,
  );
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
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function boolFromUnknown(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function readableError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function withTimeout<T>(promise: Promise<T>, ms: number, message: string): Promise<T> {
  let timeoutId: number | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timeoutId = window.setTimeout(() => reject(new Error(message)), ms);
  });
  return Promise.race([promise, timeout]).finally(() => {
    if (timeoutId !== undefined) window.clearTimeout(timeoutId);
  }) as Promise<T>;
}

class AppErrorBoundary extends Component<
  { children: ReactNode },
  { error: string | null }
> {
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
            <button
              className="primary-action"
              type="button"
              onClick={() => window.location.reload()}
            >
              重新加载
            </button>
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
  const [interventionAbilities, setInterventionAbilities] = useState<
    InterventionAbility[]
  >([]);
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
  const [filters, setFilters] = useState<EventFilters>({
    minImportance: 0,
    dialogueOnly: false,
    showNarrator: true,
    exportAvatars: true,
    exportAudio: false,
    agentId: "",
    locationId: "",
    renderLimit: 2000,
    startEventId: "",
    endEventId: "",
  });
  const [createSettings, setCreateSettings] = useState({
    name: "微世界",
    agentCount: DEFAULT_AGENT_COUNT,
    collectiveCorePrompt: "",
    seed: Date.now() % 100000000,
    speed: "slow",
    agentRequestMode: "serial" as "serial" | "parallel",
    survivalDifficulty: "NORMAL",
    worldviewId: DEFAULT_WORLDVIEW_ID,
    coreToolsetEnabled: true,
    coreToolsetId: DEFAULT_CORE_TOOLSET_ID,
    optionalToolsetIds: [
      DEFAULT_SURVIVAL_NEEDS_TOOLSET_ID,
      DEFAULT_REPRODUCTION_TOOLSET_ID,
      DEFAULT_FINANCE_INVESTING_TOOLSET_ID,
    ],
    worldToolsetId: DEFAULT_WORLD_TOOLSET_ID,
    pregnancyMode: "any_gender",
    traitMode: "agent",
    traitBudget: 500,
    llmGeneration: DEFAULT_LLM_GENERATION_SETTINGS,
    imageGeneration: DEFAULT_IMAGE_GENERATION_SETTINGS,
    werewolfRoleAssignment: DEFAULT_WEREWOLF_ROLE_ASSIGNMENT,
  });
  const [providers, setProviders] = useState<ProviderDraft[]>(() =>
    loadProviders(),
  );
  const [narratorConfig, setNarratorConfig] = useState<NarratorConfigDraft>({
    enabled: true,
    providerId: "default",
    modelName: "",
    systemPrompt: "",
  });
  const [babyModelConfigs, setBabyModelConfigs] = useState<BabyModelDraft[]>(
    [],
  );
  const [agentConfigs, setAgentConfigs] = useState<AgentConfigDraft[]>(
    Array.from({ length: DEFAULT_AGENT_COUNT }, () => blankAgentConfig()),
  );
  const [pullingProviderId, setPullingProviderId] = useState<string | null>(
    null,
  );
  const [uiSettings, setUiSettings] = useState<UiSettings>(() =>
    loadUiSettings(),
  );
  const [languageGateOpen, setLanguageGateOpen] = useState(() =>
    needsInitialLanguageChoice(),
  );
  const [setupMode, setSetupMode] = useState<SetupMode>(() => loadSetupMode());
  const [setupLeftOpen, setSetupLeftOpen] = useState(false);
  const [setupRightOpen, setSetupRightOpen] = useState(false);
  const [presetCatalog, setPresetCatalog] = useState<PresetCatalog>(
    DEFAULT_PRESET_CATALOG,
  );
  const [worldPackImporting, setWorldPackImporting] = useState(false);
  const [worldPackImportMessage, setWorldPackImportMessage] = useState("");
  const [pluginInstalling, setPluginInstalling] = useState(false);
  const [pluginInstallUrl, setPluginInstallUrl] = useState("");
  const [pluginInstallMessage, setPluginInstallMessage] = useState("");
  const [identityLibrary, setIdentityLibrary] = useState<IdentityLibraryItem[]>(
    [],
  );
  const [identitySearch, setIdentitySearch] = useState("");
  const [identityTargetIndex, setIdentityTargetIndex] = useState(0);
  const [identityWorldFilter, setIdentityWorldFilter] = useState("all");
  const [identityModelFilter, setIdentityModelFilter] = useState("all");
  const [identitySortMode, setIdentitySortMode] = useState<"recent" | "name" | "world">("recent");
  const [identityAvatarOnly, setIdentityAvatarOnly] = useState(false);
  const [deletingIdentityId, setDeletingIdentityId] = useState<string | null>(
    null,
  );
  const [interventionBusy, setInterventionBusy] = useState(false);
  const [leftRefreshBusy, setLeftRefreshBusy] = useState(false);
  const [lastLeftRefreshLabel, setLastLeftRefreshLabel] = useState("");
  const activeWorldIdRef = useRef<string | null>(null);
  const navigationVersionRef = useRef(0);
  const refreshSequenceRef = useRef(0);
  const selectedAgentIdRef = useRef<string | null>(null);
  const scheduledRefreshRef = useRef<number | null>(null);
  const refreshInFlightRef = useRef(false);
  const refreshPendingRef = useRef(false);
  const leftRefreshInFlightRef = useRef(false);
  const leftRefreshQueuedRef = useRef(false);
  const leftSnapshotSequenceRef = useRef(0);
  const fullAgentImagesLoadedWorldsRef = useRef<Set<string>>(new Set());
  const autoTtsKnownEventIdsRef = useRef<Set<number>>(new Set());
  const autoTtsInFlightEventIdsRef = useRef<Set<number>>(new Set());
  const autoTtsInitializedWorldRef = useRef<string | null>(null);
  const importedImageGenerationRef = useRef<ImageGenerationSettings | null>(null);
  const importedImagePromptNamesRef = useRef<Record<string, string>>({});

  const activateWorldView = (worldId: string) => {
    activeWorldIdRef.current = worldId;
    navigationVersionRef.current += 1;
    window.localStorage.setItem(LAST_WORLD_ID_KEY, worldId);
  };

  const deactivateWorldView = () => {
    activeWorldIdRef.current = null;
    navigationVersionRef.current += 1;
    if (scheduledRefreshRef.current !== null) {
      window.clearTimeout(scheduledRefreshRef.current);
      scheduledRefreshRef.current = null;
    }
    refreshInFlightRef.current = false;
    refreshPendingRef.current = false;
    leftRefreshInFlightRef.current = false;
    leftRefreshQueuedRef.current = false;
    leftSnapshotSequenceRef.current += 1;
    setLeftRefreshBusy(false);
    setLastLeftRefreshLabel("");
    autoTtsKnownEventIdsRef.current.clear();
    autoTtsInFlightEventIdsRef.current.clear();
    autoTtsInitializedWorldRef.current = null;
    fullAgentImagesLoadedWorldsRef.current.clear();
    window.localStorage.removeItem(LAST_WORLD_ID_KEY);
  };

  const loadRecentWorlds = async (page = recentWorldPage) => {
    const safePage = Math.max(1, Math.floor(page));
    const result = await apiClient.worlds({
      limit: RECENT_WORLD_PAGE_SIZE,
      offset: (safePage - 1) * RECENT_WORLD_PAGE_SIZE,
    });
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

  const applyLeftSnapshot = (snapshot: LeftSnapshot, worldId: string) => {
    if (activeWorldIdRef.current !== worldId) return;
    setWorld((current) => {
      if (current && current.world_id !== snapshot.world.world_id)
        return current;
      const currentMinutes = Number(current?.current_world_time_minutes ?? 0);
      const snapshotMinutes = Number(
        snapshot.world.current_world_time_minutes ?? 0,
      );
      const mergedSnapshotWorld = current
        ? {
            ...snapshot.world,
            settings:
              snapshot.world.settings &&
              Object.keys(snapshot.world.settings).length
                ? snapshot.world.settings
                : current.settings,
          }
        : snapshot.world;
      return !current || snapshotMinutes >= currentMinutes
        ? mergedSnapshotWorld
        : {
            ...mergedSnapshotWorld,
            current_world_time_minutes: currentMinutes,
            world_time_label: current.world_time_label,
          };
    });
    setAgents((currentAgents) => mergeSnapshotAgents(currentAgents, snapshot.agents));
    setLocations(snapshot.locations);
    const date = snapshot.refreshed_at
      ? new Date(snapshot.refreshed_at)
      : new Date();
    setLastLeftRefreshLabel(
      Number.isNaN(date.getTime())
        ? new Date().toLocaleTimeString()
        : date.toLocaleTimeString(),
    );
    window.localStorage.setItem(LAST_WORLD_ID_KEY, snapshot.world.world_id);
  };

  const ensureFullAgentImages = async (worldId: string, isStillActive: () => boolean) => {
    if (fullAgentImagesLoadedWorldsRef.current.has(worldId)) return;
    fullAgentImagesLoadedWorldsRef.current.add(worldId);
    try {
      const result = await apiClient.agents(worldId);
      if (!isStillActive()) return;
      if (!hasAnyAgentImage(result.agents)) return;
      setAgents((currentAgents) =>
        currentAgents.length ? mergeSnapshotAgents(result.agents, currentAgents) : result.agents,
      );
    } catch (err) {
      fullAgentImagesLoadedWorldsRef.current.delete(worldId);
      if (isStillActive()) setError(readableError(err));
    }
  };

  const refreshLeftState = async (
    worldId = world?.world_id,
    options: { manual?: boolean; force?: boolean } = {},
  ) => {
    if (!worldId) return;
    if (!options.force && leftRefreshInFlightRef.current) {
      leftRefreshQueuedRef.current = true;
      return;
    }
    const refreshVersion = navigationVersionRef.current;
    const isStillActive = () =>
      activeWorldIdRef.current === worldId &&
      navigationVersionRef.current === refreshVersion;
    const snapshotSequence = ++leftSnapshotSequenceRef.current;
    leftRefreshInFlightRef.current = true;
    if (options.manual) setLeftRefreshBusy(true);
    try {
      const snapshot = await apiClient.leftSnapshot(worldId);
      if (!isStillActive() || snapshotSequence !== leftSnapshotSequenceRef.current)
        return;
      applyLeftSnapshot(snapshot, worldId);
      if (!hasAnyAgentImage(snapshot.agents)) void ensureFullAgentImages(worldId, isStillActive);
    } catch (err) {
      if (isStillActive()) setError(readableError(err));
    } finally {
      leftRefreshInFlightRef.current = false;
      if (options.manual) setLeftRefreshBusy(false);
      if (
        leftRefreshQueuedRef.current &&
        activeWorldIdRef.current === worldId
      ) {
        leftRefreshQueuedRef.current = false;
        refreshLeftState(worldId).catch((err) => {
          if (activeWorldIdRef.current === worldId)
            setError(readableError(err));
        });
      }
    }
  };

  const refresh = async (worldId = world?.world_id) => {
    if (!worldId) return;
    const refreshVersion = navigationVersionRef.current;
    const detailAgentId = selectedAgentIdRef.current;
    const isStillActive = () =>
      activeWorldIdRef.current === worldId &&
      navigationVersionRef.current === refreshVersion;
    const eventQuery = new URLSearchParams({
      min_importance: String(filters.minImportance),
      limit: String(filters.renderLimit),
      latest: "true",
    });
    if (filters.locationId) eventQuery.set("location_id", filters.locationId);
    if (filters.agentId) eventQuery.set("agent_id", filters.agentId);
    if (filters.startEventId)
      eventQuery.set("start_event_id", filters.startEventId);
    if (filters.endEventId) eventQuery.set("end_event_id", filters.endEventId);
    if (filters.dialogueOnly) eventQuery.set("dialogue_only", "true");
    if (!filters.showNarrator) eventQuery.set("show_narrator", "false");

    const applyError = (reason: unknown) => {
      if (isStillActive()) setError(readableError(reason));
    };
    let snapshotAgentsForLlm: AgentListItem[] | null = null;
    const latestLlmStalledEvents: EventItem[] = [];

    // Use the atomic left snapshot as the single source of truth for the clock,
    // agents and locations.  The old full refresh fetched these from three
    // independent endpoints; a slower stale response could overwrite a newer
    // manual left refresh and make the map/time look frozen until reload.
    const snapshotSequence = ++leftSnapshotSequenceRef.current;
    const leftSnapshotTask = apiClient
      .leftSnapshot(worldId)
      .then((snapshot) => {
        if (!isStillActive() || snapshotSequence !== leftSnapshotSequenceRef.current)
          return;
        snapshotAgentsForLlm = snapshot.agents;
        applyLeftSnapshot(snapshot, worldId);
        if (!hasAnyAgentImage(snapshot.agents)) void ensureFullAgentImages(worldId, isStillActive);
      })
      .catch(applyError);

    const needsFullWorldSettings =
      !world ||
      world.world_id !== worldId ||
      !world.settings ||
      !Object.keys(world.settings).length;
    const fullWorldTask = needsFullWorldSettings
      ? apiClient
          .getWorld(worldId)
          .then((loadedWorld) => {
            if (!isStillActive()) return;
            setWorld((current) => {
              if (!current || current.world_id !== loadedWorld.world_id)
                return loadedWorld;
              const currentMinutes = Number(
                current.current_world_time_minutes ?? 0,
              );
              const loadedMinutes = Number(
                loadedWorld.current_world_time_minutes ?? 0,
              );
              return loadedMinutes >= currentMinutes
                ? loadedWorld
                : {
                    ...loadedWorld,
                    current_world_time_minutes: currentMinutes,
                    world_time_label: current.world_time_label,
                  };
            });
          })
          .catch(applyError)
      : Promise.resolve();

    const eventsTask = apiClient
      .events(worldId, `?${eventQuery.toString()}`)
      .then((result) => {
        if (!isStillActive()) return;
        const sortedEvents = sortEventsChronologically(result.events);
        setEvents(sortedEvents);
        if (sortedEvents.length) {
          setWorld((current) =>
            current ? worldWithFreshEventClock(current, sortedEvents) : current,
          );
          // Do not derive the left map from events here. Event fallbacks can be older
          // than the latest agent snapshot and were able to pin stale locations.
        }
        const latestEvent = sortedEvents[sortedEvents.length - 1];
        if (latestEvent?.event_type === "llm_stalled") {
          latestLlmStalledEvents.push(latestEvent);
        }
      })
      .catch(applyError);

    await Promise.allSettled([
      fullWorldTask,
      leftSnapshotTask,
      eventsTask,
    ]);
    if (!isStillActive()) return;
    const latestLlmStalledEvent = latestLlmStalledEvents[latestLlmStalledEvents.length - 1];
    if (latestLlmStalledEvent) {
      const stalledText = latestLlmStalledEvent.viewer_text;
      const actorId = latestLlmStalledEvent.actor_agent_id;
      const stalledAgent = actorId
        ? (snapshotAgentsForLlm ?? agents).find((agent) => agent.agent_id === actorId)
        : null;
      const activeFailureCount = Number(stalledAgent?.llm_consecutive_failures ?? 0);
      if (snapshotAgentsForLlm === null || activeFailureCount >= 3) {
        setError(stalledText);
      } else {
        setError((current) => (current === stalledText ? null : current));
      }
    }

    void Promise.allSettled([
      apiClient.narrations(worldId),
      apiClient.metrics(worldId),
      detailAgentId
        ? apiClient.agent(worldId, detailAgentId)
        : Promise.resolve(null),
    ]).then(([narrationResult, metricsResult, selectedAgentResult]) => {
      if (!isStillActive()) return;
      if (narrationResult.status === "fulfilled")
        setNarrations(narrationResult.value.narrations);
      else setError(readableError(narrationResult.reason));
      if (metricsResult.status === "fulfilled") setMetrics(metricsResult.value);
      else setError(readableError(metricsResult.reason));
      if (detailAgentId === selectedAgentIdRef.current) {
        if (selectedAgentResult.status === "fulfilled")
          setSelectedAgent(selectedAgentResult.value);
        else setError(readableError(selectedAgentResult.reason));
      }
    });
  };

  const scheduleRefresh = (worldId: string, delayMs = 120) => {
    if (activeWorldIdRef.current !== worldId) return;
    refreshPendingRef.current = true;
    if (scheduledRefreshRef.current !== null) return;
    scheduledRefreshRef.current = window.setTimeout(
      () => {
        scheduledRefreshRef.current = null;
        if (activeWorldIdRef.current !== worldId) return;
        if (refreshInFlightRef.current) {
          scheduleRefresh(worldId, 180);
          return;
        }
        refreshPendingRef.current = false;
        refreshInFlightRef.current = true;
        refresh(worldId)
          .catch((err) => {
            if (activeWorldIdRef.current === worldId)
              setError(readableError(err));
          })
          .finally(() => {
            refreshInFlightRef.current = false;
            if (
              refreshPendingRef.current &&
              activeWorldIdRef.current === worldId
            ) {
              refreshPendingRef.current = false;
              scheduleRefresh(worldId, 180);
            }
          });
      },
      Math.max(0, delayMs),
    );
  };

  useEffect(() => {
    let cancelled = false;
    const restoreWorld = async () => {
      setRestoringWorld(true);
      try {
        const [recent] = await withTimeout(
          Promise.all([
            loadRecentWorlds(),
            loadReusableWorlds(),
          ]),
          RESTORE_WORLD_TIMEOUT_MS,
          "读取本地游玩记录超时。请确认后端 127.0.0.1:8010 正在运行，然后刷新页面。",
        );
        const storedWorldId = window.localStorage.getItem(LAST_WORLD_ID_KEY);
        if (
          storedWorldId &&
          !recent.some((item) => item.world_id === storedWorldId)
        ) {
          window.localStorage.removeItem(LAST_WORLD_ID_KEY);
        }
      } catch (err) {
        window.localStorage.removeItem(LAST_WORLD_ID_KEY);
        if (!cancelled) setError(readableError(err));
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
    selectedAgentIdRef.current = selectedAgentId;
  }, [selectedAgentId]);

  useEffect(() => {
    if (!world?.world_id) return;
    const worldId = world.world_id;
    const ws = connectWorldSocket(world.world_id, (message) => {
      const record =
        message && typeof message === "object"
          ? (message as Record<string, unknown>)
          : {};
      const pushedWorld =
        record.world && typeof record.world === "object"
          ? (record.world as World)
          : null;
      if (
        pushedWorld?.world_id === worldId &&
        activeWorldIdRef.current === worldId
      ) {
        setWorld((current) => {
          const mergedPushedWorld =
            current &&
            current.world_id === pushedWorld.world_id &&
            (!pushedWorld.settings ||
              !Object.keys(pushedWorld.settings).length)
              ? { ...pushedWorld, settings: current.settings }
              : pushedWorld;
          if (!current || current.world_id !== pushedWorld.world_id)
            return pushedWorld;
          const currentMinutes = Number(
            current.current_world_time_minutes ?? 0,
          );
          const pushedMinutes = Number(
            pushedWorld.current_world_time_minutes ?? 0,
          );
          return pushedMinutes >= currentMinutes ? mergedPushedWorld : current;
        });
      }
      refreshLeftState(worldId).catch((err) => {
        if (activeWorldIdRef.current === worldId) setError(readableError(err));
      });
      scheduleRefresh(worldId);
    });
    return () => ws.close();
  }, [
    world?.world_id,
    filters.minImportance,
    filters.renderLimit,
    filters.locationId,
    filters.agentId,
    filters.startEventId,
    filters.endEventId,
    filters.dialogueOnly,
    filters.showNarrator,
  ]);

  useEffect(() => {
    if (!world?.world_id) return;
    const worldId = world.world_id;
    const timer = window.setInterval(
      () => {
        refreshLeftState(worldId).catch((err) => {
          if (activeWorldIdRef.current === worldId)
            setError(readableError(err));
        });
      },
      world.status === "running" ? 1500 : 12000,
    );
    return () => window.clearInterval(timer);
  }, [world?.world_id, world?.status]);

  useEffect(() => {
    if (!world?.world_id) return;
    const worldId = world.world_id;
    const timer = window.setInterval(
      () => {
        refresh(worldId).catch((err) => {
          if (activeWorldIdRef.current === worldId)
            setError(readableError(err));
        });
      },
      world.status === "running" ? 3000 : 30000,
    );
    return () => window.clearInterval(timer);
  }, [
    world?.world_id,
    world?.status,
    filters.minImportance,
    filters.renderLimit,
    filters.locationId,
    filters.agentId,
    filters.startEventId,
    filters.endEventId,
    filters.dialogueOnly,
    filters.showNarrator,
  ]);

  useEffect(() => {
    if (!world || !selectedAgentId) {
      setSelectedAgent(null);
      return;
    }
    setSelectedAgent(null);
    const requestedAgentId = selectedAgentId;
    refresh(world.world_id).catch((err) => {
      if (
        activeWorldIdRef.current === world.world_id &&
        selectedAgentIdRef.current === requestedAgentId
      )
        setError(readableError(err));
    });
  }, [world?.world_id, selectedAgentId]);

  useEffect(() => {}, []);

  useEffect(() => {
    apiClient
      .presets()
      .then(setPresetCatalog)
      .catch(() => setPresetCatalog(DEFAULT_PRESET_CATALOG));
  }, []);

  useEffect(() => {
    apiClient
      .interventionAbilities()
      .then((data) => setInterventionAbilities(data.abilities))
      .catch(() => setInterventionAbilities([]));
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
      "button, input, select, textarea, summary, label, [role='button'], .preset-tags span, .recent-world-row em",
    );
    elements.forEach((element) => {
      if (element.dataset.autoTitle === "false") return;
      if (element.title && element.dataset.autoTitle !== "true") return;
      const placeholder =
        element instanceof HTMLInputElement ||
        element instanceof HTMLTextAreaElement
          ? element.placeholder
          : "";
      const selectedText =
        element instanceof HTMLSelectElement
          ? (element.selectedOptions[0]?.textContent?.trim() ?? "")
          : "";
      const text = (
        element.getAttribute("aria-label") ||
        placeholder ||
        selectedText ||
        element.textContent ||
        ""
      )
        .trim()
        .replace(/\s+/g, " ");
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

  const applyWorldviewSelection = (
    worldviewId: string,
    catalog: PresetCatalog = presetCatalog,
  ) => {
    const worldview = catalog.worldviews.find(
      (item) => item.worldview_id === worldviewId,
    );
    const defaults = worldview?.default_create_settings ?? {};
    const matchingWorldToolset = catalog.world_toolsets.find(
      (item) => item.worldview_id === worldviewId,
    );
    const defaultOptional = Array.isArray(defaults.optional_toolset_ids)
      ? defaults.optional_toolset_ids.map(String)
      : undefined;
    const defaultWorldToolsetId =
      typeof defaults.world_toolset_id === "string"
        ? defaults.world_toolset_id
        : matchingWorldToolset?.toolset_id;
    setCreateSettings((current) => ({
      ...current,
      worldviewId,
      survivalDifficulty: ["FAIRY", "NORMAL", "HARD", "HELL"].includes(
        String(defaults.survival_difficulty),
      )
        ? String(defaults.survival_difficulty)
        : current.survivalDifficulty,
      coreToolsetEnabled:
        typeof defaults.core_toolset_enabled === "boolean"
          ? defaults.core_toolset_enabled
          : current.coreToolsetEnabled,
      coreToolsetId:
        typeof defaults.core_toolset_id === "string"
          ? defaults.core_toolset_id
          : current.coreToolsetId,
      optionalToolsetIds: defaultOptional ?? current.optionalToolsetIds,
      worldToolsetId: defaultWorldToolsetId ?? current.worldToolsetId,
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
      if (firstWorldviewId)
        applyWorldviewSelection(firstWorldviewId, result.catalog);
      setWorldPackImportMessage(
        `已导入 ${result.pack.name}，新增/刷新 ${result.registered_tool_count} 个工具。`,
      );
    } catch (err) {
      setError(readableError(err));
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
      setPluginInstallMessage(
        `已安装插件 ${result.plugin.name}，新增/刷新 ${result.registered_tool_count} 个工具。`,
      );
    } catch (err) {
      setError(readableError(err));
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
      setPluginInstallMessage(
        `已安装插件 ${result.plugin.name}，新增/刷新 ${result.registered_tool_count} 个工具。`,
      );
      setPluginInstallUrl("");
    } catch (err) {
      setError(readableError(err));
    } finally {
      setPluginInstalling(false);
    }
  };

  useEffect(() => {
    window.localStorage.setItem(UI_SETTINGS_KEY, JSON.stringify(uiSettings));
  }, [uiSettings]);

  useEffect(
    () => installI18nMirror(uiSettings.language),
    [uiSettings.language],
  );

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
    window.localStorage.setItem(
      PROVIDERS_STORAGE_KEY,
      JSON.stringify(providers),
    );
  }, [providers]);

  useEffect(() => {
    setAgentConfigs((current) => {
      return normalizeAgentConfigs(
        current,
        createSettings.agentCount,
        providers[0]?.providerId ?? "default",
      );
    });
    setBabyModelConfigs((current) =>
      normalizeBabyModelConfigs(current, providers[0]?.providerId ?? "default"),
    );
    setCreateSettings((current) => ({
      ...current,
      werewolfRoleAssignment: normalizeWerewolfRoleAssignment(
        current.werewolfRoleAssignment,
        current.agentCount,
      ),
    }));
  }, [createSettings.agentCount, providers]);

  const pullModels = async (
    providerId: string,
    override?: { baseUrl?: string; apiKey?: string },
  ) => {
    const provider = providers.find((item) => item.providerId === providerId);
    if (!provider) return;
    setPullingProviderId(providerId);
    setError(null);
    try {
      const baseUrl = override?.baseUrl?.trim() || provider.baseUrl;
      const apiKey = override?.apiKey?.trim() || provider.apiKey;
      const result = await apiClient.pullModels({
        base_url: baseUrl,
        api_key: apiKey || undefined,
      });
      setProviders((current) =>
        current.map((item) =>
          item.providerId === providerId
            ? { ...item, baseUrl, apiKey, models: result.models }
            : item,
        ),
      );
      return result.models;
    } catch (err) {
      setError(readableError(err));
      return [];
    } finally {
      setPullingProviderId(null);
    }
  };

  const exportAgentArchive = async (
    options: AgentArchiveFieldOptions = DEFAULT_ARCHIVE_FIELD_OPTIONS,
  ) => {
    const activeAgentConfigs = normalizeAgentConfigs(
      agentConfigs,
      createSettings.agentCount,
      providers[0]?.providerId ?? "default",
    );
    const allowBirth = reproductionEnabledForCreateSettings(createSettings);
    const activeBabyModelConfigs = allowBirth
      ? normalizeBabyModelConfigs(
          babyModelConfigs,
          providers[0]?.providerId ?? "default",
        ).filter((config) => config.modelName.trim())
      : [];
    const includeImageGeneration = options.imageGeneration !== false;
    const zip = new JSZip();
    const payload = {
      format: AGENT_ARCHIVE_FORMAT,
      exportedAt: new Date().toISOString(),
      agentCount: createSettings.agentCount,
      collectiveCorePrompt: options.collectivePrompt
        ? createSettings.collectiveCorePrompt
        : "",
      pregnancyMode: createSettings.pregnancyMode,
      survivalDifficulty: createSettings.survivalDifficulty,
      agentRequestMode: createSettings.agentRequestMode,
      worldviewId: createSettings.worldviewId,
      coreToolsetEnabled: createSettings.coreToolsetEnabled,
      coreToolsetId: createSettings.coreToolsetId,
      optionalToolsetIds: createSettings.optionalToolsetIds,
      worldToolsetId: createSettings.worldToolsetId,
      traitMode: createSettings.traitMode,
      traitBudget: createSettings.traitBudget,
      werewolfRoleAssignment: createSettings.werewolfRoleAssignment,
      exportOptions: options,
      providers: options.providers ? providers : [],
      narratorConfig: options.narrator ? narratorConfig : undefined,
      babyModelConfigs: options.babyModels ? activeBabyModelConfigs : [],
      imageGeneration: includeImageGeneration
        ? createSettings.imageGeneration
        : undefined,
      agents: activeAgentConfigs.map((config, index) => ({
        index,
        providerId: options.providerModels ? config.providerId : "",
        modelName: options.providerModels ? config.modelName : "",
        toolContextMode: options.toolModes ? config.toolContextMode : "dynamic",
        agentToolsetIds: options.agentToolsets ? config.agentToolsetIds : [],
        traitMode: options.traits ? config.traitMode : "inherit",
        systemPrompt: options.prompts ? config.systemPrompt : "",
        chosenName: options.names ? config.chosenName : "",
        imagePromptName: options.imagePrompts ? config.imagePromptName : "",
        appearance: options.appearances ? config.appearance : "",
        traits: options.traits ? config.traits : {},
        knowledgeMode: options.knowledge ? config.knowledgeMode : "none",
        knownAgents: options.knowledge ? config.knownAgents : {},
        ttsConfig: options.tts ? config.ttsConfig : undefined,
      })),
    };
    if (options.avatars)
      payload.agents.forEach((agent, index) => {
        const avatar = dataUrlToBytes(activeAgentConfigs[index].avatarDataUrl);
        if (!avatar) return;
        const baseName = safeArchiveName(
          agent.chosenName,
          `agent_${index + 1}`,
        );
        const avatarPath = `avatars/${String(index + 1).padStart(2, "0")}_${baseName}.${avatar.extension}`;
        zip.file(avatarPath, avatar.bytes);
        Object.assign(agent, { avatarPath });
      });
    const selectedWorldview = presetCatalog.worldviews.find(
      (item) => item.worldview_id === createSettings.worldviewId,
    );
    const worldConfigPath = "configs/world_config.json";
    const agentConfigPath = "configs/agent_config.json";
    const worldConfig = {
      format: WORLD_CONFIG_FORMAT,
      exportedAt: payload.exportedAt,
      name: createSettings.name,
      agentCount: createSettings.agentCount,
      collectiveCorePrompt: options.collectivePrompt
        ? createSettings.collectiveCorePrompt
        : "",
      speed: createSettings.speed,
      agentRequestMode: createSettings.agentRequestMode,
      pregnancyMode: createSettings.pregnancyMode,
      survivalDifficulty: createSettings.survivalDifficulty,
      worldviewId: createSettings.worldviewId,
      worldviewName: selectedWorldview?.name ?? "",
      worldviewVersion: selectedWorldview?.version ?? "",
      worldviewPackId: selectedWorldview?.pack_id ?? null,
      worldviewPackaged: Boolean(selectedWorldview?.packaged),
      coreToolsetEnabled: createSettings.coreToolsetEnabled,
      coreToolsetId: createSettings.coreToolsetId,
      optionalToolsetIds: createSettings.optionalToolsetIds,
      worldToolsetId: createSettings.worldToolsetId,
      traitMode: createSettings.traitMode,
      traitBudget: createSettings.traitBudget,
      imageGeneration: includeImageGeneration
        ? createSettings.imageGeneration
        : undefined,
      werewolfRoleAssignment: createSettings.werewolfRoleAssignment,
    };
    const bundleManifest = {
      format: BUNDLE_ARCHIVE_FORMAT,
      bundleVersion: "1.0.0",
      exportedAt: new Date().toISOString(),
      name: "AIworld bundled configuration",
      description:
        "Top-level manifest shared by imports and exports. Components may contain one or more smaller configs such as agent presets, world packs, runtime settings, or assets.",
      components: [
        {
          component_id: "world_config",
          type: "world_config",
          format: WORLD_CONFIG_FORMAT,
          path: worldConfigPath,
          required: false,
        },
        {
          component_id: "agent_config",
          type: "agent_config",
          format: AGENT_ARCHIVE_FORMAT,
          path: agentConfigPath,
          required: true,
        },
      ],
    };
    zip.file("manifest.json", JSON.stringify(bundleManifest, null, 2));
    zip.file(worldConfigPath, JSON.stringify(worldConfig, null, 2));
    zip.file(agentConfigPath, JSON.stringify(payload, null, 2));
    const blob = await zip.generateAsync({
      type: "blob",
      compression: "DEFLATE",
      compressionOptions: { level: 6 },
    });
    downloadBlob(blob, nextTinyWorldExportName("tlwagents.zip"));
  };

  const applyImportedAgentArchive = (
    parsed: Record<string, unknown>,
    importedAgents: AgentConfigDraft[],
    options: AgentArchiveFieldOptions,
    nextProviders: ProviderDraft[] = providers,
  ) => {
    if (
      ![AGENT_ARCHIVE_FORMAT, LEGACY_AGENT_ARCHIVE_FORMAT].includes(
        String(parsed.format),
      ) ||
      !Array.isArray(parsed.agents)
    ) {
      throw new Error("人员配置文件格式不正确");
    }
    const providerIds = new Set(
      nextProviders.map((provider) => provider.providerId),
    );
    const count = clampAgentCount(
      Number(parsed.agentCount) || importedAgents.length || 1,
    );
    const importedImageGeneration =
      options.imageGeneration !== false &&
      parsed.imageGeneration &&
      typeof parsed.imageGeneration === "object"
        ? normalizeImageGenerationSettings(parsed.imageGeneration)
        : null;
    if (importedImageGeneration) {
      importedImageGenerationRef.current = importedImageGeneration;
    } else {
      importedImageGenerationRef.current = null;
    }
    importedImagePromptNamesRef.current = Object.fromEntries(
      importedAgents
        .map((agent) => [
          agent.chosenName.trim(),
          agent.imagePromptName.trim(),
        ] as const)
        .filter(([name, imagePromptName]) => name && imagePromptName),
    );
    setCreateSettings((current) => ({
      ...current,
      name:
        typeof parsed.name === "string" && parsed.name.trim()
          ? parsed.name
          : current.name,
      agentCount: count,
      collectiveCorePrompt: options.collectivePrompt
        ? String(parsed.collectiveCorePrompt ?? current.collectiveCorePrompt)
        : current.collectiveCorePrompt,
      speed: ["slow", "fast"].includes(String(parsed.speed))
        ? String(parsed.speed)
        : current.speed,
      pregnancyMode: ["any_gender", "heterosexual"].includes(
        String(parsed.pregnancyMode),
      )
        ? String(parsed.pregnancyMode)
        : current.pregnancyMode,
      survivalDifficulty: ["FAIRY", "NORMAL", "HARD", "HELL"].includes(
        String(parsed.survivalDifficulty),
      )
        ? String(parsed.survivalDifficulty)
        : current.survivalDifficulty,
      agentRequestMode:
        parsed.agentRequestMode === "parallel"
          ? "parallel"
          : parsed.agentRequestMode === "serial"
            ? "serial"
            : current.agentRequestMode,
      worldviewId: String(parsed.worldviewId || current.worldviewId),
      coreToolsetEnabled:
        typeof parsed.coreToolsetEnabled === "boolean"
          ? parsed.coreToolsetEnabled
          : current.coreToolsetEnabled,
      coreToolsetId: String(parsed.coreToolsetId || current.coreToolsetId),
      optionalToolsetIds: Array.isArray(parsed.optionalToolsetIds)
        ? parsed.optionalToolsetIds.map(String)
        : current.optionalToolsetIds,
      worldToolsetId: String(
        parsed.worldToolsetId || parsed.toolsetId || current.worldToolsetId,
      ),
      traitMode: ["agent", "player", "random"].includes(
        String(parsed.traitMode),
      )
        ? String(parsed.traitMode)
        : current.traitMode,
      traitBudget: Number.isFinite(Number(parsed.traitBudget))
        ? Number(parsed.traitBudget)
        : current.traitBudget,
      imageGeneration:
        importedImageGeneration
          ? importedImageGeneration
          : current.imageGeneration,
      werewolfRoleAssignment:
        typeof parsed.werewolfRoleAssignment === "object" && parsed.werewolfRoleAssignment
          ? normalizeWerewolfRoleAssignment(parsed.werewolfRoleAssignment as WerewolfRoleAssignmentDraft, count)
          : current.werewolfRoleAssignment,
    }));
    setAgentConfigs(() => {
      return normalizeAgentConfigs(
        importedAgents,
        count,
        nextProviders[0]?.providerId ?? "default",
      );
    });
    const narrator = parsed.narratorConfig as
      | Partial<NarratorConfigDraft>
      | undefined;
    if (options.narrator && narrator) {
      setNarratorConfig((current) => ({
        enabled:
          typeof narrator.enabled === "boolean"
            ? narrator.enabled
            : current.enabled,
        providerId:
          narrator.providerId && providerIds.has(narrator.providerId)
            ? narrator.providerId
            : current.providerId,
        modelName: String(narrator.modelName ?? current.modelName),
        systemPrompt: String(narrator.systemPrompt ?? ""),
      }));
    }
    const babyConfigs = Array.isArray(parsed.babyModelConfigs)
      ? parsed.babyModelConfigs
      : [];
    if (options.babyModels) {
      setBabyModelConfigs(
        normalizeBabyModelConfigs(
          babyConfigs.map((raw) => {
            const item = raw as Partial<BabyModelDraft>;
            return {
              providerId:
                options.providerModels &&
                item.providerId &&
                providerIds.has(item.providerId)
                  ? item.providerId
                  : (nextProviders[0]?.providerId ?? "default"),
              modelName: options.providerModels
                ? String(item.modelName ?? "")
                : "",
            };
          }),
          nextProviders[0]?.providerId ?? "default",
        ),
      );
    }
  };

  const importAgentArchive = async (
    file: File,
    options: AgentArchiveFieldOptions = DEFAULT_ARCHIVE_FIELD_OPTIONS,
  ) => {
    try {
      let parsed: Record<string, unknown>;
      let nextProviders = providers;
      let importedAgents: AgentConfigDraft[];
      let importedWorldConfig: Record<string, unknown> | null = null;
      if (await isZipLikeFile(file)) {
        const zip = await JSZip.loadAsync(file);
        const manifestFile = zip.file("manifest.json");
        if (!manifestFile) throw new Error("压缩包中缺少 manifest.json");
        parsed = JSON.parse(await manifestFile.async("text"));
        if (String(parsed.format) === BUNDLE_ARCHIVE_FORMAT) {
          const worldComponent = findOptionalBundleComponent(
            parsed,
            "world_config",
          );
          if (worldComponent?.path) {
            const worldFile = zip.file(String(worldComponent.path));
            if (worldFile)
              importedWorldConfig = JSON.parse(await worldFile.async("text"));
          } else if (
            worldComponent?.config &&
            typeof worldComponent.config === "object"
          ) {
            importedWorldConfig = worldComponent.config as Record<
              string,
              unknown
            >;
          }
          const component = findBundleComponent(parsed, "agent_config");
          const componentPath = String(component.path ?? "");
          const componentFile = zip.file(componentPath);
          if (!componentPath || !componentFile)
            throw new Error("bundle manifest 缺少 agent_config 组件文件");
          parsed = mergeImportedWorldAndAgentConfig(
            importedWorldConfig,
            JSON.parse(await componentFile.async("text")),
          );
        }
        if (options.providers && Array.isArray(parsed.providers)) {
          nextProviders = normalizeImportedProviders(
            parsed.providers,
            providers,
          );
          setProviders(nextProviders);
        }
        const providerIds = new Set(
          nextProviders.map((provider) => provider.providerId),
        );
        const agents = Array.isArray(parsed.agents) ? parsed.agents : [];
        importedAgents = await Promise.all(
          agents.map(async (raw) => {
            const item = raw as Partial<AgentConfigDraft> & {
              avatarPath?: string;
            };
            const avatarDataUrl =
              options.avatars && item.avatarPath
                ? await zipFileToDataUrl(zip, item.avatarPath)
                : "";
            return {
              providerId:
                options.providerModels &&
                item.providerId &&
                providerIds.has(item.providerId)
                  ? item.providerId
                  : (nextProviders[0]?.providerId ?? "default"),
              modelName: options.providerModels
                ? String(item.modelName ?? "")
                : "",
              toolContextMode:
                options.toolModes && item.toolContextMode === "all"
                  ? "all"
                  : "dynamic",
              agentToolsetIds:
                options.agentToolsets && Array.isArray(item.agentToolsetIds)
                  ? item.agentToolsetIds.map(String)
                  : [...DEFAULT_AGENT_SPECIAL_TOOLSET_IDS],
              traitMode:
                options.traits &&
                AGENT_TRAIT_MODES.includes(String(item.traitMode))
                  ? (String(item.traitMode) as AgentConfigDraft["traitMode"])
                  : "inherit",
              systemPrompt: options.prompts
                ? String(item.systemPrompt ?? "")
                : "",
              chosenName: options.names ? String(item.chosenName ?? "") : "",
              imagePromptName: options.imagePrompts
                ? String(item.imagePromptName ?? (item as Record<string, unknown>).image_prompt_name ?? "")
                : "",
              appearance: options.appearances
                ? String(item.appearance ?? "")
                : "",
              avatarDataUrl,
              traits: options.traits
                ? {
                    ...blankAgentConfig().traits,
                    ...(typeof item.traits === "object" && item.traits
                      ? item.traits
                      : {}),
                  }
                : blankAgentConfig().traits,
              knowledgeMode:
                options.knowledge &&
                ["all", "none", "custom"].includes(String(item.knowledgeMode ?? (item as Record<string, unknown>).knowledge_mode))
                  ? (String(item.knowledgeMode ?? (item as Record<string, unknown>).knowledge_mode) as AgentConfigDraft["knowledgeMode"])
                  : "none",
              knownAgents:
                options.knowledge && item.knownAgents && typeof item.knownAgents === "object"
                  ? item.knownAgents
                  : (options.knowledge && (item as Record<string, unknown>).known_agents && typeof (item as Record<string, unknown>).known_agents === "object"
                    ? ((item as Record<string, unknown>).known_agents as AgentConfigDraft["knownAgents"])
                    : {}),
              ttsConfig: options.tts
                ? normalizeTtsConfig(
                    (item as Record<string, unknown>).ttsConfig ??
                      (item as Record<string, unknown>).tts_config,
                  )
                : blankTtsConfig(),
            };
          }),
        );
      } else {
        parsed = JSON.parse(await file.text());
        if (String(parsed.format) === BUNDLE_ARCHIVE_FORMAT) {
          const worldComponent = findOptionalBundleComponent(
            parsed,
            "world_config",
          );
          if (
            worldComponent?.config &&
            typeof worldComponent.config === "object"
          ) {
            importedWorldConfig = worldComponent.config as Record<
              string,
              unknown
            >;
          }
          const component = findBundleComponent(parsed, "agent_config");
          if (!component.config || typeof component.config !== "object")
            throw new Error("JSON bundle 缺少内嵌 agent_config 组件");
          parsed = mergeImportedWorldAndAgentConfig(
            importedWorldConfig,
            component.config as Record<string, unknown>,
          );
        }
        if (options.providers && Array.isArray(parsed.providers)) {
          nextProviders = normalizeImportedProviders(
            parsed.providers,
            providers,
          );
          setProviders(nextProviders);
        }
        const providerIds = new Set(
          nextProviders.map((provider) => provider.providerId),
        );
        const agents = Array.isArray(parsed.agents) ? parsed.agents : [];
        importedAgents = agents.map((raw) => {
          const item = raw as Partial<AgentConfigDraft>;
          return {
            providerId:
              options.providerModels &&
              item.providerId &&
              providerIds.has(item.providerId)
                ? item.providerId
                : (nextProviders[0]?.providerId ?? "default"),
            modelName: options.providerModels
              ? String(item.modelName ?? "")
              : "",
            toolContextMode:
              options.toolModes && item.toolContextMode === "all"
                ? "all"
                : "dynamic",
            agentToolsetIds:
              options.agentToolsets && Array.isArray(item.agentToolsetIds)
                ? item.agentToolsetIds.map(String)
                : [...DEFAULT_AGENT_SPECIAL_TOOLSET_IDS],
            traitMode:
              options.traits &&
              AGENT_TRAIT_MODES.includes(String(item.traitMode))
                ? (String(item.traitMode) as AgentConfigDraft["traitMode"])
                : "inherit",
            systemPrompt: options.prompts
              ? String(item.systemPrompt ?? "")
              : "",
            chosenName: options.names ? String(item.chosenName ?? "") : "",
            imagePromptName: options.imagePrompts
              ? String(item.imagePromptName ?? (item as Record<string, unknown>).image_prompt_name ?? "")
              : "",
            appearance: options.appearances
              ? String(item.appearance ?? "")
              : "",
            avatarDataUrl: options.avatars
              ? String(item.avatarDataUrl ?? "")
              : "",
            traits: options.traits
              ? {
                  ...blankAgentConfig().traits,
                  ...(typeof item.traits === "object" && item.traits
                    ? item.traits
                    : {}),
                }
              : blankAgentConfig().traits,
            knowledgeMode:
              options.knowledge &&
              ["all", "none", "custom"].includes(String(item.knowledgeMode ?? (item as Record<string, unknown>).knowledge_mode))
                ? (String(item.knowledgeMode ?? (item as Record<string, unknown>).knowledge_mode) as AgentConfigDraft["knowledgeMode"])
                : "none",
            knownAgents:
              options.knowledge && item.knownAgents && typeof item.knownAgents === "object"
                ? item.knownAgents
                : (options.knowledge && (item as Record<string, unknown>).known_agents && typeof (item as Record<string, unknown>).known_agents === "object"
                  ? ((item as Record<string, unknown>).known_agents as AgentConfigDraft["knownAgents"])
                  : {}),
            ttsConfig: options.tts
              ? normalizeTtsConfig(
                  (item as Record<string, unknown>).ttsConfig ??
                    (item as Record<string, unknown>).tts_config,
                )
              : blankTtsConfig(),
          };
        });
      }
      applyImportedAgentArchive(parsed, importedAgents, options, nextProviders);
    } catch (err) {
      setError(readableError(err));
    }
  };

  const reuseWorldAgentConfig = async (sourceWorldId: string) => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(
        apiClient.agentPresetsExportUrl(sourceWorldId),
      );
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || response.statusText);
      }
      const blob = await response.blob();
      const file = new File(
        [blob],
        `${sourceWorldId}-agent-config.tlwagents.zip`,
        { type: "application/zip" },
      );
      await importAgentArchive(file, DEFAULT_ARCHIVE_FIELD_OPTIONS);
    } catch (err) {
      setError(readableError(err));
    } finally {
      setBusy(false);
    }
  };

  const applyIdentityLibraryItem = (
    item: IdentityLibraryItem,
    targetIndex = identityTargetIndex,
  ) => {
    const safeCount = clampAgentCount(createSettings.agentCount);
    const safeIndex = Math.max(
      0,
      Math.min(safeCount - 1, Math.floor(targetIndex)),
    );
    const providerResult = upsertIdentityProvider(providers, item);
    setProviders(providerResult.providers);
    setAgentConfigs((currentConfigs) => {
      const fallbackProviderId =
        providerResult.providers[0]?.providerId ?? "default";
      const activeConfigs = normalizeAgentConfigs(
        currentConfigs,
        safeCount,
        fallbackProviderId,
      );
      const current =
        activeConfigs[safeIndex] ?? blankAgentConfig(fallbackProviderId);
      activeConfigs[safeIndex] = {
        ...current,
        providerId: providerResult.providerId ?? current.providerId,
        modelName: item.modelName || current.modelName,
        toolContextMode: item.toolContextMode === "all" ? "all" : "dynamic",
        agentToolsetIds: item.agentToolsetIds.length
          ? item.agentToolsetIds
          : current.agentToolsetIds,
        systemPrompt: item.systemPrompt || "",
        chosenName: item.name || "",
        imagePromptName: String((item as Record<string, unknown>).imagePromptName ?? (item as Record<string, unknown>).image_prompt_name ?? current.imagePromptName ?? ""),
        appearance: item.appearance || item.appearanceShort || "",
        avatarDataUrl: item.avatarDataUrl || "",
        traits: { ...current.traits, ...(item.traits ?? {}) },
        ttsConfig: normalizeTtsConfig(item.ttsConfig),
      };
      return activeConfigs;
    });
    setIdentityTargetIndex(safeIndex);
    setError(null);
  };

  const deleteIdentityLibraryItem = async (item: IdentityLibraryItem) => {
    const label = item.name || item.agentId;
    if (
      !window.confirm(
        `从历史身份库删除「${label}」？这会删除来源存档里的这个居民身份和直接相关关系/记忆，不能撤销。`,
      )
    )
      return;
    setDeletingIdentityId(item.agentId);
    setError(null);
    try {
      await apiClient.deleteIdentityLibraryItem(item.agentId);
      await loadIdentityLibrary();
    } catch (err) {
      setError(readableError(err));
    } finally {
      setDeletingIdentityId(null);
    }
  };

  const createWorld = async () => {
    setBusy(true);
    setError(null);
    try {
      const activeAgentConfigs = normalizeAgentConfigs(
        agentConfigs,
        createSettings.agentCount,
        providers[0]?.providerId ?? "default",
      );
      const allowBirth = reproductionEnabledForCreateSettings(createSettings);
      const activeBabyModelConfigs = allowBirth
        ? normalizeBabyModelConfigs(
            babyModelConfigs,
            providers[0]?.providerId ?? "default",
          ).filter((config) => config.modelName.trim())
        : [];
      const activeWerewolfRoleAssignment = normalizeWerewolfRoleAssignment(
        createSettings.werewolfRoleAssignment,
        createSettings.agentCount,
      );
      const importedImageGeneration = importedImageGenerationRef.current;
      const imageGenerationForCreate =
        importedImageGeneration?.enabled &&
        isDefaultDisabledImageGenerationSettings(createSettings.imageGeneration)
          ? importedImageGeneration
          : createSettings.imageGeneration;
      const importedImagePromptNames = importedImagePromptNamesRef.current;
      const created = await apiClient.createWorld({
        name: createSettings.name,
        agent_count: clampAgentCount(createSettings.agentCount),
        collective_core_prompt:
          createSettings.collectiveCorePrompt || undefined,
        seed: createSettings.seed,
        language: uiSettings.language,
        speed: createSettings.speed,
        agent_request_mode: createSettings.agentRequestMode,
        prompt_settings: DEFAULT_PROMPT_SETTINGS,
        llm_generation: createSettings.llmGeneration,
        survival_difficulty: createSettings.survivalDifficulty,
        worldview_id: createSettings.worldviewId,
        core_toolset_enabled: createSettings.coreToolsetEnabled,
        core_toolset_id: createSettings.coreToolsetId,
        optional_toolset_ids: createSettings.optionalToolsetIds,
        world_toolset_id: createSettings.worldToolsetId,
        toolset_id: createSettings.worldToolsetId,
        werewolf_role_assignment: {
          mode: activeWerewolfRoleAssignment.mode,
          counts: activeWerewolfRoleAssignment.counts,
          manual_roles: activeWerewolfRoleAssignment.manualRoles,
        },
        pregnancy_mode: createSettings.pregnancyMode,
        providers: providers.map((provider) => ({
          provider_id: provider.providerId,
          name: provider.name,
          base_url: provider.baseUrl,
          api_key: provider.apiKey || undefined,
          retry_count: provider.retryCount,
          retry_interval_ms: provider.retryIntervalMs,
          request_timeout_ms: provider.requestTimeoutMs,
          rpm: provider.rpm,
        })),
        narrator_config: narratorConfig.enabled
          ? {
              enabled: true,
              provider_id: narratorConfig.providerId,
              model_name: narratorConfig.modelName || undefined,
              system_prompt: narratorConfig.systemPrompt || undefined,
            }
          : { enabled: false },
        image_generation: serializeImageGenerationSettings(imageGenerationForCreate),
        baby_model_configs: activeBabyModelConfigs.map((config) => ({
          provider_id: config.providerId,
          model_name: config.modelName,
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
          image_prompt_name:
            config.imagePromptName ||
            importedImagePromptNames[config.chosenName.trim()] ||
            undefined,
          appearance: config.appearance || undefined,
          avatar_data_url: config.avatarDataUrl || undefined,
          trait_mode: traitModeForCreatePayload(
            config,
            createSettings.traitMode,
          ),
          trait_sliders: config.traits,
          knowledge_mode: config.knowledgeMode,
          known_agents: Object.fromEntries(
            Object.entries(config.knownAgents ?? {}).map(([targetIndex, entry]) => [
              targetIndex,
              {
                knows: Boolean(entry.knows),
                affection: Math.max(-100, Math.min(100, Number(entry.affection ?? 0) || 0)),
              },
            ]),
          ),
          llm_generation: config.llmGeneration,
          tts_config: serializeTtsConfig(config.ttsConfig),
        })),
      });
      activateWorldView(created.world_id);
      setWorld(created);
      await refresh(created.world_id);
      await loadRecentWorlds();
      await loadReusableWorlds();
    } catch (err) {
      setError(readableError(err));
    } finally {
      setBusy(false);
    }
  };

  const runAction = async (
    action: "start" | "pause" | "step" | "end" | "summarize" | "generateImage",
  ) => {
    if (!world) return;
    setBusy(true);
    setError(null);
    try {
      if (action === "start") {
        const updated = await apiClient.start(world.world_id);
        setWorld(updated);
      }
      if (action === "pause") {
        const updated = await apiClient.pause(world.world_id);
        setWorld(updated);
      }
      if (action === "step") await apiClient.step(world.world_id);
      if (action === "end") {
        const result = await apiClient.end(world.world_id);
        setWorld(result.world);
      }
      if (action === "summarize") await apiClient.summarize(world.world_id);
      if (action === "generateImage") await apiClient.generateImageNow(world.world_id);
      await refresh(world.world_id);
    } catch (err) {
      setError(readableError(err));
    } finally {
      setBusy(false);
    }
  };

  const replaceAgentLlm = async (
    agentId: string,
    payload: Record<string, unknown>,
  ) => {
    if (!world) return;
    setReplacingLlm(true);
    setError(null);
    try {
      const updated = await apiClient.updateAgentLlm(
        world.world_id,
        agentId,
        payload,
      );
      setSelectedAgent(updated);
      await refresh(world.world_id);
    } catch (err) {
      setError(readableError(err));
    } finally {
      setReplacingLlm(false);
    }
  };

  const updateAgentProfile = async (
    agentId: string,
    payload: Record<string, unknown>,
  ) => {
    if (!world) return;
    setError(null);
    try {
      const updated = await apiClient.updateAgentProfile(
        world.world_id,
        agentId,
        payload,
      );
      setSelectedAgent(updated);
      await refresh(world.world_id);
    } catch (err) {
      setError(readableError(err));
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
      setError(readableError(err));
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
      setError(readableError(err));
    } finally {
      setInterventionBusy(false);
    }
  };

  const requestEventTts = async (eventId: number) => {
    if (!world) return "";
    const result = await apiClient.eventTts(world.world_id, eventId);
    setEvents((current) =>
      sortEventsChronologically(
        current.map((event) =>
          event.event_id === eventId
            ? {
                ...event,
                payload: {
                  ...event.payload,
                  tts_audio_data_url: result.audio_data_url,
                },
              }
            : event,
        ),
      ),
    );
    return result.audio_data_url;
  };

  useEffect(() => {
    autoTtsKnownEventIdsRef.current.clear();
    autoTtsInFlightEventIdsRef.current.clear();
    autoTtsInitializedWorldRef.current = null;
  }, [world?.world_id]);

  useEffect(() => {
    if (!world?.world_id) return;
    const known = autoTtsKnownEventIdsRef.current;
    const inFlight = autoTtsInFlightEventIdsRef.current;
    if (autoTtsInitializedWorldRef.current !== world.world_id) {
      for (const event of events) {
        known.add(Number(event.event_id));
      }
      autoTtsInitializedWorldRef.current = world.world_id;
      return;
    }
    const newTtsEventIds: number[] = [];
    for (const event of events) {
      const eventId = Number(event.event_id);
      const wasKnown = known.has(eventId);
      known.add(eventId);
      if (!wasKnown && uiSettings.ttsGenerationMode === "on_speech") {
        const actor = agents.find(
          (agent) => agent.agent_id === event.actor_agent_id,
        );
        const hasCachedAudio =
          typeof event.payload?.tts_audio_data_url === "string" &&
          event.payload.tts_audio_data_url.startsWith("data:audio/");
        if (
          actor?.tts_enabled &&
          speechTextFromEvent(event) &&
          !hasCachedAudio &&
          !inFlight.has(eventId)
        ) {
          inFlight.add(eventId);
          newTtsEventIds.push(eventId);
        }
      }
    }
    if (!newTtsEventIds.length) return;
    const worldId = world.world_id;
    void (async () => {
      for (const eventId of newTtsEventIds) {
        if (activeWorldIdRef.current !== worldId) {
          inFlight.delete(eventId);
          continue;
        }
        try {
          await requestEventTts(eventId);
        } catch (err) {
          if (activeWorldIdRef.current === worldId) {
            setError(readableError(err));
          }
        } finally {
          inFlight.delete(eventId);
        }
      }
    })();
  }, [events, agents, uiSettings.ttsGenerationMode, world?.world_id]);

  const updateWorldRuntimeSettings = async (
    payload: WorldRuntimeSettingsPayload,
  ) => {
    if (!world) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await apiClient.updateWorldRuntimeSettings(
        world.world_id,
        payload,
      );
      setWorld(updated);
      await refresh(updated.world_id);
    } catch (err) {
      setError(readableError(err));
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
      include_audio: String(filters.exportAudio),
    });
    if (filters.agentId) query.set("agent_id", filters.agentId);
    if (filters.locationId) query.set("location_id", filters.locationId);
    if (filters.startEventId) query.set("start_event_id", filters.startEventId);
    if (filters.endEventId) query.set("end_event_id", filters.endEventId);
    return apiClient.eventsExportUrl(world.world_id, `?${query.toString()}`);
  }, [world?.world_id, filters]);

  const resetToSetup = () => {
    deactivateWorldView();
    setBusy(false);
    setReplacingLlm(false);
    setInterventionBusy(false);
    setWorld(null);
    setAgents([]);
    setLocations([]);
    setEvents([]);
    setNarrations([]);
    setMetrics(null);
    setSelectedAgentId(null);
    setSelectedAgent(null);
    setError(null);
    setFilters({
      minImportance: 0,
      dialogueOnly: false,
      showNarrator: true,
      exportAvatars: true,
      exportAudio: false,
      agentId: "",
      locationId: "",
      renderLimit: 2000,
      startEventId: "",
      endEventId: "",
    });
    loadRecentWorlds().catch(() => undefined);
    loadReusableWorlds().catch(() => undefined);
  };

  const openRecentWorld = async (worldId: string) => {
    setBusy(true);
    setError(null);
    try {
      activateWorldView(worldId);
      const loaded = await apiClient.getWorld(worldId);
      if (activeWorldIdRef.current === worldId) setWorld(loaded);
      await refresh(worldId);
    } catch (err) {
      deactivateWorldView();
      setError(readableError(err));
    } finally {
      setBusy(false);
    }
  };

  const updateRecentWorldSaveName = async (worldId: string) => {
    setBusy(true);
    setError(null);
    try {
      const updated = await apiClient.updateWorldSaveName(worldId, {
        save_name: renamingSaveName,
      });
      if (world?.world_id === updated.world_id) setWorld(updated);
      setRenamingWorldId(null);
      setRenamingSaveName("");
      await loadRecentWorlds(recentWorldPage);
      await loadReusableWorlds();
    } catch (err) {
      setError(readableError(err));
    } finally {
      setBusy(false);
    }
  };

  const deleteWorldSave = async (item: World) => {
    const saveName = saveNameForWorld(item);
    if (
      !window.confirm(
        `删除存档「${saveName}」？这会删除这个世界的居民、事件、记忆和本地记录，不能撤销。`,
      )
    )
      return;
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
      setError(readableError(err));
    } finally {
      setDeletingWorldId(null);
      setBusy(false);
    }
  };

  const filteredEvents = useMemo(() => {
    return events.filter((event) => {
      if (filters.dialogueOnly && !isSpeechEvent(event)) return false;
      if (!filters.showNarrator && event.color_class === "narrator")
        return false;
      if (
        filters.agentId &&
        event.actor_agent_id !== filters.agentId &&
        event.target_agent_id !== filters.agentId
      )
        return false;
      if (filters.locationId && event.location_id !== filters.locationId)
        return false;
      if (filters.startEventId && event.event_id < Number(filters.startEventId))
        return false;
      if (filters.endEventId && event.event_id > Number(filters.endEventId))
        return false;
      return true;
    });
  }, [events, filters]);

  const setupStyle = useMemo(
    () =>
      ({
        "--left-rail-width": `${uiSettings.leftWidth}px`,
        "--right-rail-width": `${uiSettings.rightWidth}px`,
      }) as CSSProperties,
    [uiSettings],
  );

  const recentWorldGroups = useMemo(() => {
    const groups = new Map<
      string,
      { worldviewId: string; label: string; worlds: World[] }
    >();
    for (const item of recentWorlds) {
      const worldviewId = worldviewIdForWorld(item);
      const label = worldviewLabelForWorld(
        item,
        presetCatalog,
        uiSettings.language,
      );
      const group = groups.get(worldviewId) ?? {
        worldviewId,
        label,
        worlds: [],
      };
      group.worlds.push(item);
      groups.set(worldviewId, group);
    }
    return Array.from(groups.values());
  }, [presetCatalog, recentWorlds, uiSettings.language]);

  const recentWorldPageCount = Math.max(
    1,
    Math.ceil(recentWorldTotal / RECENT_WORLD_PAGE_SIZE),
  );
  const identityWorldOptions = useMemo(() => {
    const options = new Map<string, string>();
    for (const item of identityLibrary) {
      const key = item.worldId || item.saveName || item.worldName;
      if (!key) continue;
      options.set(key, item.saveName || item.worldName || key);
    }
    return Array.from(options, ([value, label]) => ({ value, label })).sort((a, b) => a.label.localeCompare(b.label, "zh-Hans-CN"));
  }, [identityLibrary]);

  const identityModelOptions = useMemo(() => {
    const names = new Set<string>();
    for (const item of identityLibrary) {
      const label = item.modelName || item.providerName;
      if (label) names.add(label);
    }
    return Array.from(names).sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
  }, [identityLibrary]);

  const filteredIdentityLibrary = useMemo(() => {
    const q = identitySearch.trim().toLowerCase();
    return identityLibrary
      .filter((item) => {
        if (identityAvatarOnly && !item.avatarDataUrl) return false;
        if (identityWorldFilter !== "all" && item.worldId !== identityWorldFilter) return false;
        if (identityModelFilter !== "all" && item.modelName !== identityModelFilter && item.providerName !== identityModelFilter) return false;
        if (!q) return true;
        return [
          item.name,
          item.appearanceShort,
          item.appearance,
          item.worldName,
          item.saveName,
          item.modelName,
          item.providerName,
          item.worldviewName,
          item.genderIdentity ?? "",
          item.genderExpression ?? "",
        ]
          .join(" ")
          .toLowerCase()
          .includes(q);
      })
      .sort((a, b) => {
        if (identitySortMode === "name") return (a.name || "").localeCompare(b.name || "", "zh-Hans-CN");
        if (identitySortMode === "world") {
          const worldCompare = (a.saveName || a.worldName || "").localeCompare(b.saveName || b.worldName || "", "zh-Hans-CN");
          if (worldCompare) return worldCompare;
          return (a.name || "").localeCompare(b.name || "", "zh-Hans-CN");
        }
        const worldCompare = Date.parse(b.worldCreatedAt || "") - Date.parse(a.worldCreatedAt || "");
        if (worldCompare) return worldCompare;
        const worldIdCompare = (b.worldId || "").localeCompare(a.worldId || "");
        if (worldIdCompare) return worldIdCompare;
        return Number(a.createdAtWorldTime ?? 0) - Number(b.createdAtWorldTime ?? 0);
      });
  }, [identityAvatarOnly, identityLibrary, identityModelFilter, identitySearch, identitySortMode, identityWorldFilter]);

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
    const coreToolsets = presetCatalog.core_toolsets?.length
      ? presetCatalog.core_toolsets
      : DEFAULT_PRESET_CATALOG.core_toolsets;
    const optionalToolsets = presetCatalog.optional_toolsets?.length
      ? presetCatalog.optional_toolsets
      : DEFAULT_PRESET_CATALOG.optional_toolsets;
    const agentSpecialToolsets = presetCatalog.agent_special_toolsets?.length
      ? presetCatalog.agent_special_toolsets
      : (DEFAULT_PRESET_CATALOG.agent_special_toolsets ?? []);
    const worldToolsets = presetCatalog.world_toolsets?.length
      ? presetCatalog.world_toolsets
      : presetCatalog.toolsets?.length
        ? presetCatalog.toolsets
        : DEFAULT_PRESET_CATALOG.world_toolsets;
    const selectedWorldview =
      presetCatalog.worldviews.find(
        (item) => item.worldview_id === createSettings.worldviewId,
      ) ??
      presetCatalog.worldviews[0] ??
      DEFAULT_PRESET_CATALOG.worldviews[0];
    const selectedCoreToolset =
      coreToolsets.find(
        (item) => item.toolset_id === createSettings.coreToolsetId,
      ) ??
      coreToolsets[0] ??
      DEFAULT_PRESET_CATALOG.core_toolsets[0];
    const selectedWorldToolset =
      worldToolsets.find(
        (item) =>
          item.toolset_id === createSettings.worldToolsetId ||
          item.legacy_toolset_ids?.includes(createSettings.worldToolsetId),
      ) ??
      worldToolsets[0] ??
      DEFAULT_PRESET_CATALOG.world_toolsets[0];
    const selectedWorldviewName = localizedPresetName(
      selectedWorldview,
      uiSettings.language,
    );
    const selectedWorldviewDescription = localizedPresetDescription(
      selectedWorldview,
      uiSettings.language,
    );
    const selectedWorldToolsetName = localizedPresetName(
      selectedWorldToolset,
      uiSettings.language,
    );
    const selectedWorldToolsetDescription = localizedPresetDescription(
      selectedWorldToolset,
      uiSettings.language,
    );
    const allowBirth = reproductionEnabledForCreateSettings(createSettings);
    const tr = (value: string) => t(value, uiSettings.language);
    const setupDifficultyLabel =
      SURVIVAL_DIFFICULTIES.find(
        (item) => item.value === createSettings.survivalDifficulty,
      )?.label ?? "普通";
    const setupSummary = `${selectedWorldToolsetName} · ${tr(createSettings.coreToolsetEnabled ? "自带工具开启" : "自带工具关闭")} · ${tr(allowBirth ? "生育开启" : "生育关闭")} · ${tr(`${setupDifficultyLabel}难度`)}`;
    return (
      <main
        className={`setup-shell theme-${uiSettings.theme} ${setupLeftOpen ? "setup-left-open" : ""} ${setupRightOpen ? "setup-right-open" : ""}`}
        style={setupStyle}
      >
        <button
          type="button"
          className="setup-drawer-toggle setup-drawer-toggle-left"
          onClick={() => setSetupLeftOpen((value) => !value)}
          title={
            setupLeftOpen
              ? "收起左侧栏 / Hide left sidebar"
              : "拉出左侧栏 / Show left sidebar"
          }
        >
          {setupLeftOpen ? "‹" : "›"}
        </button>
        <button
          type="button"
          className="setup-drawer-toggle setup-drawer-toggle-right"
          onClick={() => setSetupRightOpen((value) => !value)}
          title={
            setupRightOpen
              ? "收起右侧栏 / Hide right sidebar"
              : "拉出右侧栏 / Show right sidebar"
          }
        >
          {setupRightOpen ? "›" : "‹"}
        </button>
        {(setupLeftOpen || setupRightOpen) && (
          <button
            type="button"
            className="setup-drawer-scrim"
            aria-label="关闭侧栏 / Close sidebars"
            onClick={() => {
              setSetupLeftOpen(false);
              setSetupRightOpen(false);
            }}
          />
        )}
        <aside className="setup-left">
          <section className="panel setup-brand-panel">
            <div className="setup-brand-copy">
              <h1>{tr("微世界")}</h1>
              <p>
                {restoringWorld
                  ? tr("正在读取本地游玩记录...")
                  : tr("本地中文多 agent 生存互动观察器")}
              </p>
            </div>
            <img
              className="setup-brand-icon"
              src="/tiny-living-world-icon-transparent.png"
              alt=""
            />
          </section>
          <UiSettingsPanel settings={uiSettings} onChange={setUiSettings} />
          <section
            id="setup-identity-library"
            className="panel identity-library-panel"
          >
            <div className="panel-heading">
              <h2>
                {tr("历史身份库")}{" "}
                {setupMode === "beginner" && (
                  <em className="beginner-marker marker-history">
                    青色: 旧角色身份
                  </em>
                )}
              </h2>
              <button
                type="button"
                className="icon-button text-icon-button"
                onClick={() =>
                  loadIdentityLibrary().catch((err) =>
                    setError(readableError(err)),
                  )
                }
              >
                {tr("刷新")}
              </button>
            </div>
            <div className="identity-library-controls">
              <div className="identity-library-search-row">
                <input
                  value={identitySearch}
                  placeholder={tr("搜索姓名、外貌、世界、模型")}
                  onChange={(event) => setIdentitySearch(event.target.value)}
                />
                <button type="button" onClick={() => setIdentitySearch("")} disabled={!identitySearch.trim()}>
                  {tr("清空")}
                </button>
              </div>
              <div className="identity-library-filter-row">
                <label>
                  {tr("世界")}
                  <select value={identityWorldFilter} onChange={(event) => setIdentityWorldFilter(event.target.value)}>
                    <option value="all">{tr("全部世界")}</option>
                    {identityWorldOptions.map((item) => (
                      <option key={item.value} value={item.value}>{item.label}</option>
                    ))}
                  </select>
                </label>
                <label>
                  {tr("模型")}
                  <select value={identityModelFilter} onChange={(event) => setIdentityModelFilter(event.target.value)}>
                    <option value="all">{tr("全部模型")}</option>
                    {identityModelOptions.map((item) => (
                      <option key={item} value={item}>{item}</option>
                    ))}
                  </select>
                </label>
                <label>
                  {tr("排序")}
                  <select value={identitySortMode} onChange={(event) => setIdentitySortMode(event.target.value as "recent" | "name" | "world")}>
                    <option value="recent">{tr("最近存档")}</option>
                    <option value="name">{tr("姓名")}</option>
                    <option value="world">{tr("世界")}</option>
                  </select>
                </label>
              </div>
              <div className="identity-library-target-row">
                <label className="identity-avatar-toggle">
                  <input type="checkbox" checked={identityAvatarOnly} onChange={(event) => setIdentityAvatarOnly(event.target.checked)} />
                  {tr("只看头像")}
                </label>
                <label className="identity-target-select">
                  {tr("应用到")}
                  {setupMode === "beginner" && (
                    <em className="beginner-marker marker-target">
                      玫红: 应用到哪个 Agent
                    </em>
                  )}
                  <select
                    value={identityTargetIndex}
                    onChange={(event) =>
                      setIdentityTargetIndex(Number(event.target.value))
                    }
                  >
                    {Array.from(
                      { length: createSettings.agentCount },
                      (_, index) => (
                        <option key={index} value={index}>
                          Agent {index + 1}
                        </option>
                      ),
                    )}
                  </select>
                </label>
              </div>
              <div className="identity-library-summary">
                <span>{filteredIdentityLibrary.length}/{identityLibrary.length} {tr("个身份")}</span>
                <span>Agent {identityTargetIndex + 1}</span>
              </div>
            </div>
            <div className="identity-library-list">
              {filteredIdentityLibrary.length ? (
                filteredIdentityLibrary.slice(0, 80).map((item) => (
                  <div className="identity-library-row" key={item.agentId}>
                    <div className="identity-library-avatar">
                      {item.avatarDataUrl ? (
                        <img src={item.avatarDataUrl} alt="" />
                      ) : (
                        <span>{(item.name || "?").slice(0, 1)}</span>
                      )}
                    </div>
                    <button
                      type="button"
                      className="identity-library-main"
                      onClick={() => applyIdentityLibraryItem(item)}
                      title={`${item.name}\n${item.saveName || item.worldName}\n${item.modelName || item.providerName || ""}\n${item.appearanceShort || item.appearance}`}
                    >
                      <span className="identity-library-title-line">
                        <strong>{item.name || tr("未命名身份")}</strong>
                        {item.avatarDataUrl && <em>{tr("头像")}</em>}
                      </span>
                      <span className="identity-library-meta">
                        <b>{item.saveName || item.worldName}</b>
                        <b>{item.modelName || tr("未指定模型")}</b>
                      </span>
                      <span className="identity-library-tags">
                        {item.worldviewName && <em>{item.worldviewName}</em>}
                        {item.genderExpression && <em>{item.genderExpression}</em>}
                      </span>
                      <small>
                        {item.appearanceShort ||
                          item.appearance.slice(0, 72) ||
                          tr("无外貌摘要")}
                      </small>
                    </button>
                    <div className="identity-library-actions">
                      <button
                        type="button"
                        onClick={() => applyIdentityLibraryItem(item)}
                      >
                        {tr("应用")}
                        {setupMode === "beginner" && (
                          <em className="beginner-marker marker-history">
                            青色
                          </em>
                        )}
                      </button>
                      <button
                        type="button"
                        className="danger-button"
                        disabled={deletingIdentityId === item.agentId}
                        onClick={() => deleteIdentityLibraryItem(item)}
                      >
                        {deletingIdentityId === item.agentId
                          ? tr("删除中")
                          : tr("删除")}
                      </button>
                    </div>
                  </div>
                ))
              ) : (
                <p className="muted">
                  {tr("还没有可用历史身份。创建或导入人员配置后会出现在这里。")}
                </p>
              )}
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
                {setupMode === "beginner" && (
                  <em className="beginner-marker marker-world">绿色: 世界名</em>
                )}
                <input
                  title="这次游玩的世界名称。存档名不是这里改，创建后可在右侧本地游玩记录里修改。"
                  value={createSettings.name}
                  placeholder="给这次世界起个名字"
                  onChange={(event) =>
                    setCreateSettings({
                      ...createSettings,
                      name: event.target.value,
                    })
                  }
                />
              </label>
              <label className="heading-setup-mode">
                <span>配置模式</span>
                {setupMode === "beginner" && (
                  <em className="beginner-marker marker-world">
                    绿色: 新手/专家
                  </em>
                )}
                <select
                  title="新手模式隐藏复杂选项，适合快速开局；专家模式显示完整世界观、工具、模型、加点和导入导出配置。"
                  value={setupMode}
                  onChange={(event) =>
                    setSetupMode(
                      event.target.value === "expert" ? "expert" : "beginner",
                    )
                  }
                >
                  <option value="beginner">新手模式</option>
                  <option value="expert">专家模式</option>
                </select>
              </label>
              <label className="heading-agent-count">
                <span>Agent 数量（角色数量）</span>
                {setupMode === "beginner" && (
                  <em className="beginner-marker marker-world">
                    绿色: 居民数量
                  </em>
                )}
                <input
                  title="这次开局创建的居民数量。"
                  type="number"
                  min="1"
                  max={MAX_AGENT_COUNT}
                  value={createSettings.agentCount}
                  onChange={(event) =>
                    setCreateSettings({
                      ...createSettings,
                      agentCount: clampAgentCount(event.target.value),
                    })
                  }
                />
              </label>
              <label className="heading-request-mode">
                <span>Agent 请求模式</span>
                {setupMode === "beginner" && (
                  <em className="beginner-marker marker-world">
                    绿色: 串行/并行
                  </em>
                )}
                <select
                  title="控制每轮 Agent 模型请求是一个个串行执行，还是并行请求后再统一结算。并行更快但模型服务压力更高。"
                  value={createSettings.agentRequestMode}
                  onChange={(event) =>
                    setCreateSettings({
                      ...createSettings,
                      agentRequestMode:
                        event.target.value === "parallel"
                          ? "parallel"
                          : "serial",
                    })
                  }
                >
                  <option value="serial">{tr("串行请求")}</option>
                  <option value="parallel">{tr("并行请求")}</option>
                </select>
              </label>
              <label className="heading-difficulty-select">
                <span>生存难度</span>
                {setupMode === "beginner" && (
                  <em className="beginner-marker marker-world">
                    绿色: 生存压力
                  </em>
                )}
                <select
                  title="控制饥饿、口渴、睡眠、疾病和生存压力的强度。"
                  value={createSettings.survivalDifficulty}
                  onChange={(event) =>
                    setCreateSettings({
                      ...createSettings,
                      survivalDifficulty: event.target.value,
                    })
                  }
                >
                  {SURVIVAL_DIFFICULTIES.map((difficulty) => (
                    <option key={difficulty.value} value={difficulty.value}>
                      {tr(difficulty.label)}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className="primary-action"
                data-auto-title="false"
                disabled={busy}
                onClick={createWorld}
                title="红色步骤: 配置完成后点击这里创建世界。进入游戏后还要点右上角继续按钮。"
              >
                {busy ? tr("正在创建居民...") : tr("创建世界")}
                {setupMode === "beginner" && (
                  <em className="beginner-marker marker-start">
                    红色: 创建世界
                  </em>
                )}
              </button>
            </div>
          </div>

          {setupMode === "expert" && (
            <section
              id="setup-world-config"
              className="panel create-panel setup-card"
            >
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
                    onChange={(event) =>
                      setCreateSettings({
                        ...createSettings,
                        seed: Number(event.target.value),
                      })
                    }
                  />
                </label>
                <label title="控制后端自动推进频率。快节奏世界观推荐快速，真实模拟推荐慢速。">
                  速度
                  <select
                    value={createSettings.speed}
                    onChange={(event) =>
                      setCreateSettings({
                        ...createSettings,
                        speed: event.target.value,
                      })
                    }
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
                      onChange={(event) =>
                        setCreateSettings({
                          ...createSettings,
                          pregnancyMode: event.target.value,
                        })
                      }
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
                    onChange={(event) =>
                      setCreateSettings({
                        ...createSettings,
                        traitMode: event.target.value,
                      })
                    }
                  >
                    <option value="agent">{tr("Agent 自己加点")}</option>
                    <option value="random">{tr("随机加点")}</option>
                    <option value="player">{tr("玩家加点")}</option>
                  </select>
                </label>
                <label
                  title={tr("Agent 自己加点和随机加点使用的固定总点数参考。")}
                >
                  固定点数
                  <input
                    type="number"
                    min="0"
                    value={createSettings.traitBudget}
                    onChange={(event) =>
                      setCreateSettings({
                        ...createSettings,
                        traitBudget: Number(event.target.value),
                      })
                    }
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
              llmGeneration={createSettings.llmGeneration}
              collectiveCorePrompt={createSettings.collectiveCorePrompt}
              providers={providers}
              agentSpecialToolsets={agentSpecialToolsets}
              narratorConfig={narratorConfig}
              imageGeneration={createSettings.imageGeneration}
              babyModelConfigs={babyModelConfigs}
              agentConfigs={agentConfigs}
              worldviewId={createSettings.worldviewId}
              werewolfEnabled={Boolean(
                selectedWorldview.default_create_settings?.werewolf_mode_enabled,
              )}
              werewolfRoleAssignment={createSettings.werewolfRoleAssignment}
              reusableWorlds={
                reusableWorlds.length ? reusableWorlds : recentWorlds
              }
              pullingProviderId={pullingProviderId}
              setupMode={setupMode}
              language={uiSettings.language}
              onProvidersChange={setProviders}
              onCollectiveCorePromptChange={(value) =>
                setCreateSettings({
                  ...createSettings,
                  collectiveCorePrompt: value,
                })
              }
              onLlmGenerationChange={(value) =>
                setCreateSettings((current) => ({
                  ...current,
                  llmGeneration: value,
                }))
              }
              onNarratorConfigChange={setNarratorConfig}
              onImageGenerationChange={(value) =>
                setCreateSettings((current) => ({
                  ...current,
                  imageGeneration: normalizeImageGenerationSettings(value),
                }))
              }
              onBabyModelConfigsChange={setBabyModelConfigs}
              onAgentConfigsChange={setAgentConfigs}
              onWerewolfRoleAssignmentChange={(value) =>
                setCreateSettings((current) => ({
                  ...current,
                  werewolfRoleAssignment: normalizeWerewolfRoleAssignment(
                    value,
                    current.agentCount,
                  ),
                }))
              }
              onPullModels={pullModels}
              onExportAgentArchive={exportAgentArchive}
              onImportAgentArchive={importAgentArchive}
              onReuseWorldConfig={reuseWorldAgentConfig}
            />
          </div>
          {busy && (
            <p className="muted create-hint">
              {tr(
                "已有姓名和外貌的居民会直接使用配置；缺少身份时才调用模型补全。",
              )}
            </p>
          )}
          {error && <p className="error-line">{error}</p>}
        </section>

        <aside className="setup-right">
          <details id="setup-worldpacks" className="panel setup-side-section preset-panel" open>
            <summary className="panel-heading setup-side-summary">
              <h2>世界观与工具集</h2>
              <span>{localizedPresetName(selectedWorldview, uiSettings.language)}</span>
            </summary>
            <div className="archive-actions worldpack-import-actions">
              <FileDropZone
                accept="application/json,.json,.aiworld,.aiworld.json,.zip,application/zip"
                disabled={worldPackImporting}
                onFile={importWorldPack}
                hint="可拖入世界包"
              >
                导入世界观文件
              </FileDropZone>
              <button
                type="button"
                disabled={worldPackImporting}
                onClick={() =>
                  apiClient
                    .presets()
                    .then(setPresetCatalog)
                    .catch((err) => setError(readableError(err)))
                }
              >
                刷新目录
              </button>
            </div>
            {worldPackImportMessage && (
              <p className="muted">{worldPackImportMessage}</p>
            )}
            {presetCatalog.content_pack_errors?.length ? (
              <div className="error-line">
                世界包有 {presetCatalog.content_pack_errors.length} 个校验错误：
                {presetCatalog.content_pack_errors[0]?.error || "未知错误"}
              </div>
            ) : null}
            <div className="preset-body">
              <label>
                世界观
                {setupMode === "beginner" && (
                  <em className="beginner-marker marker-world">
                    绿色: 选择世界观
                  </em>
                )}
                <select
                  title="选择这次游戏使用的世界观。世界观会决定地点、规则、变量和默认工具集。"
                  value={createSettings.worldviewId}
                  onChange={(event) =>
                    applyWorldviewSelection(event.target.value)
                  }
                >
                  {presetCatalog.worldviews.map((item) => (
                    <option key={item.worldview_id} value={item.worldview_id}>
                      {localizedPresetName(item, uiSettings.language)}
                    </option>
                  ))}
                </select>
              </label>
              <p>{selectedWorldviewDescription}</p>
              {setupMode === "expert" && (
                <>
                  <label
                    className="toggle-inline preset-toggle"
                    title="自带基础工具包含观察、说话、移动、睡眠等跨世界通用能力。关闭后需要世界观自己提供足够工具。"
                  >
                    <input
                      type="checkbox"
                      checked={createSettings.coreToolsetEnabled}
                      onChange={(event) =>
                        setCreateSettings({
                          ...createSettings,
                          coreToolsetEnabled: event.target.checked,
                        })
                      }
                    />
                    启用自带基础工具集
                  </label>
                  <label title="选择跨世界通用的基础行动工具集。">
                    自带工具集
                    <select
                      disabled={!createSettings.coreToolsetEnabled}
                      value={createSettings.coreToolsetId}
                      onChange={(event) =>
                        setCreateSettings({
                          ...createSettings,
                          coreToolsetId: event.target.value,
                        })
                      }
                    >
                      {coreToolsets.map((item) => (
                        <option key={item.toolset_id} value={item.toolset_id}>
                          {localizedPresetName(item, uiSettings.language)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <p>
                    {createSettings.coreToolsetEnabled
                      ? localizedPresetDescription(
                          selectedCoreToolset,
                          uiSettings.language,
                        )
                      : "已关闭自带工具集。只有当前世界观提供的工具和必要兜底会进入候选工具，特殊世界观可用这种方式完全接管行动体系。"}
                  </p>
                  <div className="optional-toolset-list">
                    <strong title="可选通用工具集可以跨世界观复用，例如生存、生育、金融。">
                      可选通用工具集
                    </strong>
                    {optionalToolsets.map((item) => {
                      const checked =
                        createSettings.optionalToolsetIds.includes(
                          item.toolset_id,
                        );
                      const toolsetName = localizedPresetName(
                        item,
                        uiSettings.language,
                      );
                      const toolsetDescription = localizedPresetDescription(
                        item,
                        uiSettings.language,
                      );
                      return (
                        <label
                          key={item.toolset_id}
                          className="toggle-inline preset-toggle optional-toolset-row"
                          title={toolsetDescription}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(event) => {
                              const nextIds = event.target.checked
                                ? Array.from(
                                    new Set([
                                      ...createSettings.optionalToolsetIds,
                                      item.toolset_id,
                                    ]),
                                  )
                                : createSettings.optionalToolsetIds.filter(
                                    (id) => id !== item.toolset_id,
                                  );
                              setCreateSettings({
                                ...createSettings,
                                optionalToolsetIds: nextIds,
                              });
                            }}
                          />
                          <span>
                            {toolsetName}
                            <small>{toolsetDescription}</small>
                          </span>
                        </label>
                      );
                    })}
                    {!allowBirth && (
                      <p>
                        通用生育与育儿工具集未勾选，所以不会开放怀孕、生子和宝宝模型配置。
                      </p>
                    )}
                  </div>
                  <label title="选择当前世界观专属的地点、住房、工作、消费、犯罪等工具集。">
                    世界工具集
                    <select
                      value={selectedWorldToolset.toolset_id}
                      onChange={(event) =>
                        setCreateSettings({
                          ...createSettings,
                          worldToolsetId: event.target.value,
                        })
                      }
                    >
                      {worldToolsets.map((item) => (
                        <option key={item.toolset_id} value={item.toolset_id}>
                          {localizedPresetName(item, uiSettings.language)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <p>{selectedWorldToolsetDescription}</p>
                </>
              )}
              <div className="preset-tags">
                <span
                  title={
                    selectedWorldview.packaged
                      ? "这个世界观包随项目内置，不需要额外导入。"
                      : "这个世界观来自你导入的外部世界包。"
                  }
                >
                  {selectedWorldview.packaged ? "内置包" : "外部包"}
                </span>
                <span title={`当前世界观版本：${selectedWorldview.version}`}>
                  世界观 v{selectedWorldview.version}
                </span>
                <span
                  title={
                    createSettings.coreToolsetEnabled
                      ? `自带基础工具集版本：${selectedCoreToolset.version}`
                      : "自带基础工具集已关闭。"
                  }
                >
                  {createSettings.coreToolsetEnabled
                    ? `自带 v${selectedCoreToolset.version}`
                    : "自带已关闭"}
                </span>
                <span
                  title={`当前启用 ${createSettings.optionalToolsetIds.length} 个可选通用工具集。`}
                >
                  可选 {createSettings.optionalToolsetIds.length} 个
                </span>
                <span
                  title={`世界观专属工具集版本：${selectedWorldToolset.version}。`}
                >
                  世界工具 v{selectedWorldToolset.version}
                </span>
              </div>
            </div>
          </details>
          <details id="setup-plugins" className="panel setup-side-section plugin-panel">
            <summary className="panel-heading setup-side-summary">
              <h2>项目插件</h2>
              <span>{pluginInstallMessage ? "有安装消息" : "导入或安装插件"}</span>
            </summary>
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
              <button
                type="button"
                disabled={pluginInstalling || !pluginInstallUrl.trim()}
                onClick={installPluginFromUrl}
              >
                {pluginInstalling ? "安装中" : "安装插件"}
              </button>
              <p>
                插件兼容 aiworld.plugin_pack.v1/v2
                或世界包格式；安装后会写入本地
                worldpacks/imported，并刷新世界观、工具集和工具目录。
              </p>
              {pluginInstallMessage && (
                <p className="muted">{pluginInstallMessage}</p>
              )}
            </div>
          </details>
          <details id="setup-recent-worlds" className="panel setup-side-section recent-worlds" open>
            <summary className="panel-heading setup-side-summary">
              <h2>
                {tr("本地游玩记录")}{" "}
                {setupMode === "beginner" && (
                  <em className="beginner-marker marker-record">
                    灰色: 继续旧存档
                  </em>
                )}
              </h2>
              <span>{recentWorldTotal} 个存档</span>
              <button
                type="button"
                className="icon-button text-icon-button"
                onClick={(event) => {
                  event.stopPropagation();
                  loadRecentWorlds(recentWorldPage).catch((err) =>
                    setError(readableError(err)),
                  );
                }}
              >
                {tr("刷新")}
              </button>
            </summary>
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
                            <button
                              type="button"
                              className="recent-world-open"
                              disabled={busy}
                              onClick={() => openRecentWorld(item.world_id)}
                            >
                              <strong>{saveNameForWorld(item)}</strong>
                              <span>世界名: {item.name}</span>
                              <span>
                                {item.world_time_label} ·{" "}
                                {item.status === "running"
                                  ? "运行中"
                                  : item.status === "paused"
                                    ? "暂停"
                                    : item.status === "ended"
                                      ? "已结束"
                                      : item.status}
                              </span>
                            </button>
                            <em>{worldDifficultyLabel(item)}</em>
                            {editing ? (
                              <form
                                className="recent-rename-form"
                                onSubmit={(event) => {
                                  event.preventDefault();
                                  updateRecentWorldSaveName(item.world_id);
                                }}
                              >
                                <input
                                  value={renamingSaveName}
                                  placeholder="存档名"
                                  onChange={(event) =>
                                    setRenamingSaveName(event.target.value)
                                  }
                                />
                                <button type="submit" disabled={busy}>
                                  保存
                                </button>
                                <button
                                  type="button"
                                  disabled={busy}
                                  onClick={() => {
                                    setRenamingWorldId(null);
                                    setRenamingSaveName("");
                                  }}
                                >
                                  取消
                                </button>
                              </form>
                            ) : (
                              <div className="recent-world-actions">
                                <button
                                  type="button"
                                  disabled={busy}
                                  onClick={() => {
                                    setRenamingWorldId(item.world_id);
                                    setRenamingSaveName(saveNameForWorld(item));
                                  }}
                                >
                                  改存档名
                                </button>
                                <button
                                  type="button"
                                  className="danger-button"
                                  disabled={busy}
                                  onClick={() => deleteWorldSave(item)}
                                >
                                  <Trash2 size={14} />
                                  <span>
                                    {deletingWorldId === item.world_id
                                      ? "删除中"
                                      : "删除"}
                                  </span>
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
                  <button
                    type="button"
                    disabled={busy || recentWorldPage <= 1}
                    onClick={() =>
                      loadRecentWorlds(recentWorldPage - 1).catch((err) =>
                        setError(readableError(err)),
                      )
                    }
                  >
                    上一页
                  </button>
                  <span>
                    {recentWorldPage} / {recentWorldPageCount} · 共{" "}
                    {recentWorldTotal} 个
                  </span>
                  <button
                    type="button"
                    disabled={busy || recentWorldPage >= recentWorldPageCount}
                    onClick={() =>
                      loadRecentWorlds(recentWorldPage + 1).catch((err) =>
                        setError(readableError(err)),
                      )
                    }
                  >
                    下一页
                  </button>
                </div>
              </>
            ) : (
              <p className="muted">{tr("还没有本地游玩记录。")}</p>
            )}
          </details>
        </aside>
      </main>
    );
  }

  const agentSpecialToolsets = presetCatalog.agent_special_toolsets?.length
    ? presetCatalog.agent_special_toolsets
    : (DEFAULT_PRESET_CATALOG.agent_special_toolsets ?? []);
  const runtimeFeatures = worldUiFeatures(world);
  const displayWorld = worldWithFreshEventClock(world, events);
  const displayAgents = agents;

  return (
    <WorldDashboard
      uiSettings={uiSettings}
      controls={
        <Controls
          world={displayWorld}
          busy={busy}
          exportUrl={apiClient.exportUrl(world.world_id)}
          presetExportUrl={apiClient.agentPresetsExportUrl(world.world_id)}
          onStart={() => runAction("start")}
          onPause={() => runAction("pause")}
          onStep={() => runAction("step")}
          onEnd={() => runAction("end")}
          onSummarize={() => runAction("summarize")}
          onGenerateImage={() => runAction("generateImage")}
          onRefresh={() =>
            refresh(world.world_id).catch((err) => {
              if (activeWorldIdRef.current === world.world_id)
                setError(readableError(err));
            })
          }
          onNewWorld={resetToSetup}
          onDeleteWorld={() => deleteWorldSave(world)}
        />
      }
      left={
        <>
          <UiSettingsPanel settings={uiSettings} onChange={setUiSettings} />
          <MapPanel
            locations={locations}
            language={uiSettings.language}
            worldTimeLabel={displayWorld.world_time_label}
            refreshing={leftRefreshBusy}
            lastRefreshLabel={lastLeftRefreshLabel}
            onRefresh={() =>
              refreshLeftState(world.world_id, {
                manual: true,
                force: true,
              }).catch((err) => {
                if (activeWorldIdRef.current === world.world_id)
                  setError(readableError(err));
              })
            }
          />
          <AgentList
            agents={displayAgents}
            selectedAgentId={selectedAgentId}
            onSelect={setSelectedAgentId}
            language={uiSettings.language}
          />
          <NarratorPanel narrations={narrations} />
          <SimulationStatusPanel
            world={displayWorld}
            agents={displayAgents}
            language={uiSettings.language}
          />
          {runtimeFeatures.showMetrics && (
            <MetricsPanel world={world} metrics={metrics} />
          )}
        </>
      }
      center={
        <>
          <EventFeed
            agents={displayAgents}
            locations={locations}
            events={filteredEvents}
            filters={filters}
            onFiltersChange={setFilters}
            onRefresh={() =>
              refresh(world.world_id).catch((err) => {
                if (activeWorldIdRef.current === world.world_id)
                  setError(readableError(err));
              })
            }
            onRequestTts={requestEventTts}
            exportUrl={eventExportUrl}
            language={uiSettings.language}
          />
          <WorldInterventionPanel
            agents={agents}
            locations={locations}
            busy={interventionBusy}
            abilities={interventionAbilities}
            onApply={applyWorldIntervention}
            onImportPack={importInterventionPack}
            language={uiSettings.language}
          />
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
          <WorldRuntimePanel
            world={world}
            agents={agents}
            providers={providers}
            busy={busy}
            onSave={updateWorldRuntimeSettings}
            language={uiSettings.language}
          />
          {runtimeFeatures.showEconomyPanel && (
            <EconomyPanel
              world={world}
              metrics={metrics}
              language={uiSettings.language}
            />
          )}
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
  </AppErrorBoundary>,
);
