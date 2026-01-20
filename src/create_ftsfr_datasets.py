"""
Create FTSFR standardized datasets for Treasury-SF basis.

Outputs:
- ftsfr_treasury_sf_basis.parquet: Treasury-SF basis spreads in basis points
"""

import sys
from pathlib import Path

sys.path.insert(0, "./src")

import pandas as pd

import chartbook
import calc_treasury_sf_basis

BASE_DIR = chartbook.env.get_project_root()
DATA_DIR = BASE_DIR / "_data"


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(">> Creating ftsfr_treasury_sf_basis...")

    # Calculate basis spreads
    df_all = calc_treasury_sf_basis.calculate_treasury_sf_basis(data_dir=DATA_DIR)

    # Convert from wide to long format
    df_stacked = df_all.stack().reset_index()
    df_stacked.columns = ["ds", "unique_id", "y"]

    # Reorder columns to FTSFR standard: unique_id, ds, y
    df_stacked = df_stacked[["unique_id", "ds", "y"]]
    df_stacked["ds"] = pd.to_datetime(df_stacked["ds"])

    # Clean up
    df_stacked = df_stacked.dropna()
    df_stacked = df_stacked.sort_values(by=["unique_id", "ds"]).reset_index(drop=True)

    # Save
    output_path = DATA_DIR / "ftsfr_treasury_sf_basis.parquet"
    df_stacked.to_parquet(output_path, index=False)
    print(f"   Saved: {output_path.name}")
    print(f"   Records: {len(df_stacked):,}")
    print(f"   Series: {df_stacked['unique_id'].nunique()}")


if __name__ == "__main__":
    main()
