import { ChevronDown, CircleDot, ImageIcon, Languages, Palette, PanelLeft, PanelRight, RotateCcw, Sparkles, Type, Volume2 } from "lucide-react";
import { useState } from "react";
import { t } from "../i18n";

export type AccentColor = "blue" | "green" | "violet" | "amber" | "cyan" | "rose";
export type Density = "compact" | "default" | "comfort";

export type UiSettings = {
  theme: "light" | "dark" | "beige";
  language: "zh" | "en";
  leftWidth: number;
  rightWidth: number;
  eventFontSize: number;
  eventAvatarSize: number;
  eventImageWidth: number;
  ttsGenerationMode: "on_demand" | "on_speech";
  accentColor: AccentColor;
  accentHue: number | null;
  density: Density;
  borderRadius: number;
};

export const DEFAULT_UI_SETTINGS: UiSettings = {
  theme: "light",
  language: "zh",
  leftWidth: 310,
  rightWidth: 390,
  eventFontSize: 14,
  eventAvatarSize: 38,
  eventImageWidth: 520,
  ttsGenerationMode: "on_demand",
  accentColor: "blue",
  accentHue: null,
  density: "default",
  borderRadius: 8,
};

const ACCENT_OPTIONS: { value: AccentColor; label: string; color: string }[] = [
  { value: "blue",   label: "Blue",   color: "#1f6fb2" },
  { value: "green",  label: "Green",  color: "#2f8f58" },
  { value: "violet", label: "Violet", color: "#6954bd" },
  { value: "amber",  label: "Amber",  color: "#b77710" },
  { value: "cyan",   label: "Cyan",   color: "#188c8c" },
  { value: "rose",   label: "Rose",   color: "#c2416b" },
];

export function UiSettingsPanel({
  settings,
  onChange
}: {
  settings: UiSettings;
  onChange: (settings: UiSettings) => void;
}) {
  const patch = (next: Partial<UiSettings>) => onChange({ ...settings, ...next });
  const [open, setOpen] = useState(true);
  return (
    <section className={`panel ui-settings-panel ${open ? "panel-open" : "panel-collapsed"}`}>
      <div className="panel-heading">
        <button type="button" className="panel-title-button" onClick={() => setOpen((value) => !value)} title={open ? t("收起", settings.language) : t("展开", settings.language)}>
          <ChevronDown size={15} className={open ? "" : "rotated-closed"} />
          <span>{t("界面", settings.language)}</span>
        </button>
        <div className="panel-heading-actions">
          <button type="button" className="icon-button" title={t("恢复默认", settings.language)} onClick={() => onChange(DEFAULT_UI_SETTINGS)}>
            <RotateCcw size={15} />
          </button>
        </div>
      </div>
      {open && <div className="ui-settings-body">
        <label>
          <span><Palette size={14} /> {t("主题", settings.language)}</span>
          <select value={settings.theme} onChange={(event) => patch({ theme: event.target.value as UiSettings["theme"] })}>
            <option value="light">{t("浅色", settings.language)}</option>
            <option value="beige">{t("米色", settings.language)}</option>
            <option value="dark">{t("深色", settings.language)}</option>
          </select>
        </label>
        <label>
          <span><Sparkles size={14} /> {t("强调色", settings.language)}</span>
          <div className="accent-picker">
            {ACCENT_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                className={`accent-swatch ${settings.accentHue === null && settings.accentColor === opt.value ? "selected" : ""}`}
                style={{ background: opt.color }}
                title={opt.label}
                onClick={() => patch({ accentColor: opt.value, accentHue: null })}
              />
            ))}
          </div>
        </label>
        <label title={t("拖动调色盘自定义强调色，点上面的色块可恢复预设。", settings.language)}>
          <span><Palette size={14} /> {t("调色盘", settings.language)}</span>
          <input
            className="accent-hue-slider"
            type="range"
            min="0"
            max="360"
            value={settings.accentHue ?? 210}
            onChange={(event) => patch({ accentHue: Number(event.target.value) })}
          />
        </label>
        <label>
          <span><CircleDot size={14} /> {t("密度", settings.language)}</span>
          <select value={settings.density} onChange={(event) => patch({ density: event.target.value as Density })}>
            <option value="compact">{t("紧凑", settings.language)}</option>
            <option value="default">{t("默认", settings.language)}</option>
            <option value="comfort">{t("舒适", settings.language)}</option>
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
        <label>
          <span><ImageIcon size={14} /> {t("图片", settings.language)}</span>
          <input type="range" min="260" max="960" value={settings.eventImageWidth} onChange={(event) => patch({ eventImageWidth: Number(event.target.value) })} />
        </label>
        <label>
          <span>{t("圆角", settings.language)}</span>
          <input type="range" min="0" max="20" value={settings.borderRadius} onChange={(event) => patch({ borderRadius: Number(event.target.value) })} />
        </label>
        <label title={t("控制 TTS 是首次点击播放时才生成，还是新发言进入事件流后自动后台生成。", settings.language)}>
          <span><Volume2 size={14} /> {t("TTS 生成", settings.language)}</span>
          <select value={settings.ttsGenerationMode} onChange={(event) => patch({ ttsGenerationMode: event.target.value === "on_speech" ? "on_speech" : "on_demand" })}>
            <option value="on_demand">{t("点播放才生成", settings.language)}</option>
            <option value="on_speech">{t("发言后自动生成", settings.language)}</option>
          </select>
        </label>
        <label title={t("切换界面语言；创建新世界时也会要求角色、身份生成和解说使用对应语言。", settings.language)}>
          <span><Languages size={14} /> {t("语言 language", settings.language)}</span>
          <select value={settings.language} onChange={(event) => patch({ language: event.target.value === "en" ? "en" : "zh" })}>
            <option value="zh">中文 Chinese</option>
            <option value="en">English 英文</option>
          </select>
        </label>
      </div>}
    </section>
  );
}
