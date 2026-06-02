import { useMemo, useState } from "react";
import type { World, WorldMetrics } from "../api/types";
import { t, type UiLanguage } from "../i18n";

export function EconomyPanel({ world, metrics, enabled, language = "zh" }: { world: World; metrics: WorldMetrics | null; enabled?: boolean; language?: UiLanguage }) {
  const market = (world.settings?.v6_market ?? {}) as Record<string, unknown>;
  const stocks = (market.stocks ?? {}) as Record<string, Record<string, unknown>>;
  const stockEntries = useMemo(() => Object.entries(stocks), [stocks]);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const selectedEntry = stockEntries.find(([ticker]) => ticker === selectedTicker) ?? stockEntries[0];
  const selected = selectedEntry?.[1];
  const selectedChange = percentChange(selected);
  const selectedUp = selectedChange >= 0;
  const flags = worldEconomyFlags(world);
  const showPanel = enabled ?? flags.showEconomyPanel;
  const showStocks = flags.showFinance && stockEntries.length > 0;
  if (!showPanel) return null;

  return (
    <section className="panel economy-panel">
      <h2>{t(showStocks ? "经济与市场" : "世界经济", language)}</h2>
      <div className="economy-body">
        {showStocks ? <p>{t("游戏内虚构市场，不是现实投资建议。", language)}</p> : <p>{t("当前世界观没有启用证券市场；这里只显示世界观声明允许的经济摘要。", language)}</p>}
        <dl>
          {showStocks && <><dt>{t("市场", language)}</dt><dd>{t(String(market.regime ?? "未开盘"), language)}</dd></>}
          {flags.showFuel && <><dt>{t("油价", language)}</dt><dd>{String(market.fuel_price ?? "-")}</dd></>}
          {flags.showHousing && <><dt>{t("无家可归", language)}</dt><dd>{Math.round((metrics?.homeless_rate ?? 0) * 100)}%</dd></>}
          {flags.showDebt && <><dt>{t("总债务", language)}</dt><dd>{String(metrics?.total_debt ?? 0)}</dd></>}
        </dl>
        {showStocks && <div className="stock-list">
          {stockEntries.slice(0, 8).map(([ticker, stock]) => {
            const change = percentChange(stock);
            const up = change >= 0;
            return (
            <button
              key={ticker}
              type="button"
              className={ticker === selectedEntry?.[0] ? "selected" : ""}
              aria-pressed={ticker === selectedEntry?.[0]}
              onClick={() => setSelectedTicker(ticker)}
            >
              <strong>{ticker}</strong>
              <span>{String(stock.name_en ?? stock.name_zh ?? "")}</span>
              <b className={up ? "stock-up" : "stock-down"}>{String(stock.price ?? "-")}</b>
            </button>
            );
          })}
        </div>}
        {showStocks && selected && (
          <div className="stock-detail">
            <div className="stock-detail-heading">
              <div>
                <strong>{selectedEntry?.[0] ?? ""} · {String(selected.name_en ?? selected.name_zh ?? "")}</strong>
                <span>{t(String(selected.sector ?? "未知行业"), language)}</span>
              </div>
              <b className={selectedUp ? "stock-up" : "stock-down"}>
                {selectedUp ? "+" : ""}{selectedChange.toFixed(2)}%
              </b>
            </div>
            <StockChart stock={selected} up={selectedUp} />
            <dl className="stock-detail-grid">
              <dt>{t("现价", language)}</dt><dd>{numberValue(selected.price).toFixed(2)}</dd>
              <dt>{t("昨收", language)}</dt><dd>{numberValue(selected.previous_price).toFixed(2)}</dd>
              <dt>{t("波动", language)}</dt><dd>{(numberValue(selected.volatility) * 100).toFixed(1)}%</dd>
              <dt>{t("情绪", language)}</dt><dd>{numberValue(selected.sentiment).toFixed(0)}</dd>
              <dt>{t("基本面", language)}</dt><dd>{numberValue(selected.fundamental_value).toFixed(2)}</dd>
              <dt>{t("流动性", language)}</dt><dd>{numberValue(selected.liquidity).toFixed(0)}</dd>
            </dl>
          </div>
        )}
      </div>
    </section>
  );
}

function worldEconomyFlags(world: World) {
  const settings = world.settings ?? {};
  const ui = asRecord(settings.worldview_ui);
  const panels = asRecord(ui.panels);
  const worldviewId = String(settings.worldview_id ?? "");
  const toolsetId = String(settings.world_toolset_id ?? settings.toolset_id ?? "");
  const defaultModern = worldviewId === "default_modern_worldview" || toolsetId === "default_modern_world_toolset" || toolsetId === "default_modern_toolset";
  const finance = boolValue(settings.finance_investing_enabled, false);
  const showFinance = boolValue(panels.finance, finance);
  const showHousing = boolValue(panels.housing, defaultModern);
  const showDebt = boolValue(panels.debt, defaultModern);
  const showEconomyPanel = boolValue(panels.economy, defaultModern || showFinance || showHousing || showDebt);
  return {
    showEconomyPanel,
    showFinance,
    showHousing,
    showDebt,
    showFuel: showFinance || defaultModern,
  };
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function boolValue(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function StockChart({ stock, up }: { stock: Record<string, unknown>; up: boolean }) {
  const rawHistory = Array.isArray(stock.history) ? stock.history : [];
  const history = rawHistory
    .map((item) => numberValue((item as Record<string, unknown>).price))
    .filter((price) => price > 0);
  const fallback = [numberValue(stock.previous_price), numberValue(stock.price)].filter((price) => price > 0);
  const prices = (history.length >= 2 ? history : fallback).length ? (history.length >= 2 ? history : fallback) : [0, 0];
  const width = 240;
  const height = 84;
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const span = Math.max(0.01, max - min);
  const points = prices
    .map((price, index) => {
      const x = prices.length === 1 ? width / 2 : (index / (prices.length - 1)) * width;
      const y = height - ((price - min) / span) * (height - 12) - 6;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg className={`stock-chart ${up ? "up" : "down"}`} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Stock price curve">
      <line x1="0" y1={height - 6} x2={width} y2={height - 6} />
      <polyline points={points} />
    </svg>
  );
}

function numberValue(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function percentChange(stock: Record<string, unknown> | undefined): number {
  if (!stock) return 0;
  if (stock.change_pct !== undefined) return numberValue(stock.change_pct);
  return numberValue(stock.day_change) * 100;
}
