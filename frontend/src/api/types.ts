export type World = {
  world_id: string;
  name: string;
  save_name?: string;
  status: "setup" | "running" | "paused" | "ended";
  seed: number;
  created_at?: string;
  current_world_time_minutes: number;
  world_time_label: string;
  settings_version?: string;
  settings: Record<string, unknown>;
};

export type WorldLocationOccupant = {
  agent_id: string;
  display_name: string;
  avatar_hint?: Record<string, unknown>;
  appearance_short?: string | null;
  lifecycle_state?: string;
  age_stage?: string;
  activity_label?: string;
};

export type WorldLocationNotice = {
  content: string;
  author_agent_id?: string | null;
  author_name?: string;
  world_time?: number;
  world_time_label?: string;
};

export type WorldLocationItem = {
  item_id?: string;
  name?: string;
  display_name?: string;
  description?: string;
  quantity?: number;
  [key: string]: unknown;
};

export type WorldLocation = {
  location_id: string;
  name: string;
  description: string;
  neighbors: string[];
  available_tools: string[];
  tags: string[];
  is_private: boolean;
  color?: string | null;
  capacity?: number | null;
  visibility_radius: number;
  occupant_count?: number;
  occupants?: WorldLocationOccupant[];
  item_count?: number;
  items?: WorldLocationItem[];
  notice_count?: number;
  notice_board?: WorldLocationNotice[];
};

export type LeftSnapshot = {
  world: World;
  agents: AgentListItem[];
  locations: WorldLocation[];
  latest_event_id?: number;
  latest_event_world_time?: number;
  state_version?: string;
  refreshed_at?: string;
};

export type WorldRefreshResult = {
  world: World;
  events: EventItem[];
  agents: AgentListItem[];
  locations: WorldLocation[];
  left_snapshot?: LeftSnapshot | null;
  image_wait_cutoff_event_id?: number | null;
  waiting_image_event_id?: number | null;
  event_delete_state: EventDeleteState;
};

export type WorldviewPreset = {
  worldview_id: string;
  name: string;
  name_i18n?: Record<string, string>;
  version: string;
  packaged: boolean;
  description: string;
  description_i18n?: Record<string, string>;
  status: string;
  entry_status?: string;
  pack_id?: string;
  pack_name?: string;
  pack_version?: string;
  source_path?: string;
  default_create_settings?: Record<string, unknown>;
};

export type ToolsetPreset = {
  toolset_id: string;
  legacy_toolset_ids?: string[];
  name: string;
  name_i18n?: Record<string, string>;
  version: string;
  packaged: boolean;
  scope?: "core" | "optional" | "world" | "agent_special" | "npc";
  tool_names?: string[];
  default_enabled?: boolean;
  worldview_id?: string;
  description: string;
  description_i18n?: Record<string, string>;
  status: string;
  entry_status?: string;
  pack_id?: string;
  pack_name?: string;
  pack_version?: string;
  source_path?: string;
};

export type PlaceholderInterface = {
  interface_id: string;
  name: string;
  status: string;
  description: string;
};

export type PresetCatalog = {
  worldviews: WorldviewPreset[];
  core_toolsets: ToolsetPreset[];
  optional_toolsets: ToolsetPreset[];
  agent_special_toolsets?: ToolsetPreset[];
  world_toolsets: ToolsetPreset[];
  toolsets: ToolsetPreset[];
  placeholder_interfaces: PlaceholderInterface[];
  content_pack_errors?: Array<{ source_path: string; error: string }>;
};

export type WorldPackImportResult = {
  ok: boolean;
  registered_tool_count: number;
  pack: {
    pack_id: string;
    name: string;
    version: string;
    source_path: string;
    worldviews: Array<{ worldview_id: string; name: string; version: string }>;
    toolsets: Array<{ toolset_id: string; name: string; scope: string }>;
  };
  catalog: PresetCatalog;
};

