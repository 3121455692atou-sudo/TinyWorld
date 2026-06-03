import type { AgentDetail, AgentListItem, EventItem, IdentityLibraryResult, InterventionAbilityCatalog, InterventionPackImportResult, Narration, PluginInstallResult, PresetCatalog, ToolCatalogSummary, World, WorldLocation, WorldMetrics, WorldPackImportResult, WorldRuntimeSettingsPayload } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? "http://127.0.0.1:8010" : "");

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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response, path));
  }
  return response.json() as Promise<T>;
}

async function upload<T>(path: string, formData: FormData): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { method: "POST", body: formData });
  if (!response.ok) {
    throw new Error(await errorMessage(response, path));
  }
  return response.json() as Promise<T>;
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
  worlds(params: { limit?: number; offset?: number } = {}) {
    const query = new URLSearchParams();
    if (params.limit) query.set("limit", String(params.limit));
    if (params.offset) query.set("offset", String(params.offset));
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
  getWorld(worldId: string) {
    return request<World>(`/api/worlds/${worldId}`);
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
  agent(worldId: string, agentId: string) {
    return request<AgentDetail>(`/api/worlds/${worldId}/agents/${agentId}`);
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
  events(worldId: string, query = "") {
    return request<{ events: EventItem[] }>(`/api/worlds/${worldId}/events${query}`);
  },
  eventTts(worldId: string, eventId: number) {
    return request<{ event_id: number; audio_data_url: string; cached: boolean }>(`/api/worlds/${worldId}/events/${eventId}/tts`, { method: "POST" });
  },
  narrations(worldId: string) {
    return request<{ narrations: Narration[] }>(`/api/worlds/${worldId}/narrator?limit=1000`);
  },
  metrics(worldId: string) {
    return request<WorldMetrics>(`/api/worlds/${worldId}/metrics`);
  },
  tools() {
    return request<ToolCatalogSummary & { tools: Array<{ tool_name: string; display_name: string }> }>("/api/tools");
  },
  summarize(worldId: string) {
    return request<{ narration_event_ids: number[] }>(`/api/worlds/${worldId}/narrator/summarize-now`, { method: "POST" });
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
