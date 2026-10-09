import type { AlertSummary, Status } from "../lib/api";
import { KIND_LABEL, utcTime } from "../lib/vocab";
import { Glyph } from "./Glyph";

export type QueueFilter = "open" | "safety" | "escalated" | "dismissed" | "all";

const FILTERS: { id: QueueFilter; label: string }[] = [
  { id: "open", label: "To review" },
  { id: "safety", label: "Crew safety" },
  { id: "escalated", label: "Escalated" },
  { id: "dismissed", label: "Dismissed" },
  { id: "all", label: "All" },
];

export function applyFilter(alerts: AlertSummary[], f: QueueFilter): AlertSummary[] {
  if (f === "all") return alerts;
  if (f === "safety") return alerts.filter((a) => a.category === "safety");
  return alerts.filter((a) => a.status === (f as Status));
}

interface Props {
  alerts: AlertSummary[];
  names: Map<string, string>;
  filter: QueueFilter;
  onFilter: (f: QueueFilter) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  freshIds: Set<string>;
}

export function Queue({ alerts, names, filter, onFilter, selectedId, onSelect, freshIds }: Props) {
  const shown = applyFilter(alerts, filter);
  return (
    <section className="queue" aria-label="Alert queue">
      <div className="queue-filters" role="tablist">
        {FILTERS.map((f) => {
          const n = applyFilter(alerts, f.id).length;
          return (
            <button
              key={f.id}
              role="tab"
              aria-selected={filter === f.id}
              className={`chip ${filter === f.id ? "is-on" : ""} ${f.id === "safety" && n ? "has-safety" : ""}`}
              onClick={() => onFilter(f.id)}
            >
              {f.label} <span className="count">{n}</span>
            </button>
          );
        })}
      </div>

      {shown.length === 0 ? (
        <p className="queue-empty">
          {filter === "open" ? "Queue is clear. New alerts appear here as the pipeline finds them." : "Nothing here yet."}
        </p>
      ) : (
        <ol className="queue-list">
          {shown.map((a) => (
            <li key={a.id}>
              <button
                className={`row sev-${a.severity} cat-${a.category} ${a.id === selectedId ? "is-selected" : ""} ${freshIds.has(a.id) ? "is-fresh" : ""}`}
                onClick={() => onSelect(a.id)}
                aria-current={a.id === selectedId}
              >
                <span className="row-glyph"><Glyph kind={a.kind} /></span>
                <span className="row-main">
                  <span className="row-title">
                    {a.mmsi ? names.get(a.mmsi) ?? a.mmsi : "Unidentified"}
                    <span className="row-kind">{KIND_LABEL[a.kind] ?? a.kind}</span>
                  </span>
                  <span className="row-sub">{a.summary}</span>
                  <span className="row-when">{utcTime(a.start)}</span>
                </span>
                <span className="row-score" aria-label={`Score ${Math.round(a.score)}`}>{Math.round(a.score)}</span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
