# Treasury-Secured Financing Basis

Treasury-SF basis measuring the spread between Treasury yields and SOFR-based secured financing rates.

## Overview

This pipeline calculates Treasury-SF basis:

```
Basis = (Treasury Yield - SOFR OIS Rate) * 100
```

Results are in basis points.

## Interpretation

- **Basis > 0**: Treasuries yield more than SOFR-based financing
- **Basis < 0**: SOFR-based financing yields more than Treasuries

## Series

- Treasury_SF_2Y: 2-Year basis
- Treasury_SF_5Y: 5-Year basis
- Treasury_SF_10Y: 10-Year basis
- Treasury_SF_20Y: 20-Year basis
- Treasury_SF_30Y: 30-Year basis

## Data Sources

- **Bloomberg**: Treasury constant maturity yields (USGG series)
- **Bloomberg**: SOFR OIS swap rates (USOSFR series)

## Outputs

- `ftsfr_treasury_sf_basis.parquet`: Daily Treasury-SF basis for all tenors

## Requirements

- Bloomberg Terminal running
- Python 3.10+
- xbbg package

## Setup

1. Ensure Bloomberg Terminal is running
2. Install dependencies: `pip install -r requirements.txt`
3. Run pipeline: `doit`