export type PluginInstallResult = {
  ok: boolean;
  registered_tool_count: number;
  plugin: {
    pack_id: string;
    name: string;
    version: string;
    source_path: string;
    worldviews: Array<{ worldview_id: string; name: string; version: string }>;
    toolsets: Array<{ toolset_id: string; name: string; scope: string }>;
  };
  catalog: PresetCatalog;
};

export type InterventionAbility = {
  ability_id: string;
  name: string;
  description: string;
  requires_actor: boolean;
  requires_target: boolean;
  requires_location: boolean;
  source_path?: string;
};

export type InterventionAbilityCatalog = {
  abilities: InterventionAbility[];
  errors?: Array<{ source_path: string; error: string }>;
};

export type InterventionPackImportResult = InterventionAbilityCatalog & {
  ok: boolean;
  imported: InterventionAbility[];
};

export type IdentityLibraryItem = {
  agentId: string;
  worldId: string;
  worldName: string;
  saveName: string;
  worldCreatedAt?: string;
  worldviewId: string;
  worldviewName: string;
  name: string;
  appearance: string;
  appearanceShort: string;
  systemPrompt: string;
  avatarDataUrl: string;
  avatarHint: Record<string, unknown>;
  providerName: string;
  modelName: string;
  baseUrl: string;
  llmRuntime: { retry_count?: number; retry_interval_ms?: number; request_timeout_ms?: number; rpm?: number };
  toolContextMode: "dynamic" | "all";
  agentToolsetIds: string[];
  ttsConfig: Record<string, unknown>;
  traits: Record<string, number>;
  genderIdentity?: string | null;
  genderExpression?: string | null;
  speakingStyle?: string | null;
  personalitySeed?: string | null;
  initialGoal?: string | null;
  createdAtWorldTime?: number | null;
  lifecycleState: string;
};

export type IdentityLibraryResult = {
  items: IdentityLibraryItem[];
};

export type StorageImageItem = {
  key: string;
  hash: string;
  kind: "generated" | "avatar" | "standing";
  kinds: Array<"generated" | "avatar" | "standing">;
  label: string;
  world_id: string;
  world_name: string;
  save_name: string;
  owner: string;
  size_bytes: number;
  reference_bytes: number;
  reference_count: number;
  preview_data_url: string;
  preview_url?: string;
  image_key?: string;
  references: Array<{
    key: string;
    kind: "generated" | "avatar" | "standing";
    label: string;
    world_id: string;
    world_name: string;
    save_name: string;
    owner: string;
  }>;
};

export type StorageImageResult = {
  items: StorageImageItem[];
  totals: {
    count: number;
    references: number;
    bytes: number;
    reference_bytes: number;
    generated: number;
    avatar: number;
    standing: number;
  };
  limit: number;
};

export type AgentListItem = {
  agent_id: string;
  display_name: string;
  image_prompt_name?: string;
  avatar_hint: { color?: string; tags?: string[]; image_data_url?: string };
  appearance_short: string;
  age_stage: string;
  lifecycle_state: string;
  location_id: string | null;
  location_name: string;
  location_color?: string | null;
  health: number;
  energy: number;
  mood_label: string;
  activity_status?: {
    state: string;
    label: string;
    is_sleeping: boolean;
    sleep_started_world_time?: number | null;
    sleep_started_label?: string | null;
    sleep_until_world_time?: number;
    sleep_until_label?: string;
    working_status?: Record<string, unknown>;
  };
  money: number;
  tts_enabled?: boolean;
  llm_consecutive_failures?: number;
  has_warning: boolean;
};

export type EventItem = {
  event_id: number;
  world_id: string;
  world_time: number;
  world_time_label: string;
  real_created_at?: string;
  event_type: string;
  actor_agent_id: string | null;
  target_agent_id: string | null;
  location_id: string | null;
  location_name?: string | null;
  location_color?: string | null;
  visibility_scope: string;
  importance: number;
  color_class: string;
  viewer_text: string;
  payload: Record<string, unknown>;
  state_delta: Record<string, unknown>;
  no_state_changed: boolean;
};

