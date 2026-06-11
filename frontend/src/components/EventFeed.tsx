import { CheckSquare, Download, Play, RefreshCw, Square, Trash2, Undo2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { AgentListItem, EventDeleteState, EventFilters, EventItem as EventType, WorldLocation } from "../api/types";
import { t, type UiLanguage } from "../i18n";
import { EventItem } from "./EventItem";

export function EventFeed({
  agents,
  events,
  filters,
  locations,
  onFiltersChange,
  onRefresh,
  onRequestTts,
  eventDeleteState,
  onDeleteEvents,
  onUndoDelete,
  onUpdateDeleteUndoLimit,
  onEditNarration,
  onCancelImageGeneration,
  onRerunImageGeneration,
  onPullImageModels,
  waitState,
  exportUrl,
  language = "zh"
}: {
  agents: AgentListItem[];
  events: EventType[];
  filters: EventFilters;
  locations?: WorldLocation[];
  onFiltersChange: (filters: EventFilters) => void;
  onRefresh: () => void;
  onRequestTts?: (eventId: number) => Promise<string>;
  eventDeleteState?: EventDeleteState;
  onDeleteEvents?: (eventIds: number[]) => Promise<void> | void;
  onUndoDelete?: () => Promise<void> | void;
  onUpdateDeleteUndoLimit?: (limit: number) => Promise<void> | void;
  onEditNarration?: (eventId: number, text: string) => Promise<void> | void;
  onCancelImageGeneration?: (eventId: number) => Promise<void> | void;
  onRerunImageGeneration?: (eventId: number, payload: { prompt: string; negative_prompt?: string; overrides?: Record<string, unknown> }) => Promise<void> | void;
  onPullImageModels?: (payload: { baseUrl: string; apiKey?: string }) => Promise<string[] | void> | string[] | void;
  waitState?: { imageWaitCutoffEventId: number | null; waitingImageEventId: number | null };
  exportUrl: string;
  language?: UiLanguage;
}) {
  const [playingSequence, setPlayingSequence] = useState(false);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedEventIds, setSelectedEventIds] = useState<Set<number>>(new Set());
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(() => {
    if (typeof window === "undefined" || !window.matchMedia) return true;
    return window.matchMedia("(min-width: 901px) and (orientation: landscape)").matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const media = window.matchMedia("(min-width: 901px) and (orientation: landscape)");
    const sync = () => setFiltersOpen(media.matches);
    sync();
    media.addEventListener?.("change", sync);
    return () => media.removeEventListener?.("change", sync);
  }, []);

  const eventLocations = Array.from(
    new Map(events.filter((event) => event.location_id).map((event) => [event.location_id as string, event.location_name || event.location_id as string])).entries()
  );
  const locationOptions = locations?.length ? locations.map((location) => [location.location_id, location.name] as const) : eventLocations;
  const visibleEventIds = useMemo(() => events.map((event) => event.event_id), [events]);
  const allVisibleSelected = visibleEventIds.length > 0 && visibleEventIds.every((eventId) => selectedEventIds.has(eventId));
  const ttsEvents = useMemo(
    () => events.filter((event) => {
      const actor = agents.find((agent) => agent.agent_id === event.actor_agent_id);
      return Boolean((actor?.tts_enabled || typeof event.payload?.tts_audio_data_url === "string" || typeof event.payload?.tts_audio_url === "string") && speechFromEvent(event));
    }),
    [agents, events],
  );

  useEffect(() => {
    setSelectedEventIds((current) => {
      const visible = new Set(visibleEventIds);
      const next = new Set(Array.from(current).filter((eventId) => visible.has(eventId)));
      return next.size === current.size ? current : next;
    });
  }, [visibleEventIds]);

  const toggleSelectionMode = () => {
    setSelectionMode((current) => {
      if (current) setSelectedEventIds(new Set());
      return !current;
    });
  };

  const toggleSelectAllVisible = () => {
    setSelectedEventIds(allVisibleSelected ? new Set() : new Set(visibleEventIds));
  };

  const toggleEventSelected = (eventId: number, selected: boolean) => {
    setSelectedEventIds((current) => {
      const next = new Set(current);
      if (selected) next.add(eventId);
      else next.delete(eventId);
      return next;
    });
  };

  const deleteSelectedEvents = async () => {
    if (!onDeleteEvents || selectedEventIds.size === 0 || deleteBusy) return;
    const ids = Array.from(selectedEventIds);
    if (!window.confirm(t(`删除选中的 ${ids.length} 条事件？可以用“撤回删除”恢复最近删除。`, language))) return;
    setDeleteBusy(true);
    try {
      await onDeleteEvents(ids);
      setSelectedEventIds(new Set());
      setSelectionMode(false);
    } finally {
      setDeleteBusy(false);
    }
  };

  const deleteSingleEvent = async (eventId: number) => {
    if (!onDeleteEvents || deleteBusy) return;
    setDeleteBusy(true);
    try {
      await onDeleteEvents([eventId]);
      setSelectedEventIds((current) => {
        const next = new Set(current);
        next.delete(eventId);
        return next;
      });
    } finally {
      setDeleteBusy(false);
    }
  };

  const undoDelete = async () => {
    if (!onUndoDelete || !eventDeleteState?.undo_available || deleteBusy) return;
    setDeleteBusy(true);
    try {
      await onUndoDelete();
    } finally {
      setDeleteBusy(false);
    }
  };

  const playTtsSequence = async () => {
    if (!onRequestTts || playingSequence) return;
    setPlayingSequence(true);
    try {
      for (const event of ttsEvents) {
        const cached =
          typeof event.payload?.tts_audio_data_url === "string"
            ? event.payload.tts_audio_data_url
            : typeof event.payload?.tts_audio_url === "string"
              ? event.payload.tts_audio_url
              : "";
        const audioUrl = cached || await onRequestTts(event.event_id);
        if (audioUrl) await playAudio(audioUrl);
      }
    } finally {
      setPlayingSequence(false);
    }
  };

  return (
    <section className="panel event-feed-panel">
      <div className="panel-heading event-feed-heading">
        <div className="event-feed-title-row">
          <h2>{t("事件流", language)}</h2>
          <button type="button" className="icon-button" title={t("刷新事件流", language)} onClick={onRefresh}>
            <RefreshCw size={15} />
          </button>
        </div>
        <details className="event-filter-details" open={filtersOpen} onToggle={(event) => setFiltersOpen(event.currentTarget.open)}>
          <summary>
            <span>{t("筛选 / 导出", language)}</span>
            <span className="event-filter-summary-count">{events.length}</span>
          </summary>
          <div className="filters">
            <label>
              <span>{t("记录筛选", language)}</span>
              <select
                value={filters.minImportance}
                onChange={(event) => onFiltersChange({ ...filters, minImportance: Number(event.target.value) })}
              >
                <option value={0}>{t("全部记录", language)}</option>
                <option value={15}>{t("隐藏琐碎", language)}</option>
                <option value={45}>{t("显著变化", language)}</option>
                <option value={70}>{t("危急/死亡", language)}</option>
              </select>
            </label>
            <label>
              <input
                type="checkbox"
                checked={filters.dialogueOnly}
                onChange={(event) => onFiltersChange({ ...filters, dialogueOnly: event.target.checked })}
              />
              {t("对话", language)}
            </label>
            <label>
              <input
                type="checkbox"
                checked={filters.showNarrator}
                onChange={(event) => onFiltersChange({ ...filters, showNarrator: event.target.checked })}
              />
              {t("解说", language)}
            </label>
            <label>
              <input
                type="checkbox"
                checked={filters.exportAvatars}
                onChange={(event) => onFiltersChange({ ...filters, exportAvatars: event.target.checked })}
              />
              {t("导出头像", language)}
            </label>
            <label>
              <input
                type="checkbox"
                checked={filters.exportImages}
                onChange={(event) => onFiltersChange({ ...filters, exportImages: event.target.checked })}
              />
              {t("导出图片", language)}
            </label>
            <label>
              <input
                type="checkbox"
                checked={filters.exportAudio}
                onChange={(event) => onFiltersChange({ ...filters, exportAudio: event.target.checked })}
              />
              {t("导出音频", language)}
            </label>
            <select value={filters.agentId} onChange={(event) => onFiltersChange({ ...filters, agentId: event.target.value })}>
              <option value="">{t("全部居民", language)}</option>
              {agents.map((agent) => <option key={agent.agent_id} value={agent.agent_id}>{agent.display_name}</option>)}
            </select>
            <select value={filters.locationId} onChange={(event) => onFiltersChange({ ...filters, locationId: event.target.value })}>
              <option value="">{t("全部地点", language)}</option>
              {locationOptions.map(([locationId, name]) => <option key={locationId} value={locationId}>{t(name, language)}</option>)}
            </select>
            <label className="event-id-filter">
              <span>ID</span>
              <input
                type="number"
                min="1"
                placeholder={t("起", language)}
                value={filters.startEventId}
                onChange={(event) => onFiltersChange({ ...filters, startEventId: event.target.value })}
              />
              <input
                type="number"
                min="1"
                placeholder={t("止", language)}
                value={filters.endEventId}
                onChange={(event) => onFiltersChange({ ...filters, endEventId: event.target.value })}
              />
            </label>
            <label>
              <span>{t("最新渲染", language)}</span>
              <select
                value={filters.renderLimit}
                onChange={(event) => onFiltersChange({ ...filters, renderLimit: Number(event.target.value) })}
              >
                <option value={100}>100</option>
                <option value={200}>200</option>
                <option value={500}>500</option>
                <option value={1000}>1000</option>
                <option value={2000}>2000</option>
                <option value={5000}>5000</option>
                <option value={10000}>10000</option>
              </select>
            </label>
            {ttsEvents.length > 0 && onRequestTts && (
              <button type="button" className="event-export-button" disabled={playingSequence} onClick={playTtsSequence} title={t("按当前事件流从上到下播放已配置 TTS 的对话", language)}>
                <Play size={15} /> {playingSequence ? t("播放中", language) : t("顺序播放", language)}
              </button>
            )}
            {onDeleteEvents && (
              <button type="button" className={`event-export-button ${selectionMode ? "active" : ""}`} onClick={toggleSelectionMode}>
                {selectionMode ? <X size={15} /> : <CheckSquare size={15} />}
                {selectionMode ? t("取消选择", language) : t("批量选择", language)}
              </button>
            )}
            {selectionMode && (
              <>
                <button type="button" className="event-export-button" onClick={toggleSelectAllVisible} disabled={!visibleEventIds.length}>
                  {allVisibleSelected ? <Square size={15} /> : <CheckSquare size={15} />}
                  {allVisibleSelected ? t("清空选择", language) : t("全选当前", language)}
                </button>
                <button type="button" className="event-export-button event-delete-button" onClick={deleteSelectedEvents} disabled={!selectedEventIds.size || deleteBusy}>
                  <Trash2 size={15} /> {t("删除选中", language)} {selectedEventIds.size ? selectedEventIds.size : ""}
                </button>
              </>
            )}
            {onUndoDelete && (
              <button type="button" className="event-export-button" disabled={!eventDeleteState?.undo_available || deleteBusy} onClick={undoDelete} title={t("恢复最近一次删除的事件批次", language)}>
                <Undo2 size={15} /> {t("撤回删除", language)}
                {eventDeleteState?.undo_count ? ` ${eventDeleteState.undo_count}` : ""}
              </button>
            )}
            {onUpdateDeleteUndoLimit && (
              <label className="event-undo-limit-filter">
                <span>{t("撤回保留", language)}</span>
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={eventDeleteState?.undo_limit ?? 5}
                  onChange={(event) => onUpdateDeleteUndoLimit(Number(event.target.value))}
                />
              </label>
            )}
            <a className="event-export-button" href={exportUrl} title={t("按当前筛选导出带浏览界面的 zip 归档", language)}>
              <Download size={15} /> {t("导出归档", language)}
            </a>
          </div>
        </details>
      </div>
      <div className="event-feed">
        {waitState?.waitingImageEventId ? (
          <div className="event-wait-banner">
            {t("事件流正在等待生图完成。后续事件仍在运行，图片完成或中断后会继续显示。", language)}
            <span>#{waitState.waitingImageEventId}</span>
          </div>
        ) : null}
        {events.length ? events.map((event) => (
          <EventItem
            key={event.event_id}
            event={event}
            agents={agents}
            onRequestTts={onRequestTts}
            selectionMode={selectionMode}
            selected={selectedEventIds.has(event.event_id)}
            onSelectionChange={toggleEventSelected}
            onDelete={onDeleteEvents ? deleteSingleEvent : undefined}
            onEditNarration={onEditNarration}
            onCancelImageGeneration={onCancelImageGeneration}
            onRerunImageGeneration={onRerunImageGeneration}
            onPullImageModels={onPullImageModels}
            language={language}
          />
        )) : <p className="empty-events">{t("暂无事件。启动世界后，如果模型正在思考，第一条行动事件会在本轮完成后出现。", language)}</p>}
      </div>
    </section>
  );
}

