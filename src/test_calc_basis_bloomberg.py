"""
Unit tests for the Bloomberg-method basis calculation: contract parsing,
OIS interpolation, and the rolling MAD outlier flag.
"""

import numpy as np
import pandas as pd

from calc_basis_bloomberg import (
    interpolate_ois,
    parse_contract_date,
    rolling_outlier_flag,
)


def test_parse_contract_date_quarterly_cycle():
    """'DEC 21' parses to (12, 2021); invalid input returns (None, None) or NaN."""
    assert parse_contract_date("DEC 21") == (12, 2021)
    assert parse_contract_date("MAR 25") == (3, 2025)
    month, year = parse_contract_date("ABC 25")
    assert np.isnan(month)
    assert parse_contract_date(None) == (None, None)


def test_interpolate_ois_at_nodes_and_midpoints():
    """Interpolation matches the curve at nodes and is linear in between."""
    # 1W=1.0, 1M=2.0, 3M=3.0, 6M=4.0, 1Y=5.0
    args = (1.0, 2.0, 3.0, 4.0, 5.0)
    assert np.isclose(interpolate_ois(7, *args), 1.0)
    assert np.isclose(interpolate_ois(30, *args), 2.0)
    assert np.isclose(interpolate_ois(90, *args), 3.0)
    assert np.isclose(interpolate_ois(180, *args), 4.0)
    assert np.isclose(interpolate_ois(360, *args), 5.0)
    # midpoint of 30-90 day segment
    assert np.isclose(interpolate_ois(60, *args), 2.5)


def test_rolling_outlier_flag_flags_isolated_spike():
    """A 100x spike inside a flat window is flagged; flat values are not."""
    dates = pd.bdate_range("2024-01-01", periods=60)
    vals = np.random.RandomState(0).normal(10.0, 0.5, size=60)
    vals[30] = 1000.0  # spike
    df = pd.DataFrame({"Date": dates, "Tenor": 10, "arb": vals})

    out = rolling_outlier_flag(
        df, group_col="Tenor", date_col="Date", value_col="arb",
        window_days=45, threshold=10,
    )
    assert out.loc[out["Date"] == dates[30], "bad_price"].iloc[0]
    assert out["bad_price"].sum() == 1
