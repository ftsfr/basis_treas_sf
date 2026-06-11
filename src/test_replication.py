"""
Replication tests against the Siriwardane-Sunderam-Wallen reference series
(``treasury_sf_implied_rf.dta``), when available in ``data_manual/``.

Adapted from the test suite by George Lord and Max Zhalilo
(https://github.com/maxz073/p10_Siriwardane_et_al_2026). Compares, for all
five tenors:
1. delivery-adjusted implied repo vs ``tfut_*_rf``
2. interpolated OIS vs ``tfut_ois_*``
3. the basis (spread) vs ``spread_*``

Each test requires the difference to be within a bps tolerance for at least
90% of valid observations. Tests skip if the reference file or pipeline
outputs are missing.
"""

from pathlib import Path

import pandas as pd
import pytest

from settings import config

DATA_DIR = Path(config("DATA_DIR"))
MANUAL_DATA_DIR = Path(config("MANUAL_DATA_DIR"))

TENORS = ["2Y", "5Y", "10Y", "20Y", "30Y"]
TENOR_TO_NUM = {"2Y": 2, "5Y": 5, "10Y": 10, "20Y": 20, "30Y": 30}

BPS_TOLERANCE_IRR = 75
BPS_TOLERANCE_OIS = 25
BPS_TOLERANCE_SPREAD = 75
MIN_FRACTION_WITHIN = 0.90


def _load_stata_df():
    """Load reference data and ensure spread_* = tfut_*_rf - tfut_ois_*."""
    path = MANUAL_DATA_DIR / "treasury_sf_implied_rf.dta"
    if not path.exists():
        pytest.skip(f"Replication reference data not found: {path}")
    df = pd.read_stata(path)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    for n in TENOR_TO_NUM.values():
        if f"spread_{n}" not in df.columns:
            df[f"spread_{n}"] = df[f"tfut_{n}_rf"] - df[f"tfut_ois_{n}"]
    return df


def _load_parquet_or_skip(name: str) -> pd.DataFrame:
    path = DATA_DIR / name
    if not path.exists():
        pytest.skip(f"Pipeline output not found: {path}. Run the pipeline first.")
    df = pd.read_parquet(path)
    if "Date" in df.columns:
        df = df.set_index("Date")
    df.index = pd.to_datetime(df.index).normalize()
    return df


def _align_dates(my_df, paper_df):
    paper = paper_df.set_index("date")
    common = my_df.index.intersection(paper.index).sort_values()
    return my_df.reindex(common), paper.reindex(common)


def _frac_within_bps(my_series, paper_series, bps_tol):
    mask = my_series.notna() & paper_series.notna()
    if mask.sum() == 0:
        return 0.0
    diff = (my_series - paper_series).abs()
    return (diff[mask] <= bps_tol).mean()


@pytest.fixture(scope="module")
def paper_df():
    return _load_stata_df()


def test_irr_vs_tfut_rf_all_tenors(paper_df):
    """Delivery-adjusted IRR within 75 bps of tfut_*_rf for >= 90% of data."""
    my_df = _load_parquet_or_skip("implied_repo_delivery_adjusted.parquet")
    my_a, paper_a = _align_dates(my_df, paper_df)
    for tenor in TENORS:
        paper_col = f"tfut_{TENOR_TO_NUM[tenor]}_rf"
        frac = _frac_within_bps(my_a[tenor], paper_a[paper_col], BPS_TOLERANCE_IRR)
        assert frac >= MIN_FRACTION_WITHIN, (
            f"IRR vs {paper_col} for {tenor}: {frac:.2%} within "
            f"{BPS_TOLERANCE_IRR} bps (required >= {MIN_FRACTION_WITHIN:.0%})"
        )


def test_ois_vs_tfut_ois_all_tenors(paper_df):
    """Interpolated OIS within 25 bps of tfut_ois_* for >= 90% of data."""
    my_df = _load_parquet_or_skip("ois_at_holding_period.parquet")
    my_a, paper_a = _align_dates(my_df, paper_df)
    for tenor in TENORS:
        paper_col = f"tfut_ois_{TENOR_TO_NUM[tenor]}"
        frac = _frac_within_bps(my_a[tenor], paper_a[paper_col], BPS_TOLERANCE_OIS)
        assert frac >= MIN_FRACTION_WITHIN, (
            f"OIS vs {paper_col} for {tenor}: {frac:.2%} within "
            f"{BPS_TOLERANCE_OIS} bps (required >= {MIN_FRACTION_WITHIN:.0%})"
        )


def test_spread_vs_paper_spread_all_tenors(paper_df):
    """Delivery-adjusted basis within 75 bps of spread_* for >= 90% of data."""
    my_df = _load_parquet_or_skip("basis_treas_sf_adj.parquet")
    my_df = my_df.rename(columns=lambda c: c.replace("Treasury_SF_", ""))
    my_a, paper_a = _align_dates(my_df, paper_df)
    for tenor in TENORS:
        paper_col = f"spread_{TENOR_TO_NUM[tenor]}"
        frac = _frac_within_bps(my_a[tenor], paper_a[paper_col], BPS_TOLERANCE_SPREAD)
        assert frac >= MIN_FRACTION_WITHIN, (
            f"Spread vs {paper_col} for {tenor}: {frac:.2%} within "
            f"{BPS_TOLERANCE_SPREAD} bps (required >= {MIN_FRACTION_WITHIN:.0%})"
        )