export type EventFilters = {
  minImportance: number;
  dialogueOnly: boolean;
  showNarrator: boolean;
  exportAvatars: boolean;
  exportImages: boolean;
  exportAudio: boolean;
  agentId: string;
  locationId: string;
  renderLimit: number;
  startEventId: string;
  endEventId: string;
};

export type EventDeleteState = {
  undo_available: boolean;
  undo_count: number;
  undo_limit: number;
  latest_batch?: {
    batch_id?: string | null;
    deleted_at?: string | null;
    event_count: number;
  } | null;
};

export type AgentArchiveFieldOptions = {
  names: boolean;
  imagePrompts: boolean;
  prompts: boolean;
  appearances: boolean;
  avatars: boolean;
  standingImages: boolean;
  collectivePrompt: boolean;
  providerModels: boolean;
  toolModes: boolean;
  agentToolsets: boolean;
  traits: boolean;
  knowledge: boolean;
  narrator: boolean;
  imageGeneration: boolean;
  babyModels: boolean;
  providers: boolean;
  tts: boolean;
  secrets: boolean;
};

export type LlmGenerationSettings = {
  stream: boolean;
  temperature: number;
  top_p: number;
  max_tokens: number;
  presence_penalty: number;
  frequency_penalty: number;
};

export type ProviderDraft = {
  providerId: string;
  name: string;
  baseUrl: string;
  apiKey: string;
  retryCount: number;
  retryIntervalMs: number;
  requestTimeoutMs: number;
  rpm: number;
  models: string[];
};

export type NarratorConfigDraft = {
  enabled: boolean;
  providerId: string;
  modelName: string;
  systemPrompt: string;
  autoFrequency: "low" | "normal" | "high";
};

export type BabyModelDraft = {
  providerId: string;
  modelName: string;
};

export type TtsConfigDraft = {
  enabled: boolean;
  provider: string;
  mode: "gptsovits" | "openai" | "mimo" | "qwen_dashscope";
  baseUrl: string;
  endpointPath: string;
  apiKey: string;
  model: string;
  voice: string;
  responseFormat: string;
  languageType: string;
  instructions: string;
  refAudioPath: string;
  promptText: string;
  promptLang: string;
  textLang: string;
  textSplitMethod: string;
  batchSize: number;
};

export type WerewolfRole = "villager" | "werewolf" | "seer" | "coroner" | "guard";

export type WerewolfRoleAssignmentDraft = {
  mode: "auto" | "counts" | "manual";
  counts: Record<WerewolfRole, number>;
  manualRoles: WerewolfRole[];
};

export type AgentKnowledgeMode = "all" | "none" | "custom";

export type AgentKnowledgeTargetDraft = {
  knows: boolean;
  affection: number;
};

export type AgentConfigDraft = {
  providerId: string;
  modelName: string;
  toolContextMode: "dynamic" | "all";
  agentToolsetIds: string[];
  traitMode: "inherit" | "agent" | "random" | "player";
  systemPrompt: string;
  chosenName: string;
  imagePromptName: string;
  appearance: string;
  avatarDataUrl: string;
  standingImageDataUrl: string;
  traits: Record<string, number>;
  knowledgeMode: AgentKnowledgeMode;
  knownAgents: Record<string, AgentKnowledgeTargetDraft>;
  llmGeneration?: Partial<LlmGenerationSettings>;
  ttsConfig: TtsConfigDraft;
};

export type PromptSettings = {
  memory_limit: number;
  recent_event_limit: number;
  recent_self_event_limit: number;
  action_option_limit: number;
  dream_memory_limit: number;
  dream_important_limit: number;
  dream_background_limit: number;
};

export type LlmConcurrencySettings = {
  default_provider_limit: number;
  provider_limits: Record<string, number>;
  model_limits: Record<string, number>;
};

export type ImageGenerationProviderType = "novelai" | "comfyui" | "sdxl" | "anima";

export type ImageGenerationPromptStyle =
  | "auto"
  | "novelai"
  | "sdxl"
  | "flux"
  | "pony"
  | "anima"
  | "danbooru"
  | "illustrious"
  | "stable_diffusion"
  | "midjourney"
  | "dalle"
  | "custom";

