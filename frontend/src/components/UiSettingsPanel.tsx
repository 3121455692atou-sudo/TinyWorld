import { Languages, Palette, PanelLeft, PanelRight, RotateCcw, Type } from "lucide-react";

export type UiSettings = {
  theme: "light" | "dark";
  language: "zh" | "en";
  leftWidth: number;
  rightWidth: number;
  eventFontSize: number;
  eventAvatarSize: number;
};

export const DEFAULT_UI_SETTINGS: UiSettings = {
  theme: "light",
  language: "zh",
  leftWidth: 310,
  rightWidth: 390,
  eventFontSize: 14,
  eventAvatarSize: 38
};

export function UiSettingsPanel({
  settings,
  onChange
}: {
  settings: UiSettings;
  onChange: (settings: UiSettings) => void;
}) {
  const patch = (next: Partial<UiSettings>) => onChange({ ...settings, ...next });
  return (
    <section className="panel ui-settings-panel">
      <div className="panel-heading">
        <h2>界面</h2>
        <button type="button" className="icon-button" title="恢复默认" onClick={() => onChange(DEFAULT_UI_SETTINGS)}>
          <RotateCcw size={15} />
        </button>
      </div>
      <div className="ui-settings-body">
        <label>
          <span><Palette size={14} /> 主题</span>
          <select value={settings.theme} onChange={(event) => patch({ theme: event.target.value as UiSettings["theme"] })}>
            <option value="light">浅色</option>
            <option value="dark">深色</option>
          </select>
        </label>
        <label>
          <span><PanelLeft size={14} /> 左栏</span>
          <input type="range" min="220" max="460" value={settings.leftWidth} onChange={(event) => patch({ leftWidth: Number(event.target.value) })} />
        </label>
        <label>
          <span><PanelRight size={14} /> 右栏</span>
          <input type="range" min="260" max="560" value={settings.rightWidth} onChange={(event) => patch({ rightWidth: Number(event.target.value) })} />
        </label>
        <label>
          <span><Type size={14} /> 文字</span>
          <input type="range" min="12" max="20" value={settings.eventFontSize} onChange={(event) => patch({ eventFontSize: Number(event.target.value) })} />
        </label>
        <label>
          <span>头像</span>
          <input type="range" min="30" max="64" value={settings.eventAvatarSize} onChange={(event) => patch({ eventAvatarSize: Number(event.target.value) })} />
        </label>
        <label title="切换界面语言；创建新世界时也会要求角色、身份生成和解说使用对应语言。">
          <span><Languages size={14} /> 语言 language</span>
          <select value={settings.language} onChange={(event) => patch({ language: event.target.value === "en" ? "en" : "zh" })}>
            <option value="zh">中文 Chinese</option>
            <option value="en">English 英文</option>
          </select>
        </label>
      </div>
    </section>
  );
}
