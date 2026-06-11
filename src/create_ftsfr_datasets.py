"""
Create FTSFR standardized datasets for the Treasury cash-futures basis.

Outputs (long format: unique_id, ds, y):
- ``ftsfr_treasury_sf_basis.parquet``: delivery-adjusted basis (corrected
  method; implied repo with optimal delivery timing minus OIS at the holding
  period)
- ``ftsfr_treasury_sf_basis_bbg.parquet``: Bloomberg-method basis
  (FUT_IMPLIED_REPO_RT minus OIS interpolated to contract maturity)
"""

import pandas as pd

from settings import config
import calc_basis_bloomberg
import calc_basis_delivery_adjusted

DATA_DIR = config("DATA_DIR")


def to_ftsfr_long(df_wide: pd.DataFrame) -> pd.DataFrame:
    """Convert a wide basis DataFrame (Date + Treasury_SF_* columns) to
    FTSFR long format (unique_id, ds, y)."""
    df = df_wide.copy()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date")
    df_stacked = df.stack().reset_index()
    df_stacked.columns = ["ds", "unique_id", "y"]
    df_stacked = df_stacked[["unique_id", "ds", "y"]]
    df_stacked["ds"] = pd.to_datetime(df_stacked["ds"])
    df_stacked = df_stacked.dropna()
    return df_stacked.sort_values(by=["unique_id", "ds"]).reset_index(drop=True)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    for label, loader, out_name in [
        (
            "delivery-adjusted",
            calc_basis_delivery_adjusted.load_basis_adj,
            "ftsfr_treasury_sf_basis.parquet",
        ),
        (
            "Bloomberg-method",
            calc_basis_bloomberg.load_basis_bbg,
            "ftsfr_treasury_sf_basis_bbg.parquet",
        ),
    ]:
        df_wide = loader(data_dir=DATA_DIR)
        df_long = to_ftsfr_long(df_wide)
        output_path = DATA_DIR / out_name
        df_long.to_parquet(output_path, index=False)
        print(
            f">> Saved {out_name} ({label}): {len(df_long):,} records, "
            f"{df_long['unique_id'].nunique()} series"
        )


if __name__ == "__main__":
    main()
