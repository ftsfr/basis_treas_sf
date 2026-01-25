"""
Plot Treasury-SF Figures.

Utilities to create and save Treasury-Secured Financing basis plots using Plotly.
"""

from pathlib import Path
from datetime import date
from typing import Optional

import pandas as pd
import plotly.graph_objects as go

from settings import config

# Defaults for plotting windows
DEFAULT_START_DATE = pd.Timestamp("2018-01-01").date()
DEFAULT_END_DATE = None  # None means use full available range

DATA_DIR = config("DATA_DIR")
OUTPUT_DIR = config("OUTPUT_DIR")


def load_treasury_sf_data(file_path: Path) -> pd.DataFrame:
    """
    Load Treasury-SF basis data from parquet file.

    Parameters
    - file_path: Path to the parquet file

    Returns
    - DataFrame with basis spreads pivoted to wide format (date index, tenor columns)
    """
    df = pd.read_parquet(file_path)

    # Pivot from long format (unique_id, ds, y) to wide format
    df_wide = df.pivot(index="ds", columns="unique_id", values="y")
    df_wide.index = pd.to_datetime(df_wide.index)

    return df_wide


def plot_figure(
    basis_df: pd.DataFrame,
    save_path: str | Path,
    start_date: Optional[date | pd.Timestamp] = DEFAULT_START_DATE,
    end_date: Optional[date | pd.Timestamp] = DEFAULT_END_DATE,
) -> go.Figure:
    """
    Create and save the Treasury-SF basis plot using Plotly.

    Parameters
    - basis_df: DataFrame with basis spreads by tenor (columns like Treasury_SF_2Y)
    - save_path: File path for the saved plot (HTML)
    - start_date: Start date for the plot window
    - end_date: End date for the plot window

    Returns
    - Plotly Figure object
    """
    start_dt = pd.to_datetime(start_date).date() if start_date is not None else None
    end_dt = pd.to_datetime(end_date).date() if end_date is not None else None

    # Tenor columns in order
    tenors = ["Treasury_SF_2Y", "Treasury_SF_5Y", "Treasury_SF_10Y", "Treasury_SF_20Y", "Treasury_SF_30Y"]

    fig = go.Figure()

    for tenor in tenors:
        if tenor not in basis_df.columns:
            continue
        label = tenor.replace("Treasury_SF_", "")
        series = basis_df[tenor]
        if start_dt is not None and end_dt is not None:
            series = series.loc[start_dt:end_dt].dropna()
        elif start_dt is not None:
            series = series.loc[start_dt:].dropna()
        else:
            series = series.dropna()

        fig.add_trace(
            go.Scatter(
                x=series.index,
                y=series.values,
                mode="lines",
                name=label,
            )
        )

    fig.update_layout(
        title="Treasury-SF Basis",
        xaxis_title="Date",
        yaxis_title="Basis Spread (bps)",
    )

    fig.write_html(save_path)
    return fig


def plot_main(data_dir: Path = DATA_DIR) -> None:
    """
    Create and save the Treasury-SF basis plot.
    """
    data_dir = Path(data_dir)
    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    file = data_dir / "ftsfr_treasury_sf_basis.parquet"
    basis_df = load_treasury_sf_data(file)

    plot_figure(
        basis_df,
        out_dir / "treasury_sf_basis.html",
        start_date=DEFAULT_START_DATE,
        end_date=DEFAULT_END_DATE,
    )


if __name__ == "__main__":
    plot_main(data_dir=DATA_DIR)
