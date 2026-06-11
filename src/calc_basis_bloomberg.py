"""
Treasury cash-futures basis using Bloomberg's implied repo (the "old" method).

The basis is the difference between Bloomberg's futures-implied repo rate on
the first-deferred Treasury futures contract (field ``FUT_IMPLIED_REPO_RT``)
and the USD OIS rate interpolated to the contract's time-to-maturity:

    Treasury_SF_{tenor} = (Implied_Repo_2 - OIS_2) * 100   [bps]

Bloomberg's implied repo assumes the CTD bond is delivered on a fixed date
(the last delivery day of the contract month). When carry is negative, the
short's delivery option makes early delivery optimal, so this assumption
biases the implied repo. See ``calc_basis_delivery_adjusted.py`` for the
delivery-timing-adjusted alternative.

Ported from the ftsfr monorepo (``src/basis_treas_sf/calc_basis_treas_sf.py``).
"""

from __future__ import annotations

import calendar
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from settings import config
import format_bbg_basis_treas_sf

DATA_DIR = config("DATA_DIR")

OUTPUT_FILE = "basis_treas_sf_bbg.parquet"


def parse_contract_date(contract_str):
    """Parse a contract string like 'DEC 21' into (month, year)."""
    if pd.isna(contract_str) or not isinstance(contract_str, str):
        return None, None
    month_abbr = contract_str[:3].upper()
    year_str = contract_str[4:6]
    month_map = {"DEC": 12, "MAR": 3, "JUN": 6, "SEP": 9}
    month = month_map.get(month_abbr, np.nan)
    try:
        year = int(year_str) + 2000
    except (ValueError, TypeError):
        year = np.nan
    return month, year


def interpolate_ois(ttm, ois_1w, ois_1m, ois_3m, ois_6m, ois_1y):
    """Interpolate the OIS rate based on time-to-maturity in days."""
    if ttm <= 7:
        return ois_1w
    elif 7 < ttm <= 30:
        return ((30 - ttm) / 23) * ois_1w + ((ttm - 7) / 23) * ois_1m
    elif 30 < ttm <= 90:
        return ((90 - ttm) / 60) * ois_1m + ((ttm - 30) / 60) * ois_3m
    elif 90 < ttm <= 180:
        return ((180 - ttm) / 90) * ois_3m + ((ttm - 90) / 90) * ois_6m
    else:
        return ((360 - ttm) / 180) * ois_6m + ((ttm - 180) / 180) * ois_1y


def rolling_outlier_flag(
    df: pd.DataFrame,
    group_col: str,
    date_col: str,
    value_col: str,
    window_days: int = 45,
    threshold: int = 10,
) -> pd.DataFrame:
    """Flag outliers using a rolling +/- window_days per group based on MAD.

    A value is flagged when its absolute deviation from the window median
    (window excludes the value itself) is at least ``threshold`` times the
    window's mean absolute deviation. Returns a copy with a boolean column
    ``bad_price``.
    """
    df = df.copy()
    df["bad_price"] = False
    df[date_col] = pd.to_datetime(df[date_col])
    df.sort_values(date_col, inplace=True)

    window = np.timedelta64(window_days, "D")
    for _, group in df.groupby(group_col):
        dates = group[date_col].values
        vals = group[value_col].to_numpy(dtype=float)
        flags = np.zeros(len(group), dtype=bool)
        for i in range(len(group)):
            if np.isnan(vals[i]):
                continue
            lo = np.searchsorted(dates, dates[i] - window, side="left")
            hi = np.searchsorted(dates, dates[i] + window, side="right")
            w = np.concatenate([vals[lo:i], vals[i + 1 : hi]])
            w = w[~np.isnan(w)]
            if w.size == 0:
                continue
            med = np.median(w)
            mad = np.abs(w - med).mean()
            if mad > 0 and abs(vals[i] - med) / mad >= threshold:
                flags[i] = True
        df.loc[group.index[flags], "bad_price"] = True
    return df