export type ImageGenerationDisplayMode = "placeholder" | "wait";

export type ImageGenerationSettings = {
  enabled: boolean;
  source_mode: "narration" | "auto_summary";
  provider_type: ImageGenerationProviderType;
  prompt_style: ImageGenerationPromptStyle;
  custom_prompt_style: string;
  prompt_llm_mode: "narrator" | "custom";
  prompt_llm_provider_id: string;
  prompt_llm_provider_name: string;
  prompt_llm_base_url: string;
  prompt_llm_api_key?: string;
  prompt_llm_model_name: string;
  prompt_llm_system_prompt: string;
  prompt_llm_generation: Partial<LlmGenerationSettings>;
  prompt_llm_retry_count: number;
  prompt_llm_retry_interval_ms: number;
  prompt_llm_request_timeout_ms: number;
  prompt_llm_rpm: number;
  auto_frequency: "low" | "normal" | "high";
  display_mode: ImageGenerationDisplayMode;
  base_url: string;
  endpoint_path: string;
  api_key?: string;
  model_name: string;
  model_options: string[];
  image_retry_count: number;
  request_timeout_seconds: number;
  comfyui_timeout_seconds: number;
  use_agent_appearance: boolean;
  reference_avatar_images: boolean;
  reference_standing_images: boolean;
  style_prompt: string;
  negative_prompt: string;
  request_template_json: string;
  custom_headers_json: string;
  nai_action: "generate" | "img2img" | "infill";
  nai_image_format: "png" | "webp";
  nai_n_samples: number;
  nai_uc_preset: number;
  nai_quality_toggle: boolean;
  nai_params_version: number;
  nai_cfg_rescale: number;
  nai_sm: boolean;
  nai_sm_dyn: boolean;
  nai_dynamic_thresholding: boolean;
  nai_reference_strength: number;
  nai_reference_information_extracted: number;
  nai_strength: number;
  nai_noise: number;
  nai_add_original_image: boolean;
  nai_params_json: string;
  width: number;
  height: number;
  steps: number;
  cfg_scale: number;
  sampler: string;
  seed: number;
  workflow_json: string;
  agent_aliases: Record<string, string>;
};

export type RuntimeNarratorConfigPayload = {
  enabled?: boolean;
  provider_id?: string;
  provider_name?: string;
  base_url?: string;
  api_key?: string;
  clear_api_key?: boolean;
  model_name?: string;
  system_prompt?: string;
  auto_frequency?: "low" | "normal" | "high";
  retry_count?: number;
  retry_interval_ms?: number;
  request_timeout_ms?: number;
  rpm?: number;
};

export type WorldRuntimeSettingsPayload = {
  collective_core_prompt?: string;
  speed?: "slow" | "fast";
  narrator_frequency?: "low" | "normal" | "high";
  narrator_config?: RuntimeNarratorConfigPayload;
  prompt_settings?: Record<string, number>;
  agent_request_mode?: "serial" | "parallel";
  event_display_mode?: "batch" | "per_agent";
  llm_concurrency?: LlmConcurrencySettings;
  llm_generation?: Partial<LlmGenerationSettings>;
  image_generation?: Partial<ImageGenerationSettings>;
  disabled_tool_modules?: string[];
};

export type ToolAuditSnapshot = {
  world_time: number;
  time_label: string;
  menu: Array<{ tool_name: string; label: string }>;
  menu_tool_count: number;
  raw_tool_count: number;
  tool_context_mode: string;
};

