"""
Pull CRSP daily Treasury data from WRDS for the implied repo calculation.

Adapted from the implementation by George Lord and Max Zhalilo
(https://github.com/maxz073/p10_Siriwardane_et_al_2026), file
``src/pull_CRSP.py``.

Reference:
    CRSP US TREASURY DATABASE GUIDE
    https://www.crsp.org/wp-content/uploads/guides/CRSP_US_Treasury_Database_Guide_for_SAS_ASCII_EXCEL_R.pdf

Purpose:
    Pull the bond-side inputs needed for the Treasury futures implied repo
    rate (IRR): clean price, accrued interest at the quote date, coupon rate,
    and a derived semiannual coupon schedule.

Notes:
    - The pull is restricted to the cheapest-to-deliver (CTD) CUSIPs observed
      in the Bloomberg futures files (FUT_CTD_CUSIP), which keeps the query
      small. CRSP ``tcusip`` and Bloomberg ``FUT_CTD_CUSIP`` are both 8-char
      CUSIPs (no check digit), so they merge directly.
    - CRSP does not provide coupon frequency or the coupon date schedule in
      ``tfz_dly``/``tfz_iss``. For Treasury notes and bonds we assume
      semiannual coupons (frequency=2, ACT/ACT) and derive previous/next
      coupon dates by stepping backward from the maturity date in 6-month
      increments (as in Lord and Zhalilo).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from pandas.tseries.offsets import DateOffset

from settings import config

DATA_DIR = Path(config("DATA_DIR"))
WRDS_USERNAME = config("WRDS_USERNAME")
START_DATE = config("START_DATE")
END_DATE = config("END_DATE")

CRSP_OUTPUT_FILE = "crsp_treasury_ctd.parquet"
FUTURES_TENORS = [2, 5, 10, 20, 30]


def collect_ctd_cusips(data_dir: Path = DATA_DIR) -> list[str]:
    """Collect unique CTD CUSIPs observed in the Bloomberg futures files."""
    cusips: set[str] = set()
    for tenor in FUTURES_TENORS:
        for leg in (1, 2):
            path = data_dir / f"treasury_{tenor}y_{leg}.parquet"
            if not path.exists():
                continue
            df = pd.read_parquet(path)
            for col in ("FUT_CTD_CUSIP", "CTD_CUSIP_EOD"):
                if col in df.columns:
                    vals = (
                        df[col]
                        .astype(str)
                        .str.strip()
                        .str.strip('"')
                        .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "0": pd.NA})
                        .dropna()
                        .unique()
                    )
                    cusips.update(vals)
    return sorted(cusips)


def _coupon_schedule(maturity: pd.Timestamp, earliest: pd.Timestamp) -> list:
    """Semiannual coupon dates stepping backward from maturity until ``earliest``.

    Mirrors the iterative ``DateOffset(months=6)`` stepping in Lord and
    Zhalilo's ``pull_CRSP.py`` (note: iterative stepping handles month-end
    dates slightly differently than a single 6*k-month offset).
    """
    dates = [pd.Timestamp(maturity)]
    while dates[-1] > earliest:
        dates.append(dates[-1] - DateOffset(months=6))
    return dates[::-1]  # ascending


def add_coupon_schedule_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Add semiannual coupon schedule fields needed for IRR work.

    Assumptions for U.S. Treasury notes/bonds: semiannual coupons, ACT/ACT.
    ``prev_coupon_date`` is the latest schedule date <= ``caldt``;
    ``next_coupon_date`` = ``prev_coupon_date`` + 6 months.
    """
    df = df.reset_index(drop=True)
    df["coupon_frequency"] = 2
    df["coupon_interval_months"] = 6
    df["day_count_basis"] = "ACT/ACT"

    import numpy as np

    prev_arr = np.full(len(df), np.datetime64("NaT"), dtype="datetime64[ns]")
    next_arr = prev_arr.copy()

    valid = df["caldt"].notna() & df["tmatdt"].notna()
    for mat, grp in df.loc[valid].groupby("tmatdt"):
        earliest = grp["caldt"].min() - DateOffset(months=6)
        schedule = pd.DatetimeIndex(_coupon_schedule(mat, earliest))
        # prev coupon = latest schedule date <= caldt
        pos = schedule.searchsorted(grp["caldt"], side="right") - 1
        pos = pos.clip(0, len(schedule) - 1)
        prev = schedule[pos]
        locs = df.index.get_indexer(grp.index)
        prev_arr[locs] = prev.to_numpy()
        next_arr[locs] = (prev + DateOffset(months=6)).to_numpy()

    df["prev_coupon_date"] = prev_arr
    df["next_coupon_date"] = next_arr
    return df