def compute_treasury_long(
    treasury_df: pd.DataFrame,
    ois_df: pd.DataFrame,
    last_day_df: pd.DataFrame,
) -> pd.DataFrame:
    """Build the long futures panel with TTM, interpolated OIS, and cleaned spreads."""
    treasury_df = treasury_df.copy()
    ois_df = ois_df.copy()
    last_day_df = last_day_df.copy()

    treasury_df["Date"] = pd.to_datetime(treasury_df["Date"]).dt.tz_localize(None)
    ois_df["Date"] = pd.to_datetime(ois_df["Date"]).dt.tz_localize(None)

    df_long = treasury_df.copy()

    # Bloomberg implied repo coverage is unreliable before mid-2004
    cutoff_date = datetime(2004, 6, 22)
    df_long = df_long[df_long["Date"] > cutoff_date].copy()

    # Time-to-maturity for the near (1) and first-deferred (2) contracts,
    # measured to the last observed business day of the contract month
    for v in [1, 2]:
        contract_col = f"Contract_{v}"
        ttm_col = f"TTM_{v}"
        mat_date_col = f"Mat_Date_{v}"

        df_long[[f"Mat_Month_{v}", f"Mat_Year_{v}"]] = df_long[contract_col].apply(
            lambda s: pd.Series(parse_contract_date(s))
        )

        df_long = df_long.merge(
            last_day_df,
            left_on=[f"Mat_Month_{v}", f"Mat_Year_{v}"],
            right_on=["Mat_Month", "Mat_Year"],
            how="left",
            suffixes=("", f"_{v}"),
        )
        def make_mat_date(row, version):
            try:
                year = int(row[f"Mat_Year_{version}"])
                month = int(row[f"Mat_Month_{version}"])
                day = row["Mat_Day"]
                if pd.isna(day):
                    # Contract month beyond the sample: use last calendar day
                    day = calendar.monthrange(year, month)[1]
                return datetime(year, month, int(day))
            except Exception:
                return pd.NaT

        df_long[mat_date_col] = df_long.apply(lambda row: make_mat_date(row, v), axis=1)
        df_long[ttm_col] = (df_long[mat_date_col] - df_long["Date"]).dt.days

        df_long.drop(
            columns=[
                f"Mat_Month_{v}",
                f"Mat_Year_{v}",
                "Mat_Month",
                "Mat_Year",
                "Mat_Day",
            ],
            inplace=True,
            errors="ignore",
        )

    df_long = df_long.merge(ois_df, on="Date", how="left")

    for v in [1, 2]:
        ttm_col = f"TTM_{v}"
        ois_col = f"OIS_{v}"
        df_long[ois_col] = df_long.apply(
            lambda row: interpolate_ois(
                row[ttm_col],
                row.get("OIS_1W", np.nan),
                row.get("OIS_1M", np.nan),
                row.get("OIS_3M", np.nan),
                row.get("OIS_6M", np.nan),
                row.get("OIS_1Y", np.nan),
            )
            if pd.notnull(row[ttm_col])
            else np.nan,
            axis=1,
        )

    # Arbitrage spread (bps): implied repo minus maturity-matched OIS
    df_long["Arb_N"] = (df_long["Implied_Repo_1"] - df_long["OIS_1"]) * 100
    df_long["Arb_D"] = (df_long["Implied_Repo_2"] - df_long["OIS_2"]) * 100
    df_long["arb"] = df_long["Arb_D"]

    df_long = rolling_outlier_flag(
        df_long,
        group_col="Tenor",
        date_col="Date",
        value_col="arb",
        window_days=45,
        threshold=10,
    )
    df_long.loc[df_long["bad_price"] & df_long["arb"].notnull(), "arb"] = np.nan

    # Require trading volume in the deferred contract
    df_long = df_long[df_long["Vol_2"].notnull()].copy()

    return df_long


def compute_treasury_output(df_long: pd.DataFrame) -> pd.DataFrame:
    """Create the final wide output with Treasury SF spreads by tenor."""
    df_long = df_long.copy()

    df_long["T_SF_Rf"] = df_long["Implied_Repo_2"] * 100
    df_long.loc[df_long["bad_price"] & df_long["T_SF_Rf"].notnull(), "T_SF_Rf"] = np.nan
    df_long["rf_ois_t_sf_mat"] = df_long["OIS_2"] * 100
    df_long["T_SF_TTM"] = df_long["TTM_2"]
    df_out = df_long[["Date", "Tenor", "T_SF_Rf", "rf_ois_t_sf_mat", "T_SF_TTM"]].copy()

    df_wide = df_out.pivot(index="Date", columns="Tenor")
    df_wide.columns = [
        "_".join([str(c) for c in col]).strip() for col in df_wide.columns.values
    ]
    df_wide.reset_index(inplace=True)

    for tenor in [2, 5, 10, 20, 30]:
        rf_col = f"T_SF_Rf_{tenor}"
        ois_col = f"rf_ois_t_sf_mat_{tenor}"
        if rf_col in df_wide.columns and ois_col in df_wide.columns:
            df_wide[f"Treasury_SF_{tenor}Y"] = df_wide[rf_col] - df_wide[ois_col]

    out_cols = ["Date"] + [
        f"Treasury_SF_{t}Y" for t in [2, 5, 10, 20, 30]
        if f"Treasury_SF_{t}Y" in df_wide.columns
    ]
    df_final = df_wide[out_cols].copy()
    value_cols = [c for c in df_final.columns if c != "Date"]
    df_final.loc[:, value_cols] = df_final[value_cols].astype(float).ffill(limit=5)

    return df_final


def calc_treasury_bbg(
    treasury_df: pd.DataFrame,
    ois_df: pd.DataFrame,
    last_day_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute the Bloomberg-method basis output from inputs (pure function)."""
    df_long = compute_treasury_long(treasury_df, ois_df, last_day_df)
    return compute_treasury_output(df_long)


def load_basis_bbg(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    """Load the saved Bloomberg-method basis output from disk."""
    df = pd.read_parquet(Path(data_dir) / OUTPUT_FILE)
    df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)
    return df


def main():
    treasury_df = format_bbg_basis_treas_sf.load_treasury_df(data_dir=DATA_DIR)
    ois_df = format_bbg_basis_treas_sf.load_ois(data_dir=DATA_DIR)
    last_day_df = format_bbg_basis_treas_sf.load_last_day(data_dir=DATA_DIR)

    keep_cols = [
        c
        for c in ois_df.columns
        if c in ["Date", "OIS_1W", "OIS_1M", "OIS_3M", "OIS_6M", "OIS_1Y"]
    ]
    ois_df = ois_df[keep_cols]

    df_final = calc_treasury_bbg(treasury_df, ois_df, last_day_df)
    output_file = DATA_DIR / OUTPUT_FILE
    df_final.to_parquet(output_file, index=False)
    print(f">> Saved {OUTPUT_FILE} ({len(df_final):,} rows)")
    print(df_final.tail(5).to_string())


if __name__ == "__main__":
    main()
