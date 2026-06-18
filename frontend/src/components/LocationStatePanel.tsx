import { ChevronDown, Home, Image as ImageIcon, List, MapPin, RefreshCw, StickyNote, Users } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { apiClient } from "../api/client";
import type { AgentListItem, EventItem, LeftSnapshot, World, WorldLocation, WorldLocationNotice } from "../api/types";
import { t, type UiLanguage } from "../i18n";
import { AgentAvatar } from "./AgentAvatar";

type LiveLocation = {
  location_id: string;
  name: string;
  description: string;
  color: string | null;
  neighbors: string[];
  tags: string[];
  is_private: boolean;
  capacity?: number | null;
  available_tools: string[];
  occupants: AgentListItem[];
  notice_board: WorldLocationNotice[];
  notice_count: number;
  item_count: number;
  source: "world" | "event" | "agent";
  order: number;
};

function isLiving(agent: AgentListItem): boolean {
  return agent.lifecycle_state !== "dead";
}

function nonEmptyString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function readDialogueAgentIds(payload: Record<string, unknown> | undefined): string[] {
  const ids = new Set<string>();
  const lines = payload?.dialogue_lines;
  if (!Array.isArray(lines)) return [];
  for (const line of lines) {
    if (!line || typeof line !== "object") continue;
    const record = line as Record<string, unknown>;
    for (const key of ["speaker_agent_id", "speaker_id", "agent_id", "target_agent_id", "listener_agent_id"]) {
      const value = nonEmptyString(record[key]);
      if (value) ids.add(value);
    }
  }
  return Array.from(ids);
}

function agentIdsFromEvent(event: EventItem, knownAgents: AgentListItem[]): string[] {
  const ids = new Set<string>();
  if (event.actor_agent_id) ids.add(event.actor_agent_id);
  if (event.target_agent_id) ids.add(event.target_agent_id);
  for (const id of readDialogueAgentIds(event.payload)) ids.add(id);

  const text = `${event.viewer_text ?? ""}\n${event.location_name ?? ""}`;
  if (text.trim()) {
    for (const agent of knownAgents) {
      const name = agent.display_name?.trim();
      if (name && text.includes(name)) ids.add(agent.agent_id);
    }
  }
  return Array.from(ids);
}

function parseWorldTimeLabel(label: string | null | undefined): number | null {
  if (!label) return null;
  const match = label.match(/第\s*(\d+)\s*天\s*(\d{1,2})[:：](\d{1,2})/);
  if (!match) return null;
  const day = Number(match[1]);
  const hour = Number(match[2]);
  const minute = Number(match[3]);
  if (![day, hour, minute].every(Number.isFinite)) return null;
  return Math.max(0, day - 1) * 1440 + hour * 60 + minute;
}

function eventClock(event: EventItem): number {
  const direct = Number(event.world_time);
  if (Number.isFinite(direct) && direct > 0) return direct;
  return parseWorldTimeLabel(event.world_time_label) ?? direct ?? 0;
}

function compareEventForLocationState(a: EventItem, b: EventItem): number {
  const timeDiff = eventClock(a) - eventClock(b);
  if (timeDiff !== 0) return timeDiff;
  return Number(a.event_id ?? 0) - Number(b.event_id ?? 0);
}

function readNestedString(record: Record<string, unknown> | undefined, path: string[]): string | null {
  let current: unknown = record;
  for (const key of path) {
    if (!current || typeof current !== "object") return null;
    current = (current as Record<string, unknown>)[key];
  }
  return nonEmptyString(current);
}

function inferLocationIdFromText(text: string, worldLocations: WorldLocation[]): string | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  let best: { locationId: string; index: number; weight: number } | null = null;
  for (const location of worldLocations) {
    const name = location.name?.trim();
    if (!name) continue;
    const index = trimmed.lastIndexOf(name);
    if (index < 0) continue;
    const before = trimmed.slice(Math.max(0, index - 12), index);
    const after = trimmed.slice(index + name.length, index + name.length + 8);
    const weight = /走向|来到|去了|去|回到|进入|抵达|走进|在|确认自己在|回到了|前往|到了/.test(before) || /里|中|附近|。|，/.test(after) ? 1 : 0;
    if (!best || weight > best.weight || (weight === best.weight && index > best.index)) {
      best = { locationId: location.location_id, index, weight };
    }
  }
  return best?.locationId ?? null;
}

