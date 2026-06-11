"""
Pull USD OIS rates and Treasury futures data from Bloomberg via xbbg.

A Bloomberg Terminal must be running on this machine for the pull to work.
Each futures tenor is saved separately (near and first-deferred generic
contracts) to avoid column naming conflicts. Formatting/combining is handled
by ``format_bbg_basis_treas_sf.py``.

Outputs (saved under DATA_DIR):
- ``ois.parquet``: Date + USD OIS tickers (1W, 1M, 2M, 3M, 4M, 5M, 6M, 9M, 1Y)
- ``treasury_{tenor}y_1.parquet``: near (front) generic contract per tenor
- ``treasury_{tenor}y_2.parquet``: first-deferred generic contract per tenor

Fields pulled for each Treasury futures contract
-------------------------------------------------
- PX_LAST: Last Price
- CURRENT_CONTRACT_MONTH_YR: Current Contract Month/Year (e.g. "SEP 25")
- FUT_ACTUAL_REPO_RT: Actual (term) repo rate to delivery of the CTD bond
- FUT_AGGTE_OPEN_INT: Aggregate open interest across listed contracts
- FUT_AGGTE_VOL: Aggregate volume across listed contracts
- FUT_CNVS_FACTOR: Conversion factor of the cheapest-to-deliver (CTD) bond
- FUT_CTD_CUSIP: CUSIP of the CTD bond
- FUT_CTD_GROSS_BASIS: CTD price minus delivery (invoice) price
- FUT_CTD_NET_BASIS: CTD gross basis adjusted for net carry
- FUT_CUR_GEN_TICKER: Current generic futures ticker
- FUT_IMPLIED_REPO_RT: Bloomberg's implied repo (cash-and-carry return) of the CTD
- FUT_PX: Futures trade price
- CONVENTIONAL_CTD_FORWARD_FRSK: Conventional CTD forward risk
- CTD_CUSIP_EOD / CNVS_FACTOR_EOD: End-of-day CTD identifiers (current day only)
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

from settings import config

DATA_DIR: Path = config("DATA_DIR")
START_DATE: str = config("START_DATE")
END_DATE: str = config("END_DATE")
MIN_NON_NULL_RATIO: float = 0.5

# USD OIS curve tickers. The 2M-9M points are used to interpolate the
# financing benchmark at the futures holding period; 1W/1M/1Y complete the
# short curve for the Bloomberg-method interpolation.
OIS_TICKER_TO_LABEL = {
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

FUTURES_FIELDS = [
    "PX_LAST",
    "CURRENT_CONTRACT_MONTH_YR",
    "FUT_ACTUAL_REPO_RT",
    "FUT_AGGTE_OPEN_INT",
    "FUT_AGGTE_VOL",
    "FUT_CNVS_FACTOR",
    "FUT_CTD_CUSIP",
    "FUT_CTD_GROSS_BASIS",
    "FUT_CTD_NET_BASIS",
    "FUT_CUR_GEN_TICKER",
    "FUT_IMPLIED_REPO_RT",
    "FUT_PX",
    "CONVENTIONAL_CTD_FORWARD_FRSK",
    "CTD_CUSIP_EOD",
    "CNVS_FACTOR_EOD",
]


def futures_ticker_map() -> dict[int, tuple[str, str]]:
    """Map tenor (years) to (near, first-deferred) generic Bloomberg tickers.

    Contracts follow Siriwardane, Sunderam, and Wallen (2023):
    TU = 2Y note, FV = 5Y note, TY = 10Y note, US = classic bond
    (15Y-25Y deliverable basket, used as the "20Y" tenor), and
    WN = Ultra Bond (>= 25Y deliverable basket, used as the "30Y" tenor).
    """
    return {
        2: ("TU1 Comdty", "TU2 Comdty"),
        5: ("FV1 Comdty", "FV2 Comdty"),
        10: ("TY1 Comdty", "TY2 Comdty"),
        20: ("US1 Comdty", "US2 Comdty"),
        30: ("WN1 Comdty", "WN2 Comdty"),
    }


def ois_tickers() -> list[str]:
    """Bloomberg tickers for the USD OIS curve used downstream."""
    return list(OIS_TICKER_TO_LABEL.keys())


def _check_coverage(df: pd.DataFrame, message: str = "") -> None:
    """Warn when a column has low non-null coverage."""
    total_rows = len(df)
    for col in df.columns:
        non_null_ratio = (df[col].notna().sum() / total_rows) if total_rows else 0.0
        if non_null_ratio < MIN_NON_NULL_RATIO:
            warnings.warn(
                f"{message} Low data coverage for {col}: "
                f"{non_null_ratio:.1%} non-null",
                category=UserWarning,
            )


def pull_ois_history(
    start_date: str = START_DATE, end_date: str = END_DATE
) -> pd.DataFrame:
    """Fetch historical USD OIS levels (PX_LAST) from Bloomberg via xbbg.

    Returns Date + raw ticker columns. Consumers rename to compact labels
    (OIS_1W, ..., OIS_1Y) via ``format_bbg_basis_treas_sf.rename_ois_columns``.
    """
    from xbbg import blp

    tickers = ois_tickers()
    df = blp.bdh(
        tickers=tickers, flds=["PX_LAST"], start_date=start_date, end_date=end_date
    )
    if isinstance(df.columns, pd.MultiIndex) and df.columns.nlevels == 2:
        df.columns = df.columns.droplevel(level=1)

    df = df.reset_index().rename(columns={"index": "Date", "date": "Date"})
    df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)
    df = df[["Date", *[t for t in tickers if t in df.columns]]]
    _check_coverage(df.drop(columns=["Date"]), message="OIS:")
    return df


def pull_futures_for_tenor(
    tenor: int, start_date: str = START_DATE, end_date: str = END_DATE
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch Treasury futures data (near and first-deferred) for one tenor."""
    from xbbg import blp

    tenor_to_tickers = futures_ticker_map()
    if tenor not in tenor_to_tickers:
        raise ValueError(f"Unsupported tenor: {tenor}")
    near_tkr, def_tkr = tenor_to_tickers[tenor]

    df = blp.bdh(
        tickers=[near_tkr, def_tkr],
        flds=FUTURES_FIELDS,
        start_date=start_date,
        end_date=end_date,
        timeout=10000,
    )

    frames = []
    for tkr in (near_tkr, def_tkr):
        one = df[tkr].copy()
        one.index.name = "Date"
        one = one.reset_index()
        one["Date"] = pd.to_datetime(one["Date"]).dt.tz_localize(None)
        _check_coverage(one.drop(columns=["Date"]), message=f"Tenor={tenor}:")
        frames.append(one)
    return frames[0], frames[1]


def load_ois(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    """Load raw OIS data from parquet file."""
    return pd.read_parquet(Path(data_dir) / "ois.parquet")


def load_treasury_tenor(
    tenor: int, data_dir: Path = DATA_DIR
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load Treasury futures data (near, first-deferred) for one tenor."""
    df1 = pd.read_parquet(Path(data_dir) / f"treasury_{tenor}y_1.parquet")
    df2 = pd.read_parquet(Path(data_dir) / f"treasury_{tenor}y_2.parquet")
    return df1, df2


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    ois = pull_ois_history()
    ois.to_parquet(DATA_DIR / "ois.parquet", index=False)
    print(f">> Saved ois.parquet ({len(ois):,} rows)")

    for tenor in futures_ticker_map():
        futures_data1, futures_data2 = pull_futures_for_tenor(tenor)
        futures_data1.to_parquet(DATA_DIR / f"treasury_{tenor}y_1.parquet", index=False)
        futures_data2.to_parquet(DATA_DIR / f"treasury_{tenor}y_2.parquet", index=False)
        print(f">> Saved treasury_{tenor}y_1.parquet, treasury_{tenor}y_2.parquet")


if __name__ == "__main__":
    main()
