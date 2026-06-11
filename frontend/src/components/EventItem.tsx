import { ChevronDown, Loader2, Pencil, Play, RefreshCw, Save, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { MouseEvent } from "react";
import type { AgentListItem, EventItem as EventType } from "../api/types";
import { t, type UiLanguage } from "../i18n";
import { AgentAvatar } from "./AgentAvatar";
import { ModelPicker } from "./ModelPicker";

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

type DialogueLine = {
  speaker_agent_id?: string | null;
  target_agent_id?: string | null;
  text: string;
  tone?: string | null;
};

export function EventItem({
  event,
  agents,
  onRequestTts,
  selectionMode = false,
  selected = false,
  onSelectionChange,
  onDelete,
  onEditNarration,
  onCancelImageGeneration,
  onRerunImageGeneration,
  language = "zh"
}: {
  event: EventType;
  agents: AgentListItem[];
  onRequestTts?: (eventId: number) => Promise<string>;
  selectionMode?: boolean;
  selected?: boolean;
  onSelectionChange?: (eventId: number, selected: boolean) => void;
  onDelete?: (eventId: number) => Promise<void> | void;
  onEditNarration?: (eventId: number, text: string) => Promise<void> | void;
  onCancelImageGeneration?: (eventId: number) => Promise<void> | void;
  onRerunImageGeneration?: (eventId: number, payload: { prompt: string; negative_prompt?: string; overrides?: Record<string, unknown> }) => Promise<void> | void;
  language?: UiLanguage;
}) {
  const [open, setOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [loadingTts, setLoadingTts] = useState(false);
  const [editingNarration, setEditingNarration] = useState(false);
  const [narrationDraft, setNarrationDraft] = useState("");
  const [savingNarration, setSavingNarration] = useState(false);
  const [imageRerunDraft, setImageRerunDraft] = useState({
    providerType: "",
    baseUrl: "",
    endpointPath: "",
    prompt: "",
    negativePrompt: "",
    modelName: "",
    modelOptions: [] as string[],
    customHeadersJson: "",
    requestTemplateJson: "",
    workflowJson: "",
    imageRetryCount: "",
    requestTimeoutSeconds: "",
    comfyuiTimeoutSeconds: "",
    naiAction: "generate",
    naiImageFormat: "png",
    naiNSamples: "",
    naiUcPreset: "",
    naiQualityToggle: true,
    naiParamsVersion: "",
    naiCfgRescale: "",
    naiReferenceStrength: "",
    naiReferenceInformationExtracted: "",
    naiStrength: "",
    naiNoise: "",
    naiSmDyn: false,
    naiDynamicThresholding: false,
    naiAddOriginalImage: false,
    naiParamsJson: "",
    width: "",
    height: "",
    steps: "",
    cfgScale: "",
    sampler: "",
    seed: "",
  });
  const [rerunningImage, setRerunningImage] = useState(false);
  const actor = agents.find((agent) => agent.agent_id === event.actor_agent_id);
  const dialogueLines = dialogueLinesFromEvent(event);
  const isSpeechEvent = dialogueLines.length > 0;
  const primaryLine = dialogueLines[0];
  const primarySpeaker = primaryLine ? agents.find((agent) => agent.agent_id === primaryLine.speaker_agent_id) || actor : actor;
  const audioUrl =
    typeof event.payload?.tts_audio_data_url === "string"
      ? event.payload.tts_audio_data_url
      : typeof event.payload?.tts_audio_url === "string"
        ? event.payload.tts_audio_url
        : "";
  const canPlayTts = Boolean(dialogueLines.length === 1 && primarySpeaker?.tts_enabled && onRequestTts);
  const displayText = localizeEventText(event, actor?.display_name, language);
  const isNarrationEvent = event.event_type === "narration";
  const canEditNarration = isNarrationEvent && Boolean(onEditNarration);
  useEffect(() => {
    if (!editingNarration) setNarrationDraft(displayText);
  }, [displayText, editingNarration]);
  useEffect(() => {
    if (event.event_type !== "image_generation") return;
    const payload = event.payload || {};
    const status = typeof payload.status === "string" ? payload.status : "";
    if (status && status !== "pending" && status !== "running") {
      setRerunningImage(false);
    }
    const overrides = payload.image_config_overrides && typeof payload.image_config_overrides === "object"
      ? payload.image_config_overrides as Record<string, unknown>
      : {};
    setImageRerunDraft({
      providerType: String(overrides.provider_type ?? payload.provider_type ?? ""),
      baseUrl: String(overrides.base_url ?? payload.base_url ?? ""),
      endpointPath: String(overrides.endpoint_path ?? payload.endpoint_path ?? ""),
      prompt: String(payload.prompt ?? payload.manual_prompt ?? ""),
      negativePrompt: String(payload.negative_prompt ?? payload.manual_negative_prompt ?? ""),
      modelName: String(overrides.model_name ?? payload.model_name ?? ""),
      modelOptions: Array.isArray(overrides.model_options) ? overrides.model_options.map(String) : Array.isArray(payload.model_options) ? payload.model_options.map(String) : [],
      customHeadersJson: String(overrides.custom_headers_json ?? payload.custom_headers_json ?? ""),
      requestTemplateJson: String(overrides.request_template_json ?? payload.request_template_json ?? ""),
      workflowJson: String(overrides.workflow_json ?? payload.workflow_json ?? ""),
      imageRetryCount: String(overrides.image_retry_count ?? payload.image_retry_count ?? ""),
      requestTimeoutSeconds: String(overrides.request_timeout_seconds ?? payload.request_timeout_seconds ?? ""),
      comfyuiTimeoutSeconds: String(overrides.comfyui_timeout_seconds ?? payload.comfyui_timeout_seconds ?? ""),
      naiAction: String(overrides.nai_action ?? payload.nai_action ?? "generate"),
      naiImageFormat: String(overrides.nai_image_format ?? payload.nai_image_format ?? "png"),
      naiNSamples: String(overrides.nai_n_samples ?? payload.nai_n_samples ?? ""),
      naiUcPreset: String(overrides.nai_uc_preset ?? payload.nai_uc_preset ?? ""),
      naiQualityToggle: Boolean(overrides.nai_quality_toggle ?? payload.nai_quality_toggle ?? true),
      naiParamsVersion: String(overrides.nai_params_version ?? payload.nai_params_version ?? ""),
      naiCfgRescale: String(overrides.nai_cfg_rescale ?? payload.nai_cfg_rescale ?? ""),
      naiReferenceStrength: String(overrides.nai_reference_strength ?? payload.nai_reference_strength ?? ""),
      naiReferenceInformationExtracted: String(overrides.nai_reference_information_extracted ?? payload.nai_reference_information_extracted ?? ""),
      naiStrength: String(overrides.nai_strength ?? payload.nai_strength ?? ""),
      naiNoise: String(overrides.nai_noise ?? payload.nai_noise ?? ""),
      naiSmDyn: Boolean(overrides.nai_sm_dyn ?? payload.nai_sm_dyn ?? false),
      naiDynamicThresholding: Boolean(overrides.nai_dynamic_thresholding ?? payload.nai_dynamic_thresholding ?? false),
      naiAddOriginalImage: Boolean(overrides.nai_add_original_image ?? payload.nai_add_original_image ?? false),
      naiParamsJson: String(overrides.nai_params_json ?? payload.nai_params_json ?? ""),
      width: String(overrides.width ?? payload.width ?? ""),
      height: String(overrides.height ?? payload.height ?? ""),
      steps: String(overrides.steps ?? payload.steps ?? ""),
      cfgScale: String(overrides.cfg_scale ?? payload.cfg_scale ?? ""),
      sampler: String(overrides.sampler ?? payload.sampler ?? ""),
      seed: String(overrides.seed ?? payload.seed ?? ""),
    });
  }, [event.event_id, event.event_type, event.payload]);
  const eventTime = (
    <span className={`event-time ${selectionMode ? "event-time-selectable" : ""}`}>
      {selectionMode && (
        <input
          type="checkbox"
          checked={selected}
          aria-label={t("选择事件", language)}
          onClick={(eventObject) => eventObject.stopPropagation()}
          onChange={(eventObject) => onSelectionChange?.(event.event_id, eventObject.target.checked)}
        />
      )}
      <span>{t(event.world_time_label, language)}</span>
    </span>
  );
  const detailActions = onDelete ? (
    <div className="event-detail-actions">
      <button
        type="button"
        className="event-delete-inline-button"
        onClick={(eventObject) => {
          eventObject.stopPropagation();
          onDelete(event.event_id);
        }}
      >
        <Trash2 size={14} /> {t("删除这条", language)}
      </button>
    </div>
  ) : null;
  const narrationEditor = canEditNarration ? (
    <div className="event-narration-editor">
      {editingNarration ? (
        <>
          <textarea value={narrationDraft} onChange={(eventObject) => setNarrationDraft(eventObject.target.value)} />
          <div className="event-detail-actions">
            <button
              type="button"
              className="event-save-inline-button"
              disabled={savingNarration || !narrationDraft.trim()}
              onClick={async (eventObject) => {
                eventObject.stopPropagation();
                if (!onEditNarration || !narrationDraft.trim()) return;
                setSavingNarration(true);
                try {
                  await onEditNarration(event.event_id, narrationDraft.trim());
                  setEditingNarration(false);
                } finally {
                  setSavingNarration(false);
                }
              }}
            >
              <Save size={14} /> {savingNarration ? t("保存中", language) : t("保存", language)}
            </button>
            <button
              type="button"
              className="event-delete-inline-button"
              disabled={savingNarration}
              onClick={(eventObject) => {
                eventObject.stopPropagation();
                setNarrationDraft(displayText);
                setEditingNarration(false);
              }}
            >
              <X size={14} /> {t("取消", language)}
            </button>
          </div>
        </>
      ) : (
        <div className="event-detail-actions">
          <button
            type="button"
            className="event-save-inline-button"
            onClick={(eventObject) => {
              eventObject.stopPropagation();
              setNarrationDraft(displayText);
              setEditingNarration(true);
            }}
          >
            <Pencil size={14} /> {t("编辑解说", language)}
          </button>
        </div>
      )}
    </div>
  ) : null;
  const locationMarker = event.location_color ? (
    <span
      className="location-marker"
      title={t(event.location_name || event.location_id || "未知地点", language)}
      style={{ backgroundColor: event.location_color }}
    />
  ) : <span className="location-marker empty" />;

  if (event.event_type === "image_generation") {
    const status = typeof event.payload?.status === "string" ? event.payload.status : "pending";
    const imageUrl =
      typeof event.payload?.image_data_url === "string"
        ? event.payload.image_data_url
        : typeof event.payload?.image_url === "string"
          ? event.payload.image_url
          : "";
    const error = typeof event.payload?.error === "string" ? event.payload.error : "";
    const title = typeof event.payload?.summary_title === "string" ? event.payload.summary_title : t("生图", language);
    const cancelable = (status === "pending" || status === "running") && Boolean(onCancelImageGeneration);
    const canRerun = Boolean(onRerunImageGeneration);
    const rerunBusy = rerunningImage && (status === "pending" || status === "running");
    const rerunProvider = imageRerunDraft.providerType || String(event.payload?.provider_type ?? "");
    const isNovelAiRerun = rerunProvider === "novelai";
    const isOpenAiRerun = rerunProvider === "sdxl" || rerunProvider === "anima";
    const showWorkflowJson = rerunProvider === "comfyui";
    const showRequestTemplate = isOpenAiRerun;
    const rerunResolutionValue = `${imageRerunDraft.width || 832}x${imageRerunDraft.height || 1216}`;
    const updateRerunResolution = (value: string) => {
      const [width, height] = value.split("x").map((item) => Number(item));
      if (Number.isFinite(width) && Number.isFinite(height)) {
        setImageRerunDraft((current) => ({ ...current, width: String(width), height: String(height) }));
      }
    };
    const submitRerun = async () => {
      if (!onRerunImageGeneration || !imageRerunDraft.prompt.trim()) return;
      const overrides: Record<string, unknown> = {};
      const textFields: Array<[keyof typeof imageRerunDraft, string]> = [
        ["providerType", "provider_type"],
        ["baseUrl", "base_url"],
        ["endpointPath", "endpoint_path"],
        ["modelName", "model_name"],
        ["sampler", "sampler"],
        ["customHeadersJson", "custom_headers_json"],
        ["requestTemplateJson", "request_template_json"],
        ["workflowJson", "workflow_json"],
        ["naiAction", "nai_action"],
        ["naiImageFormat", "nai_image_format"],
        ["naiParamsJson", "nai_params_json"],
      ];
      for (const [draftKey, payloadKey] of textFields) {
        const value = String(imageRerunDraft[draftKey] ?? "").trim();
        if (value) overrides[payloadKey] = value;
      }
      const numberFields: Array<[keyof typeof imageRerunDraft, string]> = [
        ["imageRetryCount", "image_retry_count"],
        ["requestTimeoutSeconds", "request_timeout_seconds"],
        ["comfyuiTimeoutSeconds", "comfyui_timeout_seconds"],
        ["width", "width"],
        ["height", "height"],
        ["steps", "steps"],
        ["cfgScale", "cfg_scale"],
        ["seed", "seed"],
        ["naiNSamples", "nai_n_samples"],
        ["naiUcPreset", "nai_uc_preset"],
        ["naiParamsVersion", "nai_params_version"],
        ["naiCfgRescale", "nai_cfg_rescale"],
        ["naiReferenceStrength", "nai_reference_strength"],
        ["naiReferenceInformationExtracted", "nai_reference_information_extracted"],
        ["naiStrength", "nai_strength"],
        ["naiNoise", "nai_noise"],
      ];
      for (const [draftKey, payloadKey] of numberFields) {
        const value = Number(imageRerunDraft[draftKey]);
        if (Number.isFinite(value)) overrides[payloadKey] = value;
      }
      overrides.nai_quality_toggle = imageRerunDraft.naiQualityToggle;
      overrides.nai_sm_dyn = imageRerunDraft.naiSmDyn;
      overrides.nai_dynamic_thresholding = imageRerunDraft.naiDynamicThresholding;
      overrides.nai_add_original_image = imageRerunDraft.naiAddOriginalImage;
      setRerunningImage(true);
      try {
        await onRerunImageGeneration(event.event_id, {
          prompt: imageRerunDraft.prompt.trim(),
          negative_prompt: imageRerunDraft.negativePrompt.trim(),
          overrides,
        });
        setOpen(false);
      } finally {
        setRerunningImage(false);
      }
    };
    return (
      <>
        <article className={`event-item image-event ${event.color_class}`}>
          <button className="event-main image-event-main" onClick={() => setOpen(!open)}>
            {eventTime}
            <span className="image-event-body">
              {imageUrl ? (
                <img
                  className="generated-event-image"
                  src={imageUrl}
                  alt={title}
                  title={t("点击放大", language)}
                  onClick={(eventObject) => {
                    eventObject.stopPropagation();
                    setPreviewOpen(true);
                  }}
                />
              ) : (
                <>
                  <span className="image-event-title">{title}</span>
                  <span className={`generated-image-placeholder ${status === "failed" ? "failed" : ""}`}>
                    {status === "failed"
                      ? t("图片生成失败", language)
                      : status === "canceled"
                        ? t("图片生成已中断", language)
                        : t("图片生成中", language)}
                  </span>
                  {cancelable && (
                    <button
                      type="button"
                      className="image-cancel-inline-button"
                      title={t("中断图片生成", language)}
                      onClick={(eventObject) => {
                        eventObject.stopPropagation();
                        onCancelImageGeneration?.(event.event_id);
                      }}
                    >
                      <X size={14} /> {t("中断", language)}
                    </button>
                  )}
                </>
              )}
              {error && <span className="image-event-error">{error}</span>}
            </span>
            {locationMarker}
            <ChevronDown size={15} className={open ? "rotated" : ""} />
          </button>
          {open && (
            <>
              {detailActions}
              <div className="image-rerun-editor">
                <div className="image-rerun-heading">
                  <strong>{t("重跑设置", language)}</strong>
                  <span>{t("修改提示词或模型参数后重跑当前图片", language)}</span>
                </div>
                <label>
                  <span>{t("正提示词", language)}</span>
                  <textarea
                    value={imageRerunDraft.prompt}
                    onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, prompt: eventObject.target.value }))}
                  />
                </label>
                <label>
                  <span>{t("负提示词", language)}</span>
                  <textarea
                    value={imageRerunDraft.negativePrompt}
                    onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, negativePrompt: eventObject.target.value }))}
                  />
                </label>
                <div className="image-rerun-grid">
                  <label>
                    <span>{t("请求方式", language)}</span>
                    <select value={imageRerunDraft.providerType} onChange={(eventObject) => {
                      const providerType = eventObject.target.value;
                      setImageRerunDraft((current) => providerType === "novelai"
                        ? {
                          ...current,
                          providerType,
                          modelName: current.modelName || "nai-diffusion-4-5-full",
                          sampler: current.sampler || "k_euler_ancestral",
                          width: current.width || "832",
                          height: current.height || "1216",
                          naiAction: current.naiAction || "generate",
                          naiImageFormat: current.naiImageFormat || "png",
                        }
                        : { ...current, providerType });
                    }}>
                      <option value="">{t("沿用当前", language)}</option>
                      <option value="novelai">NovelAI</option>
                      <option value="sdxl">OpenAI 兼容图片 API</option>
                      <option value="comfyui">ComfyUI workflow / API</option>
                    </select>
                  </label>
                  {!isNovelAiRerun && (
                    <label>
                      <span>Base URL</span>
                      <input
                        value={imageRerunDraft.baseUrl}
                        placeholder={showWorkflowJson ? "http://127.0.0.1:8188" : "https://example.com/v1"}
                        onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, baseUrl: eventObject.target.value }))}
                      />
                    </label>
                  )}
                  <label>
                    <span>{t("接口路径", language)}</span>
                    <input
                      value={imageRerunDraft.endpointPath}
                      placeholder={rerunProvider === "comfyui" ? "/api/generate 或留空走 workflow /prompt" : "/images/generations"}
                      onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, endpointPath: eventObject.target.value }))}
                    />
                  </label>
                  <label>
                    <span>{t("模型", language)}</span>
                    {isNovelAiRerun ? (
                      <select value={imageRerunDraft.modelName || "nai-diffusion-4-5-full"} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, modelName: eventObject.target.value }))}>
                        {NOVELAI_MODEL_OPTIONS.map((model) => <option key={model} value={model}>{model}</option>)}
                      </select>
                    ) : (
                      <ModelPicker
                        value={imageRerunDraft.modelName}
                        models={imageRerunDraft.modelOptions}
                        emptyLabel={t("不指定模型", language)}
                        manualPlaceholder={t("模型名，可留空", language)}
                        searchPlaceholder={t("搜索图片模型", language)}
                        onChange={(modelName) => setImageRerunDraft((current) => ({ ...current, modelName }))}
                      />
                    )}
                  </label>
                  {isNovelAiRerun ? (
                    <label>
                      <span>{t("尺寸", language)}</span>
                      <select value={NOVELAI_RESOLUTION_OPTIONS.some((option) => option.value === rerunResolutionValue) ? rerunResolutionValue : "832x1216"} onChange={(eventObject) => updateRerunResolution(eventObject.target.value)}>
                        {NOVELAI_RESOLUTION_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                      </select>
                    </label>
                  ) : (
                    <>
                      <label>
                        <span>{t("宽度", language)}</span>
                        <input type="number" min="256" max="2048" step="64" value={imageRerunDraft.width} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, width: eventObject.target.value }))} />
                      </label>
                      <label>
                        <span>{t("高度", language)}</span>
                        <input type="number" min="256" max="2048" step="64" value={imageRerunDraft.height} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, height: eventObject.target.value }))} />
                      </label>
                    </>
                  )}
                  <label>
                    <span>Steps</span>
                    <input type="number" min="1" max="150" value={imageRerunDraft.steps} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, steps: eventObject.target.value }))} />
                  </label>
                  <label>
                    <span>CFG</span>
                    <input type="number" min="0" max="30" step="0.1" value={imageRerunDraft.cfgScale} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, cfgScale: eventObject.target.value }))} />
                  </label>
                  <label>
                    <span>{t("采样器", language)}</span>
                    {isNovelAiRerun ? (
                      <select value={imageRerunDraft.sampler || "k_euler_ancestral"} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, sampler: eventObject.target.value }))}>
                        {NOVELAI_SAMPLER_OPTIONS.map((sampler) => <option key={sampler} value={sampler}>{sampler}</option>)}
                      </select>
                    ) : (
                      <input value={imageRerunDraft.sampler} placeholder={t("可选", language)} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, sampler: eventObject.target.value }))} />
                    )}
                  </label>
                  <label>
                    <span>Seed</span>
                    <input type="number" min="-1" value={imageRerunDraft.seed} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, seed: eventObject.target.value }))} />
                  </label>
                  <label>
                    <span>{t("失败重试次数", language)}</span>
                    <input type="number" min="0" max="100" value={imageRerunDraft.imageRetryCount} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, imageRetryCount: eventObject.target.value }))} />
                  </label>
                  <label>
                    <span>{t("请求超时秒", language)}</span>
                    <input type="number" min="0" max="86400" value={imageRerunDraft.requestTimeoutSeconds} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, requestTimeoutSeconds: eventObject.target.value }))} />
                  </label>
                  {showWorkflowJson && (
                    <label>
                      <span>{t("ComfyUI 等待秒", language)}</span>
                      <input type="number" min="0" max="86400" value={imageRerunDraft.comfyuiTimeoutSeconds} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, comfyuiTimeoutSeconds: eventObject.target.value }))} />
                    </label>
                  )}
                  {isNovelAiRerun && (
                    <>
                      <label>
                        <span>NAI Action</span>
                        <select value={imageRerunDraft.naiAction} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, naiAction: eventObject.target.value }))}>
                          <option value="generate">generate</option>
                          <option value="img2img">img2img</option>
                          <option value="infill">infill</option>
                        </select>
                      </label>
                      <label>
                        <span>NAI Format</span>
                        <select value={imageRerunDraft.naiImageFormat} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, naiImageFormat: eventObject.target.value }))}>
                          <option value="png">png</option>
                          <option value="webp">webp</option>
                        </select>
                      </label>
                      <label>
                        <span>NAI samples</span>
                        <input type="number" min="1" max="4" value={imageRerunDraft.naiNSamples} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, naiNSamples: eventObject.target.value }))} />
                      </label>
                      <label>
                        <span>ucPreset</span>
                        <input type="number" min="0" max="10" value={imageRerunDraft.naiUcPreset} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, naiUcPreset: eventObject.target.value }))} />
                      </label>
                      <label>
                        <span>cfg_rescale</span>
                        <input type="number" min="0" max="20" step="0.1" value={imageRerunDraft.naiCfgRescale} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, naiCfgRescale: eventObject.target.value }))} />
                      </label>
                      <label>
                        <span>params_version</span>
                        <input type="number" min="1" max="10" value={imageRerunDraft.naiParamsVersion} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, naiParamsVersion: eventObject.target.value }))} />
                      </label>
                      <label>
                        <span>参考强度</span>
                        <input type="number" min="0" max="1" step="0.05" value={imageRerunDraft.naiReferenceStrength} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, naiReferenceStrength: eventObject.target.value }))} />
                      </label>
                      <label>
                        <span>参考提取量</span>
                        <input type="number" min="0" max="1" step="0.05" value={imageRerunDraft.naiReferenceInformationExtracted} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, naiReferenceInformationExtracted: eventObject.target.value }))} />
                      </label>
                    </>
                  )}
                </div>
                {isNovelAiRerun && (
                  <>
                    <div className="image-rerun-grid">
                      <label>
                        <span>img2img strength</span>
                        <input type="number" min="0" max="1" step="0.05" value={imageRerunDraft.naiStrength} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, naiStrength: eventObject.target.value }))} />
                      </label>
                      <label>
                        <span>img2img noise</span>
                        <input type="number" min="0" max="1" step="0.05" value={imageRerunDraft.naiNoise} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, naiNoise: eventObject.target.value }))} />
                      </label>
                      <label className="toggle-inline">
                        <input type="checkbox" checked={imageRerunDraft.naiQualityToggle} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, naiQualityToggle: eventObject.target.checked }))} />
                        NAI qualityToggle
                      </label>
                      <label className="toggle-inline">
                        <input type="checkbox" checked={imageRerunDraft.naiSmDyn} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, naiSmDyn: eventObject.target.checked }))} />
                        sm_dyn
                      </label>
                      <label className="toggle-inline">
                        <input type="checkbox" checked={imageRerunDraft.naiDynamicThresholding} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, naiDynamicThresholding: eventObject.target.checked }))} />
                        dynamic_thresholding
                      </label>
                      <label className="toggle-inline">
                        <input type="checkbox" checked={imageRerunDraft.naiAddOriginalImage} onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, naiAddOriginalImage: eventObject.target.checked }))} />
                        add_original_image
                      </label>
                    </div>
                    <label>
                      <span>NAI parameters JSON</span>
                      <textarea
                        value={imageRerunDraft.naiParamsJson}
                        placeholder={'直接合并到 NovelAI parameters，例如 {"noise_schedule":"native","skip_cfg_above_sigma":19}。同名字段会覆盖上面的表单值。'}
                        onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, naiParamsJson: eventObject.target.value }))}
                      />
                    </label>
                  </>
                )}
                {showRequestTemplate && (
                  <label>
                    <span>{t("请求体模板 JSON", language)}</span>
                    <textarea
                      value={imageRerunDraft.requestTemplateJson}
                      placeholder={'例如 {"prompt":"{{prompt}}","negative_prompt":"{{negative_prompt}}","model":"{{model}}"}'}
                      onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, requestTemplateJson: eventObject.target.value }))}
                    />
                  </label>
                )}
                <label>
                  <span>{t("固定请求头 JSON", language)}</span>
                  <textarea
                    value={imageRerunDraft.customHeadersJson}
                    placeholder={'例如 {"x-correlation-id":"tlw-local-test"}。'}
                    onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, customHeadersJson: eventObject.target.value }))}
                  />
                </label>
                {showWorkflowJson && (
                  <label>
                    <span>ComfyUI workflow JSON</span>
                    <textarea
                      value={imageRerunDraft.workflowJson}
                      placeholder={"填 ComfyUI 导出的 API JSON；支持 {{prompt}}、{{negative_prompt}}、{{width}}、{{height}}、{{steps}}、{{cfg_scale}}。"}
                      onChange={(eventObject) => setImageRerunDraft((current) => ({ ...current, workflowJson: eventObject.target.value }))}
                    />
                  </label>
                )}
                <div className="event-detail-actions image-rerun-actions">
                  <button
                    type="button"
                    className="event-save-inline-button"
                    disabled={!canRerun || rerunBusy || !imageRerunDraft.prompt.trim()}
                    onClick={(eventObject) => {
                      eventObject.stopPropagation();
                      submitRerun();
                    }}
                  >
                    <RefreshCw size={14} className={rerunBusy ? "spin-icon" : ""} />
                    {rerunBusy ? t("重跑中", language) : t("按当前设置重跑", language)}
                  </button>
                </div>
              </div>
              <pre className="event-detail image-event-detail">
{JSON.stringify(safeEventDetails(event, displayText), null, 2)}
              </pre>
            </>
          )}
        </article>
        {previewOpen && imageUrl && (
          <div className="image-preview-backdrop" role="dialog" aria-modal="true" aria-label={title} onClick={() => setPreviewOpen(false)}>
            <button type="button" className="image-preview-close" onClick={() => setPreviewOpen(false)}>
              {t("关闭", language)}
            </button>
            <img className="image-preview-image" src={imageUrl} alt={title} onClick={(eventObject) => eventObject.stopPropagation()} />
          </div>
        )}
      </>
    );
  }

  if (isSpeechEvent) {
    const playTts = async (eventObject: MouseEvent) => {
      eventObject.stopPropagation();
      if (!onRequestTts) return;
      setLoadingTts(true);
      try {
        const nextUrl = audioUrl || await onRequestTts(event.event_id);
        if (nextUrl) await new Audio(nextUrl).play();
      } finally {
        setLoadingTts(false);
      }
    };
    return (
      <article className={`event-item dialogue-event ${event.color_class}`}>
        <button className="event-main dialogue-main" onClick={() => setOpen(!open)}>
          {eventTime}
          <span className="dialogue-stack">
            {dialogueLines.map((line, index) => {
              const speaker = agents.find((agent) => agent.agent_id === line.speaker_agent_id) || (index === 0 ? actor : undefined);
              const target = agents.find((agent) => agent.agent_id === line.target_agent_id);
              return (
                <span className="dialogue-bubble-row" key={`${event.event_id}-${index}`}>
                  <AgentAvatar agent={speaker} />
                  <span className="dialogue-body">
                    <span className="dialogue-route">
                      {speaker?.display_name ?? t("某位居民", language)}
                      {target ? ` → ${target.display_name}` : ""}
                    </span>
                    <span className="dialogue-speech">
                      {line.text}
                      {index === 0 && canPlayTts && (
                        <span className="tts-play-control" role="button" tabIndex={0} title={t("播放这句 TTS", language)} onClick={playTts}>
                          {loadingTts ? <Loader2 size={14} className="spinning" /> : <Play size={14} />}
                        </span>
                      )}
                    </span>
                  </span>
                </span>
              );
            })}
          </span>
          {locationMarker}
          <ChevronDown size={15} className={open ? "rotated" : ""} />
        </button>
        {open && (
          <>
            {detailActions}
            <pre className="event-detail dialogue-detail">
{JSON.stringify(safeEventDetails(event, displayText), null, 2)}
            </pre>
          </>
        )}
      </article>
    );
  }

  return (
    <article className={`event-item ${event.color_class}`}>
      <button className="event-main" onClick={() => setOpen(!open)}>
        {eventTime}
        <span className="event-text">{displayText}</span>
        {locationMarker}
        <ChevronDown size={15} className={open ? "rotated" : ""} />
      </button>
      {open && (
        <>
          {narrationEditor}
          {detailActions}
          <pre className="event-detail">
{JSON.stringify(safeEventDetails(event, displayText), null, 2)}
          </pre>
        </>
      )}
    </article>
  );
}

