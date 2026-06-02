import { Download, Plus, RefreshCw, Trash2, Upload } from "lucide-react";
import { useState } from "react";
import type { AgentArchiveFieldOptions, AgentConfigDraft, BabyModelDraft, NarratorConfigDraft, ProviderDraft, TtsConfigDraft, World } from "../api/types";
import { t } from "../i18n";
import { FileDropZone } from "./FileDropZone";

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
  onNarratorConfigChange: (config: NarratorConfigDraft) => void;
  onBabyModelConfigsChange: (configs: BabyModelDraft[]) => void;
  onAgentConfigsChange: (configs: AgentConfigDraft[]) => void;
  onPullModels: (providerId: string) => void;
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
  const [bulkProviderId, setBulkProviderId] = useState("");
  const [bulkModelName, setBulkModelName] = useState("");
  const [bulkToolContextMode, setBulkToolContextMode] = useState<"dynamic" | "all">("dynamic");
  const [bulkTraitMode, setBulkTraitMode] = useState<AgentConfigDraft["traitMode"]>("inherit");
  const [reuseWorldId, setReuseWorldId] = useState("");
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
    ttsConfig: defaultTtsConfig()
  });
  const normalizedAgentConfigs = Array.from({ length: safeAgentCount }, (_, index) => {
    const fallback = fallbackAgentConfig();
    const config = agentConfigs[index];
    return config ? { ...fallback, ...config, traitMode: normalizeAgentTraitMode(config.traitMode), agentToolsetIds: Array.isArray(config.agentToolsetIds) ? config.agentToolsetIds : fallback.agentToolsetIds, traits: { ...fallback.traits, ...(config.traits ?? {}) }, ttsConfig: normalizeTtsConfig(config.ttsConfig) } : fallback;
  });
  const normalizedBabyConfigs = babyModelConfigs.map((config) => ({
    providerId: config.providerId || fallbackProviderId,
    modelName: config.modelName || ""
  }));
  const updateProvider = (providerId: string, patch: Partial<ProviderDraft>) => {
    onProvidersChange(providers.map((provider) => provider.providerId === providerId ? { ...provider, ...patch } : provider));
  };
  const addProvider = () => {
    const next = `${Date.now()}`;
    onProvidersChange([...providers, { providerId: next, name: "新提供商", baseUrl: "", apiKey: "", retryCount: 2, retryIntervalMs: 1500, rpm: 0, models: [] }]);
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
  const effectiveReuseWorldId = reusableWorlds.some((item) => item.world_id === reuseWorldId) ? reuseWorldId : (reusableWorlds[0]?.world_id ?? "");
  const effectiveReuseWorld = reusableWorlds.find((item) => item.world_id === effectiveReuseWorldId);
  const effectiveReuseWorldTitle = effectiveReuseWorld
    ? `复用历史配置: ${effectiveReuseWorld.save_name || effectiveReuseWorld.name || "未命名存档"} · 世界名 ${effectiveReuseWorld.name || "未命名世界"} · ${effectiveReuseWorld.world_time_label || "无时间"}`
    : "暂无可复用的历史存档";
  const applyBulkModel = () => {
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
  const expertMode = setupMode === "expert";
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
                    <label title={text("每分钟请求上限。0 表示不按 RPM 限速，只使用并发限制。", "Requests per minute limit. 0 means no RPM throttling, only concurrency limits.")}>
                      RPM
                      <input type="number" min="0" max="100000" value={provider.rpm} onChange={(event) => updateProvider(provider.providerId, { rpm: Number(event.target.value) })} />
                    </label>
                  </div>
                )}
                <div className="provider-actions">
                  <button type="button" onClick={() => onPullModels(provider.providerId)} disabled={pullingProviderId === provider.providerId}>
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
              <li>{text("玩过的存档在右侧“本地游玩记录”里，双击或点开即可继续。", "Saved games are listed in Local play records on the right. Double-click or open one to continue.")}</li>
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
                  {providers.map((item) => <option key={item.providerId} value={item.providerId}>{item.name}</option>)}
                </select>
              </label>
              <label>
                模型
                <select
                  disabled={!narratorConfig.enabled}
                  value={narratorConfig.modelName}
                  onChange={(event) => onNarratorConfigChange({ ...narratorConfig, modelName: event.target.value })}
                >
                  <option value="">默认 pro 解说</option>
                  {(narratorProvider?.models ?? []).map((model) => <option key={model} value={model}>{model}</option>)}
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
                        <select value={config.providerId} onChange={(event) => updateBabyModel(index, { providerId: event.target.value, modelName: "" })}>
                          {providers.map((item) => <option key={item.providerId} value={item.providerId}>{item.name}</option>)}
                        </select>
                      </label>
                      <label>
                        模型
                        <select value={config.modelName} onChange={(event) => updateBabyModel(index, { modelName: event.target.value })}>
                          <option value="">不指定</option>
                          {(provider?.models ?? []).map((model) => <option key={model} value={model}>{model}</option>)}
                        </select>
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
      <section>
        <h2>Agent 模型与身份</h2>
        <div className="bulk-model-row">
          <strong>{text("一键配置模型", "One-click model setup")} {!expertMode && <em className="beginner-marker marker-model">{text("紫色: 给全部居民选模型", "Purple: choose model for all residents")}</em>}</strong>
          <label>
            <span>提供商</span>
            {!expertMode && <em className="beginner-marker marker-model">{text("紫色: 选刚才填写的提供商", "Purple: choose the provider above")}</em>}
            <select value={effectiveBulkProviderId} onChange={(event) => {
              setBulkProviderId(event.target.value);
              setBulkModelName("");
            }}>
              {providers.map((item) => <option key={item.providerId} value={item.providerId}>{item.name}</option>)}
            </select>
          </label>
          <label>
            <span>模型</span>
            {!expertMode && <em className="beginner-marker marker-model">{text("紫色: 推荐便宜模型", "Purple: cheap model recommended")}</em>}
            <select value={bulkModelName} onChange={(event) => setBulkModelName(event.target.value)}>
              <option value="">默认混用</option>
              {(bulkProvider?.models ?? []).map((model) => <option key={model} value={model}>{model}</option>)}
            </select>
          </label>
          <button type="button" onClick={applyBulkModel} title={text("紫色步骤: 把这个提供商和模型应用到所有居民。", "Purple step: apply this provider and model to every resident.")}>{text("应用到全部", "Apply to all")}</button>
        </div>
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
                  <select value={config.providerId} onChange={(event) => updateAgent(index, { providerId: event.target.value, modelName: "" })}>
                    {providers.map((item) => <option key={item.providerId} value={item.providerId}>{item.name}</option>)}
                  </select>
                </label>}
                {expertMode && <label>
                  模型
                  <select value={config.modelName} onChange={(event) => updateAgent(index, { modelName: event.target.value })}>
                    <option value="">默认混用</option>
                    {(provider?.models ?? []).map((model) => <option key={model} value={model}>{model}</option>)}
                  </select>
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
