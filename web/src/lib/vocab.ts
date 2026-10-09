// One vocabulary for the whole interface. The queue, the map legend and the case panel
// all read from here, so an alert is never called two different things.

export const KIND_LABEL: Record<string, string> = {
  dark_vessel: "Dark vessel",
  ais_gap: "AIS switched off",
  spoofing: "Position spoofing",
  rendezvous: "Meeting at sea",
  ban_period_fishing: "Fishing during the ban",
  protected_area_loitering: "Lingering in marine park",
  imbl_crossing: "Crossed the IMBL",
  imbl_proximity: "Near the IMBL",
};

export const SEVERITY_LABEL = { info: "Info", watch: "Watch", high: "High", critical: "Critical" } as const;

export function utcTime(iso: string): string {
  const d = new Date(iso);
  const day = d.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
  const hm = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
  return `${day}, ${hm} UTC`;
}

export function hoursBetween(a: string, b: string): number {
  return (new Date(b).getTime() - new Date(a).getTime()) / 3.6e6;
}

export function coord(lat: number, lon: number): string {
  const ns = lat >= 0 ? "N" : "S";
  const ew = lon >= 0 ? "E" : "W";
  return `${Math.abs(lat).toFixed(3)}° ${ns}, ${Math.abs(lon).toFixed(3)}° ${ew}`;
}