function dialogueLinesFromEvent(event: EventType): DialogueLine[] {
  const addressed = event.payload?.addressed_agent_ids;
  const isGroupAddress = Array.isArray(addressed) && addressed.length > 1;
  const rawLines = event.payload?.dialogue_lines;
  if (Array.isArray(rawLines)) {
    const parsed: DialogueLine[] = [];
    for (const line of rawLines) {
      if (!line || typeof line !== "object") continue;
      const record = line as Record<string, unknown>;
      const text = sanitizeSpeechText(firstText(record.text, record.speech));
      if (!text) continue;
      parsed.push({
        speaker_agent_id: typeof record.speaker_agent_id === "string" ? record.speaker_agent_id : event.actor_agent_id,
        target_agent_id: isGroupAddress ? null : (typeof record.target_agent_id === "string" ? record.target_agent_id : event.target_agent_id),
        tone: typeof record.tone === "string" ? record.tone : null,
        text
      });
    }
    return parsed;
  }
  const speech = sanitizeSpeechText(firstText(event.payload?.speech));
  if (speech && event.actor_agent_id) {
    return [{ speaker_agent_id: event.actor_agent_id, target_agent_id: isGroupAddress ? null : event.target_agent_id, text: speech, tone: typeof event.payload?.tone === "string" ? event.payload.tone : null }];
  }
  return fallbackDialogueLinesFromText(event);
}

