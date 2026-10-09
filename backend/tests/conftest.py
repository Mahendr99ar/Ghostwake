import os

import pytest

# Point every test at its own throwaway database before anything imports settings.
os.environ.setdefault("GW_DATABASE_URL", "sqlite:///./test-ghostwake.db")
os.environ.setdefault("GW_ANALYST_TOKEN", "test-token")
os.environ.setdefault("GW_COPILOT_PER_MINUTE", "1000")

from ghostwake.anomalies import rules  # noqa: E402
from ghostwake.ingest import ais, synthetic  # noqa: E402


@pytest.fixture(scope="session")
def scenario():
    return synthetic.build(seed=7)


@pytest.fixture(scope="session")
def cleaned(scenario):
    df, report = ais.clean(scenario.ais_raw)
    return df, report, ais.static_info(df)


@pytest.fixture(scope="session")
def alerts(cleaned):
    df, _, static = cleaned
    return rules.run_all(df, static)


@pytest.fixture(scope="session")
def pipeline_db(tmp_path_factory):
    from ghostwake import pipeline

    url = os.environ["GW_DATABASE_URL"]
    if url.startswith("sqlite:///./") and os.path.exists(url.removeprefix("sqlite:///")):
        os.remove(url.removeprefix("sqlite:///"))
    pipeline.run(seed=7, db_url=url)
    return url
