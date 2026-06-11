export type ConfigHistoryKind = "imageGeneration" | "narrator" | "providers" | "runtime" | "llmGeneration";

export type ConfigHistoryItem = {
  id: string;
  kind: ConfigHistoryKind;
  name: string;
  pinned: boolean;
  order: number;
  createdAt: string;
  updatedAt: string;
  data: Record<string, unknown>;
};

const STORAGE_KEY = "tiny_living_world_config_history_v1";

export const CONFIG_HISTORY_KIND_LABELS: Record<ConfigHistoryKind, string> = {
  imageGeneration: "生图配置",
  narrator: "解说配置",
  providers: "提供商配置",
  runtime: "运行设置",
  llmGeneration: "LLM 输出参数"
};

export function loadConfigHistory(): ConfigHistoryItem[] {
  try {
    const raw = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "[]");
    if (!Array.isArray(raw)) return [];
    return raw
      .map(normalizeConfigHistoryItem)
      .filter(Boolean) as ConfigHistoryItem[];
  } catch {
    return [];
  }
}

export function saveConfigHistory(items: ConfigHistoryItem[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, 500)));
  } catch {
    // localStorage can be unavailable in private contexts.
  }
}

export function configHistoryForKind(kind: ConfigHistoryKind): ConfigHistoryItem[] {
  return sortConfigHistory(loadConfigHistory().filter((item) => item.kind === kind));
}

export function upsertConfigHistory(kind: ConfigHistoryKind, name: string, data: Record<string, unknown>): ConfigHistoryItem {
  const now = new Date().toISOString();
  const items = loadConfigHistory();
  const cleanName = name.trim() || CONFIG_HISTORY_KIND_LABELS[kind];
  const dataKey = stableConfigDataKey(data);
  const existing = items.find((item) => item.kind === kind && stableConfigDataKey(item.data) === dataKey)
    ?? items.find((item) => item.kind === kind && item.name === cleanName);
  const item: ConfigHistoryItem = existing
    ? { ...existing, name: cleanName, data, updatedAt: now }
    : {
      id: `${kind}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`,
      kind,
      name: cleanName,
      pinned: false,
      order: Math.min(0, ...items.map((entry) => Number(entry.order) || 0)) - 1,
      createdAt: now,
      updatedAt: now,
      data
    };
  const withoutDuplicates = items.filter((entry) => {
    if (entry.id === existing?.id) return false;
    return !(entry.kind === kind && stableConfigDataKey(entry.data) === dataKey);
  });
  saveConfigHistory([item, ...withoutDuplicates]);
  return item;
}

export function sortConfigHistory(items: ConfigHistoryItem[]): ConfigHistoryItem[] {
  return [...items].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
    const orderDelta = (Number(a.order) || 0) - (Number(b.order) || 0);
    if (orderDelta) return orderDelta;
    return String(b.updatedAt || "").localeCompare(String(a.updatedAt || ""));
  });
}

function normalizeConfigHistoryItem(raw: unknown): ConfigHistoryItem | null {
  if (!raw || typeof raw !== "object") return null;
  const data = raw as Record<string, unknown>;
  const kind = String(data.kind || "") as ConfigHistoryKind;
  if (!Object.hasOwn(CONFIG_HISTORY_KIND_LABELS, kind)) return null;
  const payload = data.data && typeof data.data === "object" && !Array.isArray(data.data) ? data.data as Record<string, unknown> : {};
  return {
    id: String(data.id || `${kind}_${Math.random().toString(36).slice(2)}`),
    kind,
    name: String(data.name || CONFIG_HISTORY_KIND_LABELS[kind]),
    pinned: Boolean(data.pinned),
    order: Number.isFinite(Number(data.order)) ? Number(data.order) : 0,
    createdAt: String(data.createdAt || data.updatedAt || new Date().toISOString()),
    updatedAt: String(data.updatedAt || data.createdAt || new Date().toISOString()),
    data: payload
  };
}

function stableConfigDataKey(value: unknown): string {
  return JSON.stringify(normalizeForStableKey(value));
}

function normalizeForStableKey(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalizeForStableKey);
  if (!value || typeof value !== "object") return value;
  const record = value as Record<string, unknown>;
  const normalized: Record<string, unknown> = {};
  for (const key of Object.keys(record).sort()) {
    const item = record[key];
    if (typeof item === "undefined") continue;
    normalized[key] = normalizeForStableKey(item);
  }
  return normalized;
}
