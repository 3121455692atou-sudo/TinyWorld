import { Languages, Palette, PanelLeft, PanelRight, RotateCcw, Type } from "lucide-react";
import { t } from "../i18n";

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
        <h2>{t("界面", settings.language)}</h2>
        <button type="button" className="icon-button" title={t("恢复默认", settings.language)} onClick={() => onChange(DEFAULT_UI_SETTINGS)}>
          <RotateCcw size={15} />
        </button>
      </div>
      <div className="ui-settings-body">
        <label>
          <span><Palette size={14} /> {t("主题", settings.language)}</span>
          <select value={settings.theme} onChange={(event) => patch({ theme: event.target.value as UiSettings["theme"] })}>
            <option value="light">{t("浅色", settings.language)}</option>
            <option value="dark">{t("深色", settings.language)}</option>
          </select>
        </label>
        <label>
          <span><PanelLeft size={14} /> {t("左栏", settings.language)}</span>
          <input type="range" min="220" max="460" value={settings.leftWidth} onChange={(event) => patch({ leftWidth: Number(event.target.value) })} />
        </label>
        <label>
          <span><PanelRight size={14} /> {t("右栏", settings.language)}</span>
          <input type="range" min="260" max="560" value={settings.rightWidth} onChange={(event) => patch({ rightWidth: Number(event.target.value) })} />
        </label>
        <label>
          <span><Type size={14} /> {t("文字", settings.language)}</span>
          <input type="range" min="12" max="20" value={settings.eventFontSize} onChange={(event) => patch({ eventFontSize: Number(event.target.value) })} />
        </label>
        <label>
          <span>{t("头像", settings.language)}</span>
          <input type="range" min="30" max="64" value={settings.eventAvatarSize} onChange={(event) => patch({ eventAvatarSize: Number(event.target.value) })} />
        </label>
        <label title={t("切换界面语言；创建新世界时也会要求角色、身份生成和解说使用对应语言。", settings.language)}>
          <span><Languages size={14} /> {t("语言 language", settings.language)}</span>
          <select value={settings.language} onChange={(event) => patch({ language: event.target.value === "en" ? "en" : "zh" })}>
            <option value="zh">中文 Chinese</option>
            <option value="en">English 英文</option>
          </select>
        </label>
      </div>
    </section>
  );
}
