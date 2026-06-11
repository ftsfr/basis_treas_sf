"""
Treasury cash-futures basis with delivery-timing adjustment (the "corrected"
method).

This module computes the implied repo rate (IRR) of the cash-and-carry trade
directly from futures and cheapest-to-deliver (CTD) bond inputs, choosing the
delivery date *optimally* within the delivery month, and then subtracts the
USD OIS rate interpolated to the realized holding period:

    Treasury_SF_{tenor} = IRR - OIS(holding period)   [bps]

Why this matters: the short futures position owns the timing option -- it
chooses *when* in the delivery month to deliver. When carry is positive
(coupon income > financing cost), delivering on the last delivery day is
optimal; when carry is negative, delivering on the first delivery day is
optimal. Bloomberg's FUT_IMPLIED_REPO_RT (used in ``calc_basis_bloomberg.py``)
fixes the delivery date, which understates the implied repo whenever the
fixed date is not the optimal one.

The IRR for a candidate delivery date :math:`T_d` is

    IRR = [ F * CF + A_e + I_c - (P + A_b) ] / [ (P + A_b) d_1 - I_c d_2 ]

where F is the futures price, CF the conversion factor, P the CTD clean
price, A_b accrued interest at settlement (trade date + 1 business day),
A_e accrued interest at delivery, I_c any intervening coupon, d_1 the
settlement-to-delivery period (Act/360), and d_2 the coupon-to-delivery
reinvestment period (Act/360). The IRR is maximized over candidate delivery
dates: first delivery day, last delivery day, and (if an intervening coupon
falls in the window) the coupon date and its ex-coupon date.

Ported (with vectorization) from the implementation by George Lord and
Max Zhalilo (https://github.com/maxz073/p10_Siriwardane_et_al_2026), file
``src/calc_spread.py``, which itself follows the Treasury spot-futures
appendix of Siriwardane, Sunderam, and Wallen (2023), "Segmented Arbitrage".

Inputs (from DATA_DIR):
- ``treasury_{tenor}y_2.parquet``: first-deferred futures contract data
  (price, volume, CTD CUSIP, conversion factor, contract month)
- ``crsp_treasury_ctd.parquet``: CRSP daily CTD bond data (clean price,
  coupon rate, derived coupon schedule)
- ``ois.parquet``: USD OIS curve

Outputs (saved under DATA_DIR):
- ``implied_repo_delivery_adjusted.parquet``: IRR by tenor (bps)
- ``holding_period_days.parquet``: optimal holding period by tenor (days)
- ``ois_at_holding_period.parquet``: interpolated OIS by tenor (bps)
- ``basis_treas_sf_adj.parquet``: final basis by tenor (bps, wide format)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from settings import config
import format_bbg_basis_treas_sf
import pull_crsp_treasury

DATA_DIR = Path(config("DATA_DIR"))

OUTPUT_FILE = "basis_treas_sf_adj.parquet"

# Tenor label -> tenor years used in per-tenor futures file names.
# Contracts: TU=2Y, FV=5Y, TY=10Y, US=20Y (classic bond), WN=30Y (Ultra
# Bond), matching Siriwardane et al. and pull_bbg_basis_treas_sf. (Note:
# Lord and Zhalilo's repo swapped the 20Y/30Y tickers; here the mapping
# follows the data files and the paper.)
TENOR_YEARS = {"2Y": 2, "5Y": 5, "10Y": 10, "20Y": 20, "30Y": 30}

# OIS curve points (label -> approximate days) used to interpolate the
# financing benchmark at the holding period. Lord and Zhalilo used the
# 2M-9M points; the full set adds robustness at the edges when available.
OIS_LABEL_DAYS = {
    "OIS_1M": 30,
    "OIS_2M": 61,
    "OIS_3M": 91,
    "OIS_4M": 122,
    "OIS_5M": 152,
    "OIS_6M": 182,
    "OIS_9M": 274,
    "OIS_1Y": 365,
}

_MONTH_ABBR = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}  # fmt: skip


def _first_weekday_of_month(year: int, month: int) -> pd.Timestamp:
    """First weekday (business day) of the given month."""
    d = pd.Timestamp(year=year, month=month, day=1)
    if d.weekday() == 5:  # Saturday -> Monday
        d += pd.Timedelta(days=2)
    elif d.weekday() == 6:  # Sunday -> Monday
        d += pd.Timedelta(days=1)
    return d


def _last_weekday_of_month(year: int, month: int) -> pd.Timestamp:
    """Last weekday (business day) of the given month."""
    d = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
    if d.weekday() == 5:  # Saturday -> Friday
        d -= pd.Timedelta(days=1)
    elif d.weekday() == 6:  # Sunday -> Friday
        d -= pd.Timedelta(days=2)
    return d


def _parse_contract_month_yr(s: str) -> tuple[int, int] | None:
    """Parse 'MAR 25' or 'JUN 25' -> (year, month). Returns None if invalid."""
    if pd.isna(s) or not isinstance(s, str):
        return None
    s = str(s).strip().strip('"').strip()
    parts = s.upper().split()
    if len(parts) != 2:
        return None
    abbr, yr = parts[0], parts[1]
    if abbr not in _MONTH_ABBR:
        return None
    try:
        y = int(yr)
        year = 2000 + y if y < 100 else y
        return (year, _MONTH_ABBR[abbr])
    except (ValueError, TypeError):
        return None


def _delivery_dates_from_contract_month(raw: pd.DataFrame) -> pd.DataFrame:
    """Compute fut_dlv_dt_first/fut_dlv_dt_last (first/last weekday of the
    contract month) from ``current_contract_month_yr``."""
    raw = raw.copy()
    first_dates = []
    last_dates = []
    for val in raw["current_contract_month_yr"]:
        parsed = _parse_contract_month_yr(val)
        if parsed is None:
            first_dates.append(pd.NaT)
            last_dates.append(pd.NaT)
        else:
            year, month = parsed
            first_dates.append(_first_weekday_of_month(year, month))
            last_dates.append(_last_weekday_of_month(year, month))
    raw["fut_dlv_dt_first"] = first_dates
    raw["fut_dlv_dt_last"] = last_dates
    return raw


def _compute_ae_ic_d1_d2(merged: pd.DataFrame, delivery_col: str) -> pd.DataFrame:
    """Accrued interest, intervening coupon, and day-count terms for the IRR.

    Adds columns: Ae (accrued at delivery), Ab (accrued at settlement),
    Ic (intervening coupon), d1 (settlement->delivery, Act/360),
    d2 (coupon->delivery, Act/360).
    """
    df = merged.copy()
    df[delivery_col] = pd.to_datetime(df[delivery_col])
    df["caldt"] = pd.to_datetime(df["caldt"]).dt.normalize()
    freq = df.get("coupon_frequency", 2)
    df["coupon_cash_per_period"] = df["coupon_rate"] / freq

    next_cpn = pd.to_datetime(df["next_coupon_date"])
    prev_cpn = pd.to_datetime(df["prev_coupon_date"])
    delivery = df[delivery_col]
    last_cpn_before_delivery = prev_cpn.where(delivery < next_cpn, next_cpn)
    period_end = next_cpn.where(delivery < next_cpn, next_cpn + pd.DateOffset(months=6))
    period_days = (period_end - last_cpn_before_delivery).dt.days
    accrued_days_end = (delivery - last_cpn_before_delivery).dt.days
    df["Ae"] = df["coupon_cash_per_period"] * accrued_days_end / period_days.replace(0, 1)

    # Settlement: T+1 business day (carry starts on settlement, not trade date)
    settlement_date = df["caldt"] + pd.offsets.BDay(1)

    # Ab = accrued interest at settlement, so carry uses the correct dirty price
    last_cpn_before_settlement = prev_cpn.where(settlement_date < next_cpn, next_cpn)
    period_end_settlement = next_cpn.where(
        settlement_date < next_cpn, next_cpn + pd.DateOffset(months=6)
    )
    period_days_settlement = (period_end_settlement - last_cpn_before_settlement).dt.days
    accrued_days_settlement = (settlement_date - last_cpn_before_settlement).dt.days
    df["Ab"] = (
        df["coupon_cash_per_period"]
        * accrued_days_settlement
        / period_days_settlement.replace(0, 1)
    )

    # Ex-coupon: coupon is received by the long if caldt < ex_coupon_date and
    # the coupon date falls on or before delivery
    ex_coupon_date = next_cpn - pd.offsets.BDay(1)
    df["Ic"] = 0.0
    mask_cpn = (df["caldt"] < ex_coupon_date) & (next_cpn <= delivery)
    df.loc[mask_cpn, "Ic"] = df.loc[mask_cpn, "coupon_cash_per_period"]

    # d1 = holding period from settlement to delivery (Act/360)
    df["d1"] = (delivery - settlement_date).dt.days / 360.0
    df["d2"] = 0.0
    df.loc[mask_cpn, "d2"] = (
        df.loc[mask_cpn, delivery_col] - next_cpn.loc[mask_cpn]
    ).dt.days / 360.0
    return df


def _irr_series(
    merged: pd.DataFrame,
    m: pd.DataFrame,
    P: pd.Series,
    Ab: pd.Series,
    F: pd.Series,
    CF: pd.Series,
) -> pd.Series:
    """Implied repo rate in bps: numerator/denominator per the IRR formula."""
    num = (F * CF) + m["Ae"] + m["Ic"] - (P + Ab)
    denom = (m["d1"] * (P + Ab)) - (m["Ic"] * m["d2"])
    valid = (denom > 0) & m["d1"].notna() & (m["d1"] > 0)
    out = pd.Series(np.nan, index=merged.index, dtype=float)
    out.loc[valid] = num.loc[valid] * 10_000 / denom.loc[valid]
    return out


def load_futures_inputs(tenor: str, data_dir: Path = DATA_DIR) -> pd.DataFrame:
    """Load and clean first-deferred futures inputs for one tenor label."""
    tenor_years = TENOR_YEARS[tenor]
    path = data_dir / f"treasury_{tenor_years}y_2.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Futures input not found: {path}")
    df = pd.read_parquet(path).rename(
        columns={
            "PX_LAST": "px_last",
            "FUT_AGGTE_VOL": "px_volume",
            "FUT_CTD_CUSIP": "fut_ctd_cusip",
            "FUT_CNVS_FACTOR": "fut_cnvs_factor",
            "CURRENT_CONTRACT_MONTH_YR": "current_contract_month_yr",
        }
    )
    df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None).dt.normalize()
    df["px_last"] = pd.to_numeric(df["px_last"], errors="coerce")
    df["px_volume"] = pd.to_numeric(df["px_volume"], errors="coerce")
    df["fut_cnvs_factor"] = pd.to_numeric(df["fut_cnvs_factor"], errors="coerce")
    df["fut_ctd_cusip"] = df["fut_ctd_cusip"].astype(str).str.strip().str.strip('"')
    df.loc[df["fut_ctd_cusip"].isin(["", "nan", "None", "NaN", "0"]), "fut_ctd_cusip"] = (
        pd.NA
    )
    df = _delivery_dates_from_contract_month(df)
    cols = [
        "Date",
        "px_last",
        "px_volume",
        "fut_ctd_cusip",
        "fut_cnvs_factor",
        "current_contract_month_yr",
        "fut_dlv_dt_first",
        "fut_dlv_dt_last",
    ]
    return df[cols]


def load_crsp_inputs(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    """Load CRSP CTD bond data; normalize dates and CUSIPs."""
    df = pull_crsp_treasury.load_CRSP_treasury_for_irr(data_dir=data_dir)
    df = df.copy()
    df["caldt"] = pd.to_datetime(df["caldt"]).dt.normalize()
    df["tcusip"] = df["tcusip"].astype(str).str.strip().str.strip('"')
    for col in ["prev_coupon_date", "next_coupon_date"]:
        df[col] = pd.to_datetime(df[col])
    return df


def calc_implied_repo_for_tenor(
    futures_df: pd.DataFrame, crsp_df: pd.DataFrame, tenor: str
) -> pd.DataFrame:
    """IRR per date for one tenor, maximizing over candidate delivery dates.

    Candidate delivery dates: first delivery day, last delivery day, and (if
    an intervening coupon falls inside the window) the coupon date and its
    ex-coupon date. The maximum-IRR candidate is the short's optimal choice.
    """
    raw = futures_df[futures_df["px_volume"] > 0].copy()
    raw = raw.dropna(
        subset=[
            "px_last",
            "fut_cnvs_factor",
            "fut_ctd_cusip",
            "fut_dlv_dt_first",
            "fut_dlv_dt_last",
        ]
    )
    if raw.empty:
        return pd.DataFrame()

    merged = raw.merge(
        crsp_df,
        left_on=["Date", "fut_ctd_cusip"],
        right_on=["caldt", "tcusip"],
        how="inner",
    )
    if merged.empty:
        return pd.DataFrame()
    merged = merged.reset_index(drop=True)

    first_dlv = pd.to_datetime(merged["fut_dlv_dt_first"]).dt.normalize()
    last_dlv = pd.to_datetime(merged["fut_dlv_dt_last"]).dt.normalize()
    next_cpn = pd.to_datetime(merged["next_coupon_date"]).dt.normalize()
    ex_cpn = (next_cpn - pd.offsets.BDay(1)).dt.normalize()

    # Candidate columns in ascending date order (ties resolve to the
    # earliest candidate, matching Lord and Zhalilo's sorted iteration)
    candidates = {
        "first": (first_dlv, pd.Series(True, index=merged.index)),
        "ex_coupon": (ex_cpn, (first_dlv <= ex_cpn) & (ex_cpn <= last_dlv)),
        "coupon": (next_cpn, (first_dlv <= next_cpn) & (next_cpn <= last_dlv)),
        "last": (last_dlv, pd.Series(True, index=merged.index)),
    }

    irr_cols = []
    dlv_cols = []
    for _, (dates, valid) in candidates.items():
        temp = merged.copy()
        temp["candidate_delivery"] = dates
        m = _compute_ae_ic_d1_d2(temp, "candidate_delivery")
        irr = _irr_series(
            temp, m, temp["clean_price"], m["Ab"], temp["px_last"],
            temp["fut_cnvs_factor"],
        )
        irr[~valid | dates.isna()] = np.nan
        irr_cols.append(irr.to_numpy())
        dlv_cols.append(dates.where(valid).to_numpy(dtype="datetime64[ns]"))

    irr_mat = np.column_stack(irr_cols)
    dlv_mat = np.column_stack(dlv_cols)

    any_valid = ~np.all(np.isnan(irr_mat), axis=1)
    best_irr = np.full(len(merged), np.nan)
    best_dlv = np.full(len(merged), np.datetime64("NaT"), dtype="datetime64[ns]")
    if any_valid.any():
        best_idx = np.nanargmax(irr_mat[any_valid], axis=1)
        best_irr[any_valid] = irr_mat[any_valid, best_idx]
        best_dlv[any_valid] = dlv_mat[any_valid, best_idx]

    settlement = pd.to_datetime(merged["caldt"]) + pd.offsets.BDay(1)
    holding_days = (pd.Series(best_dlv) - settlement.reset_index(drop=True)).dt.days

    out = pd.DataFrame(
        {
            "Date": merged["Date"],
            "tenor": tenor,
            "implied_repo_bps": best_irr,
            "optimal_delivery_date": best_dlv,
            "holding_period_days": holding_days,
            "px_last": merged["px_last"],
            "px_volume": merged["px_volume"],
            "fut_ctd_cusip": merged["fut_ctd_cusip"],
        }
    )
    out = out.drop_duplicates(subset=["Date"]).set_index("Date").sort_index()
    # 5-day centered rolling median to dampen day-count/price noise
    out["implied_repo_bps"] = out["implied_repo_bps"].rolling(5, center=True).median()
    return out


def calc_irr(data_dir: Path = DATA_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Implied repo and holding period for all tenors.

    Returns (implied_repo_df, holding_period_df), each indexed by Date with
    one column per tenor. Implied repo in bps; holding period in days.
    """
    crsp_df = load_crsp_inputs(data_dir)
    repo_frames = []
    holding_frames = []
    for tenor in TENOR_YEARS:
        print(f">> Computing delivery-adjusted IRR for {tenor}...")
        futures_df = load_futures_inputs(tenor, data_dir)
        one = calc_implied_repo_for_tenor(futures_df, crsp_df, tenor)
        if not one.empty:
            repo_frames.append(
                one[["implied_repo_bps"]].rename(columns={"implied_repo_bps": tenor})
            )
            holding_frames.append(
                one[["holding_period_days"]].rename(
                    columns={"holding_period_days": tenor}
                )
            )
    if not repo_frames:
        return pd.DataFrame(), pd.DataFrame()
    implied_repo_df = pd.concat(repo_frames, axis=1).sort_index()
    holding_period_df = pd.concat(holding_frames, axis=1).sort_index()
    return implied_repo_df, holding_period_df


