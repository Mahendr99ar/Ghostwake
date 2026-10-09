"""Classic ship detection on SAR amplitude images, plus a chip renderer for the UI.

CA-CFAR (cell-averaging constant false alarm rate) is the textbook detector: for each
pixel, estimate the sea clutter from a ring of neighbours, and call the pixel a target
if it is much brighter than that local sea. It is the baseline any ML detector has to
beat; see train_yolo.py for the learned model.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage


def cfar_threshold_factor(n_train: int, pfa: float) -> float:
    # For exponentially distributed clutter power, this gives the requested false alarm rate.
    return n_train * (pfa ** (-1.0 / n_train) - 1.0)


def ca_cfar(power: np.ndarray, guard: int = 7, train: int = 10, pfa: float = 1e-6) -> np.ndarray:
    """Boolean mask of pixels that stand out from their local sea clutter.

    The guard band must be wider than half the longest ship, otherwise the ship leaks
    into its own clutter estimate and hides itself. 7 px = 70 m at 10 m pixels.
    """
    outer = 2 * (guard + train) + 1
    inner = 2 * guard + 1
    sum_outer = ndimage.uniform_filter(power, size=outer, mode="reflect") * outer**2
    sum_inner = ndimage.uniform_filter(power, size=inner, mode="reflect") * inner**2
    n_train = outer**2 - inner**2
    clutter = (sum_outer - sum_inner) / n_train
    return power > cfar_threshold_factor(n_train, pfa) * clutter


def detect(power: np.ndarray, pixel_m: float = 10.0, min_pixels: int = 3, **kw) -> list[dict]:
    """Group CFAR hits into objects and report centre, size and peak for each."""
    mask = ca_cfar(power, **kw)
    labels, n = ndimage.label(mask)
    out = []
    for k in range(1, n + 1):
        rr, cc = np.nonzero(labels == k)
        if len(rr) < min_pixels:
            continue
        extent = max(rr.max() - rr.min(), cc.max() - cc.min()) + 1
        out.append({
            "row": float(rr.mean()),
            "col": float(cc.mean()),
            "pixels": int(len(rr)),
            "length_m": float(extent * pixel_m),
            "peak": float(power[rr, cc].max()),
        })
    return out


def synthetic_scene(
    shape: tuple[int, int] = (256, 256),
    targets: list[tuple[int, int, int]] = (),
    seed: int = 0,
    looks: int = 1,
) -> np.ndarray:
    """Speckled sea (gamma-distributed power) with bright elongated targets.

    targets: (row, col, length_px)
    """
    rng = np.random.default_rng(seed)
    power = rng.gamma(shape=looks, scale=1.0 / looks, size=shape)
    for r, c, length in targets:
        half = max(1, length // 2)
        power[r - 1 : r + 2, c - half : c + half + 1] += 60.0
    return power


def chip(det_id: str, length_m: float, size: int = 64, pixel_m: float = 5.0) -> list[list[int]]:
    """An 8-bit image chip for a detection, deterministic per id.

    The demo has no real imagery, so this draws what a Sentinel-1 chip of a ship that
    size roughly looks like. With real data, crop the GeoTIFF around the detection instead.
    """
    seed = int.from_bytes(det_id.encode()[-8:].ljust(8, b"0"), "little") % (2**32)
    rng = np.random.default_rng(seed)
    # 4-look speckle: what a multilooked GRD product looks like, calmer than single-look.
    power = rng.gamma(4.0, 0.25, size=(size, size))
    length_px = max(2, int(round(length_m / pixel_m)))
    angle = rng.uniform(0, 180)
    yy, xx = np.mgrid[:size, :size] - size / 2
    t = np.radians(angle)
    along = xx * np.cos(t) + yy * np.sin(t)
    across = -xx * np.sin(t) + yy * np.cos(t)
    hull = (np.abs(along) <= length_px / 2) & (np.abs(across) <= max(1.0, length_px / 7))
    power[hull] += rng.uniform(25, 60)
    db = 10 * np.log10(power + 1e-3)
    lo, hi = np.percentile(db, 2), np.percentile(db, 99.8)
    img = np.clip((db - lo) / (hi - lo), 0, 1) * 255
    return img.astype(np.uint8).tolist()
