import { Activity, BookOpen, Cpu, Package, Settings2, Users, Volume2 } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { AgentDetail, LlmGenerationSettings, ProviderDraft, TtsConfigDraft } from "../api/types";
import { apiClient } from "../api/client";
import { FileDropZone } from "./FileDropZone";
import { ModelPicker } from "./ModelPicker";

const TRAIT_LABELS: Record<string, string> = {
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

const TRAIT_EFFECTS: Record<string, string> = {
  openness: "探索/新关系/新工具倾向；探索和学习会提升。",
  caution: "风险感知和边界；预算、研究、设边界会提升。",
  sociability: "主动聊天和参加活动；社交会提升，孤立会下降。",
  empathy: "帮助、安慰、照护和哀悼；伤害他人会下降。",
  curiosity: "观察、调查、阅读和研究；重复空转会下降。",
  discipline: "睡眠、清洁、工作、还债；拖延和冲动消费会下降。",
  aggression: "冲突、强制和犯罪倾向；和解/冥想会下降。",
  honesty: "守约、报告、道歉、还款；偷骗和隐瞒会下降。",
  creativity: "创作、提案、解决问题；创作和练习会提升。",
  neuroticism: "焦虑和应激；创伤会提升，休息/冥想会下降。"
};

const STATE_LABELS: Record<string, string> = {
  health: "生命",
  energy: "体力",
  satiety: "饱腹",
  hydration: "水分",
  hygiene: "清洁",
  social: "社交",
  fun: "乐趣",
  stress: "压力",
  mood: "心情"
};

const DEFAULT_LLM_GENERATION: LlmGenerationSettings = {
  stream: false,
  temperature: 0.7,
  top_p: 1,
  max_tokens: 0,
  presence_penalty: 0,
  frequency_penalty: 0
};

function firstString(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value;
  }
  return "";
}

