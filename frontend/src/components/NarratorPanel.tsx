import type { Narration } from "../api/types";
import { useMemo, useState } from "react";

const PAGE_SIZE = 3;

export function NarratorPanel({ narrations }: { narrations: Narration[] }) {
  const [page, setPage] = useState(1);
  const daily = useMemo(() => narrations.filter((item) => item.trigger_type === "daily_summary").slice().reverse(), [narrations]);
  const pageCount = Math.max(1, Math.ceil(daily.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount);
  const visibleDaily = daily.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);
  const latest = narrations.filter((item) => item.trigger_type !== "daily_summary").at(-1);
  return (
    <section className="panel narrator-panel">
      <div className="panel-heading">
        <h2>每日总结</h2>
        <span>{daily.length ? `${safePage} / ${pageCount}` : "0"}</span>
      </div>
      {visibleDaily.length ? (
        <div className="daily-summary-list">
          {visibleDaily.map((item) => (
            <article key={item.narrator_run_id} className={`daily-summary ${item.tone}`}>
              <strong>{item.summary_title}</strong>
              <p>{item.narration}</p>
            </article>
          ))}
          <div className="daily-summary-pagination">
            <button type="button" disabled={safePage <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))}>上一页</button>
            <button type="button" disabled={safePage >= pageCount} onClick={() => setPage((current) => Math.min(pageCount, current + 1))}>下一页</button>
          </div>
        </div>
      ) : (
        <p className="muted">还没有跨过完整的一天。</p>
      )}
      {latest && (
        <details className="latest-narration">
          <summary>最近解说</summary>
          <div className={`narration ${latest.tone}`}>
            <strong>{latest.summary_title}</strong>
            <p>{latest.narration}</p>
          </div>
        </details>
      )}
    </section>
  );
}