function fallbackDialogueLinesFromText(_event: EventType): DialogueLine[] {
  // 新事件必须通过 payload.dialogue_lines / payload.speech 渲染成头像气泡。
  // 不再从 viewer_text / agent_visible_text 里提取台词，避免旁白承载角色发言。
  return [];
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value !== "string") continue;
    const text = value.trim();
    if (text) return text;
  }
  return "";
}

function humanizeEventText(text: string): string {
  if (!text) return "";
  const original = text.trim();
  let cleaned = original;

  cleaned = cleaned.replace(/^(.+?)\s+买了(.+?)。它没有改变基础饱腹规则，但带来了不同程度的享乐和消费期待。$/u, "$1买了$2。");
  cleaned = cleaned.replace(/^系统租客向\s+(.+?)\s+支付了\s+(.+?)\s+固定租金，没有产生任何对话或剧情互动。$/u, "系统租客向 $1 支付了 $2 租金。");
  cleaned = cleaned.replace(/^系统租客按固定合约向\s+(.+?)\s+支付\s+(.+?)\s+租金。$/u, "系统租客向 $1 支付了 $2 租金。");
  cleaned = cleaned.replace(/暂时没有回应，选择把注意力收回到自己身上。/gu, "没有接话，只是把目光移开，先顾着自己的事。");
  cleaned = cleaned.replace(/和对方一起走了一小段路，边走边慢慢说话。对方明确接受了请求，因此请求被完成。/gu, "并肩走了一小段路，边走边慢慢说话。");
  cleaned = cleaned.replace(/对方明确接受了请求，因此请求被完成。?/gu, "");
  cleaned = cleaned.replace(/这只是请求，正在等待对方接受或拒绝。?/gu, "");
  cleaned = cleaned.replace(/对方能听见这句话：『([^』]+)』/gu, "说话。");
  cleaned = cleaned.replace(/[：:]\s*[“『][^”』]{1,500}[”』]/gu, "。");
  cleaned = cleaned.replace(/(?:说|说道|回答|请求|求助)[^。！？!?“『]{0,24}[“『][^”』]{1,500}[”』]/gu, "说话");
  cleaned = cleaned.replace(/注意到了这个动作，有机会躲开、抗议或选择不躲。?/gu, "看见了，空气一下子绷紧。");
  cleaned = cleaned.replace(/；目标的主观理解:\s*/gu, "，心里更像是：");
  cleaned = cleaned.replace(/没有提前发现\/来不及阻止/gu, "没来得及反应");
  cleaned = cleaned.replace(/注意到了但没有成功阻止/gu, "察觉到了，却没能避开");
  cleaned = cleaned.replace(/注意到了并选择不躲开/gu, "看见了这个动作，没有躲开");
  cleaned = cleaned.replace(/没有先得到明确同意，就完成了一次拥抱/gu, "没等对方答应，就伸手抱了过去");
  cleaned = cleaned.replace(/没有先得到明确同意，就牵住了对方的手/gu, "没等对方答应，就牵住了对方的手");
  cleaned = cleaned.replace(/没有先得到明确同意，就直接介入帮助了对方/gu, "没等对方答应，就直接插手帮了忙");
  cleaned = cleaned.replace(/没有先得到明确同意，就把对方卷入了一段不自在的同行/gu, "没等对方答应，就把对方带进了一段不自在的同行");
  cleaned = cleaned.replace(/^(.+?)\s+没能执行\s+([a-z0-9_]+)\s*[:：]\s*(.+)$/iu, (_, name: string, toolName: string, reason: string) => {
    const action = TOOL_ACTION_LABELS[toolName] ?? "行动";
    return `${name}想${action}，但没有成功：${humanizeFailureReason(reason)}。`;
  });
  cleaned = cleaned.replace(/(.+?)\s+执行了\s*v\d+\s*目录工具「([^」]+)」/gu, "$1 $2");

  cleaned = stripMechanicalBackendLanguage(cleaned);
  cleaned = cleaned.replace(/它没有改变基础饱腹规则[^。！？!?]*[。！？!?]?/gu, "");
  cleaned = cleaned.replace(/没有产生任何对话或剧情互动[。！？!?]?/gu, "");
  cleaned = cleaned.replace(/\s+/g, " ").replace(/\s+([。！？!?])/gu, "$1").trim();

  if (cleaned) return cleaned;
  return containsMechanicalBackendLanguage(original) ? "有一次行动没有顺利完成。" : original;
}

