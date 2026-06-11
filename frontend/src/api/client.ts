import type { AgentDetail, AgentListItem, EventDeleteState, EventItem, IdentityLibraryResult, InterventionAbilityCatalog, InterventionPackImportResult, LeftSnapshot, Narration, PluginInstallResult, PresetCatalog, StorageImageResult, ToolCatalogSummary, World, WorldLocation, WorldMetrics, WorldPackImportResult, WorldRuntimeSettingsPayload } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? "http://127.0.0.1:8010" : "");
const REQUEST_TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS ?? 30_000);
const UPLOAD_TIMEOUT_MS = Number(import.meta.env.VITE_UPLOAD_TIMEOUT_MS ?? 120_000);

function modelIdFromItem(item: unknown): string | null {
  if (typeof item === "string") return item.trim() || null;
  if (!item || typeof item !== "object") return null;
  const record = item as Record<string, unknown>;
  for (const key of ["id", "name", "model"]) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function normalizeModelList(payload: unknown): string[] {
  let candidates: unknown[] = [];
  if (Array.isArray(payload)) {
    candidates = payload;
  } else if (payload && typeof payload === "object") {
    const record = payload as Record<string, unknown>;
    if (Array.isArray(record.models)) candidates = record.models;
    else if (Array.isArray(record.data)) candidates = record.data;
    else {
      const single = modelIdFromItem(record.model) ?? modelIdFromItem(record.id);
      return single ? [single] : [];
    }
  }

  const seen = new Set<string>();
  const models: string[] = [];
  for (const item of candidates) {
    const model = modelIdFromItem(item);
    if (model && !seen.has(model)) {
      seen.add(model);
      models.push(model);
    }
  }
  return models;
}

type RequestOptions = { signal?: AbortSignal };

function timeoutSignal(path: string, timeoutMs: number, externalSignal?: AbortSignal) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  const abortFromCaller = () => controller.abort();
  if (externalSignal) {
    if (externalSignal.aborted) {
      abortFromCaller();
    } else {
      externalSignal.addEventListener("abort", abortFromCaller, { once: true });
    }
  }
  return {
    signal: controller.signal,
    cleanup: () => {
      clearTimeout(timeoutId);
      externalSignal?.removeEventListener("abort", abortFromCaller);
    }
  };
}

function fetchErrorMessage(path: string, error: unknown, timeoutMs: number): string {
  if (error instanceof DOMException && error.name === "AbortError") {
    return `${path} 请求超时（${Math.round(timeoutMs / 1000)} 秒）。请确认后端地址、端口和 Docker 服务状态。`;
  }
  if (error instanceof TypeError) {
    return `${path} 请求失败：${error.message || "Failed to fetch"}。如果后端日志显示 200，但前端仍失败，通常是浏览器 CORS 或局域网访问来源未被后端允许。`;
  }
  return error instanceof Error ? error.message : String(error);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const { signal, cleanup } = timeoutSignal(path, REQUEST_TIMEOUT_MS, init?.signal ?? undefined);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      cache: "no-store",
      headers,
      ...init,
      signal
    });
    if (!response.ok) {
      throw new Error(await errorMessage(response, path));
    }
    return response.json() as Promise<T>;
  } catch (error) {
    throw new Error(fetchErrorMessage(path, error, REQUEST_TIMEOUT_MS));
  } finally {
    cleanup();
  }
}

