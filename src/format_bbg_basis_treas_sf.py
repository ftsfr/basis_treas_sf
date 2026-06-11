"""
Format and combine individual Bloomberg data files into consolidated datasets.

Takes the individual parquet files created by ``pull_bbg_basis_treas_sf.py``
and combines them into a single consolidated dataset with proper column
naming and derived fields. Ported from the ftsfr monorepo
(``src/basis_treas_sf/format_bbg_basis_treas_sf.py``).

Inputs (from DATA_DIR):
- ``ois.parquet``: USD OIS rates (raw Bloomberg ticker columns)
- ``treasury_{tenor}y_{1,2}.parquet``: per-tenor futures data (near/deferred)

Outputs (saved under DATA_DIR):
- ``treasury_df.parquet``: combined long-format futures data for all tenors
- ``last_day.parquet``: (Mat_Year, Mat_Month) -> Mat_Day (last observed
  business day per month, used as the contract settlement proxy)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from settings import config

DATA_DIR: Path = config("DATA_DIR")

OIS_RENAME_MAP = {
    "USSO1Z CMPN Curncy": "OIS_1W",
    "USSOA CMPN Curncy": "OIS_1M",
    "USSOB CMPN Curncy": "OIS_2M",
    "USSOC CMPN Curncy": "OIS_3M",
    "USSOD CMPN Curncy": "OIS_4M",
    "USSOE CMPN Curncy": "OIS_5M",
    "USSOF CMPN Curncy": "OIS_6M",
    "USSOI CMPN Curncy": "OIS_9M",
    "USSO1 CMPN Curncy": "OIS_1Y",
}


def rename_ois_columns(df_ois: pd.DataFrame) -> pd.DataFrame:
    """Rename Bloomberg OIS tickers to compact labels expected downstream."""
    df = df_ois.copy()
    df.columns = [OIS_RENAME_MAP.get(c, c) for c in df.columns]
    return df


def build_last_day_mapping_from_dates(dates: pd.Series) -> pd.DataFrame:
    """Construct (Mat_Year, Mat_Month) -> Mat_Day mapping as last observed day."""
    df_dates = pd.DataFrame({"Date": pd.to_datetime(dates)})
    df_dates["Mat_Month"] = df_dates["Date"].dt.month
    df_dates["Mat_Year"] = df_dates["Date"].dt.year
    df_dates = df_dates.sort_values("Date").drop_duplicates(
        ["Mat_Year", "Mat_Month"], keep="last"
    )
    df_dates["Mat_Day"] = df_dates["Date"].dt.day
    return df_dates[["Date", "Mat_Month", "Mat_Year", "Mat_Day"]].reset_index(
        drop=True
    )


def combine_treasury_futures_data(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    """Combine per-tenor futures files into a single long-format DataFrame."""
    tenors = [2, 5, 10, 20, 30]
    frames = []

    for tenor in tenors:
        filepath_1 = data_dir / f"treasury_{tenor}y_1.parquet"
        filepath_2 = data_dir / f"treasury_{tenor}y_2.parquet"
        if not filepath_1.exists() or not filepath_2.exists():
            print(f"Warning: missing futures files for {tenor}Y tenor, skipping")
            continue

        df1 = pd.read_parquet(filepath_1).rename(
            columns={
                "FUT_IMPLIED_REPO_RT": "Implied_Repo_1",
                "FUT_AGGTE_VOL": "Vol_1",
                "PX_LAST": "Price_1",
                "CURRENT_CONTRACT_MONTH_YR": "Contract_1",
            }
        )
        df2 = pd.read_parquet(filepath_2).rename(
            columns={
                "FUT_IMPLIED_REPO_RT": "Implied_Repo_2",
                "FUT_AGGTE_VOL": "Vol_2",
                "PX_LAST": "Price_2",
                "CURRENT_CONTRACT_MONTH_YR": "Contract_2",
            }
        )

        cols_1 = ["Date", "Implied_Repo_1", "Vol_1", "Price_1", "Contract_1"]
        cols_2 = ["Date", "Implied_Repo_2", "Vol_2", "Price_2", "Contract_2"]
        for col in cols_1:
            if col not in df1.columns:
                df1[col] = None
        for col in cols_2:
            if col not in df2.columns:
                df2[col] = None

        df_tenor = df1[cols_1].merge(df2[cols_2], on="Date", how="outer")
        df_tenor["Tenor"] = tenor

        key_cols = [c for c in df_tenor.columns if c not in ("Date", "Tenor")]
        if not df_tenor[key_cols].notna().any().any():
            print(f"Warning: no meaningful data for {tenor}Y tenor, skipping")
            continue
        frames.append(df_tenor)

    if not frames:
        raise FileNotFoundError("No treasury futures files found to combine")

    treasury_df = pd.concat(frames, ignore_index=True)
    treasury_df["Date"] = pd.to_datetime(treasury_df["Date"]).dt.tz_localize(None)
    treasury_df = treasury_df.sort_values(["Date", "Tenor"]).reset_index(drop=True)
    print(f"Combined tenors: {sorted(treasury_df['Tenor'].unique())}")
    return treasury_df


def load_ois(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    """Load OIS data with compact column labels."""
    df = pd.read_parquet(Path(data_dir) / "ois.parquet")
    return rename_ois_columns(df)


def load_treasury_df(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    """Load combined Treasury futures data from parquet file."""
    return pd.read_parquet(Path(data_dir) / "treasury_df.parquet")


def load_last_day(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    """Load last day mapping from parquet file."""
    return pd.read_parquet(Path(data_dir) / "last_day.parquet")


def main():
    treasury_df = combine_treasury_futures_data(data_dir=DATA_DIR)
    treasury_df.to_parquet(DATA_DIR / "treasury_df.parquet", index=False)

    last_day = build_last_day_mapping_from_dates(treasury_df["Date"])
    last_day.to_parquet(DATA_DIR / "last_day.parquet", index=False)
    print(f">> Saved treasury_df.parquet ({len(treasury_df):,} rows), last_day.parquet")


if __name__ == "__main__":
    main()