def calc_ois_at_holding_period(
    holding_period_df: pd.DataFrame, data_dir: Path = DATA_DIR
) -> pd.DataFrame:
    """OIS rate (bps) linearly interpolated at the holding period per tenor.

    Uses all available OIS curve points (1M-1Y); per date, interpolation uses
    the non-missing points (at least two required). Holding periods outside
    the grid are clipped to the nearest endpoint.
    """
    ois = format_bbg_basis_treas_sf.load_ois(data_dir=data_dir)
    ois["Date"] = pd.to_datetime(ois["Date"]).dt.tz_localize(None).dt.normalize()
    ois = ois.set_index("Date").sort_index()

    labels = [c for c in OIS_LABEL_DAYS if c in ois.columns]
    if len(labels) < 2:
        raise ValueError(
            f"Need at least two OIS curve points from {list(OIS_LABEL_DAYS)}; "
            f"found {labels}."
        )
    node_days = np.array([OIS_LABEL_DAYS[c] for c in labels], dtype=float)

    holding = holding_period_df.copy()
    holding.index = pd.to_datetime(holding.index).normalize()
    common_idx = holding.index.intersection(ois.index).sort_values()
    holding = holding.reindex(common_idx)
    ois_vals = ois.reindex(common_idx)[labels].to_numpy(dtype=float)

    tenors = list(holding.columns)
    out = np.full((len(common_idx), len(tenors)), np.nan)
    for i in range(len(common_idx)):
        row = ois_vals[i]
        good = ~np.isnan(row)
        if good.sum() < 2:
            continue
        days = node_days[good]
        rates = row[good]
        for j in range(len(tenors)):
            h = holding.iloc[i, j]
            if pd.isna(h):
                continue
            rate_pct = np.interp(np.clip(h, days.min(), days.max()), days, rates)
            out[i, j] = rate_pct * 100.0  # percent -> bps
    return pd.DataFrame(out, index=common_idx, columns=tenors)


