# Treasury Cash-Futures Basis

This pipeline constructs the **Treasury cash-futures (spot-futures) basis**:
the return earned by buying a deliverable Treasury bond, financing it in the
repo market, and delivering it into a short Treasury futures position — the
*implied repo rate* — measured relative to a maturity-matched OIS rate.

The basis is computed **two ways**, and both are published via
`chartbook.toml`:

1. **Delivery-adjusted method** (`ftsfr_treasury_sf_basis`) — implied repo
   computed from cheapest-to-deliver (CTD) bond prices with the delivery
   date chosen *optimally* within the delivery month, as the futures short
   would choose it. This corrects a bias in standard (Bloomberg-style)
   calculations. Implementation ported from the repo by **George Lord and
   Max Zhalilo** (see [Attribution](#attribution-and-credits)).
2. **Bloomberg method** (`ftsfr_treasury_sf_basis_bbg`) — Bloomberg's own
   implied repo field (`FUT_IMPLIED_REPO_RT`), which assumes a fixed
   delivery date. Retained for comparison; this was the original method
   used in the ftsfr monorepo.

> **Note:** an earlier version of this repository computed
> "Treasury yield minus SOFR OIS swap rate," which is a yield spread, not
> the cash-futures basis. That implementation has been removed.

## How the Treasury cash-futures basis trade works

### Futures contracts and delivery

CME Treasury futures (TU = 2Y note, FV = 5Y note, TY = 10Y note,
US = classic bond, WN = Ultra Bond) are physically settled: the **short**
chooses *which* bond to deliver from a basket of eligible Treasuries and
*when* to deliver within the delivery month. The long pays the **invoice
price**

$$
\text{Invoice} = F \cdot CF + A_e,
$$

where $F$ is the futures price, $CF$ the bond-specific **conversion factor**
(the price at which the bond would yield 6%, making different coupons
roughly comparable), and $A_e$ accrued interest at delivery. Because
conversion factors are imperfect, one bond — the **cheapest-to-deliver
(CTD)** — is most economical to deliver, and futures prices track the CTD.

### Gross basis, carry, and the implied repo rate

For a deliverable bond with clean price $P$, the **gross basis** is
$B = P - F \cdot CF$. Carrying the bond to delivery earns coupon income and
pays repo financing; gross basis net of this carry is the **net basis**.
The same economics expressed as a rate of return: the **implied repo rate
(IRR)** is the financing rate at which the cash-and-carry trade — buy the
CTD at the dirty price $P + A_b$, deliver it at the invoice price — breaks
even:

$$
\text{IRR}(T_d) =
\frac{F \cdot CF + A_e + I_c - (P + A_b)}{(P + A_b)\, d_1 - I_c\, d_2},
$$

with settlement-to-delivery period $d_1$ (Act/360), intervening coupon
$I_c$ reinvested over $d_2$, and accrued interest $A_b$/$A_e$ at
settlement/delivery. (Full variable definitions and conventions are in the
data dictionaries in `chartbook.toml`.)

### The arbitrage

If the IRR exceeds the actual term financing rate, an arbitrageur can buy
the CTD, finance it in repo, short the futures, and deliver — earning the
spread. The basis spread reported here benchmarks the IRR against OIS:

$$
\text{Basis} = \text{IRR} - \text{OIS} \quad \text{(bps)}.
$$

- **Basis > 0**: futures trade rich; the cash-and-carry (long bond / short
  futures) earns more than OIS. This is the classic hedge-fund "basis
  trade," historically driven by asset managers' demand for long futures
  exposure.
- **Basis < 0**: futures trade cheap; the reverse trade is favorable.

The financing benchmark varies by author — Fleckenstein and Longstaff use
maturity-matched term repo, Barth and Kahn use T-bills maturing at
delivery, and Siriwardane, Sunderam, and Wallen use maturity-matched OIS.
This pipeline follows the OIS convention. Like Siriwardane et al., it uses
the **first-deferred** contract (the second-nearest quarterly expiry) to
avoid delivery-month complications.

In a frictionless market the basis would be ~0. Persistent deviations
reflect intermediary balance-sheet costs (Fleckenstein and Longstaff find a
mean 5Y futures-cash funding basis of 58.7 bps vs term repo over
1991–2018), hedge-fund positioning and repo funding (Barth and Kahn 2021;
hedge fund short Treasury futures reached roughly $1 trillion in 2024–25),
and segmented funding markets (Siriwardane et al. report mean spot-futures
spreads of 11–18 bps vs OIS over 2010–Feb 2020). The basis blew out in
March 2020 when basis-trade unwinds collided with dealer balance-sheet
constraints; futures margins spiked and the Fed bought roughly $1 trillion
of Treasuries in three weeks.

### The delivery timing option — why Bloomberg's basis is biased

The futures short owns several embedded options: the **quality option**
(which bond to deliver), the **timing option** (when in the delivery month
to deliver), and end-of-month/wildcard options. The timing option matters
directly for the IRR:

- **Positive carry** (coupon income > financing cost): every extra day of
  holding earns money, so the short delivers **late** (last delivery day).
- **Negative carry** (financing cost > coupon income; typical when
  short-term rates exceed bond yields): holding costs money, so the short
  delivers **early** (first delivery day).

This is not exotic: it is the stated market convention. CME's own basis
education materials instruct that the prospective delivery date should be
taken as "the contract's first delivery day, if carry to delivery is
negative, or its last delivery day, if carry to delivery is positive," and
both Fleckenstein–Longstaff and the Fed's basis-trade monitoring
methodology (Glicoes, Iorio, Monin, and Petrasek 2024) implement exactly
this first-vs-last max-IRR rule.

Bloomberg's `FUT_IMPLIED_REPO_RT` instead assumes delivery at a **fixed**
date (the last delivery day). When carry is negative, the true optimal
delivery is early, and the fixed-date IRR *understates* the implied repo —
so the Bloomberg-method basis is biased downward exactly in high-rate /
inverted-curve environments. The error went largely unnoticed through
decades of upward-sloping curves, when positive carry made last-day
delivery optimal anyway (in Fleckenstein–Longstaff's 1991–2018 5Y sample,
last-day delivery was *always* optimal); in the negative-carry regime of
2022–2024 it became first-order. The delivery-adjusted method maximizes
the IRR over candidate delivery dates (first delivery day, last delivery
day, and the CTD's coupon/ex-coupon dates when they fall inside the
window):

$$
\text{IRR}^* = \max_{T_d \in \mathcal{D}} \text{IRR}(T_d).
$$

Because a maximum over dates is weakly greater than the value at any fixed
date, the delivery-adjusted basis sits weakly above the Bloomberg-method
basis; in this data the gap averages roughly 4–9 bps and widens in
negative-carry periods.

## Methods summary

| | Delivery-adjusted (corrected) | Bloomberg (old) |
|---|---|---|
| Implied repo | Computed from CTD prices (CRSP) and futures prices, maximized over delivery dates | Bloomberg `FUT_IMPLIED_REPO_RT` (fixed delivery date) |
| Contract | First-deferred generic (TU2, FV2, TY2, US2, WN2) | Same |
| Financing benchmark | OIS interpolated (linear in days) to the *optimal holding period* | OIS interpolated (piecewise linear) to contract month-end |
| Cleaning | Volume > 0; 5-day centered rolling median on IRR | Volume filter; ±45-day rolling MAD outlier removal; ffill ≤ 5 days |
| Output | `ftsfr_treasury_sf_basis.parquet` | `ftsfr_treasury_sf_basis_bbg.parquet` |

Tenor labels follow Siriwardane et al.: 2Y=TU, 5Y=FV, 10Y=TY, **20Y=US
(classic bond)**, **30Y=WN (Ultra Bond)**.

## Attribution and credits

The delivery-adjusted implied repo implementation is ported from the
replication project by **George Lord** ([georgelord0](https://github.com/georgelord0))
and **Max Zhalilo** ([maxz073](https://github.com/maxz073)):

- **Repository:** <https://github.com/maxz073/p10_Siriwardane_et_al_2026>
- Their project replicates the Treasury spot-futures arbitrage spread from
  the appendix of *Segmented Arbitrage* (Siriwardane, Sunderam, and
  Wallen). The paper's appendix takes the implied repo directly from
  Bloomberg; Lord and Zhalilo's contribution is to replace that field with
  an implied repo computed from first principles — the
  candidate-delivery-date maximization, the CRSP/WRDS bond-side pull with
  derived coupon schedules, and the accrued-interest/intervening-coupon
  handling — after observing that Bloomberg's implied repo does not account
  for the optimal delivery decision. The unit tests for the IRR math and
  the replication test design are also theirs.

Changes made in this port: the per-row loops were vectorized; the 20Y/30Y
contract mapping was aligned to the US/WN convention used in the paper and
in this repo's data files (their repo had the two labels swapped); the OIS
interpolation accepts whichever curve points are available (they used the
2M–9M grid); and the data layer was unified with the per-tenor Bloomberg
files used by the old method. As with their original repo, this
implementation is research code and its correctness is not guaranteed.

The Bloomberg-method code is ported from the `basis_treas_sf` pipeline in
the ftsfr monorepo.

## Data requirements

| Source | Used for | Access |
|--------|----------|--------|
| Bloomberg Terminal (xbbg) | Futures prices, CTD CUSIPs, conversion factors, volumes, Bloomberg implied repo, USD OIS curve | Terminal running locally |
| CRSP Daily Treasury via WRDS | CTD bond clean prices, accrued interest, coupon rates and maturities | `WRDS_USERNAME` in `.env` (password via `~/.pgpass`) |

Without a Bloomberg Terminal, the pipeline runs from cached parquet files in
`_data/` (futures/OIS data currently cached through 2025-05-30). The CRSP
pull only requires WRDS, not Bloomberg.

## Outputs

- `_data/ftsfr_treasury_sf_basis.parquet` — delivery-adjusted basis (long format: `unique_id`, `ds`, `y`)
- `_data/ftsfr_treasury_sf_basis_bbg.parquet` — Bloomberg-method basis (same format)
- `_data/implied_repo_delivery_adjusted.parquet`, `_data/holding_period_days.parquet`, `_data/ois_at_holding_period.parquet` — corrected-method intermediates
- `_output/treasury_sf_basis.html`, `_output/treasury_sf_basis_bbg.html`, `_output/treasury_sf_basis_comparison.html` — interactive charts
- `_output/summary_treasury_sf_basis_ipynb.html` — summary notebook

## Setup

1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env`; set `WRDS_USERNAME` (and optionally
   `BLOOMBERG_TERMINAL_OPEN=True` when a terminal is running)
3. Run the pipeline: `doit` (answer the Bloomberg prompt, or set
   `SKIP_BLOOMBERG=1` to use cached data)
4. Run tests: `pytest src/`

To run the replication tests against the Siriwardane et al. reference
series, place `treasury_sf_implied_rf.dta` in `data_manual/`; the tests
skip when the file is absent.

## Academic references

- **Siriwardane, Emil, Adi Sunderam, and Jonathan Wallen** — "Segmented
  Arbitrage" ([NBER WP 30561](https://www.nber.org/papers/w30561);
  published in the *Journal of Finance*, 2025). The Treasury spot-futures
  spread construction replicated here is from this paper's appendix:
  implied repo on the first-deferred contract minus maturity-matched OIS,
  for the 2Y/5Y/10Y/20Y/30Y contracts.
- **Fleckenstein, Matthias, and Francis A. Longstaff (2020)** — "Renting
  Balance Sheet Space: Intermediary Balance Sheet Rental Costs and the
  Valuation of Derivatives," *Review of Financial Studies* 33(11),
  5051–5091 ([article](https://academic.oup.com/rfs/article-abstract/33/11/5051/5807620);
  [NBER WP 24224](https://www.nber.org/papers/w24224)). Documents the
  futures-cash funding basis and links it to intermediary balance-sheet
  costs; implements the first-vs-last optimal delivery rule.
- **Barth, Daniel, and R. Jay Kahn (2021)** — "Hedge Funds and the Treasury
  Cash-Futures Disconnect,"
  [OFR Working Paper 21-01](https://www.financialresearch.gov/working-papers/files/OFRwp-21-01-hedge-funds-and-the-treasury-cash-futures-disconnect.pdf).
  Documents the rise of the hedge-fund basis trade and its repo funding.
- **Glicoes, Jonathan, Benjamin Iorio, Phillip Monin, and Lubomir Petrasek
  (2024)** — ["Quantifying Treasury Cash-Futures Basis
  Trades"](https://www.federalreserve.gov/econres/notes/feds-notes/quantifying-treasury-cash-futures-basis-trades-20240308.html),
  FEDS Notes. The Fed's option-adjusted basis methodology, including the
  optimal-delivery-date assumption.
- **Schrimpf, Andreas, Hyun Song Shin, and Vladyslav Sushko (2020)** —
  ["Leverage and margin spirals in fixed income markets during the Covid-19
  crisis"](https://www.bis.org/publ/bisbull02.pdf), BIS Bulletin No. 2.
  The March 2020 basis-trade unwind.
- **Burghardt, Galen, and Terry Belton** — *The Treasury Bond Basis*
  (McGraw-Hill). The standard reference for basis mechanics, carry, implied
  repo, and the short's delivery options. (Choudhry's
  [*The Futures Bond Basis*](http://www.yieldcurve.com/mktresearch/files/futuresbondbasis_part1.pdf)
  reproduces the key formulas, including the intervening-coupon IRR used
  here.)
- **CME Group** — [The Treasury futures delivery
  process](https://www.cmegroup.com/education/courses/introduction-to-treasuries/learn-about-the-treasuries-delivery-process)
  and [The Treasury Futures Delivery Process (PDF)](https://www.cmegroup.com/trading/interest-rates/files/us-treasury-futures-delivery-process.pdf).
  Note the exact delivery windows: deliveries can occur on any business day
  of the contract month, with the last delivery day being the last business
  day of the month for TY/US/WN but the *third business day of the
  following month* for TU/FV — this pipeline approximates the window by
  the first/last weekday of the contract month.
