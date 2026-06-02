import { MapPin, Sparkles, Upload, Wand2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { AgentListItem, InterventionAbility, WorldLocation } from "../api/types";
import { FileDropZone } from "./FileDropZone";

const FALLBACK_ABILITIES: InterventionAbility[] = [
  { ability_id: "move_agent", name: "移动居民", description: "把居民移动到指定地点。", requires_actor: true, requires_target: false, requires_location: true },
  { ability_id: "meteor_kill", name: "陨石坠落", description: "让陨石坠落杀死指定居民。", requires_actor: true, requires_target: false, requires_location: false },
  { ability_id: "love_one_way", name: "单向心动", description: "让一名居民对另一名居民心动。", requires_actor: true, requires_target: true, requires_location: false },
  { ability_id: "love_mutual", name: "相互心动", description: "让两名居民彼此心动。", requires_actor: true, requires_target: true, requires_location: false },
  { ability_id: "miracle_pregnancy", name: "奇迹怀孕", description: "让指定居民怀孕；对象作为伴侣记录。", requires_actor: true, requires_target: true, requires_location: false },
  { ability_id: "miracle_birth", name: "奇迹诞生", description: "让指定怀孕人生下孩子。", requires_actor: true, requires_target: false, requires_location: false }
];

export function WorldInterventionPanel({
  agents,
  locations,
  busy,
  abilities = FALLBACK_ABILITIES,
  onApply,
  onImportPack
}: {
  agents: AgentListItem[];
  locations: WorldLocation[];
  busy: boolean;
  abilities?: InterventionAbility[];
  onApply: (payload: Record<string, unknown>) => Promise<void>;
  onImportPack?: (file: File) => Promise<void>;
}) {
  const livingAgents = useMemo(() => agents.filter((agent) => agent.lifecycle_state !== "dead"), [agents]);
  const publicLocations = useMemo(() => locations.filter((location) => !location.is_private), [locations]);
  const actionList = abilities.length ? abilities : FALLBACK_ABILITIES;
  const [action, setAction] = useState(actionList[0]?.ability_id ?? "move_agent");
  const [actorAgentId, setActorAgentId] = useState(livingAgents[0]?.agent_id ?? "");
  const [targetAgentId, setTargetAgentId] = useState("");
  const [locationId, setLocationId] = useState(publicLocations[0]?.location_id ?? "");
  const [note, setNote] = useState("");
  const selectedAction = actionList.find((item) => item.ability_id === action) ?? actionList[0] ?? FALLBACK_ABILITIES[0];
  const usableTargetAgents = livingAgents.filter((agent) => agent.agent_id !== actorAgentId);
  const canSubmit = Boolean((!selectedAction.requires_actor || actorAgentId) && (!selectedAction.requires_target || targetAgentId) && (!selectedAction.requires_location || locationId));
  const targetLabel = action === "miracle_pregnancy" ? "伴侣" : "对象";

  useEffect(() => {
    if (!actorAgentId && livingAgents[0]) setActorAgentId(livingAgents[0].agent_id);
    if (!locationId && publicLocations[0]) setLocationId(publicLocations[0].location_id);
    if (targetAgentId && targetAgentId === actorAgentId) setTargetAgentId("");
    if (!actionList.some((item) => item.ability_id === action)) setAction(actionList[0]?.ability_id ?? "move_agent");
  }, [action, actionList, actorAgentId, livingAgents, locationId, publicLocations, targetAgentId]);

  const submit = async () => {
    if (!canSubmit) return;
    await onApply({
      action,
      actor_agent_id: selectedAction.requires_actor ? actorAgentId : undefined,
      target_agent_id: selectedAction.requires_target ? targetAgentId : undefined,
      location_id: selectedAction.requires_location ? locationId : undefined,
      note: note.trim() || undefined
    });
    setNote("");
  };

  return (
    <section className="panel world-intervention-panel">
      <div className="panel-heading">
        <h2>影响世界</h2>
      </div>
      <div className="intervention-body">
        <div className="intervention-form">
          <div className="intervention-controls">
            <label>
              <span>方式</span>
              <select value={action} onChange={(event) => setAction(event.target.value)}>
                {actionList.map((item) => <option key={item.ability_id} value={item.ability_id}>{item.name}</option>)}
              </select>
            </label>
            {selectedAction.requires_actor && (
              <label>
                <span>{action === "miracle_pregnancy" || action === "miracle_birth" ? "怀孕人" : "居民"}</span>
                <select value={actorAgentId} onChange={(event) => {
                  setActorAgentId(event.target.value);
                  if (event.target.value === targetAgentId) setTargetAgentId("");
                }}>
                  {livingAgents.map((agent) => <option key={agent.agent_id} value={agent.agent_id}>{agent.display_name}</option>)}
                </select>
              </label>
            )}
            {selectedAction.requires_target && (
              <label>
                <span>{targetLabel}</span>
                <select value={targetAgentId} onChange={(event) => setTargetAgentId(event.target.value)}>
                  <option value="">选择{targetLabel}</option>
                  {usableTargetAgents.map((agent) => <option key={agent.agent_id} value={agent.agent_id}>{agent.display_name}</option>)}
                </select>
              </label>
            )}
            {selectedAction.requires_location && (
              <label>
                <span>地点</span>
                <select value={locationId} onChange={(event) => setLocationId(event.target.value)}>
                  {publicLocations.map((location) => <option key={location.location_id} value={location.location_id}>{location.name}</option>)}
                </select>
              </label>
            )}
            <div className="intervention-actions">
              {onImportPack && (
                <FileDropZone
                  accept=".json,.zip,.aiworld.intervention.json"
                  buttonClassName="icon-button text-icon-button"
                  onFile={onImportPack}
                  hint="可拖入"
                >
                  <Upload size={15} />
                  <span>导入能力</span>
                </FileDropZone>
              )}
              <button type="button" disabled={busy || !canSubmit} onClick={submit}>
                <Wand2 size={15} />
                <span>{busy ? "处理中" : "施加"}</span>
              </button>
            </div>
          </div>
          <label className="intervention-note">
            <span>附加描述</span>
            <input value={note} placeholder="可选，会被自然地写进事件里" onChange={(event) => setNote(event.target.value)} />
          </label>
        </div>
        <div className="intervention-help">
          <p className="intervention-hint">
            <Sparkles size={14} />
            <span>{selectedAction.description || "居民不会知道玩家存在；世界只会把它记录成偶然、恍惚、心动或无法解释的奇迹。"}</span>
          </p>
          {selectedAction.requires_location && (
            <p className="intervention-hint">
              <MapPin size={14} />
              <span>移动只改变当前位置，不会改写居民自己的记忆和性格。</span>
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
