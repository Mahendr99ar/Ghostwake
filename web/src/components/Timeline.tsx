import { useEffect, useRef } from "react";
import type { AlertSummary } from "../lib/api";
import { secondsSince } from "../lib/tracks";

interface Props {
  t0: string;
  duration: number; // seconds
  playhead: number;
  onSeek: (t: number) => void;
  playing: boolean;
  onPlay: (on: boolean) => void;
  scenes: string[]; // ISO times of radar passes
  alerts: AlertSummary[];
  selectedId: string | null;
}

const HOUR = 3600;

function label(t0: string, s: number) {
  const d = new Date(new Date(t0).getTime() + s * 1000);
  return d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
}

export function Timeline({ t0, duration, playhead, onSeek, playing, onPlay, scenes, alerts, selectedId }: Props) {
  const raf = useRef(0);

  // Replay at one hour of sea time per second of screen time.
  useEffect(() => {
    if (!playing) return;
    let last = performance.now();
    let cur = playhead >= duration ? 0 : playhead;
    const step = (now: number) => {
      cur += ((now - last) / 1000) * HOUR;
      last = now;
      if (cur >= duration) {
        onSeek(duration);
        onPlay(false);
        return;
      }
      onSeek(cur);
      raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf.current);
    // playhead is read once when play starts; the loop carries its own value forward.
  }, [playing]);

  const pct = (s: number) => `${Math.min(100, Math.max(0, (s / duration) * 100))}%`;
  const ticks = Array.from({ length: Math.floor(duration / (6 * HOUR)) + 1 }, (_, i) => i * 6 * HOUR);

  return (
    <div className="timeline">
      <button className="play" onClick={() => onPlay(!playing)} aria-label={playing ? "Pause replay" : "Play replay"}>
        {playing ? (
          <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden><rect x="2" y="1" width="3.5" height="12" fill="currentColor" /><rect x="8.5" y="1" width="3.5" height="12" fill="currentColor" /></svg>
        ) : (
          <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden><path d="M3 1 L13 7 L3 13 Z" fill="currentColor" /></svg>
        )}
      </button>

      <div className="tl-now" aria-live="off">{label(t0, playhead)} UTC</div>

      <div className="tl-track">
        <div className="tl-rail" />
        {ticks.map((s) => (
          <span key={s} className="tl-tick" style={{ left: pct(s) }}>{label(t0, s).split(", ")[1]}</span>
        ))}
        {scenes.map((iso) => (
          <span key={iso} className="tl-pass" style={{ left: pct(secondsSince(t0, iso)) }} title={`Radar pass, ${label(t0, secondsSince(t0, iso))} UTC`} />
        ))}
        {alerts.map((a) => (
          <button
            key={a.id}
            className={`tl-alert cat-${a.category} ${a.id === selectedId ? "is-on" : ""}`}
            style={{ left: pct(secondsSince(t0, a.start)) }}
            onClick={() => onSeek(secondsSince(t0, a.start))}
            aria-label={`Jump to ${a.summary}`}
            tabIndex={-1}
          />
        ))}
        <input
          className="tl-input"
          type="range"
          min={0}
          max={duration}
          step={60}
          value={playhead}
          onChange={(e) => onSeek(Number(e.target.value))}
          aria-label="Replay time"
          aria-valuetext={`${label(t0, playhead)} UTC`}
        />
      </div>
    </div>
  );
}
