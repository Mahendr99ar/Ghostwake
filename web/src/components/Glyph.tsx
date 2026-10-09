// The same marks the map draws, at list size. A ring is something radar saw; a dashed ring
// is a ship that went quiet; a triangle is a crew in danger.

interface Props { kind: string; size?: number }

export function Glyph({ kind, size = 18 }: Props) {
  const c = size / 2;
  const r = size / 2 - 2;
  const common = { width: size, height: size, viewBox: `0 0 ${size} ${size}`, "aria-hidden": true } as const;

  switch (kind) {
    case "dark_vessel":
      return (
        <svg {...common} className="glyph glyph-ghost">
          <circle cx={c} cy={c} r={r} fill="none" stroke="currentColor" strokeWidth="2" />
          <circle cx={c} cy={c} r={1.6} fill="currentColor" />
        </svg>
      );
    case "ais_gap":
      return (
        <svg {...common} className="glyph glyph-ghost">
          <circle cx={c} cy={c} r={r} fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="3 3" />
        </svg>
      );
    case "spoofing":
      return (
        <svg {...common} className="glyph">
          <circle cx={c - 3} cy={c} r={r - 3} fill="none" stroke="currentColor" strokeWidth="1.6" />
          <circle cx={c + 3} cy={c} r={r - 3} fill="none" stroke="currentColor" strokeWidth="1.6" strokeDasharray="2 2" />
        </svg>
      );
    case "rendezvous":
      return (
        <svg {...common} className="glyph">
          <circle cx={c - 3.5} cy={c} r={3} fill="currentColor" />
          <circle cx={c + 3.5} cy={c} r={3} fill="none" stroke="currentColor" strokeWidth="1.6" />
        </svg>
      );
    case "imbl_crossing":
    case "imbl_proximity":
      return (
        <svg {...common} className="glyph glyph-safety">
          <path d={`M${c} 2 L${size - 2} ${size - 3} L2 ${size - 3} Z`} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
          <line x1={c} y1={c - 2} x2={c} y2={c + 2} stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      );
    case "ban_period_fishing":
      return (
        <svg {...common} className="glyph">
          <rect x="3" y="3" width={size - 6} height={size - 6} rx="2" fill="none" stroke="currentColor" strokeWidth="2" />
          <line x1="4" y1={size - 4} x2={size - 4} y2="4" stroke="currentColor" strokeWidth="1.6" />
        </svg>
      );
    default:
      return (
        <svg {...common} className="glyph">
          <path d={`M${c} 2 L${size - 2} ${c} L${c} ${size - 2} L2 ${c} Z`} fill="none" stroke="currentColor" strokeWidth="2" />
        </svg>
      );
  }
}
