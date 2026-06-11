"""
Unit tests for the delivery-adjusted implied repo calculation.

Adapted from the test suite by George Lord and Max Zhalilo
(https://github.com/maxz073/p10_Siriwardane_et_al_2026): contract date
helpers, the IRR formula, and OIS interpolation; plus a direct test that the
delivery-timing option is exercised correctly (early delivery under negative
carry, late delivery under positive carry).
"""

import numpy as np
import pandas as pd

from calc_basis_delivery_adjusted import (
    _delivery_dates_from_contract_month,
    _first_weekday_of_month,
    _irr_series,
    _last_weekday_of_month,
    _parse_contract_month_yr,
    calc_implied_repo_for_tenor,
    calc_ois_at_holding_period,
)


def test_parse_contract_month_yr_valid_and_invalid_inputs():
    """Parse 'MAR 25' / 'JUN 2030' to (year, month); None for bad or missing input."""
    assert _parse_contract_month_yr("MAR 25") == (2025, 3)
    assert _parse_contract_month_yr('"jun 2030"') == (2030, 6)
    assert _parse_contract_month_yr("BAD 25") is None
    assert _parse_contract_month_yr(None) is None


def test_first_and_last_weekday_handles_weekend_boundaries():
    """First/last weekday of month skip weekends (Nov 2025: Mon 3rd, Fri 28th)."""
    # 2025-11-01 is Saturday, so first weekday should be Monday 2025-11-03.
    assert _first_weekday_of_month(2025, 11) == pd.Timestamp("2025-11-03")
    # 2025-11-30 is Sunday, so last weekday should be Friday 2025-11-28.
    assert _last_weekday_of_month(2025, 11) == pd.Timestamp("2025-11-28")


def test_delivery_dates_from_contract_month_maps_to_expected_columns():
    """current_contract_month_yr maps to fut_dlv_dt_first/last; invalid rows get NaT."""
    raw = pd.DataFrame({"current_contract_month_yr": ["MAR 25", "NOV 25", "BAD 25"]})
    out = _delivery_dates_from_contract_month(raw)

    assert out.loc[0, "fut_dlv_dt_first"] == pd.Timestamp("2025-03-03")
    assert out.loc[0, "fut_dlv_dt_last"] == pd.Timestamp("2025-03-31")
    assert out.loc[1, "fut_dlv_dt_first"] == pd.Timestamp("2025-11-03")
    assert out.loc[1, "fut_dlv_dt_last"] == pd.Timestamp("2025-11-28")
    assert pd.isna(out.loc[2, "fut_dlv_dt_first"])
    assert pd.isna(out.loc[2, "fut_dlv_dt_last"])


def test_irr_series_applies_formula_and_masks_invalid_rows():
    """_irr_series returns bps where denom > 0 and d1 > 0; NaN otherwise."""
    idx = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"])
    merged = pd.DataFrame(index=idx)

    m = pd.DataFrame(
        {
            "Ae": [1.0, 1.0, 1.0, 1.0],
            "Ic": [0.0, 0.0, 0.0, 10.0],
            "d1": [0.5, 0.0, 0.5, 0.5],  # row 2 invalid: d1 <= 0
            "d2": [0.0, 0.0, 0.0, 6.0],  # row 4 invalid: denominator <= 0
        },
        index=idx,
    )
    P = pd.Series([100.0, 100.0, 100.0, 100.0], index=idx)
    Ab = pd.Series([1.0, 1.0, 1.0, 1.0], index=idx)
    F = pd.Series([102.0, 102.0, 98.0, 102.0], index=idx)
    CF = pd.Series([1.0, 1.0, 1.0, 1.0], index=idx)

    out = _irr_series(merged=merged, m=m, P=P, Ab=Ab, F=F, CF=CF)

    expected_row_1 = ((102.0 + 1.0 - 101.0) * 10_000) / (0.5 * 101.0)
    expected_row_3 = ((98.0 + 1.0 - 101.0) * 10_000) / (0.5 * 101.0)

    assert np.isclose(out.loc[idx[0]], expected_row_1)
    assert np.isclose(out.loc[idx[2]], expected_row_3)
    assert np.isnan(out.loc[idx[1]])
    assert np.isnan(out.loc[idx[3]])


def _one_row_inputs(coupon_rate: float, futures_price: float):
    """Synthetic single-date futures and CRSP inputs for one CTD bond.

    The contract month is March 2025 (delivery window Mar 3 - Mar 31) and no
    coupon falls inside the window.
    """
    futures = pd.DataFrame(
        {
            "Date": [pd.Timestamp("2025-02-03")],
            "px_last": [futures_price],
            "px_volume": [1000.0],
            "fut_ctd_cusip": ["912810AA"],
            "fut_cnvs_factor": [0.9],
            "current_contract_month_yr": ["MAR 25"],
        }
    )
    futures = _delivery_dates_from_contract_month(futures)
    crsp = pd.DataFrame(
        {
            "caldt": [pd.Timestamp("2025-02-03")],
            "tcusip": ["912810AA"],
            "clean_price": [100.0],
            "coupon_rate": [coupon_rate],
            "coupon_frequency": [2],
            "prev_coupon_date": [pd.Timestamp("2024-11-15")],
            "next_coupon_date": [pd.Timestamp("2025-05-15")],
        }
    )
    return futures, crsp


def test_optimal_delivery_is_late_when_carry_is_positive():
    """High coupon accrual with futures near fair value -> deliver late."""
    # When the invoice price roughly matches the dirty purchase price, the
    # gain comes from coupon accrual, which grows with the holding period:
    # the optimal delivery date is the LAST delivery day.
    futures, crsp = _one_row_inputs(coupon_rate=12.0, futures_price=110.0)
    out = calc_implied_repo_for_tenor(futures, crsp, "10Y")
    assert out.loc[pd.Timestamp("2025-02-03"), "optimal_delivery_date"] == pd.Timestamp(
        "2025-03-31"
    )


def test_optimal_delivery_is_early_when_carry_is_negative():
    """Zero coupon (no accrual income) -> deliver early to stop financing."""
    # With no coupon accrual, the invoice proceeds are fixed while the
    # financing clock keeps running: the per-day return is maximized by
    # delivering on the FIRST delivery day.
    futures, crsp = _one_row_inputs(coupon_rate=0.0, futures_price=112.0)
    out = calc_implied_repo_for_tenor(futures, crsp, "10Y")
    assert out.loc[pd.Timestamp("2025-02-03"), "optimal_delivery_date"] == pd.Timestamp(
        "2025-03-03"
    )


def test_ois_interpolation_at_holding_period(tmp_path):
    """OIS is linearly interpolated at the holding period and reported in bps."""
    dates = pd.to_datetime(["2025-01-02", "2025-01-03"])
    ois = pd.DataFrame(
        {
            "Date": dates,
            "USSOB CMPN Curncy": [2.0, 2.0],  # 2M = 61d
            "USSOC CMPN Curncy": [3.0, 3.0],  # 3M = 91d
            "USSOF CMPN Curncy": [4.0, 4.0],  # 6M = 182d
        }
    )
    ois.to_parquet(tmp_path / "ois.parquet", index=False)

    holding = pd.DataFrame({"10Y": [76.0, 1000.0]}, index=dates)
    out = calc_ois_at_holding_period(holding, data_dir=tmp_path)

    # 76d is midway between 61d and 91d -> 2.5% -> 250 bps
    assert np.isclose(out.loc[dates[0], "10Y"], 250.0)
    # 1000d clips to the longest available node (182d) -> 4% -> 400 bps
    assert np.isclose(out.loc[dates[1], "10Y"], 400.0)
