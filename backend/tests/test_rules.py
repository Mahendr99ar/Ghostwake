"""Every behaviour planted in the synthetic scenario must come back out, and nothing else.

These are recall and precision tests on known ground truth, not snapshot tests.
If you change a threshold and one of these fails, the scenario is telling you what broke.
"""

import pandas as pd

from ghostwake.anomalies import rules


def kinds(alerts, kind):
    return {a.mmsi for a in alerts if a.kind == kind}


def test_planted_ais_gap_is_found(alerts, scenario):
    assert kinds(alerts, "ais_gap") == set(scenario.truth["gap"])
    gap = next(a for a in alerts if a.kind == "ais_gap")
    assert 10 <= gap.evidence["gap_hours"] <= 12
    assert gap.evidence["zones"] == ["gom-mnp"]


def test_planted_spoofing_is_found(alerts, scenario):
    assert kinds(alerts, "spoofing") == set(scenario.truth["spoof"])


def test_planted_rendezvous_is_found_and_harbour_pairs_are_not(alerts, scenario):
    pairs = {tuple(sorted([a.mmsi, a.evidence["other_mmsi"]])) for a in alerts if a.kind == "rendezvous"}
    assert pairs == {tuple(p) for p in scenario.truth["rendezvous"]}


def test_imbl_rule_flags_the_fishing_boat_but_not_merchant_ships(alerts, scenario):
    flagged = kinds(alerts, "imbl_crossing") | kinds(alerts, "imbl_proximity")
    assert flagged == set(scenario.truth["imbl"])
    crossing = next(a for a in alerts if a.kind == "imbl_crossing")
    assert crossing.severity == "critical"
    assert crossing.evidence["warning_lead_minutes"] > 15  # time to warn the crew


def test_ban_rule_catches_east_coast_trip_and_ignores_west_coast_boats(alerts, scenario):
    assert kinds(alerts, "ban_period_fishing") == set(scenario.truth["ban"])


def test_no_false_alarms_on_boats_tied_up_in_harbour(alerts):
    in_port = {"419220017", "419220188"}  # SAGAR LAKSHMI, KADAL RANI
    assert not ({a.mmsi for a in alerts} & in_port)


def test_injected_gap_on_a_clean_track_is_detected(cleaned):
    """Take an innocent cargo ship, delete 8 hours of its track, and expect an alert."""
    df, _, _ = cleaned
    ship = df[df.mmsi == "563104920"].copy()
    t0 = ship.ts.iloc[0] + pd.Timedelta(hours=3)
    holed = ship[(ship.ts < t0) | (ship.ts > t0 + pd.Timedelta(hours=8))]
    found = rules.ais_gaps(holed)
    assert len(found) == 1
    assert 7.9 <= found[0].evidence["gap_hours"] <= 8.5


def test_injected_teleport_is_spoofing(cleaned):
    df, _, _ = cleaned
    ship = df[df.mmsi == "563104920"].copy().reset_index(drop=True)
    ship.loc[100, "lat"] += 1.5  # ~165 km north for one fix
    assert len(rules.spoofing(ship)) == 1


def test_rules_are_quiet_on_an_ordinary_transit(cleaned):
    df, _, static = cleaned
    ship = df[df.mmsi == "477552310"]
    assert rules.run_all(ship, static) == []
