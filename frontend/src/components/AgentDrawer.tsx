import { useEffect, useMemo, useState } from "react";
import type { AgentDetail, ProviderDraft, TtsConfigDraft } from "../api/types";
import { FileDropZone } from "./FileDropZone";

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

const DESIRE_LABELS: Record<string, string> = {
  joy: "快乐",
  boredom: "无聊",
  loneliness: "孤独",
  romance_need: "恋爱需求",
  survival_pressure: "生存压力"
};

type AgentLlmUpdate = {
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
  rpm?: number;
};

type AgentProfileUpdate = {
  avatar_hint?: Record<string, unknown>;
  tts_config?: Record<string, unknown>;
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
  const [llmDraft, setLlmDraft] = useState<{ modelName: string; baseUrl: string; apiKey: string; customSystemPrompt: string; toolContextMode: "dynamic" | "all"; agentToolsetIds: string[]; retryCount: number; retryIntervalMs: number; rpm: number }>({ modelName: "", baseUrl: "", apiKey: "", customSystemPrompt: "", toolContextMode: "dynamic", agentToolsetIds: [], retryCount: 2, retryIntervalMs: 1500, rpm: 0 });
  const [ttsDraft, setTtsDraft] = useState<TtsConfigDraft>(() => defaultTtsConfig());
  const provider = useMemo(
    () => providers.find((item) => item.providerId === selectedProviderId) ?? providers[0],
    [providers, selectedProviderId]
  );

  useEffect(() => {
    if (!detail) return;
    const identity = detail.identity;
    const currentProvider = providers.find((item) => item.name === identity.model_provider_name || item.providerId === identity.model_provider_name) ?? providers[0];
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
      rpm: Number(identity.llm_rpm ?? currentProvider?.rpm ?? 0)
    });
    setTtsDraft({ ...normalizeTtsConfig(identity.tts_config), apiKey: "" });
  }, [
    detail?.identity?.agent_id,
    detail?.identity?.model_provider_name,
    detail?.identity?.model_name,
    detail?.identity?.llm_base_url,
    detail?.identity?.custom_system_prompt,
    detail?.identity?.tool_context_mode,
    detail?.identity?.llm_retry_count,
    detail?.identity?.llm_retry_interval_ms,
    detail?.identity?.llm_rpm,
    detail?.identity?.tts_config,
  ]);

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
  const modelOptions = llmDraft.modelName && !providerModels.includes(llmDraft.modelName)
    ? [llmDraft.modelName, ...providerModels]
    : providerModels;
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
      provider_name: provider?.name || selectedProviderId || undefined,
      base_url: llmDraft.baseUrl.trim() || undefined,
      model_name: llmDraft.modelName.trim() || undefined,
      custom_system_prompt: llmDraft.customSystemPrompt,
      tool_context_mode: llmDraft.toolContextMode,
      agent_toolset_ids: llmDraft.agentToolsetIds,
      retry_count: llmDraft.retryCount,
      retry_interval_ms: llmDraft.retryIntervalMs,
      rpm: llmDraft.rpm
    };
    if (typedKey) payload.api_key = typedKey;
    await onReplaceLlm(agentId, payload);
    setLlmDraft((current) => ({ ...current, apiKey: "" }));
  };
  return (
    <section className="panel agent-drawer">
      <h2>{String(identity.chosen_name)}</h2>
      <div className="drawer-tabs">
        <section>
          <h3>概览</h3>
          <div className="runtime-avatar-row">
            {((identity.avatar_hint as Record<string, unknown> | undefined)?.image_data_url) ? (
              <img src={String((identity.avatar_hint as Record<string, unknown>).image_data_url)} alt="" />
            ) : (
              <span>{String(identity.chosen_name ?? "?").slice(0, 1)}</span>
            )}
            <FileDropZone
              accept="image/*"
              className="avatar-drop-zone"
              onFile={(file) => uploadAvatar(file)}
              hint="可拖入图片"
            >
              更换头像
            </FileDropZone>
            <button type="button" disabled={!onUpdateProfile || !((identity.avatar_hint as Record<string, unknown> | undefined)?.image_data_url)} onClick={clearAvatar}>移除头像</button>
          </div>
          <p>{String(identity.appearance_full ?? "")}</p>
          <dl>
            <dt>性别身份</dt><dd>{String(identity.gender_identity ?? "未知")}</dd>
            <dt>年龄阶段</dt><dd>{String(identity.age_stage ?? "adult")}</dd>
            <dt>当前状态</dt><dd>{identity.lifecycle_state === "dead" ? `死亡${identity.death_cause ? `：${identity.death_cause}` : ""}` : detail.activity_status?.label ?? "清醒"}</dd>
            <dt>公开策略</dt><dd>{String(identity.intro_policy ?? "")}</dd>
            <dt>当前位置</dt><dd>{detail.current_location.name}</dd>
            <dt>生命周期</dt><dd>{String(identity.lifecycle_state ?? "")}</dd>
            <dt>目标</dt><dd>{String(identity.initial_goal ?? "")}</dd>
          </dl>
        </section>
        <section>
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
        </section>
        <section>
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
        </section>
        <section>
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
        </section>
        <section>
          <h3>人格</h3>
          <div className="trait-grid">
            {Object.entries(detail.traits).map(([key, value]) => (
              <div key={key} title={TRAIT_EFFECTS[key] ?? ""}><span>{TRAIT_LABELS[key] ?? key}</span><strong>{value}</strong><small>{TRAIT_EFFECTS[key] ?? ""}</small></div>
            ))}
          </div>
          <p>{String(identity.speaking_style ?? "")}</p>
        </section>
        <section>
          <h3>知识</h3>
          <div className="knowledge-list">
            {detail.knowledge_summary.map((item) => (
              <p key={String(item.target_agent_id)}>
                <strong>{String(item.target_real_name)}</strong>
                <span>{item.name_known ? `知道姓名: ${String(item.known_name)}` : `只记得外貌: ${String(item.appearance_snapshot ?? "")}`}</span>
              </p>
            ))}
          </div>
        </section>
        <section>
          <h3>关系</h3>
          {detail.relationships.map((rel) => (
            <p key={String(rel.target_agent_id)} className="rel-row">
              <strong>{String(rel.target_name)}</strong>
              <span>{String(rel.relationship_label)} · 熟悉{Math.round(Number(rel.familiarity))} 信任{Math.round(Number(rel.trust))} 好感{Math.round(Number(rel.affection))}</span>
            </p>
          ))}
        </section>
        <section>
          <h3>记忆/日记</h3>
          {[...detail.diaries_recent, ...detail.memories_recent].slice(0, 8).map((memory) => (
            <p key={memory.memory_id} className="memory-line">{memory.content}</p>
          ))}
        </section>
        <section>
          <h3>背包</h3>
          <p>钱包: {String(v5.wallet?.money ?? 0)}</p>
          {detail.inventory.length ? detail.inventory.map((item) => <p key={item.item_id}>{item.name} × {item.quantity}</p>) : <p className="muted">空</p>}
        </section>
        {showAgentEconomy && (
          <section>
            <h3>经济/住房</h3>
            <dl>
              <dt>现金</dt><dd>{String(economy.cash ?? v5.wallet?.money ?? 0)}</dd>
              <dt>净资产</dt><dd>{String(economy.net_worth ?? 0)}</dd>
              <dt>总债务</dt><dd>{String(economy.total_debt ?? 0)} · 日最低{String(economy.minimum_payment_daily ?? 0)}</dd>
              <dt>信用</dt><dd>{String(economy.credit_score ?? 0)} · 压力{String(economy.debt_stress ?? 0)}</dd>
              <dt>住房</dt><dd>{housingText}</dd>
              <dt>无家可归</dt><dd>{housing.homeless ? "是" : "否"}</dd>
              <dt>消费习惯</dt><dd>{consumptionText}</dd>
              <dt>资产</dt><dd>{v6?.assets?.length ?? 0} 件 · 车辆 {v6?.vehicles?.length ?? 0}</dd>
              <dt>股票</dt><dd>{broker ? `权益 ${String(broker.equity ?? 0)} · 浮盈亏 ${String(broker.unrealized_pnl ?? 0)}` : "未开户"}</dd>
            </dl>
          </section>
        )}
        {(showWork || showLaw || showFamily) && (
          <section>
            <h3>工作/法律/家庭</h3>
            <dl>
              {showWork && <><dt>工作</dt><dd>{String(v5.work?.job ?? "无")} · 疲劳{String(v5.work?.fatigue ?? 0)}</dd></>}
              {showLaw && <><dt>法律</dt><dd>{v5.law?.jailed ? `在押，剩余${String(v5.law?.jail_days_remaining ?? 0)}天` : "自由"}</dd></>}
              {showFamily && <><dt>家庭</dt><dd>{familySummary(familyDisplay, partnerDisplay, childrenDisplay)}</dd></>}
              <dt>创伤</dt><dd>强度 {String(v5.trauma?.emotional_intensity ?? 0)}</dd>
            </dl>
          </section>
        )}
        <section>
          <h3>LLM 配置</h3>
          <dl>
            <dt>当前提供商</dt><dd>{String(identity.model_provider_name ?? "默认")}</dd>
            <dt>当前模型</dt><dd>{String(identity.model_name ?? "默认")}</dd>
            <dt>工具上下文</dt><dd>{identity.tool_context_mode === "all" ? "固定工具集" : "动态工具"}</dd>
            <dt>失败次数</dt><dd>{failureCount ? `${failureCount} 次` : "正常"}</dd>
          </dl>
          {lastLlmError && <p className="llm-error-line">{lastLlmError}</p>}
          <div className="agent-llm-form">
            <label>
              提供商
              <select
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
                    rpm: next?.rpm ?? current.rpm
                  }));
                }}
              >
                {providers.length ? providers.map((item) => <option key={item.providerId} value={item.providerId}>{item.name}</option>) : <option value="">手动配置</option>}
              </select>
            </label>
            <button type="button" disabled={!provider || pullingProviderId === provider?.providerId} onClick={pullCurrentProviderModels}>
              {pullingProviderId === provider?.providerId ? "拉取中..." : "拉取模型"}
            </button>
            <label>
              模型
              {modelOptions.length ? (
                <select value={llmDraft.modelName} onChange={(event) => setLlmDraft({ ...llmDraft, modelName: event.target.value })}>
                  <option value="">选择模型</option>
                  {modelOptions.map((model) => <option key={model} value={model}>{model}</option>)}
                </select>
              ) : (
                <input
                  value={llmDraft.modelName}
                  placeholder="手动输入模型名"
                  onChange={(event) => setLlmDraft({ ...llmDraft, modelName: event.target.value })}
                />
              )}
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
            <label>
              RPM
              <input type="number" min="0" max="100000" value={llmDraft.rpm} title="0 表示不限 RPM，只受模型并发限制。" onChange={(event) => setLlmDraft({ ...llmDraft, rpm: Number(event.target.value) })} />
            </label>
            <label className="agent-llm-prompt">
              单独系统提示词
              <textarea value={llmDraft.customSystemPrompt} onChange={(event) => setLlmDraft({ ...llmDraft, customSystemPrompt: event.target.value })} />
            </label>
            <button type="button" className="agent-llm-save" disabled={!onReplaceLlm || replacingLlm} onClick={saveLlm}>
              {replacingLlm ? "保存中..." : "保存 LLM"}
            </button>
          </div>
        </section>
        <section>
          <h3>Agent TTS 接口</h3>
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
        </section>
      </div>
    </section>
  );
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
