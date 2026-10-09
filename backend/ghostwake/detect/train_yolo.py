"""Train a YOLO ship detector on a subset of xView3-SAR. Run this on Kaggle or Colab, not on Render.

What it does:
  1. Reads VV and VH dB GeoTIFFs for a handful of xView3 scenes.
  2. Cuts them into 800 x 800 tiles and writes YOLO labels for every vessel in the tile.
  3. Trains a small YOLO model and reports point-matched precision, recall and F1
     (a prediction counts if its centre is within 20 px = 200 m of a label, the same
     distance rule the xView3 challenge used).

Expected layout (download from https://iuu.xview.us after accepting the licence):
  data/xview3/train.csv
  data/xview3/scenes/<scene_id>/VV_dB.tif
  data/xview3/scenes/<scene_id>/VH_dB.tif

Usage:
  pip install "ghostwake[ml]"
  python -m ghostwake.detect.train_yolo --root data/xview3 --scenes 6 --epochs 30

This file is not exercised by the unit tests because it needs the dataset and a GPU.
Check the column names against the copy of train.csv you download before a long run.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

TILE = 800
MATCH_PX = 20
MIN_BOX_PX = 10


def to_uint8(db: np.ndarray, lo: float = -35.0, hi: float = 5.0) -> np.ndarray:
    x = np.nan_to_num(db, nan=lo)
    return (np.clip((x - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)


def build_tiles(root: Path, out: Path, n_scenes: int, val_frac: float = 0.2) -> Path:
    import rasterio
    from PIL import Image

    labels = pd.read_csv(root / "train.csv")
    labels = labels[labels["is_vessel"].fillna(False).astype(bool)]
    scenes = sorted(labels["scene_id"].unique())[:n_scenes]
    rng = np.random.default_rng(0)

    for split in ("train", "val"):
        (out / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "labels" / split).mkdir(parents=True, exist_ok=True)

    for sid in scenes:
        with rasterio.open(root / "scenes" / sid / "VV_dB.tif") as f:
            vv = f.read(1)
        with rasterio.open(root / "scenes" / sid / "VH_dB.tif") as f:
            vh = f.read(1)
        rgb = np.dstack([to_uint8(vv), to_uint8(vh, -40, 0), to_uint8(vv - vh, -5, 25)])
        sl = labels[labels.scene_id == sid]
        split = "val" if rng.random() < val_frac else "train"

        for r0 in range(0, rgb.shape[0] - TILE + 1, TILE):
            for c0 in range(0, rgb.shape[1] - TILE + 1, TILE):
                in_tile = sl[
                    sl.detect_scene_row.between(r0, r0 + TILE - 1)
                    & sl.detect_scene_column.between(c0, c0 + TILE - 1)
                ]
                # Keep every tile with ships, and a few empty ones so the model learns sea.
                if in_tile.empty and rng.random() > 0.05:
                    continue
                name = f"{sid}_{r0}_{c0}"
                Image.fromarray(rgb[r0 : r0 + TILE, c0 : c0 + TILE]).save(
                    out / "images" / split / f"{name}.png"
                )
                lines = []
                for _, d in in_tile.iterrows():
                    length_px = d.get("vessel_length_m")
                    box = max(MIN_BOX_PX, float(length_px) / 10 if pd.notna(length_px) else MIN_BOX_PX)
                    cx = (d.detect_scene_column - c0) / TILE
                    cy = (d.detect_scene_row - r0) / TILE
                    lines.append(f"0 {cx:.6f} {cy:.6f} {box / TILE:.6f} {box / TILE:.6f}")
                (out / "labels" / split / f"{name}.txt").write_text("\n".join(lines))

    yaml = out / "xview3.yaml"
    yaml.write_text(f"path: {out.resolve()}\ntrain: images/train\nval: images/val\nnames:\n  0: vessel\n")
    return yaml


def point_f1(pred: list[tuple[float, float]], truth: list[tuple[float, float]]) -> dict:
    from scipy.optimize import linear_sum_assignment

    if not pred or not truth:
        tp = 0
    else:
        P, T = np.array(pred), np.array(truth)
        d = np.linalg.norm(P[:, None, :] - T[None, :, :], axis=2)
        r, c = linear_sum_assignment(d)
        tp = int((d[r, c] <= MATCH_PX).sum())
    precision = tp / len(pred) if pred else 0.0
    recall = tp / len(truth) if truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "pred": len(pred), "truth": len(truth),
            "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)}


def evaluate(model, val_dir: Path) -> dict:
    tp = n_pred = n_truth = 0
    for img in sorted((val_dir / "images" / "val").glob("*.png")):
        lab = val_dir / "labels" / "val" / f"{img.stem}.txt"
        t = [(float(x.split()[1]) * TILE, float(x.split()[2]) * TILE)
             for x in lab.read_text().splitlines() if x.strip()]
        r = model.predict(str(img), verbose=False, conf=0.25)[0]
        p = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in r.boxes.xyxy.cpu().numpy()]
        m = point_f1(p, t)
        tp, n_pred, n_truth = tp + m["tp"], n_pred + m["pred"], n_truth + m["truth"]
    precision = tp / n_pred if n_pred else 0.0
    recall = tp / n_truth if n_truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "pred": n_pred, "truth": n_truth,
            "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("runs/xview3_tiles"))
    ap.add_argument("--scenes", type=int, default=6)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--model", default="yolo11n.pt")
    args = ap.parse_args()

    from ultralytics import YOLO

    yaml = build_tiles(args.root, args.out, args.scenes)
    model = YOLO(args.model)
    model.train(data=str(yaml), epochs=args.epochs, imgsz=TILE, batch=8)
    metrics = evaluate(model, args.out)
    print(json.dumps(metrics, indent=2))
    (args.out / "point_metrics.json").write_text(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