function eventLocationId(event: EventItem, worldLocations: WorldLocation[]): string | null {
  const direct = nonEmptyString(event.location_id);
  if (direct) return direct;
  const fromStateDelta =
    readNestedString(event.state_delta, ["location", "after"]) ||
    readNestedString(event.state_delta, ["location", "to"]) ||
    readNestedString(event.state_delta, ["location", "location_id"]);
  if (fromStateDelta) return fromStateDelta;
  const fromPayload =
    readNestedString(event.payload, ["destination_location_id"]) ||
    readNestedString(event.payload, ["to_location_id"]) ||
    readNestedString(event.payload, ["home_location_id"]) ||
    readNestedString(event.payload, ["location_id"]);
  if (fromPayload) return fromPayload;
  return inferLocationIdFromText(event.viewer_text ?? "", worldLocations);
}

function latestClockLabel(world: World, events: EventItem[]): string {
  const latest = events.length ? [...events].sort(compareEventForLocationState).at(-1) : null;
  return latest?.world_time_label || world.world_time_label || "";
}

function activityLabel(agent: AgentListItem): string {
  if (agent.lifecycle_state === "critical") return "危险";
  if (agent.activity_status?.label) return agent.activity_status.label;
  return "在场";
}

function isHomeLocation(location: Pick<LiveLocation, "location_id" | "name"> & Partial<Pick<LiveLocation, "is_private" | "tags">>): boolean {
  const name = location.name.trim();
  const localKey = localLocationKey(location.location_id);
  const tags = new Set(location.tags ?? []);
  if (/^\d+号小屋$/.test(name)) return true;
  if (/^(村民房间|甜心小屋|情感小屋)\d+$/.test(name)) return true;
  if (/^(villager_room|sweet_room|emotion_room)[_: -]?\d+$/i.test(localKey)) return true;
  return Boolean((location.is_private || tags.has("private")) && /小屋|住所|房间|家/.test(name));
}

function mergeAgentAvatarHints(
  baseAgents: AgentListItem[],
  imageSources: AgentListItem[],
): AgentListItem[] {
  const imageSourceById = new Map(imageSources.map((agent) => [agent.agent_id, agent]));
  return baseAgents.map((agent) => {
    const source = imageSourceById.get(agent.agent_id);
    const sourceAvatar = source?.avatar_hint ?? {};
    const agentAvatar = agent.avatar_hint ?? {};
    const imageDataUrl = agentAvatar.image_data_url || sourceAvatar.image_data_url;
    if (!imageDataUrl) return agent;
    return {
      ...agent,
      avatar_hint: {
        ...sourceAvatar,
        ...agentAvatar,
        image_data_url: imageDataUrl,
      },
    };
  });
}

function makeEmptyLocation(locationId: string, order: number): LiveLocation {
  return {
    location_id: locationId,
    name: locationId.split(":").at(-1) || locationId,
    description: "",
    color: null,
    neighbors: [],
    tags: [],
    is_private: false,
    available_tools: [],
    occupants: [],
    notice_board: [],
    notice_count: 0,
    item_count: 0,
    source: "event",
    order,
  };
}

function mergeWorldLocation(target: LiveLocation, location: WorldLocation): LiveLocation {
  return {
    ...target,
    name: location.name || target.name,
    description: location.description || target.description,
    color: location.color ?? target.color,
    neighbors: location.neighbors ?? target.neighbors,
    tags: location.tags ?? target.tags,
    is_private: Boolean(location.is_private),
    capacity: location.capacity,
    available_tools: location.available_tools ?? [],
    notice_board: location.notice_board ?? [],
    notice_count: location.notice_count ?? location.notice_board?.length ?? 0,
    item_count: location.item_count ?? location.items?.length ?? 0,
    source: "world",
  };
}

