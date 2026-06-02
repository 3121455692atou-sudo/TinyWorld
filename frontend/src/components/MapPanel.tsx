import type { AgentListItem, WorldLocation } from "../api/types";

export function MapPanel({ agents, locations }: { agents: AgentListItem[]; locations: WorldLocation[] }) {
  const rows = locations.length
    ? locations
    : Array.from(new Map(agents.filter((agent) => agent.location_id && !agent.location_name.includes("小屋")).map((agent) => [agent.location_id as string, { location_id: agent.location_id as string, name: agent.location_name, color: agent.location_color, occupant_count: 0 } as WorldLocation])).values());
  return (
    <section className="panel map-panel">
      <h2>地点</h2>
      <div className="location-list">
        {rows.map((location) => {
          const count = location.occupant_count ?? agents.filter((agent) => agent.location_id === location.location_id).length;
          return (
            <div key={location.location_id} className="location-row" title={location.description}>
              <span>{location.name}<i style={{ backgroundColor: location.color ?? "#8a99a1" }} /></span>
              <strong>{count}</strong>
            </div>
          );
        })}
      </div>
    </section>
  );
}