const MECHANICAL_BACKEND_PATTERNS: RegExp[] = [
  /工具调用格式错误/iu,
  /当前尝试的工具/iu,
  /请重新选择/iu,
  /validation\.message/iu,
  /failure_reason_code/iu,
  /llm_feedback/iu,
  /state_delta/iu,
  /payload/iu,
  /后端/iu,
  /硬规则/iu,
  /基础饱腹规则/iu,
  /数值变化/iu,
  /机制词/iu,
  /抽象结果/iu,
  /effectengine/iu,
  /ruleengine/iu,
  /deprivation_pain/iu,
  /sickness_risk/iu,
  /当前生命状态不能执行这个行为/iu,
  /这个行动需要第二行/iu,
  /这个行动需要台词/iu,
  /参数完整且符合/iu,
  /工具失败/iu,
  /missing_visible_ref/iu,
  /missing_location/iu,
  /missing_known_name/iu,
  /missing_speech/iu,
  /missing_text/iu,
  /target_not_visible/iu,
  /private_room_blocked/iu,
  /tool_name/iu,
  /reason_code/iu,
  /当前工具可能不足/iu,
  /隐藏候选/iu,
  /候选工具/iu,
  /解释过滤原因/iu,
  /向系统申请/iu,
  /agent_requested_more_candidates/iu
];