function buildLiveLocations(
  worldLocations: WorldLocation[],
  agents: AgentListItem[],
  events: EventItem[],
): LiveLocation[] {
  const locations = new Map<string, LiveLocation>();
  const ensureLocation = (locationId: string, order = 100_000) => {
    let location = locations.get(locationId);
    if (!location) {
      location = makeEmptyLocation(locationId, order + locations.size);
      locations.set(locationId, location);
    }
    return location;
  };

  worldLocations.forEach((location, index) => {
    locations.set(
      location.location_id,
      mergeWorldLocation(makeEmptyLocation(location.location_id, index), location),
    );
  });

  const agentById = new Map(agents.map((agent) => [agent.agent_id, agent]));
  const currentLocationByAgent = new Map<string, string>();

  for (const agent of agents) {
    if (!isLiving(agent) || !agent.location_id) continue;
    currentLocationByAgent.set(agent.agent_id, agent.location_id);
    const location = ensureLocation(agent.location_id);
    if (location.source !== "world") {
      if (!isUnknownLocationName(agent.location_name)) location.name = agent.location_name;
      location.color = agent.location_color ?? location.color;
      location.is_private = location.is_private || /小屋|住所|房间|家/.test(location.name);
      location.source = "agent";
    }
  }

  const sortedEvents = [...events].sort(compareEventForLocationState);
  for (const event of sortedEvents) {
    if (event.visibility_scope === "system") continue;
    const locationId = eventLocationId(event, worldLocations);
    if (!locationId) continue;
    const location = ensureLocation(locationId);
    const eventLocationName = nonEmptyString(event.location_name);
    if (eventLocationName && !isUnknownLocationName(eventLocationName)) location.name = eventLocationName;
    if (event.location_color) location.color = event.location_color;
    if (location.source !== "world") location.source = "event";

    for (const agentId of agentIdsFromEvent(event, agents)) {
      const agent = agentById.get(agentId);
      if (!agent || !isLiving(agent)) continue;
      currentLocationByAgent.set(agentId, locationId);
    }
  }

  for (const location of locations.values()) location.occupants = [];
  for (const agent of agents) {
    if (!isLiving(agent)) continue;
    const locationId = currentLocationByAgent.get(agent.agent_id) || agent.location_id;
    if (!locationId) continue;
    ensureLocation(locationId).occupants.push(agent);
  }

  return Array.from(locations.values()).sort((a, b) => {
    const occupiedDiff = Number(b.occupants.length > 0) - Number(a.occupants.length > 0);
    if (occupiedDiff !== 0) return occupiedDiff;
    if (a.order !== b.order) return a.order - b.order;
    return a.name.localeCompare(b.name, "zh-Hans-CN");
  });
}

function colorForLocation(location: LiveLocation, index: number): string {
  return location.color || ["#43a5ff", "#35b779", "#8b5cf6", "#d89b28", "#2aa4a4", "#d84c71"][index % 6];
}

const INTERNAL_MAP_LOCATION_KEYS = new Set(["hot_spring_men", "hot_spring_women", "hot_spring_mixed"]);

type MapTheme = {
  id: "modern" | "werewolf";
  imageUrl: string;
  layout: Record<string, { x: number; y: number }>;
  labels?: Record<string, string>;
  showPathOverlay?: boolean;
  internalKeys?: Set<string>;
  residentialLink?: {
    label: string;
    x: number;
    y: number;
    path?: { x1: number; y1: number; x2: number; y2: number };
  };
};

const MODERN_MAP_LAYOUT: Record<string, { x: number; y: number }> = {
  central_square: { x: 50, y: 39 },
  cafeteria: { x: 50, y: 15 },
  market: { x: 82, y: 18 },
  library: { x: 20, y: 38 },
  workshop: { x: 79, y: 38 },
  medical_room: { x: 16, y: 60 },
  garden: { x: 75, y: 58 },
  lake: { x: 18, y: 79 },
  cabin: { x: 20, y: 9 },
  campfire: { x: 14, y: 29 },
  notice_board: { x: 50, y: 53 },
  hot_spring_lobby: { x: 77, y: 80 },
  jail: { x: 50, y: 72 },
};

const WEREWOLF_MAP_LAYOUT: Record<string, { x: number; y: number }> = {
  village_square: { x: 50, y: 44 },
  discussion_hall: { x: 52, y: 25 },
  voting_room: { x: 76, y: 31 },
  dormitory: { x: 25, y: 28 },
  seer_room: { x: 20, y: 47 },
  guard_room: { x: 74, y: 47 },
  morgue: { x: 23, y: 63 },
  cafeteria: { x: 58, y: 65 },
  vending_machine: { x: 84, y: 68 },
  hot_spring: { x: 73, y: 83 },
  wolf_den: { x: 19, y: 80 },
};

