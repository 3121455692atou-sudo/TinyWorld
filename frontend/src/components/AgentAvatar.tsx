import type { AgentListItem } from "../api/types";

export function AgentAvatar({ agent, fallbackName = "?" }: { agent?: AgentListItem | null; fallbackName?: string }) {
  const imageDataUrl = agent?.avatar_hint?.image_data_url;
  const color = agent?.avatar_hint?.color ?? "#607d8b";
  const label = (agent?.display_name ?? fallbackName).slice(0, 1) || "?";
  return (
    <div className="avatar" style={{ background: color }}>
      {imageDataUrl ? <img src={imageDataUrl} alt="" /> : <span>{label}</span>}
    </div>
  );
}