def pull_CRSP_treasury_for_irr(
    start_date=START_DATE,
    end_date=END_DATE,
    wrds_username=WRDS_USERNAME,
    cusips=None,
):
    """Pull CRSP Treasury bond-side fields needed for implied repo calculations.

    Returns daily bond data with: tcusip, caldt, clean_price (bid/ask mid),
    accrued_interest_begin, dirty_price, coupon_rate, coupon schedule fields,
    and issue/maturity dates.
    """
    import wrds

    cusip_filter = ""
    if cusips:
        cusip_list = ", ".join([f"'{c}'" for c in cusips])
        cusip_filter = f"AND iss.tcusip IN ({cusip_list})"

    query = f"""
    SELECT
        tfz.kytreasno,
        tfz.kycrspid,
        iss.tcusip,

        tfz.caldt,
        iss.tdatdt,
        iss.tmatdt,

        tfz.tdbid,
        tfz.tdask,
        tfz.tdaccint,
        tfz.tdyld,

        iss.tcouprt,
        iss.itype,

        ((tfz.tdbid + tfz.tdask) / 2.0) AS clean_price,
        (((tfz.tdbid + tfz.tdask) / 2.0) + tfz.tdaccint) AS dirty_price

    FROM
        crspm.tfz_dly AS tfz
    LEFT JOIN
        crspm.tfz_iss AS iss
    ON
        tfz.kytreasno = iss.kytreasno
        AND tfz.kycrspid = iss.kycrspid
    WHERE
        tfz.caldt BETWEEN '{start_date}' AND '{end_date}'
        AND iss.itype IN (1, 2)
        {cusip_filter}
    """

    db = wrds.Connection(wrds_username=wrds_username)
    df = db.raw_sql(query, date_cols=["caldt", "tdatdt", "tmatdt"])
    db.close()

    df = df.rename(
        columns={
            "tdaccint": "accrued_interest_begin",
            "tcouprt": "coupon_rate",
        }
    )
    df = add_coupon_schedule_fields(df)
    df = df.sort_values(["tcusip", "caldt"]).reset_index(drop=True)
    return df


def load_CRSP_treasury_for_irr(data_dir=DATA_DIR) -> pd.DataFrame:
    """Load cached CRSP bond data; falls back to the students' TFZ_IRR name."""
    for name in (CRSP_OUTPUT_FILE, "TFZ_IRR.parquet"):
        path = Path(data_dir) / name
        if path.exists():
            df = pd.read_parquet(path)
            df["caldt"] = pd.to_datetime(df["caldt"])
            return df
    raise FileNotFoundError(
        f"CRSP input not found in {data_dir}. Expected {CRSP_OUTPUT_FILE} "
        "or TFZ_IRR.parquet. Run pull_crsp_treasury.py (requires WRDS)."
    )


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    cusips = collect_ctd_cusips(DATA_DIR)
    if not cusips:
        raise FileNotFoundError(
            "No CTD CUSIPs found. Run pull_bbg_basis_treas_sf.py first so the "
            "treasury_{tenor}y_{1,2}.parquet files exist."
        )
    print(f">> Pulling CRSP daily Treasury data for {len(cusips)} CTD CUSIPs...")

    df = pull_CRSP_treasury_for_irr(cusips=cusips)
    path = DATA_DIR / CRSP_OUTPUT_FILE
    df.to_parquet(path, index=False)
    print(f">> Saved {path.name} ({len(df):,} rows)")


if __name__ == "__main__":
    main()