async function upload<T>(path: string, formData: FormData): Promise<T> {
  const { signal, cleanup } = timeoutSignal(path, UPLOAD_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE}${path}`, { method: "POST", body: formData, cache: "no-store", signal });
    if (!response.ok) {
      throw new Error(await errorMessage(response, path));
    }
    return response.json() as Promise<T>;
  } catch (error) {
    throw new Error(fetchErrorMessage(path, error, UPLOAD_TIMEOUT_MS));
  } finally {
    cleanup();
  }
}

async function errorMessage(response: Response, path: string): Promise<string> {
  const text = await response.text();
  let detail = text.trim();
  try {
    const parsed = JSON.parse(text) as Record<string, unknown>;
    const rawDetail = parsed.detail ?? parsed.message ?? parsed.error;
    if (typeof rawDetail === "string") detail = rawDetail;
    else if (rawDetail) detail = JSON.stringify(rawDetail);
  } catch {
    // Non-JSON error body.
  }
  if (!detail || detail === "Internal Server Error") {
    detail = "后端内部错误。请查看后端日志获取堆栈。";
  }
  return `${path} 返回 ${response.status} ${response.statusText || ""}: ${detail}`.trim();
}

export const apiClient = {
  createWorld(payload: Record<string, unknown>) {
    return request<World>("/api/worlds", { method: "POST", body: JSON.stringify(payload) });
  },
  worlds(params: { limit?: number; offset?: number; q?: string; status?: string; worldview_id?: string; sort?: string } = {}) {
    const query = new URLSearchParams();
    if (params.limit) query.set("limit", String(params.limit));
    if (params.offset) query.set("offset", String(params.offset));
    if (params.q) query.set("q", params.q);
    if (params.status && params.status !== "all") query.set("status", params.status);
    if (params.worldview_id && params.worldview_id !== "all") query.set("worldview_id", params.worldview_id);
    if (params.sort) query.set("sort", params.sort);
    return request<{ worlds: World[]; total?: number; limit?: number; offset?: number }>(`/api/worlds${query.toString() ? `?${query.toString()}` : ""}`);
  },
  updateWorldSaveName(worldId: string, payload: { save_name: string }) {
    return request<World>(`/api/worlds/${worldId}/save-name`, { method: "PATCH", body: JSON.stringify(payload) });
  },
  deleteWorld(worldId: string) {
    return request<{ ok: boolean; world_id: string; deleted: Record<string, number> }>(`/api/worlds/${worldId}`, { method: "DELETE" });
  },
  updateWorldRuntimeSettings(worldId: string, payload: WorldRuntimeSettingsPayload) {
    return request<World>(`/api/worlds/${worldId}/runtime-settings`, { method: "PATCH", body: JSON.stringify(payload) });
  },
  presets() {
    return request<PresetCatalog>("/api/presets");
  },
  importWorldPack(file: File) {
    const formData = new FormData();
    formData.append("file", file);
    return upload<WorldPackImportResult>("/api/presets/worldpacks/import", formData);
  },
  importPlugin(file: File) {
    const formData = new FormData();
    formData.append("file", file);
    return upload<PluginInstallResult>("/api/plugins/import", formData);
  },
  installPluginFromUrl(url: string) {
    return request<PluginInstallResult>("/api/plugins/install-url", { method: "POST", body: JSON.stringify({ url }) });
  },
  interventionAbilities() {
    return request<InterventionAbilityCatalog>("/api/interventions");
  },
  importInterventionPack(file: File) {
    const formData = new FormData();
    formData.append("file", file);
    return upload<InterventionPackImportResult>("/api/interventions/import", formData);
  },
  async pullModels(payload: { base_url: string; api_key?: string }) {
    const result = await request<unknown>("/api/llm/models", { method: "POST", body: JSON.stringify(payload) });
    return { models: normalizeModelList(result) };
  },
  identityLibrary(limit = 200) {
    return request<IdentityLibraryResult>(`/api/identity-library?limit=${limit}`);
  },
  deleteIdentityLibraryItem(agentId: string) {
    return request<{ ok: boolean; agent_id: string; world_id: string; deleted: Record<string, number> }>(`/api/identity-library/${agentId}`, { method: "DELETE" });
  },
  storageImages(limit = 400) {
    return request<StorageImageResult>(`/api/storage/images?limit=${limit}`);
  },
  deleteStorageImages(keys: string[]) {
    return request<{ ok: boolean; deleted: string[]; deleted_count: number }>("/api/storage/images/delete", { method: "POST", body: JSON.stringify({ keys }) });
  },
  getWorld(worldId: string, options: RequestOptions = {}) {
    return request<World>(`/api/worlds/${worldId}`, { signal: options.signal });
  },
  leftSnapshot(worldId: string, options: RequestOptions = {}) {
    return request<LeftSnapshot>(`/api/worlds/${worldId}/left-snapshot?_=${Date.now()}`, { signal: options.signal });
  },
  start(worldId: string) {
    return request<World>(`/api/worlds/${worldId}/start`, { method: "POST" });
  },
  pause(worldId: string) {
    return request<World>(`/api/worlds/${worldId}/pause`, { method: "POST" });
  },
  step(worldId: string) {
    return request<{ event_ids: number[]; acted_agent_id: string | null }>(`/api/worlds/${worldId}/step`, { method: "POST" });
  },
  end(worldId: string) {
    return request<{ world: World; export_path: string }>(`/api/worlds/${worldId}/end`, { method: "POST" });
  },
  agents(worldId: string) {
    return request<{ agents: AgentListItem[] }>(`/api/worlds/${worldId}/agents`);
  },
  locations(worldId: string) {
    return request<{ locations: WorldLocation[] }>(`/api/worlds/${worldId}/locations`);
  },
  agent(worldId: string, agentId: string, options: RequestOptions = {}) {
    return request<AgentDetail>(`/api/worlds/${worldId}/agents/${agentId}`, { signal: options.signal });
  },
  updateAgentLlm(worldId: string, agentId: string, payload: Record<string, unknown>) {
    return request<AgentDetail>(`/api/worlds/${worldId}/agents/${agentId}/llm`, { method: "PATCH", body: JSON.stringify(payload) });
  },
  updateAgentProfile(worldId: string, agentId: string, payload: Record<string, unknown>) {
    return request<AgentDetail>(`/api/worlds/${worldId}/agents/${agentId}/profile`, { method: "PATCH", body: JSON.stringify(payload) });
  },
  applyIntervention(worldId: string, payload: Record<string, unknown>) {
    return request<{ ok: boolean; event_ids: number[]; world: World }>(`/api/worlds/${worldId}/interventions`, { method: "POST", body: JSON.stringify(payload) });
  },
  events(worldId: string, query = "", options: RequestOptions = {}) {
    return request<{ events: EventItem[]; image_wait_cutoff_event_id?: number | null; waiting_image_event_id?: number | null }>(`/api/worlds/${worldId}/events${query}`, { signal: options.signal });
  },
  eventDeleteState(worldId: string, options: RequestOptions = {}) {
    return request<EventDeleteState>(`/api/worlds/${worldId}/events/delete-state`, { signal: options.signal });
  },
  updateEventDeleteState(worldId: string, limit: number) {
    return request<EventDeleteState>(`/api/worlds/${worldId}/events/delete-state`, { method: "PATCH", body: JSON.stringify({ limit }) });
  },
  deleteEvents(worldId: string, eventIds: number[]) {
    return request<EventDeleteState & { ok: boolean; deleted_event_ids: number[] }>(`/api/worlds/${worldId}/events/delete`, { method: "POST", body: JSON.stringify({ event_ids: eventIds }) });
  },
  undoEventDelete(worldId: string) {
    return request<EventDeleteState & { ok: boolean; restored_event_ids: number[]; restored_original_event_ids: number[]; remapped_event_ids: Record<string, number> }>(`/api/worlds/${worldId}/events/undo-delete`, { method: "POST" });
  },
  updateEventText(worldId: string, eventId: number, text: string) {
    return request<{ ok: boolean; event: EventItem }>(`/api/worlds/${worldId}/events/${eventId}`, { method: "PATCH", body: JSON.stringify({ text }) });
  },
  eventTts(worldId: string, eventId: number) {
    return request<{ event_id: number; audio_data_url: string; cached: boolean }>(`/api/worlds/${worldId}/events/${eventId}/tts`, { method: "POST" });
  },
  narrations(worldId: string, options: RequestOptions = {}) {
    return request<{ narrations: Narration[] }>(`/api/worlds/${worldId}/narrator?limit=1000`, { signal: options.signal });
  },
  metrics(worldId: string, options: RequestOptions = {}) {
    return request<WorldMetrics>(`/api/worlds/${worldId}/metrics`, { signal: options.signal });
  },
  tools() {
    return request<ToolCatalogSummary & { tools: Array<{ tool_name: string; display_name: string }> }>("/api/tools");
  },
  summarize(worldId: string) {
    return request<{ narration_event_ids: number[] }>(`/api/worlds/${worldId}/narrator/summarize-now`, { method: "POST" });
  },
  generateImageNow(worldId: string) {
    return request<{ image_event_ids: number[] }>(`/api/worlds/${worldId}/image-generation/generate-now`, { method: "POST" });
  },
  generateImageFromPrompt(worldId: string, payload: { prompt: string; negative_prompt?: string; title?: string }) {
    return request<{ image_event_ids: number[] }>(`/api/worlds/${worldId}/image-generation/generate-prompt`, { method: "POST", body: JSON.stringify(payload) });
  },
  cancelImageGeneration(worldId: string, eventId: number) {
    return request<{ ok: boolean; event: EventItem }>(`/api/worlds/${worldId}/image-generation/${eventId}/cancel`, { method: "POST" });
  },
  rerunImageGeneration(worldId: string, eventId: number, payload: { prompt: string; negative_prompt?: string; overrides?: Record<string, unknown> }) {
    return request<{ ok: boolean; event: EventItem }>(`/api/worlds/${worldId}/image-generation/${eventId}/rerun`, { method: "POST", body: JSON.stringify(payload) });
  },
  exportUrl(worldId: string) {
    return `${API_BASE}/api/worlds/${worldId}/export`;
  },
  eventsExportUrl(worldId: string, query = "") {
    return `${API_BASE}/api/worlds/${worldId}/events/export${query}`;
  },
  agentPresetsExportUrl(worldId: string) {
    return `${API_BASE}/api/worlds/${worldId}/agents/export`;
  }
};