export type AgentDetail = {
  world_id: string;
  tool_audit_history?: ToolAuditSnapshot[];
  identity: Record<string, string | boolean | null | Record<string, unknown>>;
  activity_status?: {
    state: string;
    label: string;
    is_sleeping: boolean;
    sleep_started_world_time?: number | null;
    sleep_started_label?: string | null;
    sleep_until_world_time?: number;
    sleep_until_label?: string;
    working_status?: Record<string, unknown>;
  };
  traits: Record<string, number>;
  dynamic_state: Record<string, number | string | null>;
  state_display_schema?: {
    dynamic_fields?: string[];
    worldpack?: Record<string, unknown>;
  };
  worldview_state?: {
    key: string;
    state: Record<string, unknown>;
    schema?: Record<string, unknown>;
  };
  v5_state: {
    wallet: Record<string, unknown>;
    work: Record<string, unknown>;
    family: Record<string, unknown>;
    family_display?: Record<string, unknown>;
    law: Record<string, unknown>;
    trauma: Record<string, unknown>;
    desires: Record<string, unknown>;
    morality: Record<string, unknown>;
    tool_learning: Record<string, unknown>;
  };
  v6_state?: {
    economy_profile: Record<string, unknown>;
    hedonic_state: Record<string, unknown>;
    housing: Record<string, unknown>;
    assets: Array<Record<string, unknown>>;
    liabilities: Array<Record<string, unknown>>;
    vehicles: Array<Record<string, unknown>>;
    creator_profile: Record<string, unknown>;
    broker_account: Record<string, unknown> | null;
    social_status: Record<string, unknown>;
    economy_ledger: Array<Record<string, unknown>>;
  };
  current_location: { location_id: string | null; name: string };
  inventory: Array<{ item_id: string; name: string; quantity: number }>;
  knowledge_summary: Array<Record<string, string | boolean | number | null>>;
  relationships: Array<Record<string, string | number | null>>;
  memory_display_limit?: number;
  memory_buckets?: Array<{
    key: string;
    label: string;
    count: number;
    items: Array<{ memory_id: number; type: string; content: string; importance: number; visibility?: string; archived?: boolean; world_time: number }>;
  }>;
  memories_recent: Array<{ memory_id: number; type: string; content: string; importance: number; visibility?: string; archived?: boolean; world_time: number }>;
  diaries_recent: Array<{ memory_id: number; type?: string; content: string; importance?: number; visibility?: string; archived?: boolean; world_time: number }>;
  recent_events: EventItem[];
};

export type Narration = {
  narrator_run_id: number;
  trigger_type?: string;
  summary_title: string;
  narration: string;
  tone: string;
  importance: number;
  created_world_time: number;
  error: string | null;
};

export type WorldMetrics = {
  population: number;
  alive: number;
  dead: number;
  births: number;
  children: number;
  pregnant: number;
  child_need_risk: number;
  hunger_risk: number;
  thirst_risk: number;
  employment_rate: number;
  burnout_rate: number;
  jailed: number;
  wanted: number;
  adult_intimacy_events: number;
  crime_attempts: number;
  crime_detected: number;
  jail_sentences: number;
  jail_escapes: number;
  jail_escape_failures: number;
  crime_attempt_rate: number;
  llm_invalid_tool_call_rate: number;
  avg_cash?: number;
  median_cash?: number;
  avg_net_worth?: number;
  gini_net_worth?: number;
  landlord_rate?: number;
  homeless_rate?: number;
  total_debt?: number;
  avg_debt_stress?: number;
  luxury_purchase_count?: number;
  premium_food_count?: number;
  rent_late_count?: number;
  eviction_count?: number;
  stock_account_count?: number;
  stock_trade_count?: number;
  creator_work_count?: number;
  creator_viral_count?: number;
};

export type ModelUsageEntry = {
  source_type: string;
  source_id: string;
  label: string;
  provider_id: string;
  provider_name: string;
  model_name: string;
  base_url: string;
  editable: boolean;
  implicit: boolean;
  warning: string;
  note: string;
  last_llm_phase: string;
  last_llm_world_time: number | null;
  last_llm_completed_at: string;
  last_llm_latency_ms: number | null;
  last_llm_token_usage: Record<string, unknown>;
  last_llm_error: string;
  llm_consecutive_failures: number;
};

export type ToolCatalogSummary = {
  count: number;
  v5_catalog_count: number;
  v6_catalog_count?: number;
  runtime_local_count: number;
};
