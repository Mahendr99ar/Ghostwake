import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";

// Paints the 64 x 64 radar chip for a detection onto a canvas, pixel for pixel.
export function SarChip({ detectionId, lengthM }: { detectionId: string; lengthM: number }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const { data } = useQuery({ queryKey: ["chip", detectionId], queryFn: () => api.chip(detectionId) });

  useEffect(() => {
    const c = canvas.current;
    if (!c || !data) return;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    const img = ctx.createImageData(data.size, data.size);
    data.pixels.forEach((row, y) =>
      row.forEach((v, x) => {
        const i = (y * data.size + x) * 4;
        img.data[i] = v;
        img.data[i + 1] = v;
        img.data[i + 2] = v;
        img.data[i + 3] = 255;
      }),
    );
    ctx.putImageData(img, 0, 0);
  }, [data]);

  return (
    <figure className="chip-figure">
      <canvas ref={canvas} width={64} height={64} className="sar-chip" aria-label="Radar image around the detection" />
      <figcaption>
        320 m square around the detection, 5 m pixels. Return length about {Math.round(lengthM)} m.
        {data?.synthetic && <> Demo imagery, generated to match the detection.</>}
      </figcaption>
    </figure>
  );
}
