import numpy as np

from ghostwake import risk
from ghostwake.detect import sar
from ghostwake.fusion import match


def test_every_ais_ship_on_radar_gets_matched_to_itself(cleaned, scenario, alerts):
    df, _, _ = cleaned
    gaps = [a for a in alerts if a.kind == "ais_gap"]
    results = match.match_all(df, scenario.scenes, gaps)
    wrong = [d for r in results for d in r.detections
             if d["truth"] == "ais" and d["matched_mmsi"] is not None
             and d["matched_mmsi"] != _truth_mmsi(scenario, d)]
    assert wrong == []
    ais_dets = [d for r in results for d in r.detections if d["truth"] == "ais"]
    matched = [d for d in ais_dets if d["matched_mmsi"]]
    assert len(matched) / len(ais_dets) >= 0.95


def _truth_mmsi(scenario, det):
    scene = next(s for s in scenario.scenes if det["id"].startswith(s["scene_id"]))
    return scene["detections"][int(det["id"].rsplit("-", 1)[1])]["truth_mmsi"]


def test_dark_ships_become_alerts_and_clutter_does_not(cleaned, scenario, alerts):
    df, _, _ = cleaned
    gaps = [a for a in alerts if a.kind == "ais_gap"]
    results = match.match_all(df, scenario.scenes, gaps)
    dark_ids = {d["id"] for r in results for d in r.detections if d["truth"] == "dark"}
    clutter_ids = {d["id"] for r in results for d in r.detections if d["truth"] == "clutter"}
    alert_ids = {a.detection_id for r in results for a in r.alerts}
    assert dark_ids <= alert_ids  # recall 1.0 on planted dark ships
    assert not (clutter_ids & alert_ids)  # clutter filtered by size and confidence


def test_silent_vessel_is_linked_to_its_radar_blip(cleaned, scenario, alerts):
    df, _, _ = cleaned
    gaps = [a for a in alerts if a.kind == "ais_gap"]
    results = match.match_all(df, scenario.scenes, gaps)
    linked = [a for r in results for a in r.alerts if a.evidence.get("possible_identity")]
    assert len(linked) == 1
    det = next(d for r in results for d in r.detections if d["id"] == linked[0].detection_id)
    assert _truth_mmsi(scenario, det) == "412339871"


def test_cfar_finds_planted_ships_and_little_else():
    targets = [(40, 60, 8), (120, 200, 12), (200, 90, 5)]
    img = sar.synthetic_scene(targets=targets, seed=3)
    found = sar.detect(img)
    centres = np.array([(f["row"], f["col"]) for f in found])
    for r, c, _ in targets:
        assert np.min(np.hypot(centres[:, 0] - r, centres[:, 1] - c)) < 3
    assert len(found) <= len(targets) + 2


def test_chip_is_deterministic_and_8_bit():
    a = np.array(sar.chip("S1-x-001", 30))
    b = np.array(sar.chip("S1-x-001", 30))
    assert a.shape == (64, 64)
    assert a.min() >= 0 and a.max() <= 255
    assert (a == b).all()


def test_scores_explain_themselves(cleaned, alerts):
    _, _, static = cleaned
    scored = risk.score(list(alerts), dict(zip(static.mmsi, static.flag)))
    for a in scored:
        assert 0 < a.score <= 100
        assert a.score == min(100, sum(c["points"] for c in a.contributions))
    gap = next(a for a in scored if a.kind == "ais_gap")
    reasons = " ".join(c["reason"] for c in gap.contributions)
    assert "protected area" in reasons and "No flag" in reasons