const MAP_THEMES: Record<MapTheme["id"], MapTheme> = {
  modern: {
    id: "modern",
    imageUrl: "/location-map-default.png",
    layout: MODERN_MAP_LAYOUT,
    labels: {
      central_square: "中央广场",
      cafeteria: "公共食堂",
      market: "集市",
      library: "图书馆",
      workshop: "工作坊",
      medical_room: "医务室",
      garden: "花园",
      lake: "湖边",
      cabin: "林间小屋",
      campfire: "篝火营地",
      notice_board: "布告栏",
      hot_spring_lobby: "温泉前厅",
      jail: "临时看守所",
    },
    internalKeys: INTERNAL_MAP_LOCATION_KEYS,
    residentialLink: {
      label: "住宅区",
      x: 50,
      y: 10,
      path: { x1: 50, y1: 39, x2: 50, y2: -4 },
    },
  },
  werewolf: {
    id: "werewolf",
    imageUrl: "/location-map-werewolf.png",
    layout: WEREWOLF_MAP_LAYOUT,
    labels: {
      village_square: "村庄广场",
      discussion_hall: "村庄会议厅",
      voting_room: "议事侧厅",
      seer_room: "安静小屋",
      guard_room: "值守小屋",
      morgue: "医务间",
      wolf_den: "林间隐蔽处",
      cafeteria: "村庄食堂",
      vending_machine: "自动售货机",
      hot_spring: "村外温泉",
      dormitory: "集体宿舍",
    },
  },
};

const WORLDVIEW_MAP_THEME_IDS: Partial<Record<string, MapTheme["id"] | null>> = {
  fast_modern_worldview: "modern",
  default_modern_worldview: "modern",
  werewolf_game_worldview: "werewolf",
  sweet_romance_worldview: null,
  pure_emotion_worldview: null,
};

function localLocationKey(locationId: string): string {
  return locationId.split(":").at(-1) || locationId;
}

function isUnknownLocationName(name: string | null | undefined): boolean {
  const trimmed = name?.trim();
  return !trimmed || trimmed === "未知地点" || trimmed === "未知";
}

function displayLocationName(location: Pick<LiveLocation, "location_id" | "name">, theme: MapTheme | null): string {
  const fallback = theme?.labels?.[localLocationKey(location.location_id)];
  if (fallback && isUnknownLocationName(location.name)) return fallback;
  return location.name || fallback || localLocationKey(location.location_id);
}

function mapThemeForWorld(world: World, locations: WorldLocation[]): MapTheme | null {
  const worldviewId = nonEmptyString(world.settings?.worldview_id);
  const configuredThemeId = worldviewId ? WORLDVIEW_MAP_THEME_IDS[worldviewId] : undefined;
  if (configuredThemeId !== undefined) return configuredThemeId ? MAP_THEMES[configuredThemeId] : null;
  if (world.settings?.werewolf_mode_enabled) return MAP_THEMES.werewolf;
  if (worldviewId) return null;

  const localKeys = new Set(locations.map((location) => localLocationKey(location.location_id)));
  if (localKeys.has("village_square") && localKeys.has("discussion_hall")) return MAP_THEMES.werewolf;
  if (localKeys.has("central_square") && localKeys.has("cafeteria")) return MAP_THEMES.modern;
  return null;
}

function isMapLocation(location: LiveLocation, theme: MapTheme | null): boolean {
  if (!theme) return false;
  const key = localLocationKey(location.location_id);
  return !isHomeLocation(location) && !(theme.internalKeys ?? INTERNAL_MAP_LOCATION_KEYS).has(key) && Boolean(theme.layout[key]);
}

