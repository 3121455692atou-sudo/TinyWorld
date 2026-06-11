import { ArrowUp, ArrowDown, Database, History, Pin, PinOff, RefreshCcw, Settings, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { apiClient } from "../api/client";
import type { StorageImageItem } from "../api/types";
import { CONFIG_HISTORY_KIND_LABELS, type ConfigHistoryItem, loadConfigHistory, saveConfigHistory, sortConfigHistory } from "../configHistory";
import { t, type UiLanguage } from "../i18n";

type Props = {
  language: UiLanguage;
  onOpenStorage: () => void;
  onOpenConfigHistory: () => void;
};

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function kindLabel(kind: StorageImageItem["kind"], language: UiLanguage): string {
  if (kind === "generated") return t("生成图", language);
  if (kind === "standing") return t("立绘", language);
  return t("头像", language);
}

function kindsLabel(item: StorageImageItem, language: UiLanguage): string {
  return item.kinds.map((kind) => kindLabel(kind, language)).join(" / ");
}

function storageImageDisplayName(item: StorageImageItem): string {
  if (item.image_key) return item.image_key;
  if (item.references[0]?.key) return item.references[0].key;
  if (item.hash) return item.hash;
  return item.label;
}

function readableError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function SettingsMenuPanel({ language, onOpenStorage, onOpenConfigHistory }: Props) {
  const [open, setOpen] = useState(false);
  return (
    <section className="panel settings-menu-panel">
      <button type="button" className="settings-menu-button" onClick={() => setOpen((current) => !current)}>
        <Settings size={17} />
        <span>{t("设置", language)}</span>
        <small>{t("管理存储、历史配置和全局选项", language)}</small>
      </button>
      {open && (
        <div className="settings-menu-list">
          <button type="button" onClick={onOpenStorage}>
            <Database size={15} /> {t("存储库管理", language)}
          </button>
          <button type="button" onClick={onOpenConfigHistory}>
            <History size={15} /> {t("历史配置管理", language)}
          </button>
        </div>
      )}
    </section>
  );
}

export function ConfigHistoryManagerView({
  language,
  onClose
}: {
  language: UiLanguage;
  onClose: () => void;
}) {
  const [items, setItems] = useState<ConfigHistoryItem[]>(() => loadConfigHistory());
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<"" | ConfigHistoryItem["kind"]>("");

  const visible = useMemo(() => {
    const lowerQuery = query.trim().toLowerCase();
    return sortConfigHistory(items).filter((item) => {
      if (kind && item.kind !== kind) return false;
      if (!lowerQuery) return true;
      return `${item.name} ${CONFIG_HISTORY_KIND_LABELS[item.kind]}`.toLowerCase().includes(lowerQuery);
    });
  }, [items, query, kind]);

  const commit = (next: ConfigHistoryItem[]) => {
    setItems(next);
    saveConfigHistory(next);
    setSelected((current) => new Set([...current].filter((id) => next.some((item) => item.id === id))));
  };

  const updateItem = (id: string, patch: Partial<ConfigHistoryItem>) => {
    commit(items.map((item) => item.id === id ? { ...item, ...patch, updatedAt: new Date().toISOString() } : item));
  };

  const moveItem = (id: string, direction: -1 | 1) => {
    const ordered = sortConfigHistory(items);
    const index = ordered.findIndex((item) => item.id === id);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= ordered.length) return;
    const current = ordered[index];
    const neighbor = ordered[target];
    commit(items.map((item) => {
      if (item.id === current.id) return { ...item, order: neighbor.order, updatedAt: new Date().toISOString() };
      if (item.id === neighbor.id) return { ...item, order: current.order, updatedAt: new Date().toISOString() };
      return item;
    }));
  };

  const deleteSelected = () => {
    if (!selected.size) return;
    if (!window.confirm(`删除选中的 ${selected.size} 条历史配置？`)) return;
    commit(items.filter((item) => !selected.has(item.id)));
  };

  return (
    <section className="storage-manager-view">
      <header className="storage-manager-view-header">
        <div>
          <span><History size={17} /> {t("设置", language)}</span>
          <h2>{t("历史配置管理", language)}</h2>
          <p>{t("这里统一管理创建页和运行页可复用的历史配置。配置区只负责选择，不在选择时删除或排序。", language)}</p>
        </div>
        <button type="button" onClick={onClose}>
          <X size={16} /> {t("返回", language)}
        </button>
      </header>
      <div className="storage-manager storage-manager-main">
        <div className="storage-manager-actions">
          <input value={query} placeholder={t("搜索配置", language)} onChange={(event) => setQuery(event.target.value)} />
          <select value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}>
            <option value="">{t("全部类型", language)}</option>
            {Object.entries(CONFIG_HISTORY_KIND_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <button type="button" onClick={() => setSelected(new Set(visible.map((item) => item.id)))} disabled={!visible.length}>
            {t("全选当前结果", language)}
          </button>
          <button type="button" onClick={() => setSelected(new Set())} disabled={!selected.size}>
            {t("清空选择", language)}
          </button>
          <button type="button" className="danger-button" onClick={deleteSelected} disabled={!selected.size}>
            <Trash2 size={14} /> {t("删除选中", language)}
          </button>
        </div>
        <div className="config-history-list">
          {visible.length ? visible.map((item) => (
            <label key={item.id} className="config-history-row">
              <input
                type="checkbox"
                checked={selected.has(item.id)}
                onChange={(event) => setSelected((current) => {
                  const next = new Set(current);
                  if (event.target.checked) next.add(item.id);
                  else next.delete(item.id);
                  return next;
                })}
              />
              <span>
                <strong>{item.name}</strong>
                <small>{CONFIG_HISTORY_KIND_LABELS[item.kind]} · {new Date(item.updatedAt).toLocaleString()}</small>
              </span>
              <button type="button" title={item.pinned ? t("取消置顶", language) : t("置顶", language)} onClick={(event) => { event.preventDefault(); updateItem(item.id, { pinned: !item.pinned }); }}>
                {item.pinned ? <PinOff size={14} /> : <Pin size={14} />}
              </button>
              <button type="button" title={t("上移", language)} onClick={(event) => { event.preventDefault(); moveItem(item.id, -1); }}>
                <ArrowUp size={14} />
              </button>
              <button type="button" title={t("下移", language)} onClick={(event) => { event.preventDefault(); moveItem(item.id, 1); }}>
                <ArrowDown size={14} />
              </button>
            </label>
          )) : <p className="empty-hint">{t("暂无历史配置。", language)}</p>}
        </div>
      </div>
    </section>
  );
}

export function StorageManagerView({
  language,
  onError,
  onClose
}: {
  language: UiLanguage;
  onError?: (message: string) => void;
  onClose: () => void;
}) {
  const [items, setItems] = useState<StorageImageItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [previewItem, setPreviewItem] = useState<StorageImageItem | null>(null);
  const [busy, setBusy] = useState(false);

  const selectedItems = useMemo(() => items.filter((item) => selected.has(item.key)), [items, selected]);
  const stats = useMemo(() => {
    const numberValue = (value: unknown) => Number.isFinite(Number(value)) ? Number(value) : 0;
    return {
      uniqueCount: items.length,
      referenceCount: items.reduce((sum, item) => sum + numberValue(item.reference_count), 0),
      uniqueBytes: items.reduce((sum, item) => sum + numberValue(item.size_bytes), 0),
      referenceBytes: items.reduce((sum, item) => sum + numberValue(item.reference_bytes), 0),
      selectedCount: selectedItems.length,
      selectedReferenceCount: selectedItems.reduce((sum, item) => sum + numberValue(item.reference_count), 0),
      selectedBytes: selectedItems.reduce((sum, item) => sum + numberValue(item.size_bytes), 0),
      selectedReferenceBytes: selectedItems.reduce((sum, item) => sum + numberValue(item.reference_bytes), 0),
    };
  }, [items, selectedItems]);

  const loadStorage = async () => {
    setBusy(true);
    try {
      const result = await apiClient.storageImages(200);
      setItems(result.items);
      setSelected((current) => new Set([...current].filter((key) => result.items.some((item) => item.key === key))));
    } catch (error) {
      onError?.(readableError(error));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    loadStorage().catch(() => undefined);
  }, []);

  const toggleKey = (key: string, checked: boolean) => {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(key);
      else next.delete(key);
      return next;
    });
  };

  const setKindSelected = (kind: StorageImageItem["kind"], checked: boolean) => {
    setSelected((current) => {
      const next = new Set(current);
      for (const item of items) {
        if ((item.kinds ?? [item.kind]).includes(kind)) {
          if (checked) next.add(item.key);
          else next.delete(item.key);
        }
      }
      return next;
    });
  };

  const deleteSelected = async () => {
    const keys = [...selected];
    if (!keys.length) return;
    const ok = window.confirm(`删除选中的 ${keys.length} 张图片？这会清空数据库里的图片内容，但不会删除事件或角色。`);
    if (!ok) return;
    setBusy(true);
    try {
      await apiClient.deleteStorageImages(keys);
      setSelected(new Set());
      await loadStorage();
    } catch (error) {
      onError?.(readableError(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="storage-manager-view">
      <header className="storage-manager-view-header">
        <div>
          <span><Database size={17} /> {t("设置", language)}</span>
          <h2>{t("存储库管理", language)}</h2>
          <p>{t("相同图片会按内容合并显示，并列出有多少事件、头像或立绘正在引用它。删除图片会清空所有引用，不会删除事件、角色或存档。", language)}</p>
        </div>
        <button type="button" onClick={onClose}>
          <X size={16} /> {t("返回", language)}
        </button>
      </header>
      <div className="storage-manager storage-manager-main">
        <div className="storage-manager-actions">
          <button type="button" onClick={() => loadStorage()} disabled={busy}>
            <RefreshCcw size={14} /> {busy ? t("读取中", language) : t("刷新", language)}
          </button>
          <button type="button" onClick={() => setSelected(new Set(items.map((item) => item.key)))} disabled={!items.length || busy}>
            {t("全选当前结果", language)}
          </button>
          <button type="button" onClick={() => setSelected(new Set())} disabled={!selected.size || busy}>
            {t("清空选择", language)}
          </button>
          <button type="button" className="danger-button" onClick={deleteSelected} disabled={!selected.size || busy}>
            <Trash2 size={14} /> {t("删除选中", language)}
          </button>
        </div>
        {items.length > 0 && (
          <>
            <div className="storage-manager-summary">
              <span>{t("唯一图片", language)} {stats.uniqueCount} / {formatBytes(stats.uniqueBytes)}</span>
              <span>{t("引用", language)} {stats.referenceCount} 处 / {formatBytes(stats.referenceBytes)}</span>
              <span>{t("选中", language)} {stats.selectedCount} 张 / 引用 {stats.selectedReferenceCount} 处 / {formatBytes(stats.selectedReferenceBytes)}</span>
            </div>
            <div className="storage-kind-actions">
              {(["generated", "avatar", "standing"] as const).map((kind) => {
                const kindItems = items.filter((item) => (item.kinds ?? [item.kind]).includes(kind));
                const checked = kindItems.length > 0 && kindItems.every((item) => selected.has(item.key));
                return (
                  <label key={kind}>
                    <input type="checkbox" checked={checked} onChange={(event) => setKindSelected(kind, event.target.checked)} />
                    {kindLabel(kind, language)} {kindItems.length}
                  </label>
                );
              })}
            </div>
          </>
        )}
        <div className="storage-image-list">
          {items.length ? items.map((item) => (
            <label
              key={item.key}
              className="storage-image-row"
              onMouseEnter={() => setPreviewItem(item)}
              onMouseLeave={() => setPreviewItem((current) => current?.key === item.key ? null : current)}
            >
              <input type="checkbox" checked={selected.has(item.key)} onChange={(event) => toggleKey(item.key, event.target.checked)} />
              <span>
                <strong>{storageImageDisplayName(item)}</strong>
                <small>{kindsLabel(item, language)} · 引用 {item.reference_count} 处</small>
                <small>{item.label}</small>
              </span>
            </label>
          )) : (
            <p className="empty-hint">{busy ? t("读取中", language) : t("没有可管理的图片。", language)}</p>
          )}
        </div>
        {previewItem && (previewItem.preview_url || previewItem.preview_data_url) && (
          <div className="storage-hover-preview" aria-hidden="true">
            <img src={previewItem.preview_url || previewItem.preview_data_url} alt="" />
            <span>{previewItem.label}</span>
          </div>
        )}
      </div>
    </section>
  );
}
