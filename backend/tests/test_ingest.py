import pandas as pd

from ghostwake.ingest import ais


def test_mmsi_variants_normalise_to_nine_digits():
    assert ais.normalise_mmsi("419220977") == "419220977"
    assert ais.normalise_mmsi(" 419220977 ") == "419220977"
    assert ais.normalise_mmsi("MMSI:419220977") == "419220977"
    assert ais.normalise_mmsi("12345") is None
    assert ais.normalise_mmsi(None) is None


def test_mixed_timestamp_formats_all_parse_to_the_same_instant():
    col = pd.Series(["2026-05-20T01:00:00Z", "2026-05-20 01:00:00+00:00", "1779238800"])
    parsed = ais.parse_timestamps(col)
    assert parsed.notna().all()
    assert parsed.nunique() == 1


def test_cleaner_drops_garbage_and_reports_why(cleaned):
    df, report, _ = cleaned
    assert report.bad_position == 12  # 6 rows at lat 91, 6 at 0,0
    assert report.duplicates > 0
    assert report.rows_out == len(df)
    assert df["lat"].between(-90, 90).all()
    assert not ((df.lat.abs() < 1e-6) & (df.lon.abs() < 1e-6)).any()
    assert not df.duplicated(["mmsi", "ts"]).any()
    # sorted per vessel, so diff() based rules can trust the order
    assert (df.groupby("mmsi")["ts"].diff().dropna() > pd.Timedelta(0)).all()


def test_static_info_has_one_row_per_vessel(cleaned):
    df, _, static = cleaned
    assert len(static) == df["mmsi"].nunique()
    assert static.loc[static.mmsi == "412339871", "name"].item() == "SEA FALCON"