function formatWorldMinute(value: unknown): string {
  const minutes = Math.max(0, Math.floor(Number(value) || 0));
  const day = Math.floor(minutes / 1440) + 1;
  const inDay = minutes % 1440;
  const hour = Math.floor(inDay / 60);
  const minute = inDay % 60;
  return `第${day}天 ${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function normalizeLlmGeneration(raw: unknown): LlmGenerationSettings {
  const data = raw && typeof raw === "object" ? raw as Partial<LlmGenerationSettings> & Record<string, unknown> : {};
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

const DESIRE_LABELS: Record<string, string> = {
  joy: "快乐",
  boredom: "无聊",
  loneliness: "孤独",
  romance_need: "恋爱需求",
  survival_pressure: "生存压力"
};

type DrawerSectionKey = "overview" | "state" | "asset" | "social" | "memory" | "model" | "voice" | "tools";
type DrawerTabKey = Exclude<DrawerSectionKey, "overview">;
type DrawerAccent = "info" | "state" | "asset" | "social" | "memory" | "model" | "voice";
type MemoryPanelTab = string;
type MemoryPanelItem = { id: string; content: string; world_time: number; importance: number | null; label: string };
type MemoryPanelBucket = { key: string; label: string; items: MemoryPanelItem[]; count: number };
const DEFAULT_DRAWER_OPEN: Record<DrawerSectionKey, boolean> = {
  overview: true,
  state: true,
  asset: true,
  social: false,
  memory: false,
  model: false,
  voice: false,
  tools: false
};
const DEFAULT_DRAWER_TAB: DrawerTabKey = "state";

function DrawerSection({
  title,
  summary,
  open,
  onOpenChange,
  accent = "info",
  compactCollapsed = false,
  icon,
  tooltip,
  children
}: {
  title: string;
  summary?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  accent?: DrawerAccent;
  compactCollapsed?: boolean;
  icon?: ReactNode;
  tooltip?: string;
  children: ReactNode;
}) {
  return (
    <details className={`drawer-section drawer-section-${accent}${compactCollapsed ? " drawer-section-compact" : ""}`} open={open} onToggle={(event) => onOpenChange(event.currentTarget.open)}>
      <summary className="drawer-section-summary" title={tooltip || title} aria-label={tooltip || title}>
        {compactCollapsed && !open && icon ? (
          <span className="drawer-section-icon-only" aria-hidden="true">{icon}</span>
        ) : (
          <>
            <span>{title}</span>
            {summary && <small>{summary}</small>}
          </>
        )}
      </summary>
      <div className="drawer-section-body">{children}</div>
    </details>
  );
}

function DrawerPanel({
  title,
  summary,
  accent = "info",
  children
}: {
  title: string;
  summary?: string;
  accent?: DrawerAccent;
  children: ReactNode;
}) {
  return (
    <section className={`drawer-section drawer-section-${accent} drawer-section-active-panel`}>
      <header className="drawer-section-heading">
        <span>{title}</span>
        {summary && <small>{summary}</small>}
      </header>
      <div className="drawer-section-body">{children}</div>
    </section>
  );
}

type AgentLlmUpdate = {
  provider_id?: string;
  provider_name?: string;
  base_url?: string;
  api_key?: string;
  clear_api_key?: boolean;
  model_name?: string;
  custom_system_prompt?: string;
  tool_context_mode?: "dynamic" | "all";
  agent_toolset_ids?: string[];
  retry_count?: number;
  retry_interval_ms?: number;
  request_timeout_ms?: number;
  rpm?: number;
  llm_generation?: Partial<LlmGenerationSettings>;
};

type AgentProfileUpdate = {
  avatar_hint?: Record<string, unknown>;
  tts_config?: Record<string, unknown>;
  image_prompt_name?: string;
};

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

export function AgentDrawer({
  detail,
  providers = [],
  agentSpecialToolsets = [],
  pullingProviderId,
  replacingLlm = false,
  uiFeatures,
  onPullModels,
  onReplaceLlm,
  onUpdateProfile
}: {
  detail: AgentDetail | null;
  providers?: ProviderDraft[];
  agentSpecialToolsets?: Array<{ toolset_id: string; name: string; description: string }>;
  uiFeatures?: { showAgentEconomy?: boolean; showWork?: boolean; showLaw?: boolean; showFamily?: boolean };
  pullingProviderId?: string | null;
  replacingLlm?: boolean;
  onPullModels?: (providerId: string, override?: { baseUrl?: string; apiKey?: string }) => void | Promise<string[] | void>;
  onReplaceLlm?: (agentId: string, payload: AgentLlmUpdate) => Promise<void>;
  onUpdateProfile?: (agentId: string, payload: AgentProfileUpdate) => Promise<void>;
}) {
  const [selectedProviderId, setSelectedProviderId] = useState("");
  const [agentDrawerOpen, setAgentDrawerOpen] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState<Record<DrawerSectionKey, boolean>>(DEFAULT_DRAWER_OPEN);
  const [activeDrawerTab, setActiveDrawerTab] = useState<DrawerTabKey | null>(DEFAULT_DRAWER_TAB);
  const [memoryPanelTab, setMemoryPanelTab] = useState<MemoryPanelTab>("");
  const [llmDraft, setLlmDraft] = useState<{ modelName: string; baseUrl: string; apiKey: string; customSystemPrompt: string; toolContextMode: "dynamic" | "all"; agentToolsetIds: string[]; retryCount: number; retryIntervalMs: number; requestTimeoutMs: number; rpm: number; llmGeneration: LlmGenerationSettings }>({ modelName: "", baseUrl: "", apiKey: "", customSystemPrompt: "", toolContextMode: "dynamic", agentToolsetIds: [], retryCount: 2, retryIntervalMs: 1500, requestTimeoutMs: 300000, rpm: 0, llmGeneration: DEFAULT_LLM_GENERATION });
  const [ttsDraft, setTtsDraft] = useState<TtsConfigDraft>(() => defaultTtsConfig());
  const [imagePromptNameDraft, setImagePromptNameDraft] = useState("");
  const [agentTools, setAgentTools] = useState<{ count: number; categories: Record<string, number>; tools: Array<{ tool_name: string; display_name: string; catalog_category?: string }> } | null>(null);
  const [agentToolsLoading, setAgentToolsLoading] = useState(false);
  const provider = useMemo(
    () => providers.find((item) => item.providerId === selectedProviderId) ?? providers[0],
    [providers, selectedProviderId]
  );
  const providerSignature = useMemo(
    () => providers.map((item) => `${item.providerId}:${item.name}:${item.baseUrl}:${item.models.length}`).join("|"),
    [providers]
  );
  const agentToolsetSignature = useMemo(
    () => agentSpecialToolsets.map((item) => item.toolset_id).join("|"),
    [agentSpecialToolsets]
  );

  useEffect(() => {
    if (!detail) return;
    const identity = detail.identity;
    const providerId = String(identity.model_provider_id ?? "");
    const providerName = String(identity.model_provider_name ?? "");
    const currentProvider =
      providers.find((item) => item.providerId === providerId) ??
      providers.find((item) => item.name === providerName || item.providerId === providerName) ??
      providers[0];
    setSelectedProviderId(currentProvider?.providerId ?? "");
    setLlmDraft({
      modelName: String(identity.model_name ?? ""),
      baseUrl: String(identity.llm_base_url ?? currentProvider?.baseUrl ?? ""),
      apiKey: currentProvider?.apiKey ?? "",
      customSystemPrompt: String(identity.custom_system_prompt ?? ""),
      toolContextMode: identity.tool_context_mode === "all" ? "all" : "dynamic",
      agentToolsetIds: Array.isArray(identity.agent_toolset_ids) ? identity.agent_toolset_ids.map(String) : agentSpecialToolsets.map((item) => item.toolset_id),
      retryCount: Number(identity.llm_retry_count ?? currentProvider?.retryCount ?? 2),
      retryIntervalMs: Number(identity.llm_retry_interval_ms ?? currentProvider?.retryIntervalMs ?? 1500),
      requestTimeoutMs: Number(identity.llm_request_timeout_ms ?? currentProvider?.requestTimeoutMs ?? 300000),
      rpm: Number(identity.llm_rpm ?? currentProvider?.rpm ?? 0),
      llmGeneration: normalizeLlmGeneration(identity.llm_generation)
    });
    setTtsDraft({ ...normalizeTtsConfig(identity.tts_config), apiKey: "" });
    setImagePromptNameDraft(String(identity.image_prompt_name ?? ""));
  }, [
    detail?.identity?.agent_id,
    detail?.identity?.model_provider_id,
    detail?.identity?.model_provider_name,
    detail?.identity?.model_name,
    detail?.identity?.llm_base_url,
    detail?.identity?.custom_system_prompt,
    detail?.identity?.image_prompt_name,
    detail?.identity?.tool_context_mode,
    detail?.identity?.llm_retry_count,
    detail?.identity?.llm_retry_interval_ms,
    detail?.identity?.llm_request_timeout_ms,
    detail?.identity?.llm_rpm,
    detail?.identity?.llm_generation,
    detail?.identity?.tts_config,
    providerSignature,
    agentToolsetSignature,
  ]);
  useEffect(() => {
    if (!detail) return;
    setAgentDrawerOpen(true);
    setDrawerOpen(DEFAULT_DRAWER_OPEN);
    setActiveDrawerTab(DEFAULT_DRAWER_TAB);
    setMemoryPanelTab("");
  }, [detail?.identity?.agent_id]);

  // 加载 agent 可用工具
  useEffect(() => {
    if (!detail || activeDrawerTab !== "tools") return;
    if (agentTools) return; // 已经加载过
    const worldId = detail.world_id;
    const agentId = String(detail.identity.agent_id);
    if (!worldId || !agentId) return;
    setAgentToolsLoading(true);
    apiClient.agentTools(worldId, agentId)
      .then(setAgentTools)
      .catch(() => {})
      .finally(() => setAgentToolsLoading(false));
  }, [detail, activeDrawerTab, agentTools]);

  if (!detail) {
    return (
      <section className="panel agent-drawer">
        <h2>详情</h2>
        <p className="muted">选择一个居民查看状态。</p>
      </section>
    );
  }
  const identity = detail.identity;
  const agentId = String(identity.agent_id);
  const avatarHint = identity.avatar_hint && typeof identity.avatar_hint === "object" ? identity.avatar_hint as Record<string, unknown> : {};
  const avatarImageUrl = firstString(
    avatarHint.image_data_url,
    avatarHint.imageDataUrl,
    avatarHint.image_url,
    avatarHint.imageUrl,
  );
  const standingImageUrl = firstString(
    avatarHint.standing_image_data_url,
    avatarHint.standingImageDataUrl,
    avatarHint.standing_image_url,
    avatarHint.standingImageUrl,
    avatarHint.standing_url,
    avatarHint.standingUrl,
  );
  const v5 = detail.v5_state;
  const v6 = detail.v6_state;
  const economy = v6?.economy_profile ?? {};
  const housing = v6?.housing ?? {};
  const hedonic = v6?.hedonic_state ?? {};
  const broker = v6?.broker_account ?? null;
  const showAgentEconomy = uiFeatures?.showAgentEconomy ?? true;
  const showWork = uiFeatures?.showWork ?? true;
  const showLaw = uiFeatures?.showLaw ?? true;
  const showFamily = true;
  const housingText = formatHousing(housing);
  const consumptionText = formatConsumptionHabit(hedonic);
  const familyDisplay = typeof v5.family_display === "object" && v5.family_display ? v5.family_display as Record<string, unknown> : {};
  const partnerDisplay = typeof familyDisplay.partner === "object" && familyDisplay.partner ? familyDisplay.partner as Record<string, unknown> : null;
  const childrenDisplay = Array.isArray(familyDisplay.children) ? familyDisplay.children as Array<Record<string, unknown>> : [];
  const configuredStateFields = detail.state_display_schema?.dynamic_fields;
  const stateFieldKeys = Array.isArray(configuredStateFields) && configuredStateFields.length
    ? configuredStateFields.map(String)
    : Object.keys(STATE_LABELS);
  const worldviewState = detail.worldview_state?.state ?? {};
  const worldviewSchema = detail.worldview_state?.schema ?? {};
  const worldProgress = typeof worldviewState.progress === "object" && worldviewState.progress ? worldviewState.progress as Record<string, unknown> : {};
  const worldResources = typeof worldviewState.resources === "object" && worldviewState.resources ? worldviewState.resources as Record<string, unknown> : {};
  const resourceLabels = typeof worldviewSchema.resources === "object" && worldviewSchema.resources ? worldviewSchema.resources as Record<string, unknown> : {};
  const progressLabels = typeof worldviewSchema.progress === "object" && worldviewSchema.progress ? worldviewSchema.progress as Record<string, unknown> : {};
  const worldFlags = Array.isArray(worldviewState.flags) ? worldviewState.flags.map(String) : [];
  const failureCount = Number(identity.llm_consecutive_failures ?? 0);
  const lastLlmError = String(identity.last_llm_error ?? "");
  const providerModels = provider?.models ?? [];
  const inventoryItems = [...detail.inventory].sort((a, b) => String(a.name).localeCompare(String(b.name), "zh-Hans-CN"));
  const inventoryTotal = inventoryItems.reduce((sum, item) => sum + Number(item.quantity || 0), 0);
  const knowledgeByTarget = new Map(detail.knowledge_summary.map((item) => [String(item.target_agent_id), item]));
  const relationshipByTarget = new Map(detail.relationships.map((rel) => [String(rel.target_agent_id), rel]));
  const socialTargetIds = Array.from(new Set([...knowledgeByTarget.keys(), ...relationshipByTarget.keys()]));
  const socialCognitionRows = socialTargetIds.map((targetId) => {
    const knowledge = knowledgeByTarget.get(targetId);
    const relationship = relationshipByTarget.get(targetId);
    const targetName = String(relationship?.target_name ?? knowledge?.target_real_name ?? targetId);
    const knownName = String(knowledge?.known_name ?? "");
    const appearance = String(knowledge?.appearance_snapshot ?? "");
    const knowledgeText = knowledge
      ? Boolean(knowledge.name_known)
        ? `知道姓名: ${knownName || targetName}`
        : appearance
          ? `只记得外貌: ${appearance}`
          : "见过但身份不明确"
      : "暂无身份认知";
    const relationText = relationship
      ? `${String(relationship.relationship_label ?? "未标注关系")} · 熟悉${Math.round(Number(relationship.familiarity ?? 0))} 信任${Math.round(Number(relationship.trust ?? 0))} 好感${Math.round(Number(relationship.affection ?? 0))}`
      : "暂无关系记录";
    return { targetId, targetName, knowledgeText, relationText };
  });
  const backendMemoryBuckets: MemoryPanelBucket[] = Array.isArray(detail.memory_buckets)
    ? detail.memory_buckets.map((bucket) => ({
      key: String(bucket.key || bucket.label || "memory"),
      label: String(bucket.label || memoryTypeLabel(String(bucket.key || ""))),
      count: Number(bucket.count ?? bucket.items.length),
      items: bucket.items
        .map((memory) => memoryPanelItem(memory, String(bucket.label || memoryTypeLabel(String(memory.type || bucket.key || "")))))
        .sort((a, b) => b.world_time - a.world_time)
    })).filter((bucket) => bucket.items.length)
    : [];
  const fallbackMemoryBuckets = buildFallbackMemoryBuckets(detail);
  const memoryBuckets = backendMemoryBuckets.length ? backendMemoryBuckets : fallbackMemoryBuckets;
  const diarySeen = new Set(detail.diaries_recent.map((memory) => `${Number(memory.world_time ?? 0)}:${String(memory.content ?? "")}`));
  for (const event of detail.recent_events) {
    if (String(event.event_type ?? "") !== "diary" || String(event.actor_agent_id ?? "") !== agentId) continue;
    const content = String(event.viewer_text ?? "");
    const worldTime = Number(event.world_time ?? 0);
    const key = `${worldTime}:${content}`;
    if (diarySeen.has(key)) continue;
    diarySeen.add(key);
    let diaryBucket = memoryBuckets.find((bucket) => bucket.key === "diary");
    if (!diaryBucket) {
      diaryBucket = { key: "diary", label: "日记", count: 0, items: [] };
      memoryBuckets.push(diaryBucket);
    }
    diaryBucket.items.push({
      id: `diary-event-${event.event_id}`,
      content,
      world_time: worldTime,
      importance: Number(event.importance ?? 0),
      label: "日记事件"
    });
  }
  for (const bucket of memoryBuckets) bucket.items.sort((a, b) => b.world_time - a.world_time);
  const activeMemoryBucket = memoryBuckets.find((bucket) => bucket.key === memoryPanelTab) ?? memoryBuckets[0];
  const memoryTotal = memoryBuckets.reduce((sum, bucket) => sum + bucket.items.length, 0);
  const diaryTotal = memoryBuckets.find((bucket) => bucket.key === "diary")?.items.length ?? detail.diaries_recent.length;
  const memorySummary = `${memoryBuckets.length} 类 · ${memoryTotal} 条${diaryTotal ? ` · 日记 ${diaryTotal}` : ""}`;
  const setDrawerSectionOpen = (key: DrawerSectionKey, open: boolean) => {
    setDrawerOpen((current) => current[key] === open ? current : { ...current, [key]: open });
  };
  const pullCurrentProviderModels = async () => {
    if (!provider || !onPullModels) return;
    const models = await onPullModels(provider.providerId, {
      baseUrl: llmDraft.baseUrl,
      apiKey: llmDraft.apiKey || provider.apiKey,
    });
    if (Array.isArray(models) && models.length) {
      setLlmDraft((current) => ({
        ...current,
        modelName: current.modelName && models.includes(current.modelName) ? current.modelName : models[0],
      }));
    }
  };
  const uploadAvatar = (file: File | undefined) => {
    if (!file || !onUpdateProfile) return;
    const reader = new FileReader();
    reader.onload = () => {
      const current = (identity.avatar_hint && typeof identity.avatar_hint === "object" ? identity.avatar_hint : {}) as Record<string, unknown>;
      onUpdateProfile(agentId, { avatar_hint: { ...current, image_data_url: String(reader.result || ""), source: "runtime_upload" } });
    };
    reader.readAsDataURL(file);
  };
  const clearAvatar = () => {
    if (!onUpdateProfile) return;
    const current = (identity.avatar_hint && typeof identity.avatar_hint === "object" ? identity.avatar_hint : {}) as Record<string, unknown>;
    const { image_data_url: _image, ...rest } = current;
    onUpdateProfile(agentId, { avatar_hint: rest });
  };
  const uploadStandingImage = (file: File | undefined) => {
    if (!file || !onUpdateProfile) return;
    const reader = new FileReader();
    reader.onload = () => {
      const current = (identity.avatar_hint && typeof identity.avatar_hint === "object" ? identity.avatar_hint : {}) as Record<string, unknown>;
      onUpdateProfile(agentId, { avatar_hint: { ...current, standing_image_data_url: String(reader.result || ""), standing_image_source: "runtime_upload" } });
    };
    reader.readAsDataURL(file);
  };
  const clearStandingImage = () => {
    if (!onUpdateProfile) return;
    const current = (identity.avatar_hint && typeof identity.avatar_hint === "object" ? identity.avatar_hint : {}) as Record<string, unknown>;
    const { standing_image_data_url: _image, standing_image_source: _source, ...rest } = current;
    onUpdateProfile(agentId, { avatar_hint: rest });
  };
  const saveImagePromptName = async () => {
    if (!onUpdateProfile) return;
    await onUpdateProfile(agentId, { image_prompt_name: imagePromptNameDraft.trim() });
  };
  const saveTts = async () => {
    if (!onUpdateProfile) return;
    const payload: Record<string, unknown> = {
      enabled: ttsDraft.enabled,
      provider: ttsDraft.provider.trim(),
      mode: ttsDraft.mode,
      base_url: ttsDraft.baseUrl.trim(),
      endpoint_path: ttsDraft.endpointPath.trim(),
      model: ttsDraft.model.trim(),
      voice: ttsDraft.voice.trim(),
      response_format: ttsDraft.responseFormat.trim(),
      language_type: ttsDraft.languageType.trim(),
      instructions: ttsDraft.instructions.trim(),
      ref_audio_path: ttsDraft.refAudioPath.trim(),
      prompt_text: ttsDraft.promptText.trim(),
      prompt_lang: ttsDraft.promptLang.trim(),
      text_lang: ttsDraft.textLang.trim(),
      text_split_method: ttsDraft.textSplitMethod.trim(),
      batch_size: ttsDraft.batchSize
    };
    if (ttsDraft.apiKey.trim()) payload.api_key = ttsDraft.apiKey.trim();
    await onUpdateProfile(agentId, { tts_config: payload });
    setTtsDraft((current) => ({ ...current, apiKey: "" }));
  };
  const setTtsMode = (mode: TtsConfigDraft["mode"]) => {
    const patch: Partial<TtsConfigDraft> = mode === "qwen_dashscope"
      ? { provider: "Qwen TTS", baseUrl: "https://dashscope-intl.aliyuncs.com/api/v1", endpointPath: "/services/aigc/multimodal-generation/generation", model: "qwen3-tts-flash", voice: "Cherry", responseFormat: "wav", languageType: "Chinese" }
      : mode === "mimo"
        ? { provider: "Mimo TTS", endpointPath: "/audio/speech", responseFormat: "mp3" }
        : mode === "openai"
          ? { provider: "OpenAI 兼容 TTS", endpointPath: "/audio/speech", model: "tts-1", voice: "alloy", responseFormat: "mp3" }
          : { provider: "GPT-SoVITS", baseUrl: "", endpointPath: "/tts", responseFormat: "wav", textLang: "zh", promptLang: "zh", textSplitMethod: "cut5" };
    setTtsDraft((current) => normalizeTtsConfig({ ...current, ...patch, mode }));
  };
  const saveLlm = async () => {
    if (!onReplaceLlm) return;
    const typedKey = llmDraft.apiKey.trim();
    const payload: AgentLlmUpdate = {
      provider_id: provider?.providerId || selectedProviderId || undefined,
      provider_name: provider?.name || selectedProviderId || undefined,
      base_url: llmDraft.baseUrl.trim() || undefined,
      model_name: llmDraft.modelName.trim() || undefined,
      custom_system_prompt: llmDraft.customSystemPrompt,
      tool_context_mode: llmDraft.toolContextMode,
      agent_toolset_ids: llmDraft.agentToolsetIds,
      retry_count: llmDraft.retryCount,
      retry_interval_ms: llmDraft.retryIntervalMs,
      request_timeout_ms: llmDraft.requestTimeoutMs,
      rpm: llmDraft.rpm,
      llm_generation: llmDraft.llmGeneration
    };
    if (typedKey) payload.api_key = typedKey;
    await onReplaceLlm(agentId, payload);
    setLlmDraft((current) => ({ ...current, apiKey: "" }));
  };
  const drawerTabItems: Array<{ key: DrawerTabKey; title: string; summary: string; accent: DrawerAccent; icon: ReactNode }> = [
    { key: "state", title: "身体、需求与世界变量", summary: "情绪欲望、生命体征、世界观专属状态", accent: "state", icon: <Activity size={18} /> },
    { key: "asset", title: "资产、背包与生活", summary: `钱包 ${String(v5.wallet?.money ?? 0)} · 背包 ${inventoryTotal} 件`, accent: "asset", icon: <Package size={18} /> },
    { key: "social", title: "人格与认知关系", summary: `${detail.relationships.length} 段关系 · ${socialCognitionRows.length} 个认知对象`, accent: "social", icon: <Users size={18} /> },
    { key: "memory", title: "记忆与日记", summary: memorySummary, accent: "memory", icon: <BookOpen size={18} /> },
    { key: "model", title: "模型与工具配置", summary: `${String(identity.model_name ?? "默认")} · ${identity.tool_context_mode === "all" ? "固定工具集" : "动态工具"}`, accent: "model", icon: <Cpu size={18} /> },
    { key: "voice", title: "Agent TTS 接口", summary: ttsDraft.enabled ? "已启用" : "未启用", accent: "voice", icon: <Volume2 size={18} /> },
    { key: "tools", title: "可用工具审计", summary: "查看 agent 当前可用的工具列表", accent: "model", icon: <Settings2 size={18} /> },
  ];
  return (
    <section className="panel agent-drawer">
      <details className="agent-drawer-page" open={agentDrawerOpen} onToggle={(event) => setAgentDrawerOpen(event.currentTarget.open)}>
        <summary className="panel-heading agent-drawer-page-summary">
          <h2>{String(identity.chosen_name)}</h2>
          <small>{detail.current_location.name} · {detail.activity_status?.label ?? "清醒"}</small>
        </summary>
        <div className="drawer-tabs">
        <DrawerSection title="概览" summary={`${detail.current_location.name} · ${detail.activity_status?.label ?? "清醒"}`} accent="info" open={drawerOpen.overview} onOpenChange={(open) => setDrawerSectionOpen("overview", open)}>
          <div className="runtime-avatar-row">
            {avatarImageUrl ? (
              <img src={avatarImageUrl} alt="" />
            ) : (
              <span>{String(identity.chosen_name ?? "?").slice(0, 1)}</span>
            )}
            <FileDropZone accept="image/*" className="avatar-drop-zone" onFile={(file) => uploadAvatar(file)} hint="可拖入图片">
              更换头像
            </FileDropZone>
            <button type="button" disabled={!onUpdateProfile || !avatarImageUrl} onClick={clearAvatar}>移除头像</button>
          </div>
          <div className="runtime-standing-row">
            {standingImageUrl && (
              <img src={standingImageUrl} alt="" />
            )}
            <div className="runtime-standing-actions">
              <FileDropZone accept="image/*" className="avatar-drop-zone" onFile={(file) => uploadStandingImage(file)} hint="可拖入图片">
                更换立绘
              </FileDropZone>
              <button type="button" disabled={!onUpdateProfile || !standingImageUrl} onClick={clearStandingImage}>移除立绘</button>
            </div>
          </div>
          <div className="runtime-image-prompt-row">
            <label>
              <span>生图角色名</span>
              <input
                value={imagePromptNameDraft}
                placeholder="saki / character tag"
                onChange={(event) => setImagePromptNameDraft(event.target.value)}
              />
            </label>
            <button type="button" disabled={!onUpdateProfile} onClick={saveImagePromptName}>保存</button>
          </div>
          <p>{String(identity.appearance_full ?? "")}</p>
          <dl>
            <dt>性别身份</dt><dd>{String(identity.gender_identity ?? "未知")}</dd>
            <dt>年龄阶段</dt><dd>{String(identity.age_stage ?? "adult")}</dd>
            <dt>当前状态</dt><dd>{identity.lifecycle_state === "dead" ? `死亡${identity.death_cause ? `：${identity.death_cause}` : ""}` : detail.activity_status?.label ?? "清醒"}</dd>
            <dt>公开策略</dt><dd>{String(identity.intro_policy ?? "")}</dd>
            <dt>当前位置</dt><dd>{detail.current_location.name}</dd>
            <dt>生命周期</dt><dd>{String(identity.lifecycle_state ?? "")}</dd>
            {identity.werewolf_observer_role && <><dt>村庄危机身份</dt><dd>{String(identity.werewolf_observer_role)}</dd></>}
            <dt>目标</dt><dd>{String(identity.initial_goal ?? "")}</dd>
          </dl>
        </DrawerSection>

        <nav className="drawer-icon-tabs" aria-label="角色详情分类">
          {drawerTabItems.map((tab) => {
            const active = activeDrawerTab === tab.key;
            return (
              <button
                key={tab.key}
                type="button"
                className={`drawer-icon-tab drawer-section-${tab.accent}${active ? " active" : ""}`}
                title={`${tab.title}: ${tab.summary}`}
                aria-label={tab.title}
                aria-pressed={active}
                onClick={() => setActiveDrawerTab((current) => current === tab.key ? null : tab.key)}
              >
                {tab.icon}
              </button>
            );
          })}
        </nav>

        {activeDrawerTab === "state" && (
        <DrawerPanel title="身体、需求与世界变量" summary="情绪欲望、生命体征、世界观专属状态" accent="state">
          <h3>情绪欲望</h3>
          <div className="bars">
            {Object.entries(DESIRE_LABELS).map(([key, label]) => (
              <div key={key} className="bar-row">
                <span>{label}</span>
                <meter min={0} max={100} low={20} high={75} optimum={key === "joy" ? 80 : 20} value={Number(v5.desires?.[key] ?? 0)} />
                <strong>{Math.round(Number(v5.desires?.[key] ?? 0))}</strong>
              </div>
            ))}
          </div>
          <h3>动态状态</h3>
          <div className="bars">
            {stateFieldKeys.map((key) => (
              <div key={key} className="bar-row">
                <span>{STATE_LABELS[key] ?? key}</span>
                <meter min={key === "mood" ? -100 : 0} max={100} low={20} high={75} optimum={key === "stress" ? 0 : 80} value={Number(detail.dynamic_state[key] ?? 0)} />
                <strong>{Math.round(Number(detail.dynamic_state[key] ?? 0))}</strong>
              </div>
            ))}
          </div>
          <h3>世界观变量</h3>
          <div className="trait-grid worldview-state-grid">
            {Object.entries(worldProgress).map(([key, value]) => (
              <div key={`progress-${key}`}><span>{String(progressLabels[key] ?? (key === "level" ? "等级" : key === "exp" ? "经验" : key))}</span><strong>{String(value)}</strong></div>
            ))}
            {Object.entries(worldResources).map(([key, value]) => (
              <div key={`resource-${key}`}><span>{String(resourceLabels[key] ?? key)}</span><strong>{String(value)}</strong></div>
            ))}
          </div>
          {worldFlags.length ? <p className="memory-line">状态: {worldFlags.slice(-8).join("、")}</p> : <p className="muted">暂无世界观专属状态。</p>}
        </DrawerPanel>
        )}

        {activeDrawerTab === "asset" && (
          <DrawerPanel title="资产、背包与生活" summary={`钱包 ${String(v5.wallet?.money ?? 0)} · 背包 ${inventoryTotal} 件`} accent="asset">
            <dl>
              <dt>钱包</dt><dd>{String(v5.wallet?.money ?? 0)}</dd>
              {showAgentEconomy && <><dt>现金</dt><dd>{String(economy.cash ?? v5.wallet?.money ?? 0)}</dd></>}
              {showAgentEconomy && <><dt>净资产</dt><dd>{String(economy.net_worth ?? 0)}</dd></>}
              {showAgentEconomy && <><dt>总债务</dt><dd>{String(economy.total_debt ?? 0)} · 日最低{String(economy.minimum_payment_daily ?? 0)}</dd></>}
              {showAgentEconomy && <><dt>信用</dt><dd>{String(economy.credit_score ?? 0)} · 压力{String(economy.debt_stress ?? 0)}</dd></>}
              {showAgentEconomy && <><dt>住房</dt><dd>{housingText}</dd></>}
              {showAgentEconomy && <><dt>消费习惯</dt><dd>{consumptionText}</dd></>}
              {showAgentEconomy && <><dt>资产</dt><dd>{v6?.assets?.length ?? 0} 件 · 车辆 {v6?.vehicles?.length ?? 0}</dd></>}
              {showAgentEconomy && <><dt>股票</dt><dd>{broker ? `权益 ${String(broker.equity ?? 0)} · 浮盈亏 ${String(broker.unrealized_pnl ?? 0)}` : "未开户"}</dd></>}
              {showWork && <><dt>工作</dt><dd>{String(v5.work?.job ?? "无")} · 疲劳{String(v5.work?.fatigue ?? 0)}</dd></>}
              {showLaw && <><dt>法律</dt><dd>{v5.law?.jailed ? `在押，剩余${String(v5.law?.jail_days_remaining ?? 0)}天` : "自由"}</dd></>}
              {showFamily && <><dt>家庭</dt><dd>{familySummary(familyDisplay, partnerDisplay, childrenDisplay)}</dd></>}
              <dt>创伤</dt><dd>强度 {String(v5.trauma?.emotional_intensity ?? 0)}</dd>
            </dl>
            <div className="inventory-heading">
              <strong>背包</strong>
              <span>{inventoryItems.length} 种 / {inventoryTotal} 件</span>
            </div>
            {inventoryItems.length ? (
              <div className="inventory-compact-list">
                {inventoryItems.map((item) => (
                  <div className="inventory-compact-row" key={item.item_id} title={item.name}>
                    <span>{item.name}</span>
                    <strong>×{item.quantity}</strong>
                  </div>
                ))}
              </div>
            ) : <p className="muted">背包为空。</p>}
          </DrawerPanel>
        )}

        {activeDrawerTab === "memory" && (
          <DrawerPanel title="记忆与日记" summary={memorySummary} accent="memory">
            {memoryBuckets.length ? (
              <div className="memory-subtabs" role="tablist" aria-label="记忆类型">
                {memoryBuckets.map((bucket) => {
                  const active = activeMemoryBucket?.key === bucket.key;
                  return (
                    <button
                      key={bucket.key}
                      type="button"
                      className={active ? "active" : ""}
                      role="tab"
                      aria-selected={active}
                      onClick={() => setMemoryPanelTab(bucket.key)}
                    >
                      {bucket.label} <small>{bucket.items.length}</small>
                    </button>
                  );
                })}
              </div>
            ) : null}
            {activeMemoryBucket ? (activeMemoryBucket.items.length ? (
              <div className="memory-list">
                {activeMemoryBucket.items.map((memory) => (
                  <article key={memory.id} className="memory-card">
                    <header className="memory-card-meta">
                      <strong>{memory.label}</strong>
                      <span>{formatWorldMinute(memory.world_time)}</span>
                      {memory.importance !== null && <b>重要度 {Math.round(Number(memory.importance ?? 0))}</b>}
                    </header>
                    <p>{memory.content}</p>
                  </article>
                ))}
              </div>
            ) : <p className="muted">暂无{activeMemoryBucket.label}。</p>) : <p className="muted">暂无记忆。</p>}
          </DrawerPanel>
        )}

        {activeDrawerTab === "social" && (
        <DrawerPanel title="人格与认知关系" summary={`${detail.relationships.length} 段关系 · ${socialCognitionRows.length} 个认知对象`} accent="social">
          <h3>人格</h3>
          <div className="trait-grid">
            {Object.entries(detail.traits).map(([key, value]) => (
              <div key={key} title={TRAIT_EFFECTS[key] ?? ""}><span>{TRAIT_LABELS[key] ?? key}</span><strong>{value}</strong><small>{TRAIT_EFFECTS[key] ?? ""}</small></div>
            ))}
          </div>
          <p>{String(identity.speaking_style ?? "")}</p>
          <h3>认知与关系</h3>
          {socialCognitionRows.length ? (
            <div className="social-cognition-list">
              {socialCognitionRows.map((row) => (
                <div key={row.targetId} className="social-cognition-row">
                  <strong>{row.targetName}</strong>
                  <span>{row.knowledgeText}</span>
                  <span>{row.relationText}</span>
                </div>
              ))}
            </div>
          ) : <p className="muted">暂无身份认知或关系记录。</p>}
        </DrawerPanel>
        )}

        {activeDrawerTab === "model" && (
        <DrawerPanel title="模型与工具配置" summary={`${String(identity.model_name ?? "默认")} · ${identity.tool_context_mode === "all" ? "固定工具集" : "动态工具"}`} accent="model">
          <dl>
            <dt>当前提供商</dt><dd>{provider?.name || String(identity.model_provider_name ?? "默认")}</dd>
            <dt>当前模型</dt><dd>{String(identity.model_name ?? "默认")}</dd>
            <dt>工具上下文</dt><dd>{identity.tool_context_mode === "all" ? "固定工具集" : "动态工具"}</dd>
            <dt>失败次数</dt><dd>{failureCount ? `${failureCount} 次` : "正常"}</dd>
          </dl>
          {lastLlmError && <p className="llm-error-line">{lastLlmError}</p>}
          <div className="agent-llm-form">
            <label>
              提供商
              <select
                key={`agent-drawer-provider-${providerSignature}`}
                value={selectedProviderId}
                onChange={(event) => {
                  const next = providers.find((item) => item.providerId === event.target.value);
                  setSelectedProviderId(event.target.value);
                  setLlmDraft((current) => ({
                    ...current,
                    baseUrl: next?.baseUrl ?? current.baseUrl,
                    modelName: next?.models?.[0] ?? "",
                    apiKey: next?.apiKey ?? "",
                    retryCount: next?.retryCount ?? current.retryCount,
                    retryIntervalMs: next?.retryIntervalMs ?? current.retryIntervalMs,
                    requestTimeoutMs: next?.requestTimeoutMs ?? current.requestTimeoutMs,
                    rpm: next?.rpm ?? current.rpm
                  }));
                }}
              >
                {providers.length ? providers.map((item) => <option key={item.providerId} value={item.providerId} title={item.name}>{item.name}</option>) : <option value="">手动配置</option>}
              </select>
            </label>
            <button type="button" disabled={!provider || pullingProviderId === provider?.providerId} onClick={pullCurrentProviderModels}>
              {pullingProviderId === provider?.providerId ? "拉取中..." : "拉取模型"}
            </button>
            <label>
              模型
              <ModelPicker
                value={llmDraft.modelName}
                models={providerModels}
                emptyLabel="选择模型"
                searchPlaceholder="搜索模型名"
                onChange={(modelName) => setLlmDraft({ ...llmDraft, modelName })}
              />
            </label>
            <label>
              工具上下文
              <select value={llmDraft.toolContextMode} onChange={(event) => setLlmDraft({ ...llmDraft, toolContextMode: event.target.value === "all" ? "all" : "dynamic" })}>
                <option value="dynamic">动态工具</option>
                <option value="all">固定工具集</option>
              </select>
            </label>
            {agentSpecialToolsets.length > 0 && (
              <div className="agent-toolset-picker drawer-toolset-picker">
                <span>特殊工具集</span>
                <div>
                  {agentSpecialToolsets.map((toolset) => (
                    <label key={toolset.toolset_id} title={toolset.description}>
                      <input
                        type="checkbox"
                        checked={llmDraft.agentToolsetIds.includes(toolset.toolset_id)}
                        onChange={(event) => {
                          const current = new Set(llmDraft.agentToolsetIds);
                          if (event.target.checked) current.add(toolset.toolset_id);
                          else current.delete(toolset.toolset_id);
                          setLlmDraft({ ...llmDraft, agentToolsetIds: Array.from(current) });
                        }}
                      />
                      {toolset.name.replace(/^特殊/, "")}
                    </label>
                  ))}
                </div>
              </div>
            )}
            <label>
              Base URL
              <input value={llmDraft.baseUrl} onChange={(event) => setLlmDraft({ ...llmDraft, baseUrl: event.target.value })} />
            </label>
            <label>
              API Key
              <input
                type="password"
                placeholder="留空表示不修改"
                value={llmDraft.apiKey}
                onChange={(event) => setLlmDraft({ ...llmDraft, apiKey: event.target.value })}
              />
            </label>
            <label>
              重试次数
              <input type="number" min="0" max="100000" value={llmDraft.retryCount} onChange={(event) => setLlmDraft({ ...llmDraft, retryCount: Number(event.target.value) })} />
            </label>
            <label>
              重试间隔 ms
              <input type="number" min="0" max="21600000" step="100" value={llmDraft.retryIntervalMs} onChange={(event) => setLlmDraft({ ...llmDraft, retryIntervalMs: Number(event.target.value) })} />
            </label>
            <label title="单次模型请求等待完整响应的毫秒数。0 表示不主动超时。">
              请求超时 ms
              <input type="number" min="0" max="86400000" step="1000" value={llmDraft.requestTimeoutMs} onChange={(event) => setLlmDraft({ ...llmDraft, requestTimeoutMs: Number(event.target.value) })} />
            </label>
            <label>
              RPM
              <input type="number" min="0" max="100000" value={llmDraft.rpm} title="0 表示不限 RPM，只受模型并发限制。" onChange={(event) => setLlmDraft({ ...llmDraft, rpm: Number(event.target.value) })} />
            </label>
            <details className="agent-llm-generation-config">
              <summary>输出参数 · 流式/温度等</summary>
              <div className="llm-generation-grid">
                <label className="toggle-inline">
                  <input type="checkbox" checked={llmDraft.llmGeneration.stream} onChange={(event) => setLlmDraft({ ...llmDraft, llmGeneration: { ...llmDraft.llmGeneration, stream: event.target.checked } })} />
                  流式输出
                </label>
                <label>Temperature<input type="number" min="0" max="2" step="0.05" value={llmDraft.llmGeneration.temperature} onChange={(event) => setLlmDraft({ ...llmDraft, llmGeneration: normalizeLlmGeneration({ ...llmDraft.llmGeneration, temperature: Number(event.target.value) }) })} /></label>
                <label>Top P<input type="number" min="0" max="1" step="0.05" value={llmDraft.llmGeneration.top_p} onChange={(event) => setLlmDraft({ ...llmDraft, llmGeneration: normalizeLlmGeneration({ ...llmDraft.llmGeneration, top_p: Number(event.target.value) }) })} /></label>
                <label>Max tokens<input type="number" min="0" max="200000" step="128" value={llmDraft.llmGeneration.max_tokens} onChange={(event) => setLlmDraft({ ...llmDraft, llmGeneration: normalizeLlmGeneration({ ...llmDraft.llmGeneration, max_tokens: Number(event.target.value) }) })} /></label>
                <label>Presence penalty<input type="number" min="-2" max="2" step="0.1" value={llmDraft.llmGeneration.presence_penalty} onChange={(event) => setLlmDraft({ ...llmDraft, llmGeneration: normalizeLlmGeneration({ ...llmDraft.llmGeneration, presence_penalty: Number(event.target.value) }) })} /></label>
                <label>Frequency penalty<input type="number" min="-2" max="2" step="0.1" value={llmDraft.llmGeneration.frequency_penalty} onChange={(event) => setLlmDraft({ ...llmDraft, llmGeneration: normalizeLlmGeneration({ ...llmDraft.llmGeneration, frequency_penalty: Number(event.target.value) }) })} /></label>
              </div>
            </details>
            <label className="agent-llm-prompt">
              单独系统提示词
              <textarea value={llmDraft.customSystemPrompt} onChange={(event) => setLlmDraft({ ...llmDraft, customSystemPrompt: event.target.value })} />
            </label>
            <button type="button" className="agent-llm-save" disabled={!onReplaceLlm || replacingLlm} onClick={saveLlm}>
              {replacingLlm ? "保存中..." : "保存 LLM"}
            </button>
          </div>
        </DrawerPanel>
        )}

        {activeDrawerTab === "voice" && (
        <DrawerPanel title="Agent TTS 接口" summary={ttsDraft.enabled ? "已启用" : "未启用"} accent="voice">
          <div className="agent-llm-form tts-config-form">
            <label className="toggle-inline">
              <input type="checkbox" checked={ttsDraft.enabled} onChange={(event) => setTtsDraft({ ...ttsDraft, enabled: event.target.checked })} />
              启用 TTS
            </label>
            <label>
              类型
              <select value={ttsDraft.mode} onChange={(event) => setTtsMode(event.target.value as TtsConfigDraft["mode"])}>
                <option value="gptsovits">GPT-SoVITS</option>
                <option value="openai">OpenAI 兼容</option>
                <option value="mimo">Mimo TTS</option>
                <option value="qwen_dashscope">Qwen / DashScope</option>
              </select>
            </label>
            <label>
              提供商
              <input value={ttsDraft.provider} placeholder="本地或云端 TTS 名称" onChange={(event) => setTtsDraft({ ...ttsDraft, provider: event.target.value })} />
            </label>
            <label>
              Base URL
              <input value={ttsDraft.baseUrl} placeholder="填写 TTS 服务地址" onChange={(event) => setTtsDraft({ ...ttsDraft, baseUrl: event.target.value })} />
            </label>
            <label>
              接口路径
              <input value={ttsDraft.endpointPath} placeholder={ttsDraft.mode === "qwen_dashscope" ? "/services/aigc/multimodal-generation/generation" : ttsDraft.mode === "gptsovits" ? "/tts" : "/audio/speech"} onChange={(event) => setTtsDraft({ ...ttsDraft, endpointPath: event.target.value })} />
            </label>
            <label>
              API Key
              <input type="password" value={ttsDraft.apiKey} placeholder="留空不修改密钥" onChange={(event) => setTtsDraft({ ...ttsDraft, apiKey: event.target.value })} />
            </label>
            {["openai", "mimo", "qwen_dashscope"].includes(ttsDraft.mode) && (
              <>
                <label>
                  模型
                  <input value={ttsDraft.model} placeholder={ttsDraft.mode === "qwen_dashscope" ? "qwen3-tts-flash" : "tts-1"} onChange={(event) => setTtsDraft({ ...ttsDraft, model: event.target.value })} />
                </label>
                <label>
                  音色
                  <input value={ttsDraft.voice} placeholder={ttsDraft.mode === "qwen_dashscope" ? "Cherry" : "voice id / speaker"} onChange={(event) => setTtsDraft({ ...ttsDraft, voice: event.target.value })} />
                </label>
                <label>
                  格式
                  <input value={ttsDraft.responseFormat} placeholder={ttsDraft.mode === "qwen_dashscope" ? "wav" : "mp3"} onChange={(event) => setTtsDraft({ ...ttsDraft, responseFormat: event.target.value })} />
                </label>
              </>
            )}
            {ttsDraft.mode === "qwen_dashscope" && (
              <>
                <label>
                  语言
                  <input value={ttsDraft.languageType} placeholder="Chinese / English / Auto" onChange={(event) => setTtsDraft({ ...ttsDraft, languageType: event.target.value })} />
                </label>
                <label className="agent-llm-prompt">
                  指令
                  <textarea value={ttsDraft.instructions} placeholder="可选。仅 instruct 模型支持语速、情绪等控制。" onChange={(event) => setTtsDraft({ ...ttsDraft, instructions: event.target.value })} />
                </label>
              </>
            )}
            {ttsDraft.mode === "gptsovits" && (
              <>
                <label className="agent-llm-prompt">
                  参考音频路径
                  <input value={ttsDraft.refAudioPath} placeholder="填写本机参考音频路径，例如 /path/to/reference.wav" onChange={(event) => setTtsDraft({ ...ttsDraft, refAudioPath: event.target.value })} />
                </label>
                <label className="agent-llm-prompt">
                  参考音频文字
                  <input value={ttsDraft.promptText} placeholder="参考音频里说的原文" onChange={(event) => setTtsDraft({ ...ttsDraft, promptText: event.target.value })} />
                </label>
                <label>
                  文本语言
                  <input value={ttsDraft.textLang} placeholder="zh" onChange={(event) => setTtsDraft({ ...ttsDraft, textLang: event.target.value })} />
                </label>
                <label>
                  参考语言
                  <input value={ttsDraft.promptLang} placeholder="zh" onChange={(event) => setTtsDraft({ ...ttsDraft, promptLang: event.target.value })} />
                </label>
                <label>
                  切分
                  <input value={ttsDraft.textSplitMethod} placeholder="cut5" onChange={(event) => setTtsDraft({ ...ttsDraft, textSplitMethod: event.target.value })} />
                </label>
                <label>
                  格式
                  <input value={ttsDraft.responseFormat} placeholder="wav" onChange={(event) => setTtsDraft({ ...ttsDraft, responseFormat: event.target.value })} />
                </label>
              </>
            )}
            <button type="button" className="agent-llm-save" disabled={!onUpdateProfile} onClick={saveTts}>保存 TTS</button>
          </div>
        </DrawerPanel>
        )}

        {activeDrawerTab === "tools" && (
        <DrawerPanel title="可用工具审计" summary={agentTools ? `${agentTools.count} 个工具` : "加载中..."} accent="model">
          {agentToolsLoading ? (
            <p className="muted">正在加载工具列表...</p>
          ) : agentTools ? (
            <>
              <dl>
                <dt>工具总数</dt><dd>{agentTools.count}</dd>
              </dl>
              {Object.keys(agentTools.categories).length > 0 && (
                <>
                  <h3>按类别统计</h3>
                  <div className="trait-grid">
                    {Object.entries(agentTools.categories).map(([cat, count]) => (
                      <div key={cat}><span>{cat || "核心"}</span><strong>{count}</strong></div>
                    ))}
                  </div>
                </>
              )}
              <h3>工具列表</h3>
              <div className="agent-tools-list" style={{ maxHeight: "300px", overflow: "auto" }}>
                <table style={{ width: "100%", fontSize: "0.85em" }}>
                  <thead>
                    <tr><th>工具名</th><th>显示名</th><th>类别</th></tr>
                  </thead>
                  <tbody>
                    {agentTools.tools.map((tool) => (
                      <tr key={tool.tool_name}>
                        <td style={{ fontFamily: "monospace", fontSize: "0.9em" }}>{tool.tool_name}</td>
                        <td>{tool.display_name}</td>
                        <td>{tool.catalog_category || "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p className="muted">无法加载工具列表</p>
          )}
        </DrawerPanel>
        )}
        </div>
      </details>
    </section>
  );
}

function memoryPanelItem(
  memory: { memory_id: number; type?: string; content: string; importance?: number | null; world_time: number },
  fallbackLabel: string
): MemoryPanelItem {
  const type = String(memory.type || "").trim();
  return {
    id: `memory-${type || fallbackLabel}-${memory.memory_id}`,
    content: String(memory.content ?? ""),
    world_time: Number(memory.world_time ?? 0),
    importance: memory.importance === undefined || memory.importance === null ? null : Number(memory.importance),
    label: type ? memoryTypeLabel(type) : fallbackLabel
  };
}

function buildFallbackMemoryBuckets(detail: AgentDetail): MemoryPanelBucket[] {
  const grouped = new Map<string, MemoryPanelBucket>();
  const addItem = (key: string, label: string, item: MemoryPanelItem) => {
    const bucket = grouped.get(key) ?? { key, label, count: 0, items: [] };
    bucket.items.push(item);
    bucket.count = bucket.items.length;
    grouped.set(key, bucket);
  };
  for (const memory of detail.memories_recent) {
    const key = String(memory.type || "memory");
    addItem(key, memoryTypeLabel(key), memoryPanelItem(memory, memoryTypeLabel(key)));
  }
  for (const memory of detail.diaries_recent) {
    addItem("diary", "日记", memoryPanelItem({ ...memory, type: "diary", importance: memory.importance ?? null }, "日记"));
  }
  return Array.from(grouped.values())
    .map((bucket) => ({ ...bucket, items: bucket.items.sort((a, b) => b.world_time - a.world_time) }))
    .filter((bucket) => bucket.items.length);
}

function memoryTypeLabel(type: string): string {
  const normalized = type.trim();
  const labels: Record<string, string> = {
    short: "短期记忆",
    long: "长期记忆",
    summary: "梦境/摘要",
    diary: "日记",
    relationship: "关系记忆",
    event: "事件记忆",
    episodic: "事件记忆",
    pregnancy: "怀孕/育儿",
    werewolf: "狼人杀记忆",
    memory: "主动记忆"
  };
  return labels[normalized] ?? (normalized || "记忆");
}

function formatHousing(housing: Record<string, unknown>): string {
  const status = String(housing.status ?? (housing.homeless ? "homeless" : "renter"));
  if (housing.homeless || status === "homeless") return "无稳定住所";
  if (status === "dependent" || housing.guardian_dependent) return "随监护人居住";
  if (status === "homeowner") return "自有住房";

  const rent = numberOrDefault(housing.rent_per_10_days, 30);
  const dueDay = numberOrDefault(housing.next_rent_due_day, 10);
  const label = status === "renter" ? "租住中" : status;
  return `${label} · 每10天房租${rent} · 第${dueDay}天到期`;
}

function formatConsumptionHabit(hedonic: Record<string, unknown>): string {
  const threshold = numberOrNull(hedonic.luxury_threshold);
  const pain = numberOrNull(hedonic.deprivation_pain);
  if (threshold === null && pain === null) return "暂无记录";
  const parts = [];
  if (threshold !== null) parts.push(`平时期待 ${threshold}`);
  if (pain !== null) parts.push(`落差感 ${pain}`);
  return parts.join(" · ");
}

function familySummary(familyDisplay: Record<string, unknown>, partnerDisplay: Record<string, unknown> | null, childrenDisplay: Array<Record<string, unknown>>): string {
  const parts: string[] = [];
  parts.push(`伴侣 ${String(partnerDisplay?.name ?? "无")}`);
  const guardians = Array.isArray(familyDisplay.guardians) ? familyDisplay.guardians as Array<Record<string, unknown>> : [];
  if (guardians.length) parts.push(`监护人 ${guardians.map((item) => String(item.name ?? item.agent_id ?? "")).filter(Boolean).join("、")}`);
  parts.push(childrenDisplay.length ? `孩子 ${childrenDisplay.map((item) => String(item.name ?? item.agent_id ?? "")).filter(Boolean).join("、")}` : "孩子 0");
  const pregnancy = typeof familyDisplay.pregnancy === "object" && familyDisplay.pregnancy ? familyDisplay.pregnancy as Record<string, unknown> : null;
  if (pregnancy?.pregnant) {
    const coParent = String(pregnancy.co_parent_name ?? "");
    parts.push(coParent ? `怀孕中，共同父母 ${coParent}` : "怀孕中");
  }
  return parts.join(" · ");
}

function numberOrDefault(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function numberOrNull(value: unknown): number | null {
  if (value === undefined || value === null || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
