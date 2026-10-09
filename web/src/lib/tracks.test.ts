import { describe, expect, it } from "vitest";
import { positionAt } from "./tracks";

const track = { mmsi: "1", path: [[78, 8], [78.1, 8.1], [79, 9]] as [number, number][], t: [0, 600, 40000] };

describe("positionAt", () => {
  it("interpolates between close fixes", () => {
    const p = positionAt(track, 300)!;
    expect(p[0]).toBeCloseTo(78.05);
    expect(p[1]).toBeCloseTo(8.05);
  });

  it("refuses to invent a position inside a long silence", () => {
    expect(positionAt(track, 20000)).toBeNull();
  });

  it("returns null outside the track", () => {
    expect(positionAt(track, -5)).toBeNull();
    expect(positionAt(track, 50000)).toBeNull();
  });
});
