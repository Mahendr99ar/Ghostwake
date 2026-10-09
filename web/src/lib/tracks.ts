import type { Track } from "./api";

// Where was this ship at time t (seconds since the replay start)?
// Returns null when t falls in a silence longer than maxGapS, because drawing a ship
// where we have no fix is exactly the mistake this whole tool exists to avoid.
export function positionAt(track: Track, t: number, maxGapS = 1800): [number, number] | null {
  const ts = track.t;
  if (!ts.length || t < ts[0] || t > ts[ts.length - 1]) return null;
  let lo = 0;
  let hi = ts.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (ts[mid] <= t) lo = mid;
    else hi = mid;
  }
  if (ts[hi] - ts[lo] > maxGapS) return null;
  const f = ts[hi] === ts[lo] ? 0 : (t - ts[lo]) / (ts[hi] - ts[lo]);
  const [x0, y0] = track.path[lo];
  const [x1, y1] = track.path[hi];
  return [x0 + f * (x1 - x0), y0 + f * (y1 - y0)];
}

export function secondsSince(t0: string, iso: string): number {
  return (new Date(iso).getTime() - new Date(t0).getTime()) / 1000;
}
