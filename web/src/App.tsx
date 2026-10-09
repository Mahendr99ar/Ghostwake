import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./lib/api";
import { secondsSince } from "./lib/tracks";
import { useTheme, type ThemePref } from "./lib/theme";
import { MapView } from "./components/MapView";
import { Queue, applyFilter, type QueueFilter } from "./components/Queue";
import { CasePanel } from "./components/CasePanel";
import { Timeline } from "./components/Timeline";

function replayLabel(iso?: string) {
  if (!iso) return "";
  const d = new Date(iso);
  const day = (n: number) => new Date(d.getTime() + n * 864e5).toLocaleDateString("en-GB", { day: "numeric", timeZone: "UTC" });
  const month = d.toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });
  return `${day(0)} to ${day(1)} ${month}`;
}

const THEMES: { id: ThemePref; label: string }[] = [
  { id: "auto", label: "Auto" },
  { id: "light", label: "Day" },
  { id: "dark", label: "Night" },
];

export default function App() {
  const qc = useQueryClient();
  const { pref, setPref, theme } = useTheme();
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 60_000 });
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });
  const alerts = useQuery({ queryKey: ["alerts"], queryFn: api.alerts });
  const tracks = useQuery({ queryKey: ["tracks"], queryFn: api.tracks, staleTime: Infinity });
  const detections = useQuery({ queryKey: ["detections"], queryFn: api.detections, staleTime: Infinity });
  const vessels = useQuery({ queryKey: ["vessels"], queryFn: api.vessels });

  const [filter, setFilter] = useState<QueueFilter>("open");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [playhead, setPlayhead] = useState(13 * 3600);
  const [playing, setPlaying] = useState(false);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const [mobileView, setMobileView] = useState<"queue" | "map">("queue");

  const selected = useQuery({
    queryKey: ["alert", selectedId],
    queryFn: () => api.alert(selectedId!),
    enabled: !!selectedId,
  });

  // A dark blip that fits a silent ship's track: fetch that ship's gap so the map can draw it.
  const linkedGapId = selected.data?.evidence?.possible_identity?.gap_alert as string | undefined;
  const linkedGap = useQuery({
    queryKey: ["alert", linkedGapId],
    queryFn: () => api.alert(linkedGapId!),
    enabled: !!linkedGapId,
  });

  const names = useMemo(() => new Map((vessels.data ?? []).map((v) => [v.mmsi, v.name])), [vessels.data]);
  const t0 = tracks.data?.t0 ?? null;
  const duration = useMemo(
    () => Math.max(3600, ...(tracks.data?.tracks ?? []).map((t) => t.t[t.t.length - 1] ?? 0)),
    [tracks.data],
  );
  const scenes = useMemo(() => [...new Set((detections.data ?? []).map((d) => d.ts))].sort(), [detections.data]);

  // The silent stretch, drawn as the dashed "ghost wake".
  const ghostLine = useMemo<[number, number][] | null>(() => {
    const a = selected.data;
    if (!a) return null;
    const gap = a.kind === "ais_gap" ? a : linkedGap.data;
    if (!gap?.evidence?.last_fix) return null;
    const { last_fix: l, next_fix: n } = gap.evidence;
    const line: [number, number][] = [[l.lon, l.lat]];
    if (a.kind === "dark_vessel") line.push([a.lon, a.lat]);
    line.push([n.lon, n.lat]);
    return line;
  }, [selected.data, linkedGap.data]);

  // Live updates: new alerts and reviews made by other analysts.
  useEffect(() => {
    let es: EventSource | null = null;
    try {
      es = new EventSource(api.streamUrl());
    } catch {
      return;
    }
    const refresh = () => qc.invalidateQueries({ queryKey: ["alerts"] });
    es.addEventListener("alert.created", (e) => {
      const { id } = JSON.parse((e as MessageEvent).data);
      setFresh((s) => new Set(s).add(id));
      refresh();
    });
    es.addEventListener("alert.reviewed", refresh);
    return () => es?.close();
  }, [qc]);

  const select = (id: string) => {
    setSelectedId(id);
    setMobileView("queue");
    setFresh((s) => {
      const n = new Set(s);
      n.delete(id);
      return n;
    });
    const a = alerts.data?.find((x) => x.id === id);
    if (a && t0) setPlayhead(Math.max(0, secondsSince(t0, a.start)));
  };

  // j / k to walk the queue, Escape to close the case. Analysts live on the keyboard.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      const list = applyFilter(alerts.data ?? [], filter);
      const i = list.findIndex((a) => a.id === selectedId);
      if (e.key === "j" && list.length) select(list[Math.min(list.length - 1, i + 1)].id);
      if (e.key === "k" && list.length) select(list[Math.max(0, i - 1)].id);
      if (e.key === "Escape") setSelectedId(null);
      if (e.key === " " && e.target === document.body) {
        e.preventDefault();
        setPlaying((p) => !p);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const loading = alerts.isLoading || tracks.isLoading;
  const failed = alerts.isError || tracks.isError;
  const run = health.data?.last_run;

  return (
    <div className={`app view-${mobileView} ${selectedId ? "has-case" : ""}`}>
      <header className="topbar">
        <div className="brand">
          <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden>
            <path d="M5 21c3 0 3-2 6-2s3 2 6 2 3-2 6-2" fill="none" style={{ stroke: "var(--sodium)" }} strokeWidth="2" strokeLinecap="round" strokeDasharray="3 3" />
            <circle cx="16" cy="12" r="5" fill="none" style={{ stroke: "var(--paper)" }} strokeWidth="2" />
          </svg>
          <span className="wordmark">GhostWake</span>
        </div>
        <p className="context">
          Gulf of Mannar and approaches
          {run && <span className="context-sub">Replay of {replayLabel(run.params.scenario_start)}, simulated data</span>}
        </p>
        {run && (
          <p className="provenance">
            {run.counts.vessels} vessels on AIS, {run.counts.scenes} radar passes, {run.cleaning.duplicates + run.cleaning.bad_position} bad rows removed
          </p>
        )}
        <div className="theme-switch" role="group" aria-label="Colour theme">
          {THEMES.map((t) => (
            <button
              key={t.id}
              aria-pressed={pref === t.id}
              onClick={() => setPref(t.id)}
              title={t.id === "auto" ? "Follow your device setting" : undefined}
            >
              {t.label}
            </button>
          ))}
        </div>
        <nav className="mobile-switch" aria-label="View">
          <button aria-pressed={mobileView === "queue"} onClick={() => setMobileView("queue")}>Alerts</button>
          <button aria-pressed={mobileView === "map"} onClick={() => setMobileView("map")}>Map</button>
        </nav>
      </header>

      <aside className="side">
        {failed ? (
          <div className="state-msg">
            <p>Can't reach the GhostWake API.</p>
            <p className="case-fine">Check that the backend is running and that VITE_API_URL points at it, then reload.</p>
          </div>
        ) : loading ? (
          <div className="state-msg"><p>Loading tracks and alerts</p></div>
        ) : selected.data ? (
          <CasePanel alert={selected.data} names={names} onClose={() => setSelectedId(null)} />
        ) : (
          <Queue
            alerts={alerts.data ?? []}
            names={names}
            filter={filter}
            onFilter={setFilter}
            selectedId={selectedId}
            onSelect={select}
            freshIds={fresh}
          />
        )}
      </aside>

      <main className="stage">
        <MapView
          tracks={tracks.data?.tracks ?? []}
          t0={t0}
          detections={detections.data ?? []}
          alerts={alerts.data ?? []}
          zones={meta.data?.zones ?? null}
          selected={selected.data ?? null}
          ghostLine={ghostLine}
          playhead={playhead}
          onPick={select}
          theme={theme}
        />
        <div className="legend" aria-label="Map key">
          <span><i className="k k-ship" /> Ship on AIS</span>
          <span><i className="k k-radar" /> Radar, matched</span>
          <span><i className="k k-dark" /> Radar, no AIS</span>
          <span><i className="k k-wake" /> Silent stretch</span>
          <span><i className="k k-imbl" /> IMBL (approx.)</span>
        </div>
        {t0 && (
          <Timeline
            t0={t0}
            duration={duration}
            playhead={playhead}
            onSeek={setPlayhead}
            playing={playing}
            onPlay={setPlaying}
            scenes={scenes}
            alerts={alerts.data ?? []}
            selectedId={selectedId}
          />
        )}
      </main>
    </div>
  );
}