function containsMechanicalBackendLanguage(text: string): boolean {
  return MECHANICAL_BACKEND_PATTERNS.some((pattern) => pattern.test(text));
}

function stripMechanicalBackendLanguage(text: string): string {
  let cleaned = text;
  cleaned = cleaned.replace(/工具调用格式错误[:：]?/giu, "");
  cleaned = cleaned.replace(/当前尝试的工具是\s*[a-z0-9_]+[。.]?/giu, "");
  cleaned = cleaned.replace(/请重新选择[^。！？!?]*[。！？!?]?/giu, "");
  cleaned = cleaned.replace(/([^。！？!?]*?(后端|硬规则|payload|state_delta|failure_reason_code|failure_reason|reason_code|tool_name|llm_feedback|missing_visible_ref|missing_location|missing_known_name|missing_speech|missing_text|target_not_visible|private_room_blocked|当前工具可能不足|隐藏候选|候选工具|解释过滤原因|向系统申请|agent_requested_more_candidates|基础饱腹规则|数值变化|机制词|抽象结果|thirst|mood|sickness_risk|curiosity|消费期待|享乐阈值|deprivation_pain|EffectEngine|RuleEngine|validation\.message)[^。！？!?]*[。！？!?]?)/giu, "");
  return cleaned;
}


