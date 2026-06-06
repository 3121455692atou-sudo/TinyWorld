import { RefreshCw } from "lucide-react";
import type { WorldLocation } from "../api/types";
import { t, type UiLanguage } from "../i18n";

export function MapPanel({
  locations,
  language = "zh",
  worldTimeLabel = "",
  refreshing = false,
  lastRefreshLabel = "",
  onRefresh,
}: {
  locations: WorldLocation[];
  language?: UiLanguage;
  worldTimeLabel?: string;
  refreshing?: boolean;
  lastRefreshLabel?: string;
  onRefresh?: () => void;
}) {
  return (
    <section className="panel map-panel">
      <div className="panel-heading map-panel-heading">
        <div className="panel-title-stack">
          <h2>{t("地点", language)}</h2>
          {worldTimeLabel && (
            <span className="map-time-label">{worldTimeLabel}</span>
          )}
        </div>
        {onRefresh && (
          <button
            type="button"
            className="mini-refresh-button"
            disabled={refreshing}
            onClick={onRefresh}
            title="手动刷新左侧时间和地点"
          >
            <RefreshCw size={14} className={refreshing ? "spin-icon" : ""} />
            <span>{refreshing ? "刷新中" : "刷新"}</span>
          </button>
        )}
      </div>
      {lastRefreshLabel && (
        <div className="map-refresh-note">左侧快照：{lastRefreshLabel}</div>
      )}
      <div className="location-list">
        {locations.length ? (
          locations.map((location) => (
            <div
              key={location.location_id}
              className="location-row"
              title={t(location.description || "", language)}
            >
              <span className="location-main-line">
                {t(location.name, language)}
                <i style={{ backgroundColor: location.color ?? "#8a99a1" }} />
              </span>
            </div>
          ))
        ) : (
          <div className="location-row muted">暂无地点</div>
        )}
      </div>
    </section>
  );
}
