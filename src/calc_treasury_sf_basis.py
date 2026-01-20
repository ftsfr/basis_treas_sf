"""
Calculate Treasury-Secured Financing (SF) basis.

The Treasury-SF basis is calculated as:
    Basis = Treasury Yield - SF Rate (SOFR OIS)

This spread measures the relative value between Treasury securities and
SOFR-based secured financing rates at various maturities.

Data Sources:
    - Bloomberg Treasury constant maturity yields
    - Bloomberg SOFR OIS swap rates
"""

import sys
from pathlib import Path

sys.path.insert(0, "./src")

import pandas as pd
import numpy as np

import chartbook
import pull_bbg_treasury_sf

BASE_DIR = chartbook.env.get_project_root()
DATA_DIR = BASE_DIR / "_data"

# Mapping from Bloomberg tickers to tenor names
TREASURY_MAPPING = {
    "USGG2YR": "2Y",
    "USGG5YR": "5Y",
    "USGG10YR": "10Y",
    "USGG20YR": "20Y",
    "USGG30YR": "30Y",
}

SF_MAPPING = {
    "USOSFR2": "2Y",
    "USOSFR5": "5Y",
    "USOSFR10": "10Y",
    "USOSFR20": "20Y",
    "USOSFR30": "30Y",
}

# Output column names
OUTPUT_COLUMNS = {
    "2Y": "Treasury_SF_2Y",
    "5Y": "Treasury_SF_5Y",
    "10Y": "Treasury_SF_10Y",
    "20Y": "Treasury_SF_20Y",
    "30Y": "Treasury_SF_30Y",
}


def prepare_data(treasury_df, sf_df):
    """
    Prepare Treasury and SF data for basis calculations.

    Parameters
    ----------
    treasury_df : pd.DataFrame
        Treasury yields from Bloomberg
    sf_df : pd.DataFrame
        SF rates from Bloomberg

    Returns
    -------
    pd.DataFrame
        Merged DataFrame with standardized column names
    """
    # Set Date as index
    treasury_df = (
        treasury_df.set_index("index") if "index" in treasury_df.columns else treasury_df
    )
    sf_df = (
        sf_df.set_index("index") if "index" in sf_df.columns else sf_df
    )

    # Clean up column names - extract ticker from Bloomberg format
    def clean_columns(df, mapping, suffix):
        new_cols = {}
        for col in df.columns:
            if "_PX_LAST" in col:
                ticker = col.split()[0]
                if ticker in mapping:
                    new_cols[col] = f"{mapping[ticker]}_{suffix}"
        df = df.rename(columns=new_cols)
        return df

    treasury_df = clean_columns(treasury_df, TREASURY_MAPPING, "Treasury")
    sf_df = clean_columns(sf_df, SF_MAPPING, "SF")

    # Merge dataframes
    df_merged = treasury_df.merge(
        sf_df, left_index=True, right_index=True, how="inner"
    )

    return df_merged


def compute_treasury_sf_basis(df_merged):
    """
    Compute Treasury-SF basis in basis points.

    The basis is calculated as: (Treasury Yield - SF Rate) * 100
    to convert from percentage to basis points.

    Parameters
    ----------
    df_merged : pd.DataFrame
        DataFrame with Treasury yields and SF rates

    Returns
    -------
    pd.DataFrame
        DataFrame with basis spreads for each tenor
    """
    tenors = ["2Y", "5Y", "10Y", "20Y", "30Y"]

    for tenor in tenors:
        treas_col = f"{tenor}_Treasury"
        sf_col = f"{tenor}_SF"
        output_col = OUTPUT_COLUMNS[tenor]

        if treas_col in df_merged.columns and sf_col in df_merged.columns:
            # Basis = Treasury - SF, converted to basis points
            df_merged[output_col] = (df_merged[treas_col] - df_merged[sf_col]) * 100

    return df_merged


def calculate_treasury_sf_basis(end_date=None, data_dir=DATA_DIR):
    """
    Calculate Treasury-SF basis spreads.

    Parameters
    ----------
    end_date : str, optional
        End date for the data
    data_dir : Path
        Directory containing the data files

    Returns
    -------
    pd.DataFrame
        DataFrame with basis spreads in basis points
    """
    data_dir = Path(data_dir)

    print(">> Calculating Treasury-SF basis...")

    # Load data
    treasury_df = pull_bbg_treasury_sf.load_treasury_yields(data_dir=data_dir)
    sf_df = pull_bbg_treasury_sf.load_sf_rates(data_dir=data_dir)

    # Prepare data
    df_merged = prepare_data(treasury_df, sf_df)

    # Filter by end date if specified
    if end_date:
        date = pd.Timestamp(end_date).date()
        df_merged = df_merged.loc[:date]

    # Compute basis
    df_merged = compute_treasury_sf_basis(df_merged)

    # Extract just the basis columns
    basis_cols = [col for col in OUTPUT_COLUMNS.values() if col in df_merged.columns]
    basis_df = df_merged[basis_cols].copy()

    # Forward fill missing values
    basis_df = basis_df.ffill()

    print(f">> Records: {len(basis_df):,}")
    return basis_df


def load_treasury_sf_basis(data_dir=DATA_DIR):
    """Load calculated Treasury-SF basis from parquet file."""
    path = data_dir / "treasury_sf_basis.parquet"
    return pd.read_parquet(path)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    basis_df = calculate_treasury_sf_basis(data_dir=DATA_DIR)
    basis_df.to_parquet(DATA_DIR / "treasury_sf_basis.parquet")
    print(">> Saved treasury_sf_basis.parquet")


if __name__ == "__main__":
    main()