function formatNoticeTime(notice: WorldLocationNotice): string {
  if (notice.world_time_label) return notice.world_time_label;
  const minutes = Number(notice.world_time ?? NaN);
  if (!Number.isFinite(minutes) || minutes <= 0) return "";
  const day = Math.floor(minutes / 1440) + 1;
  const minuteOfDay = minutes % 1440;
  const hour = Math.floor(minuteOfDay / 60);
  const minute = minuteOfDay % 60;
  return `第${day}天 ${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

export function LocationStatePanel({
  world,
  locations,
  agents,
  events,
  eventVersion,
  clockLabelOverride,
  totalOccupantsOverride,
  focusLocationRequest,
  language = "zh",
  refreshing = false,
  lastRefreshLabel = "",
  onRefresh,
}: {
  world: World;
  locations: WorldLocation[];
  agents: AgentListItem[];
  events: EventItem[];
  eventVersion?: string | number;
  clockLabelOverride?: string;
  totalOccupantsOverride?: number;
  focusLocationRequest?: { locationId: string; nonce: number } | null;
  language?: UiLanguage;
  refreshing?: boolean;
  lastRefreshLabel?: string;
  onRefresh?: () => void;
}) {
  const [openLocationId, setOpenLocationId] = useState<string | null>(null);
  const [mapOpen, setMapOpen] = useState(true);
  const [locationListOpen, setLocationListOpen] = useState(false);
  const [homeListOpen, setHomeListOpen] = useState(false);
  const [snapshotOverride, setSnapshotOverride] = useState<LeftSnapshot | null>(null);
  const [fullAgents, setFullAgents] = useState<AgentListItem[]>([]);

  useEffect(() => {
    if (!world.world_id) return;
    let cancelled = false;
    let inFlight: AbortController | null = null;
    const loadSnapshot = async () => {
      if (cancelled || inFlight) return;
      inFlight = new AbortController();
      try {
        const snapshot = await apiClient.leftSnapshot(world.world_id, {
          signal: inFlight.signal,
        });
        if (!cancelled && snapshot.world.world_id === world.world_id) {
          setSnapshotOverride(snapshot);
        }
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
      } finally {
        inFlight = null;
      }
    };
    void loadSnapshot();
    const timer = window.setInterval(loadSnapshot, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      inFlight?.abort();
    };
  }, [world.world_id]);

  useEffect(() => {
    if (!world.world_id) return;
    let cancelled = false;
    apiClient.agents(world.world_id).then((result) => {
      if (!cancelled) setFullAgents(result.agents);
    }).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [world.world_id]);

  const effectiveWorld = snapshotOverride?.world ?? world;
  const effectiveLocations = snapshotOverride?.locations ?? locations;
  const effectiveAgents = useMemo(
    () =>
      mergeAgentAvatarHints(
        snapshotOverride?.agents ?? agents,
        [...fullAgents, ...agents],
      ),
    [agents, fullAgents, snapshotOverride?.agents],
  );
  const liveLocations = useMemo(
    () => buildLiveLocations(effectiveLocations, effectiveAgents, events),
    [effectiveLocations, effectiveAgents, events, eventVersion],
  );
  const mapTheme = useMemo(
    () => mapThemeForWorld(effectiveWorld, effectiveLocations),
    [effectiveWorld, effectiveLocations],
  );
  const mapLocations = useMemo(
    () => liveLocations.filter((location) => isMapLocation(location, mapTheme)),
    [liveLocations, mapTheme],
  );
  const shouldShowMap = Boolean(mapTheme && mapLocations.length);
  const publicLocations = useMemo(
    () => liveLocations.filter((location) => !isHomeLocation(location)),
    [liveLocations],
  );
  const homeLocations = useMemo(
    () => liveLocations.filter(isHomeLocation),
    [liveLocations],
  );
  const mapPathSegments = useMemo(() => {
    const mapKeys = new Set(mapLocations.map((location) => localLocationKey(location.location_id)));
    const seen = new Set<string>();
    const segments: Array<{ from: { x: number; y: number }; to: { x: number; y: number } }> = [];
    if (!mapTheme) return segments;
    for (const location of mapLocations) {
      const fromKey = localLocationKey(location.location_id);
      const from = mapTheme.layout[fromKey];
      if (!from) continue;
      for (const neighborId of location.neighbors) {
        const toKey = localLocationKey(neighborId);
        if (!mapKeys.has(toKey)) continue;
        const to = mapTheme.layout[toKey];
        if (!to) continue;
        const pairKey = [fromKey, toKey].sort().join(":");
        if (seen.has(pairKey)) continue;
        seen.add(pairKey);
        segments.push({ from, to });
      }
    }
    return segments;
  }, [mapLocations, mapTheme]);
  const clockLabel =
    snapshotOverride?.world.world_time_label ||
    clockLabelOverride ||
    latestClockLabel(effectiveWorld, events);
  const totalOccupants =
    snapshotOverride
      ? effectiveAgents.filter(isLiving).length
      : typeof totalOccupantsOverride === "number"
      ? totalOccupantsOverride
      : liveLocations.reduce((sum, location) => sum + location.occupants.length, 0);
  const selectedLocation = openLocationId
    ? liveLocations.find((location) => location.location_id === openLocationId) ?? null
    : null;
  const selectedLocationIndex = selectedLocation
    ? liveLocations.findIndex((location) => location.location_id === selectedLocation.location_id)
    : -1;
  const selectedLocationColor =
    selectedLocation && selectedLocationIndex >= 0
      ? colorForLocation(selectedLocation, selectedLocationIndex)
      : "#43a5ff";
  const selectedLocationIsHome = selectedLocation ? isHomeLocation(selectedLocation) : false;
  const selectedNotes = selectedLocation?.notice_board ?? [];

  useEffect(() => {
    if (!focusLocationRequest?.locationId) return;
    const target = liveLocations.find((location) => location.location_id === focusLocationRequest.locationId);
    setOpenLocationId(target?.location_id ?? focusLocationRequest.locationId);
    if (!target) return;
    if (isMapLocation(target, mapTheme)) {
      setMapOpen(true);
      return;
    }
    setLocationListOpen(true);
    if (isHomeLocation(target)) setHomeListOpen(true);
  }, [focusLocationRequest?.nonce]);

  useEffect(() => {
    setMapOpen(shouldShowMap);
    setLocationListOpen(!shouldShowMap);
    setHomeListOpen(false);
    setOpenLocationId(null);
  }, [effectiveWorld.world_id, mapTheme?.id, shouldShowMap]);

  const selectedLocationCard = selectedLocation ? (
    <article
      key={selectedLocation.location_id}
      className={[
        "live-location-detail-card",
        "live-location-detail-panel",
        selectedLocationIsHome ? "home-location" : "",
      ].filter(Boolean).join(" ")}
      style={{ "--location-color": selectedLocationColor } as CSSProperties}
    >
      <div className="live-location-detail-heading">
        {!selectedLocationIsHome && <span className="live-location-color" />}
        <strong className="live-location-detail-name">{t(displayLocationName(selectedLocation, mapTheme), language)}</strong>
      </div>
      <div className="live-location-detail-grid">
        <div>
          <span className="detail-label">{t("现在这里", language)}</span>
          <strong><span className="live-location-detail-count">{selectedLocation.occupants.length}</span> {t("人", language)}</strong>
        </div>
        <div>
          <span className="detail-label">{t("地点类型", language)}</span>
          <strong>{selectedLocation.is_private ? t("私人地点", language) : t("公共地点", language)}</strong>
        </div>
        <div>
          <span className="detail-label">{t("纸条", language)}</span>
          <strong>{selectedNotes.length ? selectedNotes.length : t("没有", language)}</strong>
        </div>
        <div>
          <span className="detail-label">{t("物品", language)}</span>
          <strong>{selectedLocation.item_count || t("没有", language)}</strong>
        </div>
      </div>

      <div className="live-location-section">
        <div className="live-location-section-title"><Users size={13} />{t("有哪些人", language)}</div>
        {selectedLocation.occupants.length ? (
          <div className="live-location-occupants">
            {selectedLocation.occupants.map((agent) => (
              <div className="live-location-occupant" key={agent.agent_id}>
                <AgentAvatar agent={agent} />
                <span>
                  <strong>{agent.display_name}</strong>
                  {!selectedLocationIsHome && <small>{activityLabel(agent)}</small>}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="live-location-empty">{t("现在没有人在这里。", language)}</p>
        )}
      </div>

      <div className="live-location-section">
        <div className="live-location-section-title"><MapPin size={13} />{t("这个地点是干嘛的", language)}</div>
        <p className="live-location-description">
          {selectedLocation.description ? t(selectedLocation.description, language) : t("暂无地点说明。", language)}
        </p>
        {selectedLocation.tags.length > 0 && (
          <div className="live-location-tags">
            {selectedLocation.tags.slice(0, 8).map((tag) => <span key={tag}>{tag}</span>)}
          </div>
        )}
      </div>

      <div className="live-location-section">
        <div className="live-location-section-title"><StickyNote size={13} />{t("留言纸条", language)}</div>
        {selectedNotes.length ? (
          <div className="live-location-notes">
            {selectedNotes.slice(-6).reverse().map((notice, noteIndex) => {
              const timeLabel = formatNoticeTime(notice);
              return (
                <blockquote key={`${selectedLocation.location_id}:notice:${noteIndex}`}>
                  <p>{notice.content}</p>
                  <footer>
                    {notice.author_name || t("匿名", language)}{timeLabel ? ` · ${timeLabel}` : ""}
                  </footer>
                </blockquote>
              );
            })}
          </div>
        ) : (
          <p className="live-location-empty">{t("这里没有留下纸条。", language)}</p>
        )}
      </div>
    </article>
  ) : null;

  return (
    <section className="panel live-location-panel">
      <div className="panel-heading live-location-heading">
        <div className="panel-title-stack">
          <h2>{t("地点", language)}</h2>
          <span className="live-location-clock">{clockLabel}</span>
        </div>
        {onRefresh && (
          <button
            type="button"
            className="mini-refresh-button"
            disabled={refreshing}
            onClick={onRefresh}
            title={t("刷新事件流和地点", language)}
          >
            <RefreshCw size={14} className={refreshing ? "spin-icon" : ""} />
            <span>{refreshing ? t("刷新中", language) : t("刷新", language)}</span>
          </button>
        )}
      </div>
      <div className="live-location-subline">
        <span>{t("跟随事件流", language)}</span>
        <span>{t("在场", language)} {totalOccupants}</span>
        {lastRefreshLabel && <span>{lastRefreshLabel}</span>}
      </div>
      <div className="live-location-list">
        {liveLocations.length ? (
          <>
            {shouldShowMap && (
              <button
                type="button"
                className="live-location-section-toggle"
                onClick={() => setMapOpen((value) => !value)}
                aria-expanded={mapOpen}
              >
                <span><ImageIcon size={14} />{t("地点图片", language)}</span>
                <ChevronDown size={14} className={mapOpen ? "chevron open" : "chevron"} />
              </button>
            )}
            {shouldShowMap && mapOpen && mapTheme && (
              <div className="live-location-map-card">
                <div
                  className={["live-location-map-art", `theme-${mapTheme.id}`].join(" ")}
                  role="img"
                  aria-label={t("地点图片", language)}
                  style={{ "--location-map-image": `url("${mapTheme.imageUrl}")` } as CSSProperties}
                >
                  {mapTheme.showPathOverlay && (
                    <svg className="live-location-map-paths" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                      {mapTheme.residentialLink?.path && (
                        <line
                          x1={mapTheme.residentialLink.path.x1}
                          y1={mapTheme.residentialLink.path.y1}
                          x2={mapTheme.residentialLink.path.x2}
                          y2={mapTheme.residentialLink.path.y2}
                          className="residential-path"
                        />
                      )}
                      {mapPathSegments.map((segment) => (
                        <line
                          key={`${segment.from.x}:${segment.from.y}-${segment.to.x}:${segment.to.y}`}
                          x1={segment.from.x}
                          y1={segment.from.y}
                          x2={segment.to.x}
                          y2={segment.to.y}
                        />
                      ))}
                    </svg>
                  )}
                  {mapTheme.residentialLink && (
                    <div
                      className="live-location-map-residential-link"
                      style={{
                        "--residential-x": `${mapTheme.residentialLink.x}%`,
                        "--residential-y": `${mapTheme.residentialLink.y}px`,
                      } as CSSProperties}
                    >
                      <Home size={13} />
                      <span>{t(mapTheme.residentialLink.label, language)}</span>
                    </div>
                  )}
                  {mapLocations.map((location) => {
                    const locationIndex = liveLocations.findIndex((item) => item.location_id === location.location_id);
                    const isOpen = openLocationId === location.location_id;
                    const key = localLocationKey(location.location_id);
                    const layout = mapTheme.layout[key];
                    const color = colorForLocation(location, locationIndex >= 0 ? locationIndex : 0);
                    return (
                      <button
                        type="button"
                        key={location.location_id}
                        className={[
                          "live-location-map-marker",
                          isOpen ? "active" : "",
                        ].filter(Boolean).join(" ")}
                        style={{
                          "--location-color": color,
                          "--marker-x": `${layout.x}%`,
                          "--marker-y": `${layout.y}%`,
                        } as CSSProperties}
                        onClick={() => setOpenLocationId(isOpen ? null : location.location_id)}
                        aria-pressed={isOpen}
                      >
                        <span className="live-location-map-dot" />
                        <span className="live-location-map-label">{t(displayLocationName(location, mapTheme), language)}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            <button
              type="button"
              className="live-location-section-toggle"
              onClick={() => setLocationListOpen((value) => !value)}
              aria-expanded={locationListOpen}
            >
              <span><List size={14} />{t("地点列表", language)}</span>
              <ChevronDown size={14} className={locationListOpen ? "chevron open" : "chevron"} />
            </button>
            {locationListOpen && (
              <div className="live-location-tabs" role="tablist" aria-label={t("地点列表", language)}>
                {publicLocations.map((location) => {
                  const locationIndex = liveLocations.findIndex((item) => item.location_id === location.location_id);
                  const isOpen = openLocationId === location.location_id;
                  const color = colorForLocation(location, locationIndex >= 0 ? locationIndex : 0);
                  const style = { "--location-color": color } as CSSProperties;
                  return (
                    <button
                      type="button"
                      className={[
                        "live-location-tab",
                        isOpen ? "active" : "",
                      ].filter(Boolean).join(" ")}
                      key={location.location_id}
                      style={style}
                      role="tab"
                      onClick={() => setOpenLocationId(isOpen ? null : location.location_id)}
                      aria-expanded={isOpen}
                      aria-selected={isOpen}
                    >
                      <span className="live-location-tab-title">
                        <span className="live-location-color" />
                        <span className="live-location-name">{t(displayLocationName(location, mapTheme), language)}</span>
                      </span>
                      <span className="live-location-count" title={t("当前人数", language)}>
                        <Users size={12} aria-hidden="true" />
                        <span className="live-location-count-value">{location.occupants.length}</span>
                      </span>
                      <ChevronDown size={13} className={isOpen ? "chevron open" : "chevron"} />
                    </button>
                  );
                })}
                {homeLocations.length > 0 && (
                  <div className="live-location-home-group">
                    <button
                      type="button"
                      className="live-location-home-toggle"
                      onClick={() => setHomeListOpen((value) => !value)}
                      aria-expanded={homeListOpen}
                    >
                      <span><Home size={14} />{t("角色小屋", language)}</span>
                      <span className="live-location-count">
                        <Users size={12} aria-hidden="true" />
                        {homeLocations.reduce((sum, location) => sum + location.occupants.length, 0)}
                      </span>
                      <ChevronDown size={13} className={homeListOpen ? "chevron open" : "chevron"} />
                    </button>
                    {homeListOpen && (
                      <div className="live-location-home-tabs">
                        {homeLocations.map((location) => {
                          const isOpen = openLocationId === location.location_id;
                          return (
                            <button
                              type="button"
                              className={[
                                "live-location-tab",
                                "home-location",
                                isOpen ? "active" : "",
                              ].filter(Boolean).join(" ")}
                              key={location.location_id}
                              role="tab"
                              onClick={() => setOpenLocationId(isOpen ? null : location.location_id)}
                              aria-expanded={isOpen}
                              aria-selected={isOpen}
                            >
                              <span className="live-location-tab-title">
                                <span className="live-location-name">{t(displayLocationName(location, mapTheme), language)}</span>
                              </span>
                              <span className="live-location-count" title={t("当前人数", language)}>
                                <Users size={12} aria-hidden="true" />
                                <span className="live-location-count-value">{location.occupants.length}</span>
                              </span>
                              <ChevronDown size={13} className={isOpen ? "chevron open" : "chevron"} />
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
            {selectedLocationCard}
          </>
        ) : (
          <div className="live-location-empty-card">{t("暂无地点", language)}</div>
        )}
      </div>
    </section>
  );
}
