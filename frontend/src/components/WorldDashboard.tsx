import type { CSSProperties, ReactNode } from "react";
import { useState } from "react";
import type { UiSettings } from "./UiSettingsPanel";

export function WorldDashboard({
  uiSettings,
  controls,
  left,
  center,
  right,
  error
}: {
  uiSettings: UiSettings;
  controls: ReactNode;
  left: ReactNode;
  center: ReactNode;
  right: ReactNode;
  error: string | null;
}) {
  const [leftOpen, setLeftOpen] = useState(false);
  const [rightOpen, setRightOpen] = useState(false);
  const style = {
    "--left-rail-width": `${uiSettings.leftWidth}px`,
    "--right-rail-width": `${uiSettings.rightWidth}px`,
    "--event-font-size": `${uiSettings.eventFontSize}px`,
    "--avatar-size": `${uiSettings.eventAvatarSize}px`,
    "--agent-avatar-size": `${uiSettings.eventAvatarSize}px`,
    "--event-avatar-size": `${uiSettings.eventAvatarSize}px`,
    "--event-image-width": `${uiSettings.eventImageWidth}px`,
    "--radius": `${uiSettings.borderRadius}px`,
    "--radius-sm": `${Math.max(uiSettings.borderRadius - 2, 0)}px`,
    "--radius-md": `${uiSettings.borderRadius}px`,
    "--radius-lg": `${uiSettings.borderRadius + 4}px`,
    "--density": uiSettings.density === "compact" ? "0.82" : uiSettings.density === "comfort" ? "1.15" : "1",
    ...(uiSettings.accentHue !== null && uiSettings.accentHue !== undefined
      ? { "--accent": `hsl(${uiSettings.accentHue}, 60%, 46%)` }
      : {}),
  } as CSSProperties;
  const accentClass = uiSettings.accentHue === null && uiSettings.accentColor !== "blue" ? `accent-${uiSettings.accentColor}` : "";
  const densityClass = uiSettings.density !== "default" ? `density-${uiSettings.density}` : "";
  return (
    <main className={`dashboard theme-${uiSettings.theme} ${accentClass} ${densityClass} ${leftOpen ? "left-rail-open" : ""} ${rightOpen ? "right-rail-open" : ""}`} style={style}>
      <header className="topbar">{controls}</header>
      {error && <div className="error-line">{error}</div>}
      <section className="workspace">
        <button
          type="button"
          className="rail-drawer-toggle rail-drawer-toggle-left"
          onClick={() => setLeftOpen((value) => !value)}
          title={leftOpen ? "收起左侧栏 / Hide left sidebar" : "拉出左侧栏 / Show left sidebar"}
        >
          {leftOpen ? "‹" : "›"}
        </button>
        <button
          type="button"
          className="rail-drawer-toggle rail-drawer-toggle-right"
          onClick={() => setRightOpen((value) => !value)}
          title={rightOpen ? "收起右侧栏 / Hide right sidebar" : "拉出右侧栏 / Show right sidebar"}
        >
          {rightOpen ? "›" : "‹"}
        </button>
        {(leftOpen || rightOpen) && <button type="button" className="rail-drawer-scrim" aria-label="关闭侧栏 / Close sidebars" onClick={() => {
          setLeftOpen(false);
          setRightOpen(false);
        }} />}
        <aside className="left-rail">{left}</aside>
        <section className="event-column">{center}</section>
        <aside className="right-rail">{right}</aside>
      </section>
    </main>
  );
}
