import type { EventItem } from "../api/types";

export function ConversationViewer({ events }: { events: EventItem[] }) {
  return (
    <section className="panel conversation-panel">
      <h2>对话</h2>
      <div className="conversation-list">
        {events.slice(-8).map((event) => (
          <p key={event.event_id}>
            <span>{event.world_time_label}</span>
            {typeof event.payload?.speech === "string" ? `“${event.payload.speech}”` : event.viewer_text}
          </p>
        ))}
      </div>
    </section>
  );
}