function hideBackendMechanicalText(text: string): string {
  if (!text) return "";
  return stripMechanicalBackendLanguage(text)
    .replace(/参数完整且符合当前地点\/目标的工具/giu, "合适的做法")
    .replace(/这是别人的私人小屋，不能直接移动进去。可以敲门请求进入；如果对方授权过你使用，也可以正常进入；也可以选择入室盗窃\/抢劫并承担后果。?/giu, "入口不对外开放，没能直接进去")
    .replace(/\s+/g, " ")
    .trim();
}

function sanitizeSpeechText(text: string): string {
  const cleaned = text.trim();
  if (!cleaned) return "";
  return containsMechanicalBackendLanguage(cleaned) ? "" : cleaned;
}

function safeEventDetails(event: EventType, displayText: string): Record<string, unknown> {
  return {
    event_id: event.event_id,
    type: event.event_type,
    importance: event.importance,
    text: displayText || "有一次行动被记录。"
  };
}

const TOOL_ACTION_LABELS: Record<string, string> = {
  drink_water: "喝水",
  drink_bottled_water: "喝水",
  eat_food: "吃饭",
  eat_portable_food: "吃东西",
  sleep: "睡觉",
  return_home: "回家",
  move_to_location: "移动",
  wash: "洗漱",
  buy_portable_food: "买食物",
  buy_bottled_water: "取水"
};

