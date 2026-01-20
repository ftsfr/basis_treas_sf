"""
Fetches Treasury yields and secured financing (SF) rates from Bloomberg.

This module pulls Treasury constant maturity yields and SOFR-based secured financing
rates to calculate Treasury-SF basis spreads.
"""

import sys
from pathlib import Path

sys.path.insert(0, "./src")

import pandas as pd

import chartbook

BASE_DIR = chartbook.env.get_project_root()
DATA_DIR = BASE_DIR / "_data"
END_DATE = pd.Timestamp.today().strftime("%Y-%m-%d")


def pull_treasury_sf_data(start_date="2000-01-01", end_date=END_DATE):
    """
    Fetch historical Treasury yields and SF rates from Bloomberg using xbbg.

    Parameters
    ----------
    start_date : str
        Start date in 'YYYY-MM-DD' format
    end_date : str
        End date in 'YYYY-MM-DD' format

    Returns
    -------
    dict
        Dictionary with two DataFrames:
        - 'treasury_yields': Treasury constant maturity yields
        - 'sf_rates': SOFR-based secured financing rates
    """
    # import here to enhance compatibility with devices that don't support xbbg
    from xbbg import blp

    # Treasury yield tickers (constant maturity)
    treasury_tickers = [
        "USGG2YR Index",   # 2-Year Treasury
        "USGG5YR Index",   # 5-Year Treasury
        "USGG10YR Index",  # 10-Year Treasury
        "USGG20YR Index",  # 20-Year Treasury
        "USGG30YR Index",  # 30-Year Treasury
    ]

    # SOFR-based secured financing rate tickers
    # These are SOFR OIS swap rates at various tenors
    sf_tickers = [
        "USOSFR2 Curncy",   # 2-Year SOFR OIS
        "USOSFR5 Curncy",   # 5-Year SOFR OIS
        "USOSFR10 Curncy",  # 10-Year SOFR OIS
        "USOSFR20 Curncy",  # 20-Year SOFR OIS
        "USOSFR30 Curncy",  # 30-Year SOFR OIS
    ]

    fields = ["PX_LAST"]

    # Helper to flatten multi-index columns from xbbg
    def process_bloomberg_df(df):
        if not df.empty and isinstance(df.columns, pd.MultiIndex):
            df.columns = [f"{t[0]}_{t[1]}" for t in df.columns]
            df.reset_index(inplace=True)
        return df

    print(">> Pulling Treasury-SF data from Bloomberg...")

    # Pull Treasury yields
    print("   Pulling Treasury yields...")
    treasury_df = process_bloomberg_df(
        blp.bdh(
            tickers=treasury_tickers,
            flds=fields,
            start_date=start_date,
            end_date=end_date,
        )
    )

    # Pull SF rates
    print("   Pulling secured financing (SOFR OIS) rates...")
    sf_df = process_bloomberg_df(
        blp.bdh(
            tickers=sf_tickers,
            flds=fields,
            start_date=start_date,
            end_date=end_date,
        )
    )

    return {
        "treasury_yields": treasury_df,
        "sf_rates": sf_df,
    }


def load_treasury_yields(data_dir=DATA_DIR):
    """Load Treasury yields from parquet file."""
    path = data_dir / "treasury_yields.parquet"
    return pd.read_parquet(path)


def load_sf_rates(data_dir=DATA_DIR):
    """Load SF rates from parquet file."""
    path = data_dir / "sf_rates.parquet"
    return pd.read_parquet(path)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Pull data from source
    data = pull_treasury_sf_data()

    # Save each dataset to parquet
    data["treasury_yields"].to_parquet(DATA_DIR / "treasury_yields.parquet")
    print(f">> Saved treasury_yields.parquet")

    data["sf_rates"].to_parquet(DATA_DIR / "sf_rates.parquet")
    print(f">> Saved sf_rates.parquet")


if __name__ == "__main__":
    main()
