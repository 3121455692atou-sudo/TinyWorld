import { Activity, ChevronDown, RefreshCw, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { AgentListItem, ModelUsageEntry, World } from "../api/types";
import type { UiLanguage } from "../i18n";

/** Latest step_progress / status push received over the world websocket. */
export type RuntimeProgress = {
  phase: string;
  completed: number | null;
  total: number | null;
  /** Client time (ms) the message arrived. */
  at: number;
  /** Client time (ms) the current round's planning started, when known. */
  roundStartedAt: number | null;
};

const ROUND_START_PHASES = new Set(["batch_start", "parallel_start", "batch_prepare", "parallel_prepare", "parallel_planning"]);
const WAITING_PHASES = new Set(["batch_start", "batch_prepare", "batch_planning", "parallel_start", "parallel_prepare", "parallel_planning", "parallel_llm"]);

const PHASE_LABELS: Record<string, [string, string]> = {
  batch_start: ["回合开始", "Round started"],
  batch_prepare: ["准备居民", "Preparing residents"],
  batch_planning: ["逐个等待模型决定行动", "Waiting for models (serial)"],
  batch_stalled: ["有模型卡住", "A model stalled"],
  batch_execution: ["执行行动", "Executing actions"],
  batch_work_complete: ["结算工作", "Settling work"],
  batch_life_events: ["生活事件", "Life events"],
  batch_narration: ["生成解说", "Narrating"],
  parallel_start: ["回合开始", "Round started"],
  parallel_prepare: ["准备居民", "Preparing residents"],
  parallel_planning: ["并行请求模型中", "Requesting models (parallel)"],
  parallel_llm: ["模型陆续返回", "Models responding"],
  parallel_execution: ["执行行动", "Executing actions"],
  parallel_work_complete: ["结算工作", "Settling work"],
  parallel_life_events: ["生活事件", "Life events"],
  parallel_narration: ["生成解说", "Narrating"],
  events: ["产生新事件", "New events"],
  completed: ["本轮完成", "Round complete"],
  status: ["状态变更", "Status changed"],
};

export function phaseLabel(phase: string, language: UiLanguage): string {
  const pair = PHASE_LABELS[phase];
  if (pair) return language === "en" ? pair[1] : pair[0];
  return phase || (language === "en" ? "Unknown" : "未知");
}

export function isRoundStartPhase(phase: string): boolean {
  return ROUND_START_PHASES.has(phase);
}

function formatAgo(ms: number, language: UiLanguage): string {
  const sec = Math.max(0, Math.round(ms / 1000));
  if (sec < 60) return language === "en" ? `${sec}s` : `${sec} 秒`;
  const min = Math.floor(sec / 60);
  if (min < 60) return language === "en" ? `${min}m ${sec % 60}s` : `${min} 分 ${sec % 60} 秒`;
  const hr = Math.floor(min / 60);
  return language === "en" ? `${hr}h ${min % 60}m` : `${hr} 小时 ${min % 60} 分`;
}

function formatTokens(usage: Record<string, unknown>): string {
  const total = Number(usage?.total_tokens ?? 0);
  if (!total) return "";
  return total >= 1000 ? `${(total / 1000).toFixed(1)}k tok` : `${total} tok`;
}

type RowState = "error" | "waiting" | "done" | "idle" | "dead";

type Row = {
  key: string;
  entry: ModelUsageEntry;
  state: RowState;
  completedAt: number | null;
};

export function RuntimeMonitor({
  world,
  agents,
  entries,
  progress,
  language = "zh",
  onRefreshUsage,
}: {
  world: World;
  agents: AgentListItem[];
  entries: ModelUsageEntry[];
  progress: RuntimeProgress | null;
  language?: UiLanguage;
  onRefreshUsage: () => Promise<void> | void;
}) {
  const L = (zh: string, en: string) => (language === "en" ? en : zh);
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [loading, setLoading] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const running = world.status === "running";

  // Tick once a second so "waiting for N seconds" stays live.
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  // Poll model usage only while the panel is open. Read-only GET.
  const refreshRef = useRef(onRefreshUsage);
  refreshRef.current = onRefreshUsage;
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        await refreshRef.current();
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    const timer = window.setInterval(load, running ? 3000 : 10000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [open, running, world.world_id]);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const deadIds = useMemo(
    () => new Set(agents.filter((agent) => agent.lifecycle_state === "dead").map((agent) => agent.agent_id)),
    [agents],
  );

  const inWaitingPhase = running && !!progress && WAITING_PHASES.has(progress.phase);
  const roundStart = progress?.roundStartedAt ?? null;

  const rows: Row[] = useMemo(() => {
    const list = entries.map((entry) => {
      const parsed = entry.last_llm_completed_at ? Date.parse(entry.last_llm_completed_at) : NaN;
      const completedAt = Number.isFinite(parsed) ? parsed : null;
      let state: RowState = completedAt ? "done" : "idle";
      if (entry.source_type === "agent" && deadIds.has(entry.source_id)) state = "dead";
      else if (entry.last_llm_error || entry.llm_consecutive_failures > 0) state = "error";
      else if (
        entry.source_type === "agent" &&
        inWaitingPhase &&
        roundStart !== null &&
        (completedAt === null || completedAt < roundStart)
      ) state = "waiting";
      return { key: `${entry.source_type}:${entry.source_id}`, entry, state, completedAt };
    });
    const order: Record<RowState, number> = { error: 0, waiting: 1, done: 2, idle: 3, dead: 4 };
    return list.sort((a, b) => {
      if (order[a.state] !== order[b.state]) return order[a.state] - order[b.state];
      return (a.completedAt ?? 0) - (b.completedAt ?? 0);
    });
  }, [entries, deadIds, inWaitingPhase, roundStart]);

  const waitingRows = rows.filter((row) => row.state === "waiting");
  const errorRows = rows.filter((row) => row.state === "error");
  const sinceProgress = progress ? now - progress.at : null;
  const stale = running && sinceProgress !== null && sinceProgress > 60_000;
  const veryStale = running && sinceProgress !== null && sinceProgress > 180_000;

  const tone = errorRows.length ? "error" : !running ? "idle" : veryStale ? "error" : stale ? "warn" : "ok";

  const statusText = running ? L("运行中", "Running") : world.status === "paused" ? L("已暂停", "Paused") : world.status === "ended" ? L("已结束", "Ended") : world.status;
  let chip: string;
  if (!running) chip = statusText;
  else if (!progress) chip = L("运行中", "Running");
  else {
    const count = progress.total ? ` ${progress.completed ?? 0}/${progress.total}` : "";
    chip = `${phaseLabel(progress.phase, language)}${count}`;
  }
  if (errorRows.length) chip += L(` · ${errorRows.length} 出错`, ` · ${errorRows.length} failing`);
  const chipTime = running && sinceProgress !== null ? formatAgo(sinceProgress, language) : "";

  const percent =
    progress && progress.total ? Math.min(100, Math.round(((progress.completed ?? 0) / progress.total) * 100)) : null;

  const manualRefresh = async () => {
    setLoading(true);
    try {
      await onRefreshUsage();
    } finally {
      setLoading(false);
    }
  };

  let hint = "";
  if (running && waitingRows.length) {
    const names = waitingRows.slice(0, 4).map((row) => row.entry.label).join("、");
    hint = L(
      `正在等 ${waitingRows.length} 个模型回复：${names}${waitingRows.length > 4 ? " 等" : ""}。后端会等它们全部返回后才推进剧情。`,
      `Waiting on ${waitingRows.length} model(s): ${names}${waitingRows.length > 4 ? "…" : ""}. The round advances once all respond.`,
    );
  } else if (errorRows.length) {
    hint = L(`${errorRows.length} 个模型最近一次调用出错（见下方红色条目）。同一模型连续失败过多时，后端会自动暂停世界。`, `${errorRows.length} model(s) failed recently; repeated failures auto-pause the world.`);
  } else if (running && !progress) {
    hint = L("刚打开页面，还没收到本轮进度推送；下一次进度到来后会显示阶段和等待中的模型。", "No progress push received yet since opening; phase and waiting models appear after the next update.");
  } else if (!running) {
    hint = L("世界未在运行，后端不会发起新的模型请求。", "The world is not running; no new model requests are made.");
  }

  return (
    <div className={`runtime-monitor tone-${tone} ${open ? "is-open" : ""}`} ref={rootRef}>
      <button
        type="button"
        className="runtime-monitor-toggle"
        aria-expanded={open}
        title={L("展开后端模型运行情况", "Show backend model activity")}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="runtime-dot" />
        <Activity size={14} />
        <span className="runtime-chip-text">{chip}</span>
        {chipTime && <span className="runtime-chip-time">{chipTime}</span>}
        <ChevronDown size={14} className="runtime-chevron" />
      </button>
      {open && (
        <div className="runtime-popover" role="dialog" aria-label={L("后端运行情况", "Backend activity")}>
          <div className="runtime-popover-head">
            <strong>{L("后端运行情况", "Backend activity")}</strong>
            <button type="button" className="runtime-ghost" title={L("立即刷新", "Refresh now")} onClick={manualRefresh}>
              <RefreshCw size={14} className={loading ? "spin" : ""} />
            </button>
            <button type="button" className="runtime-ghost" title={L("收起", "Close")} onClick={() => setOpen(false)}>
              <X size={14} />
            </button>
          </div>

          <div className="runtime-summary">
            <div>
              <span>{L("世界", "World")}</span>
              <strong>{statusText}</strong>
            </div>
            <div>
              <span>{L("当前阶段", "Phase")}</span>
              <strong>{progress ? phaseLabel(progress.phase, language) : "—"}</strong>
            </div>
            <div>
              <span>{L("距上次进展", "Since last progress")}</span>
              <strong className={veryStale ? "is-bad" : stale ? "is-warn" : ""}>
                {sinceProgress !== null ? formatAgo(sinceProgress, language) : "—"}
              </strong>
            </div>
            <div>
              <span>{L("等待 / 出错", "Waiting / errors")}</span>
              <strong>
                {waitingRows.length} / <b className={errorRows.length ? "is-bad" : ""}>{errorRows.length}</b>
              </strong>
            </div>
          </div>

          {percent !== null && (
            <div className="runtime-progress" title={`${progress?.completed ?? 0}/${progress?.total ?? 0}`}>
              <div className="runtime-progress-bar" style={{ width: `${percent}%` }} />
              <span>
                {progress?.completed ?? 0}/{progress?.total ?? 0}
              </span>
            </div>
          )}

          {hint && <p className={`runtime-hint ${errorRows.length || veryStale ? "is-bad" : stale ? "is-warn" : ""}`}>{hint}</p>}

          <div className="runtime-rows">
            {rows.length ? rows.map(({ key, entry, state, completedAt }) => {
              const tokens = formatTokens(entry.last_llm_token_usage);
              const latency = entry.last_llm_latency_ms ? `${(entry.last_llm_latency_ms / 1000).toFixed(1)}s` : "";
              let stateText = "";
              if (state === "waiting") stateText = L(`等待 ${formatAgo(now - (roundStart ?? now), language)}`, `waiting ${formatAgo(now - (roundStart ?? now), language)}`);
              else if (state === "error") stateText = L(`出错${entry.llm_consecutive_failures ? ` ×${entry.llm_consecutive_failures}` : ""}`, `error${entry.llm_consecutive_failures ? ` ×${entry.llm_consecutive_failures}` : ""}`);
              else if (state === "dead") stateText = L("已出局", "out");
              else if (completedAt) stateText = L(`${formatAgo(now - completedAt, language)}前`, `${formatAgo(now - completedAt, language)} ago`);
              else stateText = L("未调用", "not called");
              return (
                <div className={`runtime-row state-${state}`} key={key}>
                  <span className="runtime-row-dot" />
                  <div className="runtime-row-main">
                    <div className="runtime-row-top">
                      <strong>{entry.label}</strong>
                      <em>{stateText}</em>
                    </div>
                    <div className="runtime-row-sub">
                      <code title={`${entry.provider_name} · ${entry.base_url}`}>{entry.model_name || L("未配置", "unset")}</code>
                      {latency && <span>{latency}</span>}
                      {tokens && <span>{tokens}</span>}
                    </div>
                    {entry.last_llm_error && <div className="runtime-row-error" title={entry.last_llm_error}>{entry.last_llm_error}</div>}
                  </div>
                </div>
              );
            }) : <p className="runtime-empty">{loading ? L("读取中…", "Loading…") : L("暂无模型信息", "No model info")}</p>}
          </div>
          <p className="runtime-foot">{L("只读查看，每 3 秒刷新，不会影响后端运行。", "Read-only, refreshes every 3s; does not affect the backend.")}</p>
        </div>
      )}
    </div>
  );
}