def calc_arbitrage_spread(
    implied_repo_df: pd.DataFrame,
    holding_period_df: pd.DataFrame,
    data_dir: Path = DATA_DIR,
) -> pd.DataFrame:
    """Spread (bps) = delivery-adjusted implied repo - OIS at holding period."""
    ois_df = calc_ois_at_holding_period(holding_period_df, data_dir=data_dir)
    irr_aligned, ois_aligned = implied_repo_df.align(ois_df, join="inner", axis=0)
    return (irr_aligned - ois_aligned[irr_aligned.columns]).sort_index()


def load_basis_adj(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    """Load the saved delivery-adjusted basis output from disk."""
    df = pd.read_parquet(Path(data_dir) / OUTPUT_FILE)
    df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)
    return df


def main():
    implied_repo_df, holding_period_df = calc_irr(data_dir=DATA_DIR)
    if implied_repo_df.empty:
        raise RuntimeError("No implied repo produced; check input data.")

    implied_repo_df.reset_index().to_parquet(
        DATA_DIR / "implied_repo_delivery_adjusted.parquet", index=False
    )
    holding_period_df.reset_index().to_parquet(
        DATA_DIR / "holding_period_days.parquet", index=False
    )

    ois_df = calc_ois_at_holding_period(holding_period_df, data_dir=DATA_DIR)
    ois_df.reset_index().rename(columns={"index": "Date"}).to_parquet(
        DATA_DIR / "ois_at_holding_period.parquet", index=False
    )

    spreads = calc_arbitrage_spread(implied_repo_df, holding_period_df, DATA_DIR)
    out = spreads.rename(columns={t: f"Treasury_SF_{t}" for t in spreads.columns})
    out.index.name = "Date"
    out.reset_index().to_parquet(DATA_DIR / OUTPUT_FILE, index=False)
    print(f">> Saved {OUTPUT_FILE} ({len(out):,} rows)")
    print(out.tail(5).to_string())


if __name__ == "__main__":
    main()
