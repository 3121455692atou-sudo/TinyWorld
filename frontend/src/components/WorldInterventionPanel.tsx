import { MapPin, Sparkles, Upload, Wand2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { AgentListItem, InterventionAbility, WorldLocation } from "../api/types";
import { t, type UiLanguage } from "../i18n";
import { FileDropZone } from "./FileDropZone";

const FALLBACK_ABILITIES: InterventionAbility[] = [
  { ability_id: "move_agent", name: "移动居民", description: "把居民移动到指定地点；不同能力会要求不同对象。", requires_actor: true, requires_target: false, requires_location: true },
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
  onImportPack,
  language = "zh"
}: {
  agents: AgentListItem[];
  locations: WorldLocation[];
  busy: boolean;
  abilities?: InterventionAbility[];
  onApply: (payload: Record<string, unknown>) => Promise<void>;
  onImportPack?: (file: File) => Promise<void>;
  language?: UiLanguage;
}) {
  const livingAgents = useMemo(() => agents.filter((agent) => agent.lifecycle_state !== "dead"), [agents]);
  const publicLocations = useMemo(() => locations.filter((location) => !location.is_private), [locations]);
  const actionList = useMemo(() => abilities.length ? abilities : FALLBACK_ABILITIES, [abilities]);
  const [action, setAction] = useState(actionList[0]?.ability_id ?? "move_agent");
  const [actorAgentId, setActorAgentId] = useState(livingAgents[0]?.agent_id ?? "");
  const [targetAgentId, setTargetAgentId] = useState("");
  const [locationId, setLocationId] = useState(publicLocations[0]?.location_id ?? "");
  const [note, setNote] = useState("");
  const selectedAction = useMemo(
    () => actionList.find((item) => item.ability_id === action) ?? actionList[0] ?? FALLBACK_ABILITIES[0],
    [action, actionList],
  );
  const selectedDescription = selectedAction.description || "居民不会知道玩家存在；世界只会把它记录成偶然、恍惚、心动或无法解释的奇迹。";
  const otherActionNames = actionList.filter((item) => item.ability_id !== selectedAction.ability_id).slice(0, 4).map((item) => item.name);
  const abilitySummary = otherActionNames.length
    ? `${actionList.length} 种能力 · 当前：${selectedAction.name} · 还可切换：${otherActionNames.join("、")}${actionList.length > otherActionNames.length + 1 ? "等" : ""}`
    : `${actionList.length} 种能力 · 当前：${selectedAction.name}`;
  const usableTargetAgents = livingAgents.filter((agent) => agent.agent_id !== actorAgentId);
  const canSubmit = Boolean((!selectedAction.requires_actor || actorAgentId) && (!selectedAction.requires_target || targetAgentId) && (!selectedAction.requires_location || locationId));
  const targetLabel = action === "miracle_pregnancy" ? "伴侣" : "对象";
  const [expanded, setExpanded] = useState(false);
  const toggleLabel = expanded ? t("收起", language) : t("展开", language);

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
    <section className={`panel world-intervention-panel ${expanded ? "is-expanded" : "is-collapsed"}`} data-expanded={expanded ? "true" : "false"}>
      <div className="panel-heading intervention-heading">
        <div className="intervention-heading-copy">
          <h2>{t("影响世界", language)}</h2>
          <small title={abilitySummary}>{t(abilitySummary, language)}</small>
        </div>
        <button type="button" className="icon-button text-icon-button intervention-drawer-toggle" aria-expanded={expanded} aria-label={toggleLabel} title={toggleLabel} onClick={() => setExpanded((value) => !value)}>
          <span className="intervention-toggle-label">{toggleLabel}</span>
          <span className="intervention-toggle-arrow" aria-hidden="true">{expanded ? "⌄" : "⌃"}</span>
        </button>
      </div>
      {!expanded && <div className="intervention-collapsed-actions" aria-label={t("可快速选择的影响能力", language)}>
        {actionList.slice(0, 6).map((item) => (
          <button key={item.ability_id} type="button" className={item.ability_id === action ? "active" : ""} onClick={() => {
            setAction(item.ability_id);
            setExpanded(true);
          }}>
            {t(item.name, language)}
          </button>
        ))}
        {actionList.length > 6 && (
          <button type="button" onClick={() => setExpanded(true)}>{t(`还有 ${actionList.length - 6} 种`, language)}</button>
        )}
      </div>}
      {expanded && <div className="intervention-body">
        <div className="intervention-form">
          <div className="intervention-controls">
            <label>
              <span>{t("方式", language)}</span>
              <select value={action} onChange={(event) => setAction(event.target.value)}>
                {actionList.map((item) => <option key={item.ability_id} value={item.ability_id}>{t(item.name, language)}</option>)}
              </select>
            </label>
            {selectedAction.requires_actor && (
              <label>
                <span>{t(action === "miracle_pregnancy" || action === "miracle_birth" ? "怀孕人" : "居民", language)}</span>
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
                <span>{t(targetLabel, language)}</span>
                <select value={targetAgentId} onChange={(event) => setTargetAgentId(event.target.value)}>
                  <option value="">{t(targetLabel === "伴侣" ? "选择伴侣" : "选择对象", language)}</option>
                  {usableTargetAgents.map((agent) => <option key={agent.agent_id} value={agent.agent_id}>{agent.display_name}</option>)}
                </select>
              </label>
            )}
            {selectedAction.requires_location && (
              <label>
                <span>{t("地点", language)}</span>
                <select value={locationId} onChange={(event) => setLocationId(event.target.value)}>
                  {publicLocations.map((location) => <option key={location.location_id} value={location.location_id}>{t(location.name, language)}</option>)}
                </select>
              </label>
            )}
            <div className="intervention-actions">
              {onImportPack && (
                <FileDropZone
                  accept=".json,.zip,.aiworld.intervention.json"
                  buttonClassName="icon-button text-icon-button"
                  onFile={onImportPack}
                  hint={t("可拖入", language)}
                >
                  <Upload size={15} />
                  <span>{t("导入能力", language)}</span>
                </FileDropZone>
              )}
              <button type="button" disabled={busy || !canSubmit} onClick={submit}>
                <Wand2 size={15} />
                <span>{busy ? t("处理中", language) : t("施加", language)}</span>
              </button>
            </div>
          </div>
          <label className="intervention-note">
            <span>{t("附加描述", language)}</span>
            <input value={note} placeholder={t("可选，会被自然地写进事件里", language)} onChange={(event) => setNote(event.target.value)} />
          </label>
        </div>
        <div className="intervention-help">
          <p className="intervention-hint">
            <Sparkles size={14} />
            <span key={selectedAction.ability_id}>{t(selectedDescription, language)}</span>
          </p>
          {selectedAction.requires_location && (
            <p className="intervention-hint">
              <MapPin size={14} />
              <span>{t("移动只改变当前位置，不会改写居民自己的记忆和性格。", language)}</span>
            </p>
          )}
        </div>
      </div>}
    </section>
  );
}