function humanizeFailureReason(reason: string): string {
  const cleaned = stripMechanicalBackendLanguage(reason)
    .replace(/这是别人的私人小屋，不能直接移动进去。可以敲门请求进入；如果对方授权过你使用，也可以正常进入；也可以选择入室盗窃\/抢劫并承担后果。?/gu, "入口不对外开放，没能直接进去")
    .replace(/当前生命状态不能执行这个行为。?/gu, "现在的身体状态撑不住这个动作")
    .replace(/工具失败。?/gu, "行动没有完成")
    .replace(/。$/u, "")
    .trim();
  return cleaned || "行动没有完成";
}



function localizeEventText(event: EventType, actorName: string | undefined, language: UiLanguage): string {
  const translated = t(humanizeEventText(event.viewer_text), language);
  if (language !== "en" || !containsCjk(translated)) return translated;
  return englishEventFallback(event, actorName);
}

function containsCjk(text: string): boolean {
  return /[\u3400-\u9fff]/u.test(text);
}

function englishEventFallback(event: EventType, actorName: string | undefined): string {
  const actor = actorName || "A resident";
  const location = typeof event.location_name === "string" && event.location_name.trim() ? t(event.location_name, "en") : "";
  const where = location ? ` at ${location}` : "";
  switch (event.event_type) {
    case "look":
      return `${actor} looked around${where}.`;
    case "observe":
      return `${actor} observed someone nearby${where}.`;
    case "self_status":
      return `${actor} checked their own condition.`;
    case "move":
      return `${actor} moved to another location.`;
    case "sleep":
    case "wake":
      return `${actor} rested or woke up.`;
    case "dream":
      return `${actor} dreamed and processed recent memories.`;
    case "dialogue":
      return `${actor} spoke.`;
    case "work":
    case "work_break":
      return `${actor} dealt with work or fatigue.`;
    case "supplies":
    case "supply":
    case "eat":
    case "drink":
      return `${actor} handled basic supplies.`;
    case "relationship":
    case "romance":
    case "boundary":
      return `${actor} dealt with a relationship matter.`;
    case "tool_failed":
      return `${actor} tried something, but it did not work.`;
    case "narration":
      return "The narrator recorded a scene.";
    default:
      return `${actor} did something${where}.`;
  }
}