function speechFromEvent(event: EventType): string {
  const rawLines = event.payload?.dialogue_lines;
  if (Array.isArray(rawLines)) {
    for (const line of rawLines) {
      if (!line || typeof line !== "object") continue;
      const record = line as Record<string, unknown>;
      const value = typeof record.text === "string" ? record.text : typeof record.speech === "string" ? record.speech : "";
      if (value.trim() && !containsMechanicalBackendLanguage(value)) return value.trim();
    }
  }
  const value = event.payload?.speech;
  return typeof value === "string" && value.trim() && !containsMechanicalBackendLanguage(value) ? value.trim() : "";
}

function containsMechanicalBackendLanguage(text: string): boolean {
  return /工具调用格式错误|当前尝试的工具|请重新选择|failure_reason_code|llm_feedback|state_delta|payload|后端|硬规则|当前工具可能不足|隐藏候选|候选工具|解释过滤原因|向系统申请|agent_requested_more_candidates|基础饱腹规则|数值变化|机制词|抽象结果|EffectEngine|RuleEngine/iu.test(text);
}

function playAudio(audioUrl: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const audio = new Audio(audioUrl);
    audio.onended = () => resolve();
    audio.onerror = () => reject(new Error("audio playback failed"));
    audio.play().catch(reject);
  });
}
