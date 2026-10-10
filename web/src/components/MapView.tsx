import { useEffect, useMemo, useRef } from "react";
import maplibregl, { type GeoJSONSource, type StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { PathLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { TripsLayer } from "@deck.gl/geo-layers";
import { PathStyleExtension, type PathStyleExtensionProps } from "@deck.gl/extensions";
import type { AlertDetail, AlertSummary, Detection, Track } from "../lib/api";
import { positionAt, secondsSince } from "../lib/tracks";

// Colours are repeated from styles.css because deck.gl wants RGB arrays, not CSS variables.
// Night is the chart room; day borrows from printed nautical charts: pale water, buff land.
type RGB = [number, number, number];
interface Palette {
  sea: string; land: string; coast: string; border: string; zone: string; flare: string;
  seaglass: RGB; ink: RGB; sodium: RGB; flareRgb: RGB;
  trackAlpha: number; labelAlpha: number;
}

const PALETTES: Record<"light" | "dark", Palette> = {
  dark: {
    sea: "#0B1C2B", land: "#17324A", coast: "#2B4A64", border: "#2B4A64", zone: "#8FB8B2", flare: "#E4574B",
    seaglass: [143, 184, 178], ink: [230, 225, 211], sodium: [240, 163, 58], flareRgb: [228, 87, 75],
    trackAlpha: 38, labelAlpha: 150,
  },
  light: {
    sea: "#DCE8EE", land: "#E8DFC6", coast: "#9DB2BC", border: "#B9A887", zone: "#2C7A72", flare: "#C23B2E",
    seaglass: [44, 122, 114], ink: [19, 40, 58], sodium: [181, 101, 10], flareRgb: [194, 59, 46],
    trackAlpha: 60, labelAlpha: 190,
  },
};

const PORTS: { name: string; at: [number, number] }[] = [
  { name: "Thoothukudi", at: [78.195, 8.755] },
  { name: "Rameswaram", at: [79.318, 9.278] },
  { name: "Vizhinjam", at: [76.98, 8.37] },
  { name: "Kollam", at: [76.56, 8.87] },
  { name: "Colombo", at: [79.84, 6.95] },
];

// OpenFreeMap serves OpenMapTiles vector data with no API key. If it can't be reached the
// map still works: sea and land are close in tone, so the data reads fine on a plain field.
const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

function styleFor(c: Palette): StyleSpecification {
  return {
    version: 8,
    sources: {
      omt: { type: "vector", url: "https://tiles.openfreemap.org/planet" },
      zones: { type: "geojson", data: EMPTY },
    },
    layers: [
      { id: "land", type: "background", paint: { "background-color": c.land } },
      { id: "sea", type: "fill", source: "omt", "source-layer": "water", paint: { "fill-color": c.sea } },
      { id: "coast", type: "line", source: "omt", "source-layer": "water", paint: { "line-color": c.coast, "line-width": 0.7 } },
      {
        id: "borders", type: "line", source: "omt", "source-layer": "boundary",
        filter: ["all", ["==", ["get", "admin_level"], 2], ["!=", ["get", "maritime"], 1]],
        paint: { "line-color": c.border, "line-width": 1 },
      },
      { id: "mpa-fill", type: "fill", source: "zones", filter: ["==", ["get", "kind"], "protected"],
        paint: { "fill-color": c.zone, "fill-opacity": 0.09 } },
      { id: "mpa-line", type: "line", source: "zones", filter: ["==", ["get", "kind"], "protected"],
        paint: { "line-color": c.zone, "line-opacity": 0.6, "line-width": 1 } },
      { id: "imbl", type: "line", source: "zones", filter: ["==", ["get", "kind"], "boundary"],
        paint: { "line-color": c.flare, "line-width": 1.4, "line-dasharray": [6, 4], "line-opacity": 0.85 } },
    ],
  };
}

const reduceMotion = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

interface Props {
  tracks: Track[];
  t0: string | null;
  detections: Detection[];
  alerts: AlertSummary[];
  zones: GeoJSON.FeatureCollection | null;
  selected: AlertDetail | null;
  ghostLine: [number, number][] | null;
  playhead: number;
  onPick: (alertId: string) => void;
  theme: "light" | "dark";
}

export function MapView({ tracks, t0, detections, alerts, zones, selected, ghostLine, playhead, onPick, theme }: Props) {
  const c = PALETTES[theme];
  const themeRef = useRef(theme);
  themeRef.current = theme;
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const overlay = useRef<MapboxOverlay | null>(null);
  const ready = useRef(false);
  const pulse = useRef(0);
  const draw = useRef<() => void>(() => {});
  const geo = useRef<() => void>(() => {});

  // Which alert should a click on a ship or a blip open?
  const byMmsi = useMemo(() => {
    const m = new Map<string, string>();
    for (const a of alerts) if (a.mmsi && !m.has(a.mmsi)) m.set(a.mmsi, a.id);
    return m;
  }, [alerts]);
  const byDetection = useMemo(() => new Map(alerts.filter((a) => a.detection_id).map((a) => [a.detection_id!, a.id])), [alerts]);

  useEffect(() => {
    if (!box.current) return;
    const m = new maplibregl.Map({
      container: box.current,
      style: styleFor(c),
      center: [78.6, 8.4],
      zoom: 6.6,
      // The basemap's own TileJSON already carries the OpenFreeMap / OpenStreetMap credit,
      // so we don't add our own copy of it.
      attributionControl: { compact: true },
      dragRotate: false,
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    const ov = new MapboxOverlay({ interleaved: false, layers: [] });
    m.addControl(ov);
    // The style is parsed even when the basemap tiles can't be fetched, so our own
    // sources are there to fill as soon as it is.
    // No basemap (offline, or tiles blocked on this network): paint the whole field as sea
    // instead of land, so the tracks still sit on water.
    m.on("error", (e: { sourceId?: string }) => {
      if (e.sourceId === "omt" && m.getLayer("land")) {
        m.setPaintProperty("land", "background-color", PALETTES[themeRef.current].sea);
      }
    });
    // A theme switch replaces the whole style, which empties our zones source, so
    // refill it every time the style changes.
    m.on("styledata", () => {
      ready.current = true;
      geo.current();
    });
    // Keep the credit folded into its (i) button so it never sits on top of the timeline.
    m.once("load", () => {
      box.current?.querySelector(".maplibregl-ctrl-attrib")?.classList.remove("maplibregl-compact-show");
    });
    // The map lives in a panel that can be hidden on phones; follow its real size.
    const ro = new ResizeObserver(() => m.resize());
    ro.observe(box.current);
    map.current = m;
    overlay.current = ov;
    return () => {
      ready.current = false;
      ro.disconnect();
      m.remove();
    };
  }, []);

  geo.current = () => {
    const m = map.current;
    if (!m || !ready.current) return;
    (m.getSource("zones") as GeoJSONSource | undefined)?.setData(zones ?? EMPTY);
  };

  useEffect(() => geo.current(), [zones]);

  const firstTheme = useRef(true);
  useEffect(() => {
    if (firstTheme.current) {
      firstTheme.current = false;
      return;
    }
    map.current?.setStyle(styleFor(c), { diff: false });
  }, [theme]);

  useEffect(() => {
    if (!selected || !map.current) return;
    const opts = { center: [selected.lon, selected.lat] as [number, number], zoom: Math.max(map.current.getZoom(), 8.2) };
    reduceMotion ? map.current.jumpTo(opts) : map.current.flyTo({ ...opts, speed: 1.4 });
  }, [selected?.id]);

  // Layers are rebuilt on every change. With a few thousand points this is cheap,
  // and it keeps the drawing logic in one readable function.
  draw.current = () => {
    if (!overlay.current) return;
    const focus = new Set<string>();
    if (selected?.mmsi) focus.add(selected.mmsi);
    const other = selected?.evidence?.other_mmsi;
    if (other) focus.add(other);

    const heads = tracks
      .map((tr) => ({ mmsi: tr.mmsi, at: positionAt(tr, playhead) }))
      .filter((h): h is { mmsi: string; at: [number, number] } => h.at !== null);

    const dets = t0
      ? detections.map((d) => ({ ...d, near: Math.abs(secondsSince(t0, d.ts) - playhead) < 3 * 3600 }))
      : [];
    const p = pulse.current;

    overlay.current.setProps({
      layers: [
        new PathLayer<Track>({
          id: "history",
          data: tracks,
          getPath: (d) => d.path,
          getColor: (d) => (focus.has(d.mmsi) ? [...c.ink, 150] : [...c.seaglass, c.trackAlpha]),
          getWidth: (d) => (focus.has(d.mmsi) ? 1.6 : 1),
          widthUnits: "pixels",
          updateTriggers: { getColor: [...focus, theme], getWidth: [...focus] },
        }),
        new TripsLayer<Track>({
          id: "trails",
          data: tracks,
          getPath: (d) => d.path,
          getTimestamps: (d) => d.t,
          getColor: c.seaglass,
          currentTime: playhead,
          trailLength: 3 * 3600,
          fadeTrail: true,
          widthMinPixels: 2,
          capRounded: true,
        }),
        // The ghost wake: where a silent ship must have gone. Drawn above everything else.
        new PathLayer<[number, number][], PathStyleExtensionProps<[number, number][]>>({
          id: "ghost-wake",
          data: ghostLine ? [ghostLine] : [],
          getPath: (d) => d,
          getColor: [...c.sodium, 255],
          getWidth: 3,
          widthUnits: "pixels",
          capRounded: true,
          getDashArray: [2, 2.5],
          dashJustified: true,
          extensions: [new PathStyleExtension({ dash: true })],
        }),
        new ScatterplotLayer<Detection & { near: boolean }>({
          id: "radar",
          data: dets,
          pickable: true,
          stroked: true,
          filled: false,
          radiusUnits: "pixels",
          getPosition: (d) => [d.lon, d.lat],
          getRadius: (d) => (d.matched_mmsi ? 5 : 7 + (d.near ? 3 * p : 0)),
          getLineColor: (d) =>
            d.matched_mmsi ? [...c.seaglass, d.near ? 170 : 60] : [...c.sodium, d.near ? 255 : 100],
          getLineWidth: (d) => (d.matched_mmsi ? 1 : 2),
          lineWidthUnits: "pixels",
          updateTriggers: { getRadius: [p, playhead], getLineColor: [playhead, theme] },
          onClick: ({ object }) => {
            const id = object && byDetection.get(object.id);
            if (id) onPick(id);
          },
        }),
        new ScatterplotLayer<{ mmsi: string; at: [number, number] }>({
          id: "ships",
          data: heads,
          pickable: true,
          radiusUnits: "pixels",
          getPosition: (d) => d.at,
          getRadius: (d) => (focus.has(d.mmsi) ? 5 : 3),
          getFillColor: (d) => (focus.has(d.mmsi) ? c.ink : [...c.seaglass, 230]),
          stroked: true,
          getLineColor: (d) => (focus.has(d.mmsi) ? [...c.sodium, 255] : [0, 0, 0, 0]),
          getLineWidth: 2,
          lineWidthUnits: "pixels",
          updateTriggers: { getRadius: [...focus], getFillColor: [...focus, theme], getLineColor: [...focus, theme] },
          onClick: ({ object }) => {
            const id = object && byMmsi.get(object.mmsi);
            if (id) onPick(id);
          },
        }),
        new ScatterplotLayer({
          id: "selected",
          data: selected ? [selected] : [],
          radiusUnits: "pixels",
          stroked: true,
          filled: false,
          getPosition: (d: AlertDetail) => [d.lon, d.lat],
          getRadius: 14,
          getLineColor: selected?.category === "safety" ? [...c.flareRgb, 255] : [...c.ink, 220],
          getLineWidth: 1.5,
          lineWidthUnits: "pixels",
        }),
        new TextLayer({
          id: "ports",
          data: PORTS,
          getPosition: (d) => d.at,
          getText: (d) => d.name,
          getColor: [...c.ink, 150],
          getSize: 12,
          fontFamily: "Archivo, system-ui, sans-serif",
          getTextAnchor: "start",
          getPixelOffset: [8, 0],
        }),
      ],
      getCursor: ({ isHovering }) => (isHovering ? "pointer" : "grab"),
    });
  };

  useEffect(() => draw.current(), [tracks, t0, detections, selected, ghostLine, playhead, byMmsi, byDetection, theme]);

  // The one piece of ambient motion: unexplained radar blips breathe slowly.
  useEffect(() => {
    if (reduceMotion) return;
    let raf = 0;
    let last = 0;
    const tick = (now: number) => {
      if (now - last > 50) {
        pulse.current = (Math.sin(now / 700) + 1) / 2;
        draw.current();
        last = now;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  return <div ref={box} className="map" role="application" aria-label="Map of vessel tracks and radar detections" />;
}
