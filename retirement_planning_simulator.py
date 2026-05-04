"""
Retirement Monte Carlo Simulator
=================================
Simulates 2,000 randomized retirement scenarios to project portfolio survival,
tax burden, and optimal Roth conversion strategy across ages 60–95.

HOW TO USE THIS SCRIPT
-----------------------
1. Edit the configuration constants in the sections below (portfolio balances,
   return assumptions, spending, income, healthcare).
2. Run:  python retirement_sim.py
3. Five chart files and one Excel workbook are written to the same folder.

TWO SCENARIOS ARE COMPARED IN EVERY RUN
-----------------------------------------
  Scenario A — Subsidized ACA (USE_ACA_SUBSIDY = True):
      Before Medicare at 65, health insurance cost = min(8.5% × MAGI, benchmark).
      The income-linked premium creates an 8.5% marginal surcharge on every dollar
      of Roth conversion, limiting conversions to ~$40k/yr at ages 60–64.

  Scenario B — Full-price ACA (USE_ACA_SUBSIDY = False):
      You pay the full benchmark premium ($18k/yr) regardless of income.
      No income-linked surcharge, so the optimizer can convert much more in the
      low-income window before Social Security and RMDs begin (ages 60–75).

KEY DESIGN PRINCIPLES
-----------------------
1. REAL returns, REAL expenses — no nominal/real mismatch.
   MEAN_RETURN = 7% is already inflation-adjusted (standard equity long-run).
   Expenses use only the spending-smile adjustment; no CPI inflation is layered on.
   All dollar figures in every chart are in today's (2025) purchasing power.

2. Tax brackets and Social Security benefits are indexed at INFLATION each year.
   This correctly models tax bracket creep and SS COLA in real terms even though
   the rest of the simulation is in real dollars.

3. Ordinary income and long-term capital gains (LTCG) are kept strictly separate
   in every tax calculation.  Roth conversions are ordinary income; gains from
   selling the taxable brokerage account are LTCG and stack on top at preferential
   0%/15%/20% rates.  Mixing them would overstate the marginal tax cost of converting.

4. The Roth optimizer uses a two-pass coarse/fine search for speed, and bases its
   decision only on income already recognized at conversion time — it does NOT
   pre-load expected IRA withdrawals, which would wrongly suppress conversions.

5. Withdrawal waterfall for living expenses:  cash → taxable → IRA → Roth.
   Tax and healthcare bills follow the same waterfall if cash is insufficient.

6. The spending smile (Blanchett 2013) models declining real discretionary spending
   after early retirement: spending peaks ~65, declines through slow-go and no-go
   years.  Healthcare is modeled separately via ACA/Medicare.

OUTPUT FILES
------------
  chart1_montecarlo.png           — Monte Carlo fan chart (all 2,000 scenarios)
  chart2_median_subsidized_aca.png — Detailed median-path breakdown, Scenario A
  chart2_median_no_aca_subsidy.png — Detailed median-path breakdown, Scenario B
  chart3_percentile_paths.png     — P10/P25/P50/P75/P90 scenario trajectories
  chart4_comparison.png           — Side-by-side comparison of both scenarios
  retirement_results.xlsx         — Full simulation data + parameters
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
from matplotlib.ticker import FuncFormatter
from matplotlib.gridspec import GridSpec


# =============================================================================
# SECTION 1 — SIMULATION CONTROLS
# =============================================================================
# These control how many random scenarios are generated and the age range.
# Increasing SIMS improves statistical precision but takes longer to run.
# SEED ensures reproducible results; change it to get a different random draw.

START_AGE = 60      # age at start of retirement simulation
END_AGE   = 95      # age at end of simulation
SIMS      = 2_000   # number of independent random scenarios
SEED      = 54      # random seed for reproducibility


# =============================================================================
# SECTION 2 — INITIAL PORTFOLIO BALANCES
# =============================================================================
# All values in TODAY'S dollars (real, 2025 purchasing power).
# The Roth account starts at $0 — it is built entirely through conversions
# during the simulation, which is the realistic starting point if the IRA
# has never been converted before.

CASH_START    =   300_000   # money market / savings — earns no return in model
TAXABLE_START = 1_000_000   # brokerage account — invested, generates dividends + gains
IRA_START     = 1_000_000   # traditional IRA / 401(k) — pre-tax, subject to RMDs at 73
ROTH_START    = 1_000_000   # Roth IRA — already after-tax, grows and withdraws tax-free


# =============================================================================
# SECTION 3 — INVESTMENT RETURN ASSUMPTIONS
# =============================================================================
# MEAN_RETURN is the expected REAL (inflation-adjusted) total return per year.
# 7% is a standard long-run equity assumption (e.g., Vanguard, Bogle research).
# Returns follow a lognormal distribution, parameterized to match the
# specified MEAN_RETURN and VOL_RETURN exactly. CRASH_FLOOR is retained
# as a practical safety floor (lognormal already prevents < -100%).
#
# The taxable brokerage account grows at PRICE_RETURN only, because dividends
# are extracted each year as taxable income (they don't stay in the account).
# IRA and Roth grow at the full MEAN_RETURN because dividends reinvest tax-free.

MEAN_RETURN = 0.07    # real total return on IRA and Roth (7% = price + dividends)
VOL_RETURN  = 0.15    # standard deviation of annual returns — controls scenario spread
CRASH_FLOOR = -0.40   # practical floor for single-year loss

DIV_YIELD    = 0.03   # annual dividend yield on the taxable brokerage account
PRICE_RETURN = MEAN_RETURN - DIV_YIELD   # = 0.04 — used to compute lognormal mu for price return

QUAL_DIV_PCT   = 0.80   # 80% of dividends are "qualified" — taxed at LTCG rates
COST_BASIS_PCT = 0.70   # 70% of the taxable account's value is cost basis (not gain)
                        # The remaining 30% is unrealized gain, taxed as LTCG when sold


# =============================================================================
# SECTION 4 — SPENDING ASSUMPTIONS
# =============================================================================
# BASE_EXPENSES is your annual lifestyle cost in today's dollars.
# It covers everything EXCEPT healthcare premiums, which are modeled separately.
#
# The spending smile adjusts this figure each year based on empirical research
# showing that real discretionary spending declines after early retirement:
#
#   Ages 60–65: +0.5%/yr real — "go-go" years, active travel and hobbies
#   Ages 65–75: −0.5%/yr real — go-go years tapering off
#   Ages 75–85: −1.0%/yr real — "slow-go" years, reduced activity
#   Ages 85–96: −0.5%/yr real — "no-go" years, stable but lower spending
#
# Set all rates to 0.0 to model flat real spending (no smile effect).
# The smile only adjusts the lifestyle component — healthcare is separately modeled.

BASE_EXPENSES = 250_000   # annual lifestyle spending in today's 2025 dollars

SMILE_REAL_CHANGE = {
    (60, 65): +0.005,   # +0.5%/yr real — peak-activity early retirement
    (65, 75): -0.005,   # −0.5%/yr real — go-go years tapering
    (75, 85): -0.010,   # −1.0%/yr real — slow-go years
    (85, 96): -0.005,   # −0.5%/yr real — no-go years
}


# =============================================================================
# SECTION 5 — INFLATION
# =============================================================================
# INFLATION is used ONLY for two purposes:
#   (a) indexing federal and Virginia tax brackets upward each year — this
#       correctly models "bracket creep" where brackets erode in real terms
#
# It is NOT applied to living expenses (see Section 4 above) because the
# portfolio return (MEAN_RETURN) is already a real (inflation-adjusted) figure.
# Applying inflation to expenses on top of a real return would create an
# inconsistency where real lifestyle costs grow every year — not realistic.

INFLATION = 0.035   # 3.5% annual inflation, used for bracket/SS indexing only


# =============================================================================
# SECTION 6 — SOCIAL SECURITY INCOME
# =============================================================================
# SS benefits are expressed in today's dollars and inflated by COLA (INFLATION)
# each year so they maintain their real purchasing power, which matches how
# actual Social Security cost-of-living adjustments work.
#
# Delaying SS to age 70 maximizes the monthly benefit.  To model earlier
# claiming, change SS_START_AGE and adjust SS_AMOUNT accordingly.

SS_START_AGE = 70         # age at which Social Security benefits begin
SS_AMOUNT    = 100_000    # annual SS benefit in today's dollars (couple)


# =============================================================================
# SECTION 7 — ROTH CONVERSION STRATEGY
# =============================================================================
# Strategic Roth conversions happen each year from age START_AGE through
# ROTH_END_AGE (the year before RMDs begin).  After age 75, RMDs from the IRA
# are mandatory and large enough that additional conversions are rarely optimal.
#
# The optimizer finds the largest conversion whose marginal all-in cost (federal
# tax + Virginia tax + healthcare surcharge) stays below MARGINAL_STOP.
#
# WHY 35%?
#   At ages 60–64 with ACA:  12% fed + 15% LTCG push + 8.5% ACA = 35.5%
#     — 35% allows conversion through the entire 12% federal bracket
#   At ages 65–75 (Medicare, no ACA):  22% fed + 5.75% VA = 27.75%
#     — 35% comfortably covers the full 22% bracket, which is the primary
#       window for tax-efficient conversion before RMDs start
#   Future RMDs at 76+ will be taxed at 22–24%+, so converting now at
#   under 35% locks in savings on a growing IRA balance.

# SECURE 2.0: RMD age = 75 for those born 1960 or later; change to 73 if born 1951-1959.
RMD_START_AGE = 75
ROTH_END_AGE  = RMD_START_AGE - 1  # convert through the year before RMDs begin
MARGINAL_STOP = 0.35  # stop converting when the next $1k costs more than 35% all-in


# =============================================================================
# SECTION 8 — HEALTHCARE ASSUMPTIONS
# =============================================================================
# Three distinct healthcare phases are modeled:
#
#   Ages 60–64  (pre-Medicare):
#     ACA marketplace insurance.  Under USE_ACA_SUBSIDY=True, the net premium
#     is income-linked: min(8.5% × MAGI, BENCHMARK_PREMIUM).  This creates an
#     effective 8.5% marginal surcharge on every dollar of Roth conversion —
#     the key constraint limiting conversions before Medicare.
#     Under USE_ACA_SUBSIDY=False, you pay the full BENCHMARK_PREMIUM regardless
#     of income, removing the surcharge and enabling much larger conversions.
#
#   Ages 65+  (Medicare):
#     MEDICARE_BASE covers standard Part B + Part D premiums for a couple.
#     IRMAA surcharges apply to higher incomes (see irmaa_surcharge() below).
#
# USE_ACA_SUBSIDY is the key scenario toggle:
#   True  → Scenario A: subsidized ACA, limited Roth conversion pre-65
#   False → Scenario B: full-price ACA, maximum Roth conversion pre-65

MEDICARE_AGE      = 65
ACA_FPL_2         = 20_440    # 2025 federal poverty level for a 2-person household
BENCHMARK_PREMIUM = 18_000    # full-cost ACA benchmark silver plan (couple/year)
MEDICARE_BASE     = 6_000     # approximate base Medicare Part B+D (couple/year)

# Net Investment Income Tax (IRC §1411): 3.8% federal surtax on investment
# income for MFJ filers with MAGI > $250,000.  Threshold is NOT inflation-
# adjusted (erodes in real value each year, capturing more income over time).
# Applies to: LTCG, qualified dividends, ordinary dividends.
# Does NOT apply to: IRA withdrawals, RMDs, Roth conversions, SS benefits.
NIIT_RATE          = 0.038
NIIT_THRESHOLD_MFJ = 250_000   # nominal dollars, not inflation-adjusted

USE_ACA_SUBSIDY   = True      # True = subsidized ACA;  False = full-price ACA
                              # This global is overridden in main() for each scenario


# =============================================================================
# SECTION 9 — TAX TABLES (2025 BASE YEAR)
# =============================================================================
# Federal brackets are for Married Filing Jointly (MFJ).
# All thresholds are in 2025 dollars; they are indexed by INFLATION each year
# in the simulation (see inflate_brackets() below).
#
# LTCG brackets apply to long-term capital gains and qualified dividends.
# Unlike ordinary brackets, LTCG rates stack ON TOP of ordinary income —
# the 0% zone is available only up to the total income threshold, not the
# ordinary income threshold.  This creates the "LTCG bracket push" effect:
# every extra dollar of Roth conversion (ordinary income) fills the ordinary
# bracket from the bottom, pushing LTCG out of the 0% zone into 15%.
#
# RMD_TABLE maps age → IRS Uniform Lifetime Table life expectancy factor.
# Annual RMD = IRA balance / factor.  The table starts at age 73 (SECURE 2.0).

BASE_BRACKETS_2025 = [             # (taxable income threshold, marginal rate)
    (0,        0.10),
    (23_200,   0.12),
    (94_300,   0.22),
    (201_050,  0.24),
    (383_900,  0.32),
    (487_450,  0.35),
    (731_200,  0.37),
]
STD_DED_2025 = 30_000              # MFJ (IRS Rev. Proc. 2024-40)            

LTCG_BRACKETS_2025 = [             # (total income threshold, LTCG rate)
    (0,        0.00),
    (96_700,   0.15),              # IRS Rev. Proc. 2024-40
    (600_050,  0.20),
]

RMD_TABLE = {                      # IRS Uniform Lifetime Table (SECURE 2.0)
    75:24.6, 76:23.7, 77:22.9, 78:22.0,
    79:21.1, 80:20.2, 81:19.4, 82:18.5, 83:17.7, 84:16.8,
    85:16.0, 86:15.2, 87:14.4, 88:13.7, 89:12.9, 90:12.2,
    91:11.5, 92:10.8, 93:10.1, 94:9.5,  95:8.9,
}

# Virginia state income tax — Married Filing Jointly.
# VA brackets are NOT inflation-indexed (fixed thresholds every year).
# Social Security is fully exempt from Virginia income tax.
# LTCG is taxed as ordinary income in Virginia (no preferential rate).
VA_STD_DED_MFJ = 17_500
VA_BRACKETS = [
    (0,       0.0200),
    (3_000,   0.0300),
    (5_000,   0.0500),
    (17_000,  0.0575),   # top rate: 5.75%
]


# =============================================================================
# SECTION 10 — CHART COLORS AND OUTPUT FILE
# =============================================================================
C_BLUE   = "#1F497D"   # primary data color (portfolio, median path)
C_GREEN  = "#2E7D32"   # Social Security, Roth balance
C_RED    = "#C0504D"   # federal tax, P10 scenario, alert
C_ORANGE = "#E36C09"   # IRA balance/withdrawals, Virginia tax
C_PURPLE = "#8064A2"   # Roth conversion, healthcare
C_TEAL   = "#006464"   # taxable account, cash
C_CYAN   = "#17BECF"   # Roth withdrawals (tax-free)
C_GRAY   = "#595959"   # milestone annotations
GRID_CLR = "#CCCCCC"   # chart gridlines
OUTPUT_FILE = "retirement_results.xlsx"


# =============================================================================
# SECTION 11 — HELPER FUNCTIONS
# =============================================================================

def smile_expenses(age, base_expenses=None):
    """
    Return real lifestyle spending for the given age, adjusted by the
    retirement spending smile curve (SMILE_REAL_CHANGE).

    No CPI inflation is applied — the result is in today's purchasing power.
    The smile only adjusts the non-healthcare lifestyle component.

    Example: at age 80 the factor is roughly 0.927, so spending = $231,750
    rather than the base $250,000 — about 7% lower in real terms.
    """
    real_factor = 1.0
    for yr in range(START_AGE, age):
        for (s, e), rate in SMILE_REAL_CHANGE.items():
            if s <= yr < e:
                real_factor *= (1 + rate)
                break
    
    base = BASE_EXPENSES if base_expenses is None else base_expenses
    return base * real_factor


def inflate(x, years):
    """
    Grow x at the INFLATION rate for the given number of years.
    Used for Social Security COLA and tax bracket indexing only —
    NOT for living expenses.
    """
    return x * (1 + INFLATION) ** years


def inflate_brackets(brackets, std, years):
    """
    Return inflation-adjusted (brackets, standard_deduction) for a given
    simulation year.  Federal brackets are indexed to INFLATION; Virginia
    brackets are static and do not use this function.
    """
    f = (1 + INFLATION) ** years
    return [(int(t * f), r) for t, r in brackets], int(std * f)


def calc_ordinary_tax(gross_income, brackets, std_ded):
    """
    Federal ordinary income tax on gross income (before standard deduction).
    Applies the MFJ bracket schedule after subtracting the standard deduction.

    This function handles ONLY ordinary income (wages, IRA withdrawals, Roth
    conversions, RMDs, ordinary dividends).  Capital gains are handled
    separately by calc_ltcg_tax().
    """
    taxable = max(0.0, gross_income - std_ded)
    tax = 0.0
    for i, (t, r) in enumerate(brackets):
        nxt = brackets[i + 1][0] if i + 1 < len(brackets) else float("inf")
        if taxable > t:
            tax += (min(taxable, nxt) - t) * r
    return tax


def calc_ltcg_tax(ltcg, ordinary_gross, std_ded, brackets):
    """
    Federal tax on long-term capital gains and qualified dividends.

    LTCG stacks ON TOP of net ordinary income in the LTCG rate schedule.
    That means the 0% LTCG zone is available only to the extent that
    (ordinary_net + LTCG) stays below the first LTCG threshold.

    The LTCG bracket-push effect: as ordinary income rises (e.g., from a
    Roth conversion), it consumes more of the 0% LTCG zone, pushing LTCG
    into the 15% zone.  This is a real incremental cost of converting and
    is correctly accounted for in the Roth optimizer.

    Parameters:
        ltcg            — total capital gains + qualified dividends this year
        ordinary_gross  — gross ordinary income (before standard deduction)
        std_ded         — inflation-adjusted standard deduction
        brackets        — inflation-adjusted LTCG bracket schedule
    """
    ordinary_net = max(0.0, ordinary_gross - std_ded)
    remaining = ltcg
    tax = 0.0
    for i, (t, r) in enumerate(brackets):
        nxt   = brackets[i + 1][0] if i + 1 < len(brackets) else float("inf")
        start = max(t, ordinary_net)      # LTCG starts above ordinary_net
        room  = max(0.0, nxt - start)     # room available in this LTCG bracket
        used  = min(room, remaining)      # LTCG that falls in this bracket
        tax  += used * r
        remaining -= used
        if remaining <= 0:
            break
    return tax


def calc_va_tax(income):
    """
    Virginia state income tax (MFJ).

    Notes:
      - Social Security is fully exempt; exclude SS before calling this.
      - LTCG is taxed as ordinary income (no preferential state rate).
        Pass (ordinary + LTCG) as a single combined income figure.
      - VA brackets are NOT inflation-indexed (thresholds are fixed each year).
    """
    taxable = max(0.0, income - VA_STD_DED_MFJ)
    tax = 0.0
    for i, (t, r) in enumerate(VA_BRACKETS):
        nxt = VA_BRACKETS[i + 1][0] if i + 1 < len(VA_BRACKETS) else float("inf")
        if taxable > t:
            tax += (min(taxable, nxt) - t) * r
    return tax


def calc_ss_taxable(ss, other_income):
    """
    Determine the taxable portion of Social Security benefits using the
    IRS provisional income test (MFJ thresholds). 
    IRS provisional-income thresholds are NOT inflation-indexed

    Provisional income = other_income + 50% of SS benefits.
      Below $32,000:  0% of SS is taxable
      $32k – $44k:    up to 50% of SS is taxable
      Above $44,000:  up to 85% of SS is taxable (maximum taxable fraction)

    other_income should include ALL non-SS income: RMDs, IRA withdrawals,
    Roth conversions, ordinary dividends, and capital gains.  Including all
    sources is critical — omitting IRA withdrawals would understate SS taxation.
    """
    if ss <= 0:
        return 0.0
    provisional = other_income + 0.5 * ss
    if provisional <= 32_000:
        return 0.0
    elif provisional <= 44_000:
        return min(0.5 * (provisional - 32_000), 0.5 * ss)
    return min(0.85 * ss, 0.85 * (provisional - 44_000) + 6_000)


def aca_net_premium(magi):
    """
    ACA net health insurance premium using the ARP/IRA smooth-cap formula.

    Net premium = min(8.5% × MAGI, BENCHMARK_PREMIUM)

    This is the income-linked premium under the Affordable Care Act when
    you are eligible for subsidies.  The 8.5% rate is the maximum share of
    income you pay; above a high enough income the premium equals the full
    benchmark cost.  There is no sudden cliff (the old 400% FPL cliff was
    eliminated by the American Rescue Plan and extended by the IRA).

    The 8.5% multiplier acts as a marginal surcharge on Roth conversions:
    each additional dollar of conversion raises MAGI by $1 and the premium
    by $0.085 — on top of the income tax rate.  This is why converting while
    receiving ACA subsidies is more expensive than converting after Medicare.

    Model assumes flat 8.5% ACA contribution; this overestimates premiums 
    at low income levels and slightly understates optimal Roth conversions early.
    """
    if magi <= ACA_FPL_2:
        return 0.0
    return min(0.085 * magi, BENCHMARK_PREMIUM)


def irmaa_surcharge(magi):
    """
    Medicare IRMAA (Income-Related Monthly Adjustment Amount) surcharges.

    Returns the annual surcharge for Part B + Part D combined, for a couple.
    These are assessed on income from two years prior (IRMAA lookback).

    Thresholds are for MFJ (2025 values, not inflation-adjusted in model):
      ≤ $212k : no surcharge
      $212k–$266k : +$2,000/yr (couple)
      $266k–$334k : +$4,000/yr
      $334k–$400k : +$6,400/yr
      $400k–$750k : +$11,200/yr
      > $750k     : +$11,200/yr (capped)
    """
    for threshold, surcharge in [
        (212_000,  0),
        (266_000,  2_200),
        (334_000,  4_800),
        (400_000,  7_500),
        (750_000, 10_100),
    ]:
        if magi <= threshold:
            return surcharge
    return 12_800


def calc_niit(ltcg, dividends, magi):
    """
    Net Investment Income Tax (IRC §1411): 3.8% federal surtax on NII
    when MAGI exceeds the MFJ threshold of $250,000.
    Applies to the LESSER of NII or (MAGI - threshold).
    NII = LTCG (gains + qualified dividends) + ordinary dividends.
    IRA/RMD/Roth conversions and Social Security are excluded from NII.
    The threshold is not inflation-adjusted — its real value erodes
    over time, gradually exposing more income to NIIT.
    """
    nii = ltcg + dividends
    if magi <= NIIT_THRESHOLD_MFJ:
        return 0.0
    return NIIT_RATE * min(nii, magi - NIIT_THRESHOLD_MFJ)


# =============================================================================
# SECTION 12 — ROTH CONVERSION OPTIMIZER
# =============================================================================

def optimal_roth_conversion(rmd_ord_div, ord_div, ss, ltcg_fixed, ira_balance,
                             age, brackets, std_ded, ltcg_brackets,
                             use_aca_subsidy=None, irmaa_lookback_magi=0.0):
    """
    Find the largest Roth conversion amount whose marginal all-in cost
    (federal + Virginia + healthcare) stays below MARGINAL_STOP.

    HOW THE OPTIMIZER WORKS
    ───────────────────────
    It steps through conversion amounts from $0 upward, computing the
    incremental cost of each additional $1,000.  It stops when the marginal
    cost of the next $1,000 exceeds MARGINAL_STOP.

    WHY ORDINARY AND LTCG ARE PASSED SEPARATELY
    ─────────────────────────────────────────────
    A Roth conversion is ordinary income — it fills tax brackets from the
    bottom.  LTCG (from selling the taxable account + qualified dividends)
    is fixed for the year and stacks on top at preferential 0%/15%/20% rates.
    Mixing them into one number would tax LTCG at ordinary rates, massively
    overstating the marginal cost and suppressing conversions to near-zero.

    The optimizer also captures the LTCG bracket-push effect: as ordinary
    income rises above the standard deduction, it consumes the 0% LTCG zone,
    pushing existing capital gains from 0% into 15%.  This is a real and
    correctly modeled incremental cost.

    WHY SS IS RE-COMPUTED AT EACH CONVERSION LEVEL
    ────────────────────────────────────────────────
    The taxable portion of Social Security is NOT fixed — it rises with
    income via the IRS provisional income test.  In the phase-in zone
    ($32k–$44k provisional), each $1 of conversion adds $0.50 of taxable SS;
    above $44k provisional, each $1 adds $0.85.  Freezing SS taxable at the
    conv=0 level understates the true marginal cost of converting and causes
    the optimizer to allow too many conversions at ages when SS is in the
    phase-in zone.  Passing ss separately and calling calc_ss_taxable() inside
    total_cost() ensures the correct dynamic SS tax is included at each step.

    WHY IRA WITHDRAWALS ARE NOT INCLUDED IN rmd_ord_div
    ───────────────────────────────────────────────────────
    IRA withdrawals for living expenses happen AFTER the conversion decision.
    Including them in base income would pre-fill brackets and suppress
    conversions during exactly the years when the IRA-to-Roth window is
    most valuable (ages 60–75, before SS and RMDs begin).

    TWO-PASS SEARCH FOR SPEED
    ──────────────────────────
    The IRA can grow to $8–10M before RMDs begin.  A single $1,000-step loop
    would need 8,000–10,000 iterations per call, making 2,000 simulations × 36
    years too slow.  The two-pass approach uses:
      Pass 1: $5,000 steps — ~200 iterations maximum to find approximate boundary
      Pass 2: $1,000 steps — ~10 iterations in the ±$5k neighborhood for precision

    Parameters:
        rmd_ord_div     — RMDs + ordinary dividends (non-SS, non-conversion income)
        ord_div         - ordinary dividends for NIIT calculation
        ss              — full Social Security benefit this year (0 if not yet started)
        ltcg_fixed      — capital gains + qualified dividends (fixed for this year)
        ira_balance     — current IRA balance (conversion cannot exceed this)
        age             — current age (determines healthcare formula)
        brackets        — inflation-adjusted federal ordinary income brackets
        std_ded         — inflation-adjusted standard deduction
        ltcg_brackets   — inflation-adjusted LTCG brackets
        use_aca_subsidy      — override the global USE_ACA_SUBSIDY if provided
        irmaa_lookback_magi  — MAGI from 2 years prior for IRMAA computation
                               (0.0 for pre-Medicare ages, ignored by ACA formula)
    """
    # No Roth conversion after RMD age
    if age >= RMD_START_AGE:
        return 0.0            
      
    aca_subsidy = USE_ACA_SUBSIDY if use_aca_subsidy is None else use_aca_subsidy

    def total_cost(conv):
        """All-in tax + healthcare cost at a given conversion amount.

        SS taxable is re-computed at each conversion level because the
        provisional income test is income-dependent: more conversion →
        higher provisional income → more SS becomes taxable.
        This correctly captures the marginal SS cost in the phase-in zone.
        """
        # Re-compute SS taxable at this conversion level
        other_for_ss = rmd_ord_div + conv + ltcg_fixed
        ss_tax   = calc_ss_taxable(ss, other_for_ss)
        ordinary = rmd_ord_div + conv + ss_tax
        fed  = calc_ordinary_tax(ordinary, brackets, std_ded)
        fed += calc_ltcg_tax(ltcg_fixed, ordinary, std_ded, ltcg_brackets)
        # Include Virginia tax so the stop threshold reflects the combined
        # federal + state marginal rate (22% fed + 5.75% VA = 27.75%)
        # All SS benefits are exempted from VA taxes
        va   = calc_va_tax(ordinary + ltcg_fixed - ss_tax)
        magi = ordinary + ltcg_fixed
        # NIIT: Roth conversion is not NII, but pushes MAGI over $250k,
        # exposing existing NII (ltcg_fixed) to 3.8%.
        # niit = calc_niit(ltcg_fixed, 0.0, magi)
        # Pass ord_div alongside ltcg_fixed
        niit = calc_niit(ltcg_fixed, ord_div, magi)

        if age >= MEDICARE_AGE:
            # Use the 2-year lookback MAGI for IRMAA (SSA rule),
            # passed in from the simulation loop.
            health = MEDICARE_BASE + irmaa_surcharge(irmaa_lookback_magi)
        elif aca_subsidy:
            health = aca_net_premium(magi)     # income-linked: 0–8.5% of MAGI
        else:
            health = BENCHMARK_PREMIUM         # flat full-price: no marginal surcharge
        return fed + niit + va + health

    # ── Pass 1: coarse $5,000 steps ─────────────────────────────────────────
    coarse = 5_000
    best   = 0
    prev   = total_cost(0)
    for conv in range(coarse, int(ira_balance) + coarse, coarse):
        c = total_cost(conv)
        if (c - prev) / coarse > MARGINAL_STOP:
            break                    # marginal rate exceeded — stop here
        prev = c
        best = conv                  # this level is still acceptable

    # ── Pass 2: fine $1,000 steps around the coarse boundary ─────────────────
    fine_lo = max(0, best - coarse)
    best    = fine_lo
    prev    = total_cost(fine_lo)
    fine_hi = min(fine_lo + 2 * coarse + 1_000, int(ira_balance) + 1_000)
    for conv in range(fine_lo + 1_000, fine_hi, 1_000):
        c = total_cost(conv)
        if (c - prev) / 1_000 > MARGINAL_STOP:
            break
        prev = c
        best = conv

    return best


# =============================================================================
# SECTION 13 — MONTE CARLO SIMULATION ENGINE
# =============================================================================

def run_simulation(scenario_label="Baseline"):
    """
    Run SIMS independent retirement scenarios and return a DataFrame with
    one row per (simulation, age) pair — SIMS × (END_AGE − START_AGE + 1) rows.

    WITHIN EACH YEAR, the sequence of events is:
      1. Compute inflation-indexed values (expenses, SS, tax brackets)
      2. Taxable account pays dividends (automatically recognized income)
      3. Compute RMD if age ≥ RMD_START_AGE (= 75 for born 1960+; 73 for 1951-1959))
      4. Decide Roth conversion (optimizer, ages 60–75 only)
      5. Fund lifestyle expenses from waterfall: cash → taxable → IRA → Roth
      6. Compute all taxes (federal ordinary, federal LTCG, Virginia, SS provisional)
      7. Compute healthcare cost (ACA or Medicare + IRMAA)
      8. Pay taxes+health from waterfall: cash → taxable → IRA → Roth
      9. Apply investment returns to taxable (price-only), IRA, and Roth
     10. Record all values for this year

    NOTE: The global USE_ACA_SUBSIDY controls which healthcare formula is used
    in both the optimizer (step 4) and the actual healthcare charge (step 7).
    Change it before calling run_simulation() to switch scenarios.
    """
    np.random.seed(SEED)
    years   = END_AGE - START_AGE + 1

    # ── Generate return matrix: lognormal model ─────────────────────────────
    # Lognormal is the correct model for investment returns:
    #   - Always > -100%: no impossible outcomes (no artificial floor needed,
    #     though CRASH_FLOOR is retained as a practical safety clip)
    #   - Log-returns are normal and self-consistent across time horizons
    #   - Right-skewed: matches empirical equity return distributions
    #
    # Parameterization: MEAN_RETURN and VOL_RETURN are the arithmetic mean
    # and std dev of simple annual returns. Converted to lognormal mu/sigma:
    #   sigma² = log(1 + VOL² / (1 + MEAN)²)
    #   mu     = log(1 + MEAN) - 0.5 * sigma²
    # This ensures the lognormal distribution has exactly the specified
    # arithmetic mean and standard deviation.
    #
    # r_price decomposition: (1 + r_total) = (1 + r_price) * (1 + DIV_YIELD)
    # Rearranging: r_price = (1 + r_total) / (1 + DIV_YIELD) - 1
    # This correctly separates price return from dividend yield at every
    # return level (unlike linear scaling which breaks at extreme returns).

    sigma2      = np.log(1 + (VOL_RETURN**2) / (1 + MEAN_RETURN)**2)
    sigma       = np.sqrt(sigma2)
    mu_log      = np.log(1 + MEAN_RETURN) - 0.5 * sigma2
    log_returns = np.random.normal(mu_log, sigma, (SIMS, years))
    r_total     = np.clip(np.exp(log_returns) - 1, CRASH_FLOOR, None)
    r_price     = (1 + r_total) / (1 + DIV_YIELD) - 1

    rows = []

    for sim in range(SIMS):
        # Each simulation starts with the same initial balances
        cash, taxable, ira, roth = CASH_START, TAXABLE_START, IRA_START, ROTH_START
        # Running cost basis of the taxable account. Initialized from COST_BASIS_PCT.
        # Reduced proportionally whenever shares are sold; unchanged by price gains.
        taxable_basis = TAXABLE_START * COST_BASIS_PCT
        # IRMAA is assessed on MAGI from 2 years prior (SSA lookback rule).
        magi_history  = [0.0] * years   # index i = MAGI at simulation year i

        for i, age in enumerate(range(START_AGE, END_AGE + 1)):

            # ── Step 1: Inflation-indexed values for this year ────────────────
            # Expenses use the real spending smile (no inflation).
            # SS inflates for COLA. Tax brackets inflate for bracket indexing.
            #expenses  = smile_expenses(age)
            expenses  = smile_expenses(age, BASE_EXPENSES)
            ss = SS_AMOUNT if age >= SS_START_AGE else 0.0
            brackets, std = inflate_brackets(BASE_BRACKETS_2025, STD_DED_2025, i)
            ltcg_bkts, _ = inflate_brackets(LTCG_BRACKETS_2025, 0, i)

            # ── Step 2: Dividend income from taxable account ──────────────────
            # Dividends are generated automatically by the portfolio each year.
            # They are split into ordinary (taxed at bracket rates) and
            # qualified (taxed at preferential LTCG rates).
            # Dividends are deposited to the cash account — this is how a
            # brokerage account works: distributions land in the settlement
            # account each quarter whether or not you reinvest them.
            # The taxable account grows at PRICE_RETURN (= MEAN_RETURN - DIV_YIELD)
            # which already excludes the dividend component, so adding dividends
            # to cash here is correct and avoids double-counting.
            dividends = taxable * DIV_YIELD
            ord_div   = dividends * (1 - QUAL_DIV_PCT)   # ordinary dividend income
            qual_div  = dividends * QUAL_DIV_PCT          # qualified dividend income
            cash     += dividends                         # dividends land in cash account

            # ── Step 3: Required Minimum Distribution (age 73+) ──────────────
            # IRS mandates a minimum annual withdrawal from pre-tax accounts.
            # The RMD is computed from the IRS Uniform Lifetime Table factor.
            # RMD goes directly to cash (it is ordinary income when received).
            rmd = 0.0
            if age >= RMD_START_AGE:
                rmd   = min(ira / RMD_TABLE.get(age, 8.9), ira)
                ira  -= rmd
                cash += rmd

            # ── Step 4: Roth conversion decision (ages 60–72 only) ───────────
            # Estimate LTCG from taxable sales needed to cover expenses.
            # This is passed to the optimizer separately from ordinary income
            # because LTCG is taxed at preferential rates, not bracket rates.
            expected_sold = min(taxable, max(0.0, expenses - ss - cash))
            # Dynamic gain fraction: as price return grows the account without
            # growing the basis, the taxable gain fraction rises over time.
            gain_frac_est = (1.0 - taxable_basis / taxable) if taxable > 0 else (1.0 - COST_BASIS_PCT)
            expected_ltcg = expected_sold * gain_frac_est + qual_div

            # Base ordinary income = income we KNOW is already recognized
            # this year, before any conversion amount is decided.
            # Critically, we do NOT include expected IRA withdrawals — those
            # are a consequence of expenses that happen after the conversion,
            # and including them would incorrectly suppress conversion headroom.
            # rmd_ord_div: non-SS, non-conversion ordinary income known at decision time.
            # ss is passed separately so the optimizer re-computes the taxable SS
            # fraction at each conversion level (it rises with income via the
            # provisional income test — freezing it at conv=0 understates cost).
            rmd_ord_div = rmd + ord_div

            roth_conv = 0.0
            if age <= ROTH_END_AGE and ira > 0:
                # Pass the 2-year lookback MAGI so the optimizer uses
                # the correct IRMAA tier when deciding how much to convert.
                irmaa_opt_magi = magi_history[i - 2] if i >= 2 else 0.0
                roth_conv = min(
                    optimal_roth_conversion(
                        rmd_ord_div, ord_div, ss, expected_ltcg, ira,
                        age, brackets, std, ltcg_bkts,
                        irmaa_lookback_magi=irmaa_opt_magi,
                    ),
                    ira,
                )  # uses global USE_ACA_SUBSIDY
                ira  -= roth_conv   # moved out of pre-tax IRA
                roth += roth_conv   # landed in tax-free Roth (taxes paid separately)

            # ── Step 5: Fund lifestyle expenses ──────────────────────────────
            # Waterfall: most liquid and tax-efficient sources drawn first.
            # SS offsets the need before any portfolio withdrawal.
            # Roth is drawn last to preserve tax-free compound growth.
            needed    = max(0.0, expenses - ss)
            used_cash = min(cash, needed);    cash    -= used_cash;    needed -= used_cash
            sold_tax  = min(taxable, needed)
            if sold_tax > 0 and taxable > 0:
                gain_frac_5    = 1.0 - taxable_basis / taxable   # gain fraction at time of sale
                ltcg_from_sold = sold_tax * gain_frac_5          # LTCG this sale generates
                taxable_basis -= (sold_tax / taxable) * taxable_basis   # reduce basis proportionally
            else:
                ltcg_from_sold = 0.0
            taxable -= sold_tax;     needed -= sold_tax
            ira_wd    = min(ira, needed);     ira     -= ira_wd;       needed -= ira_wd
            roth_wd   = min(roth, needed);    roth    -= roth_wd
            # If needed > 0 after Roth, the household is insolvent (all accounts empty)

            # ── Steps 6–8: Compute taxes, healthcare, and pay — iteratively ──────
            #
            # Steps 6, 7, and 8 are combined into a single iterative loop
            # because they are mutually dependent:
            #   - Selling taxable in step 8 generates LTCG → changes tax bill
            #   - Drawing IRA in step 8 is ordinary income → changes tax + SS taxable
            #   - More tax → may require more sales → more LTCG → more tax ...
            #
            # The iteration converges in 3–5 steps because each marginal sale
            # generates tax at a rate < 100%, so the series is contracting.
            #
            # Variables accumulated across iterations:
            #   extra_sold   — additional taxable sold in step 8 (beyond step 5)
            #   extra_ira_wd — additional IRA drawn in step 8 (beyond step 5)
            # These are added to the step 5 amounts when recording the final row.

            extra_sold   = 0.0   # extra taxable sold to cover tax shortfall
            extra_ira_wd = 0.0   # extra IRA drawn to cover tax shortfall

            for _iter in range(15):

                # ── Step 6: Recompute tax on all income including step-8 sales ─
                # Total taxable sales this year = step-5 amount + step-8 extra
                total_sold  = sold_tax + extra_sold
                # Total IRA withdrawal = step-5 amount + step-8 extra
                total_ira_wd = ira_wd + extra_ira_wd

                # Dynamic gain fraction based on current taxable account state.
                # Computed once per iteration before any income aggregation.
                gain_frac = ((taxable - taxable_basis) / taxable
                             if taxable > 0 else 0.0)

                # SS provisional income: include ALL non-SS income flowing through MAGI.
                # Qualified dividends are LTCG-rate income but still part of AGI,
                # so they count toward provisional income under IRS Publication 915.
                other_for_ss   = (rmd + roth_conv + total_ira_wd + ord_div
                                  + total_sold * gain_frac
                                  + qual_div)
                ss_taxable     = calc_ss_taxable(ss, other_for_ss)

                ordinary_gross = rmd + roth_conv + total_ira_wd + ss_taxable + ord_div
                ltcg           = ltcg_from_sold + qual_div   # dynamic: actual gain from sales
                magi           = ordinary_gross + ltcg

                fed_tax  = calc_ordinary_tax(ordinary_gross, brackets, std)
                fed_tax += calc_ltcg_tax(ltcg, ordinary_gross, std, ltcg_bkts)
                # NIIT (IRC §1411): 3.8% on NII when MAGI > $250k.
                # NII = LTCG + all dividends (not IRA/RMD/SS).
                # NIIT: NII = LTCG (includes qual_div gains) + all dividends
                # NII = ltcg_from_sold + qual_div + ord_div = all investment income.
                # niit     = calc_niit(ltcg, ord_div + qual_div, magi)
                niit     = calc_niit(ltcg, ord_div, magi)
                va_tax   = calc_va_tax(rmd + roth_conv + total_ira_wd + ord_div + ltcg)
                total_tax = fed_tax + niit + va_tax

                # ── Step 7: Healthcare cost ────────────────────────────────────
                if age >= MEDICARE_AGE:
                    irmaa_magi = magi_history[i - 2] if i >= 2 else 0.0
                    health = MEDICARE_BASE + irmaa_surcharge(irmaa_magi)
                elif USE_ACA_SUBSIDY:
                    health = aca_net_premium(magi)
                else:
                    health = BENCHMARK_PREMIUM

                # ── Step 8: Pay — waterfall with convergence check ─────────────
                due = total_tax + health
                cash_used  = min(cash, due)
                shortfall  = due - cash_used

                if shortfall < 0.01:
                    # Cash covers the entire bill — no asset sales needed
                    cash -= cash_used
                    break

                # Fill shortfall: taxable → IRA → Roth
                new_extra_sold   = min(taxable, shortfall)
                if new_extra_sold > extra_sold and taxable > 0:   # incremental sale this iter
                    inc = new_extra_sold - extra_sold
                    gain_frac_8     = 1.0 - taxable_basis / taxable
                    ltcg_from_sold += inc * gain_frac_8            # accumulate LTCG
                    taxable_basis  -= (inc / taxable) * taxable_basis
                shortfall       -= new_extra_sold
                new_extra_ira_wd = min(ira - extra_ira_wd, shortfall)  # don't exceed IRA balance
                shortfall       -= new_extra_ira_wd
                new_extra_roth   = min(roth, shortfall)   # last resort
                shortfall       -= new_extra_roth

                # Check convergence: did the extra sales change from last iteration?
                if (abs(new_extra_sold   - extra_sold)   < 1.0 and
                    abs(new_extra_ira_wd - extra_ira_wd) < 1.0):
                    # Converged — apply the final amounts
                    extra_sold    = new_extra_sold
                    extra_ira_wd  = new_extra_ira_wd
                    cash         -= cash_used
                    taxable      -= extra_sold
                    ira          -= extra_ira_wd
                    roth         -= new_extra_roth
                    break

                extra_sold   = new_extra_sold
                extra_ira_wd = new_extra_ira_wd

            # Update the step-5 totals so the recorded row reflects everything
            sold_tax  += extra_sold    # total taxable sold this year (steps 5 + 8)
            ira_wd    += extra_ira_wd  # total IRA withdrawn this year (steps 5 + 8)
            magi_history[i] = magi     # record for IRMAA lookback


            # ── Step 9: Apply end-of-year investment returns ──────────────────
            # Taxable grows at price-only return (dividends already extracted above).
            # IRA and Roth grow at the full total return (dividends reinvested).
            # Cash earns nothing (conservative assumption).
            taxable       *= (1 + r_price[sim, i])
            # taxable_basis unchanged — price appreciation is unrealized gain on top of basis
            ira     *= (1 + r_total[sim, i])
            roth    *= (1 + r_total[sim, i])

            # ── Step 10: Record year-end snapshot ────────────────────────────
            rows.append({
                "Sim":           sim + 1,
                "Age":           age,
                # Account balances (end of year, after returns)
                "Portfolio":     cash + taxable + ira + roth,
                "Cash":          cash,
                "Taxable":       taxable,
                "IRA":           ira,
                "Roth":          roth,
                # Income sources
                "SS":            ss,
                "RMD":           rmd,
                "Roth Conv":     roth_conv,
                "Taxable Sold":  sold_tax,
                "IRA WD":        ira_wd,
                "Roth WD":       roth_wd,
                "Ord Div":       ord_div,
                "Qual Div":      qual_div,
                # Tax inputs
                "Ordinary":      ordinary_gross,
                "LTCG":          ltcg,
                "MAGI":          magi,
                "SS Taxable":    ss_taxable,
                # Tax outputs
                "Fed Tax":       fed_tax,
                "VA Tax":        va_tax,
                "NIIT":          niit,                 
                "Tax":           total_tax,
                "Health":        health,
                # Spending
                "Expenses":      expenses,
                "Taxable Income": ordinary_gross + ltcg,
            })

    return pd.DataFrame(rows)

# =============================================================================
# SECTION 14 — CHART FORMATTING HELPERS
# =============================================================================

# Axis formatters — convert raw numbers to human-readable labels
fmt_k   = FuncFormatter(lambda x, _: f"${x/1e3:,.0f}k")    # e.g. 250000 → "$250k"
fmt_m   = FuncFormatter(lambda x, _: f"${x/1e6:,.1f}M")    # e.g. 6300000 → "$6.3M"
fmt_pct = FuncFormatter(lambda x, _: f"{x:.0%}")            # e.g. 0.991 → "99%"

def grid(ax, axis="y"):
    """Apply consistent light dashed gridlines to an axes object."""
    ax.grid(True, axis=axis, color=GRID_CLR, linestyle="--", linewidth=0.7, alpha=0.8)
    ax.set_axisbelow(True)

def add_milestones(ax):
    """
    Annotate key retirement milestones with vertical dotted lines.
    Called after data is plotted so get_ylim() returns the correct range.
    Text is placed near the top of the chart area.
    """
    ymin, ymax = ax.get_ylim()
    ypos = ymin + (ymax - ymin) * 0.97
    for m_age, label in [(65, "Medicare"), (70, "SS"), (RMD_START_AGE, "RMDs")]:
        ax.axvline(m_age, color=C_GRAY, lw=0.9, ls=":")
        ax.text(m_age + 0.2, ypos, label, fontsize=7.5, color=C_GRAY, va="top")

def save_chart(fig, filename, chart_num):
    """
    Save a figure to disk with error handling and full path reporting.
    Uses subplots_adjust instead of tight_layout to avoid the known
    matplotlib conflict between tight_layout and twinx axes.
    """
    path = os.path.abspath(filename)

    # Delete the file if exists before saving with the same name
    if os.path.exists(filename):
        os.remove(filename)

    try:
        fig.savefig(path, dpi=150, bbox_inches="tight")
        print(f"Chart {chart_num} saved: {path}")
    except Exception as e:
        print(f"Chart {chart_num} FAILED to save: {e}")
    finally:
        plt.close(fig)


# =============================================================================
# SECTION 15 — CHART 1: MONTE CARLO FAN
# =============================================================================

def chart1_fan(summary):
    """
    Monte Carlo fan chart showing the spread of all 2,000 portfolio outcomes.

    Displays:
      - Shaded bands for 10th–90th and 25th–75th percentile ranges
      - Median and mean portfolio paths
      - Portfolio survival rate on a right-side axis (% of sims still solvent)
      - Vertical milestone lines for Medicare, SS, and RMD start ages

    Uses Scenario A (subsidized ACA) summary data.
    """
    fig, ax = plt.subplots(figsize=(11, 6.5))
    fig.patch.set_facecolor("#F8F9FA"); ax.set_facecolor("#F8F9FA")

    ages = summary["Age"]

    # Shaded probability bands
    ax.fill_between(ages, summary["P10"], summary["P90"],
                    color=C_BLUE, alpha=0.15, label="10th-90th Pctile")
    ax.fill_between(ages, summary["P25"], summary["P75"],
                    color=C_BLUE, alpha=0.28, label="25th-75th Pctile")
    ax.plot(ages, summary["P10"],    color=C_BLUE,   lw=0.8, ls="--", alpha=0.5)
    ax.plot(ages, summary["P90"],    color=C_BLUE,   lw=0.8, ls="--", alpha=0.5)
    ax.plot(ages, summary["Median"], color=C_BLUE,   lw=2.5, label="Median")
    ax.plot(ages, summary["Mean"],   color=C_ORANGE, lw=1.5, ls=":",  label="Mean")

    # Survival rate on right axis
    ax2 = ax.twinx()
    ax2.plot(ages, summary["Survival"], color=C_RED, lw=2.0, ls="-.", label="Survival Rate")
    ax2.set_ylim(0, 1.15); ax2.yaxis.set_major_formatter(fmt_pct)
    ax2.set_ylabel("Survival Rate", color=C_RED, fontsize=10)
    ax2.tick_params(axis="y", colors=C_RED)

    ax.yaxis.set_major_formatter(fmt_m)
    ax.set_xlabel("Age", fontsize=11)
    ax.set_ylabel("Portfolio Value  (Real 2025 $)", fontsize=11)
    ax.set_title(
        f"Monte Carlo Retirement Projection  |  {SIMS:,} Simulations  |  Ages {START_AGE}-{END_AGE}",
        fontsize=12, fontweight="bold", pad=12)
    ax.set_xlim(START_AGE, END_AGE)
    add_milestones(ax)

    # Combine legends from both axes
    l1, lb1 = ax.get_legend_handles_labels()
    l2, lb2 = ax2.get_legend_handles_labels()
    ax.legend(l1+l2, lb1+lb2, loc="upper right", fontsize=9, framealpha=0.9)
    grid(ax)

    # subplots_adjust avoids the tight_layout / twinx incompatibility
    fig.subplots_adjust(left=0.08, right=0.88, top=0.92, bottom=0.08)
    #save_chart(fig, "chart1_montecarlo.png", 1)
    return fig


# =============================================================================
# SECTION 16 — CHART 2: MEDIAN PATH DETAIL (3-PANEL)
# =============================================================================

def chart2_median(df_med, filename="chart2_median_detail.png", subtitle="Subsidized ACA"):
    """
    Three-panel breakdown of the median simulation path.

    Panel 1 — Funding Sources vs. Expenses:
        Stacked bars show where money comes from each year:
        SS (green), Taxable Sales (teal), Roth Conv (purple), IRA WD (orange),
        RMD (red), Roth WD (cyan).  The dashed line is the spending target.
        This panel clearly shows the Roth conversion window (ages 60–72) and
        when each account type is drawn upon.

    Panel 2 — Portfolio Composition:
        Stacked area chart of account balances over time.  Shows how the mix
        shifts from IRA-heavy at 60 to Roth-dominant by the late 80s.

    Panel 3 — Taxes, Healthcare & Effective Rates:
        Stacked bars: federal tax (red), Virginia tax (orange), healthcare (purple).
        Overlaid lines: effective rates as % of total spending and taxable income.
        The spike at ages 73+ reflects RMDs driving up ordinary income.

    Parameters:
        df_med    — median-path DataFrame (one row per age)
        filename  — output filename (allows two versions: subsidized vs no-subsidy)
        subtitle  — scenario label shown in the chart title
    """
    fig = plt.figure(figsize=(13, 16)); fig.patch.set_facecolor("#F8F9FA")
    gs  = GridSpec(3, 1, figure=fig, hspace=0.40)
    ax1 = fig.add_subplot(gs[0]); ax2 = fig.add_subplot(gs[1]); ax3 = fig.add_subplot(gs[2])
    for ax in [ax1, ax2, ax3]: ax.set_facecolor("#F8F9FA")

    fig.suptitle(f"Median Path — Retirement Breakdown  (Real 2025 $)  |  {subtitle}",
                 fontsize=13, fontweight="bold", y=0.995)
    ages = df_med["Age"].values

    # ── Panel 1: Funding Sources ─────────────────────────────────────────────
    # Running bottoms for stacked bars
    b0 = df_med["SS"]
    b1 = b0 + df_med["Taxable Sold"]
    b2 = b1 + df_med["Roth Conv"]
    b3 = b2 + df_med["IRA WD"]
    b4 = b3 + df_med["RMD"]

    ax1.bar(ages, df_med["SS"],           color=C_GREEN,  label="Social Security",           alpha=0.9)
    ax1.bar(ages, df_med["Taxable Sold"], bottom=b0,       color=C_TEAL,   label="Taxable Sold",     alpha=0.9)
    ax1.bar(ages, df_med["Roth Conv"],    bottom=b1,       color=C_PURPLE, label="Roth Conv (tax event)", alpha=0.9)
    ax1.bar(ages, df_med["IRA WD"],       bottom=b2,       color=C_ORANGE, label="IRA Withdrawal",   alpha=0.9)
    ax1.bar(ages, df_med["RMD"],          bottom=b3,       color=C_RED,    label="RMD",              alpha=0.9)
    ax1.bar(ages, df_med["Roth WD"],      bottom=b4,       color=C_CYAN,   label="Roth WD (tax-free)", alpha=0.9)
    ax1.plot(ages, df_med["Expenses"], color="black", lw=2, ls="--",
             label="Lifestyle Expenses (real $)", zorder=5)

    ax1.yaxis.set_major_formatter(fmt_k)
    ax1.set_title("Funding Sources vs. Expenses", fontsize=11, fontweight="bold")
    ax1.legend(loc="upper right", fontsize=8, ncol=2, framealpha=0.85)
    grid(ax1); ax1.set_xlim(START_AGE-0.5, END_AGE+0.5); add_milestones(ax1)

    # ── Panel 2: Portfolio Composition ──────────────────────────────────────
    ax2.stackplot(ages,
                  df_med["Cash"], df_med["Taxable"], df_med["IRA"], df_med["Roth"],
                  labels=["Cash", "Taxable", "IRA / Pre-Tax", "Roth"],
                  colors=[C_TEAL, C_BLUE, C_ORANGE, C_GREEN], alpha=0.85)
    ax2.yaxis.set_major_formatter(fmt_m)
    ax2.set_title("Portfolio Composition Over Time", fontsize=11, fontweight="bold")
    ax2.legend(loc="upper left", fontsize=9)
    grid(ax2); ax2.set_xlim(START_AGE-0.5, END_AGE+0.5); add_milestones(ax2)

    # ── Panel 3: Taxes, Healthcare & Effective Rates ─────────────────────────
    ax3r = ax3.twinx()    # right axis for rate lines

    ax3.bar(ages, df_med["Fed Tax"],
            color=C_RED,    label="Federal Tax",   alpha=0.85)
    ax3.bar(ages, df_med["VA Tax"],
            bottom=df_med["Fed Tax"],
            color=C_ORANGE, label="Virginia Tax",  alpha=0.85)
    ax3.bar(ages, df_med["Health"],
            bottom=df_med["Fed Tax"] + df_med["VA Tax"],
            color=C_PURPLE, label="Healthcare",    alpha=0.85)

    # Effective rate lines: total burden as % of expenses and as % of taxable income
    burden  = df_med["Tax"] + df_med["Health"]
    ti      = df_med["Taxable Income"].replace(0, np.nan)
    r_spend = burden / df_med["Expenses"]
    r_tax   = np.where(ti >= 20_000, burden / ti, np.nan)  # suppress near-zero income

    l1, = ax3r.plot(ages, r_spend, color=C_BLUE,  lw=2.2, label="(Tax+Health) / Expenses")
    l2, = ax3r.plot(ages, r_tax,   color=C_GREEN, lw=2.2, ls="--", label="(Tax+Health) / Taxable Income")

    ax3.yaxis.set_major_formatter(fmt_k); ax3.set_ylabel("Annual Cost ($)", fontsize=9)
    ax3r.set_ylim(0, 0.60); ax3r.yaxis.set_major_formatter(fmt_pct)
    ax3r.set_ylabel("Effective Rate", fontsize=9, color=C_BLUE)
    ax3r.tick_params(axis="y", colors=C_BLUE)
    ax3.set_title("Taxes, Healthcare & Effective Rates", fontsize=11, fontweight="bold")
    ax3.set_xlabel("Age", fontsize=10)

    bar_h = [mpatches.Patch(color=C_RED,    label="Federal Tax"),
             mpatches.Patch(color=C_ORANGE, label="Virginia Tax"),
             mpatches.Patch(color=C_PURPLE, label="Healthcare")]
    ax3r.legend(handles=bar_h+[l1,l2], loc="upper right", fontsize=8, framealpha=0.9)
    grid(ax3); ax3.set_xlim(START_AGE-0.5, END_AGE+0.5); add_milestones(ax3)

    #save_chart(fig, filename, "2")
    return fig


# =============================================================================
# SECTION 17 — CHART 3: PERCENTILE SCENARIO PATHS
# =============================================================================

def chart3_paths(df):
    """
    Show five individual simulation paths selected at fixed percentiles of the
    terminal portfolio value: P10, P25, P50, P75, P90.

    Unlike the fan chart (which shows statistical bands), each line here is
    internally consistent — it is a single simulation's full history.  This
    makes it easier to see how bad sequences of returns compound over time
    in the pessimistic scenarios.

    Left panel:  portfolio value for each scenario path
    Right panel: annual tax + healthcare cost for each scenario path
                 (shows how RMDs and IRMAA drive up costs in good scenarios)
    """
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.patch.set_facecolor("#F8F9FA")
    fig.suptitle("Percentile Retirement Scenarios  (Real 2025 $)", fontsize=13, fontweight="bold")

    # Select the representative simulation for each percentile
    terminal = df.groupby("Sim")["Portfolio"].last().sort_values()
    n = len(terminal)
    pct_map = {10: int(n*0.10), 25: int(n*0.25), 50: int(n*0.50),
               75: int(n*0.75), 90: int(n*0.90)}
    colors  = {10: C_RED, 25: C_ORANGE, 50: C_BLUE, 75: C_GREEN, 90: C_TEAL}

    for ax in axes: ax.set_facecolor("#F8F9FA")
    ax_p, ax_t = axes

    for pct, idx in pct_map.items():
        sim_df = df[df["Sim"] == terminal.index[idx]]
        lw = 2.2 if pct == 50 else 1.3   # median path drawn thicker
        ax_p.plot(sim_df["Age"], sim_df["Portfolio"],
                  color=colors[pct], lw=lw, label=f"P{pct}")
        ax_t.plot(sim_df["Age"], sim_df["Tax"] + sim_df["Health"],
                  color=colors[pct], lw=lw, label=f"P{pct}")

    ax_p.yaxis.set_major_formatter(fmt_m)
    ax_p.set_title("Portfolio Value by Scenario", fontsize=11, fontweight="bold")
    ax_p.set_xlabel("Age"); ax_p.set_ylabel("Portfolio (Real $)")
    ax_p.legend(fontsize=9); grid(ax_p)

    ax_t.yaxis.set_major_formatter(fmt_k)
    ax_t.set_title("Annual Tax + Healthcare by Scenario", fontsize=11, fontweight="bold")
    ax_t.set_xlabel("Age"); ax_t.set_ylabel("Tax + Healthcare ($)")
    ax_t.legend(fontsize=9); grid(ax_t)

    plt.tight_layout()
    #save_chart(fig, "chart3_percentile_paths.png", 3)
    return fig


# =============================================================================
# SECTION 18 — CHART 4: SCENARIO COMPARISON (SUBSIDIZED vs NO-SUBSIDY ACA)
# =============================================================================

def chart4_comparison(df_a, df_b, sum_a, sum_b, label_a, label_b):
    """
    Four-panel side-by-side comparison of Scenario A (subsidized ACA) vs
    Scenario B (no ACA subsidy / full-price ACA).

    Panel A — Median portfolio:   shows overall wealth trajectory
    Panel B — Roth conversions:   shows how much larger conversions are when
                                  the ACA surcharge is removed (ages 60–64)
    Panel C — IRA balance:        shows faster IRA depletion under no-subsidy,
                                  which reduces future RMDs and tax burden
    Panel D — Tax + healthcare:   shows whether larger upfront conversions
                                  reduce the late-life tax spike from RMDs

    Blue = Scenario A (Subsidized ACA)
    Red  = Scenario B (No ACA Subsidy)
    """
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.patch.set_facecolor("#F8F9FA")
    fig.suptitle(f"Scenario Comparison: {label_a}  vs.  {label_b}",
                 fontsize=14, fontweight="bold", y=0.98)

    colors = {label_a: C_BLUE, label_b: C_RED}
    for ax in axes.flat: ax.set_facecolor("#F8F9FA")

    # ── Panel A: Median portfolio path ───────────────────────────────────────
    ax = axes[0, 0]
    for df, lbl in [(df_a, label_a), (df_b, label_b)]:
        med = df.groupby("Age")["Portfolio"].median()
        ax.plot(med.index, med.values, color=colors[lbl], lw=2.2, label=lbl)
    ax.yaxis.set_major_formatter(fmt_m)
    ax.set_title("Median Portfolio Value", fontsize=11, fontweight="bold")
    ax.set_xlabel("Age"); ax.set_ylabel("Portfolio (Real 2025 $)")
    ax.legend(fontsize=9); grid(ax); add_milestones(ax)
    ax.set_xlim(START_AGE, END_AGE)

    # ── Panel B: Annual Roth conversion ──────────────────────────────────────
    # Bars are offset side-by-side for clarity.
    # The key difference appears at ages 60–64: no-subsidy converts much more.
    ax = axes[0, 1]
    for df, lbl in [(df_a, label_a), (df_b, label_b)]:
        med = df.groupby("Age")["Roth Conv"].median()
        ax.bar(med.index + (-0.35 if lbl == label_a else 0.35),
               med.values, width=0.65, color=colors[lbl], alpha=0.8, label=lbl)
    ax.yaxis.set_major_formatter(fmt_k)
    ax.set_title("Annual Roth Conversion (Median)", fontsize=11, fontweight="bold")
    ax.set_xlabel("Age"); ax.set_ylabel("Conversion Amount ($)")
    ax.legend(fontsize=9); grid(ax)
    ax.set_xlim(START_AGE-0.5, 74.5)   # zoom to the conversion window only

    # ── Panel C: IRA balance over time ───────────────────────────────────────
    # Lower IRA under no-subsidy = smaller future RMDs = lower tax burden at 73+
    ax = axes[1, 0]
    for df, lbl in [(df_a, label_a), (df_b, label_b)]:
        med = df.groupby("Age")["IRA"].median()
        ax.plot(med.index, med.values, color=colors[lbl], lw=2.2, label=lbl)
    ax.yaxis.set_major_formatter(fmt_m)
    ax.set_title("Median IRA Balance (drives future RMDs)", fontsize=11, fontweight="bold")
    ax.set_xlabel("Age"); ax.set_ylabel("IRA Balance (Real $)")
    ax.legend(fontsize=9); grid(ax); add_milestones(ax)
    ax.set_xlim(START_AGE, END_AGE)

    # ── Panel D: Annual tax + healthcare ─────────────────────────────────────
    ax = axes[1, 1]
    for df, lbl in [(df_a, label_a), (df_b, label_b)]:
        med_tax    = df.groupby("Age")["Tax"].median()
        med_health = df.groupby("Age")["Health"].median()
        ages_arr   = med_tax.index
        ax.bar(ages_arr + (-0.35 if lbl == label_a else 0.35),
               (med_tax + med_health).values, width=0.65,
               color=colors[lbl], alpha=0.8, label=f"{lbl}")
    ax.yaxis.set_major_formatter(fmt_k)
    ax.set_title("Annual Tax + Healthcare (Median)", fontsize=11, fontweight="bold")
    ax.set_xlabel("Age"); ax.set_ylabel("Annual Cost ($)")
    ax.legend(fontsize=9); grid(ax); add_milestones(ax)
    ax.set_xlim(START_AGE-0.5, END_AGE+0.5)

    plt.tight_layout()
    #save_chart(fig, "chart4_comparison.png", 4)
    return fig


# =============================================================================
# SECTION 19 — SUMMARY STATISTICS PRINTER
# =============================================================================

def print_comparison(df_med_a, sum_a, label_a, df_med_b, sum_b, label_b):
    """
    Print a side-by-side summary table comparing the median path outcomes
    across both scenarios.  Shows terminal portfolio, Roth conversions,
    healthcare costs, lifetime tax burden, and survival rates.
    """
    print()
    print("=" * 72)
    print("  SCENARIO COMPARISON — MEDIAN PATH  (Real 2025 $)")
    print(f"  {'Metric':<40} {label_a:>14}  {label_b:>14}")
    print("=" * 72)

    rows = [
        ("Terminal portfolio (age 95)",     df_med_a.iloc[-1]["Portfolio"],  df_med_b.iloc[-1]["Portfolio"]),
        ("  of which IRA",                  df_med_a.iloc[-1]["IRA"],        df_med_b.iloc[-1]["IRA"]),
        ("  of which Roth",                 df_med_a.iloc[-1]["Roth"],       df_med_b.iloc[-1]["Roth"]),
        ("Total Roth conversions",          df_med_a["Roth Conv"].sum(),     df_med_b["Roth Conv"].sum()),
        ("Healthcare paid (pre-65 only)",   df_med_a[df_med_a["Age"]<65]["Health"].sum(),
                                            df_med_b[df_med_b["Age"]<65]["Health"].sum()),
        ("Total lifetime tax+health",       df_med_a["Tax"].sum()+df_med_a["Health"].sum(),
                                            df_med_b["Tax"].sum()+df_med_b["Health"].sum()),
        ("Peak annual tax+health",         (df_med_a["Tax"]+df_med_a["Health"]).max(),
                                           (df_med_b["Tax"]+df_med_b["Health"]).max()),
    ]

    for label, va, vb in rows:
        diff = vb - va
        sign = "+" if diff >= 0 else ""
        print(f"  {label:<40} ${va:>13,.0f}  ${vb:>13,.0f}  ({sign}${diff:,.0f})")

    print()
    print("  SURVIVAL RATES  (% of 2,000 simulations still solvent)")
    for chk in [75, 80, 85, 90, 95]:
        ra = sum_a[sum_a["Age"] == chk]
        rb = sum_b[sum_b["Age"] == chk]
        if not ra.empty and not rb.empty:
            print(f"  Age {chk}: {ra['Survival'].values[0]:.1%}  vs  {rb['Survival'].values[0]:.1%}")
    print("=" * 72)


# =============================================================================
# SECTION 20 — MAIN: RUN BOTH SCENARIOS AND PRODUCE ALL OUTPUTS
# =============================================================================

if __name__ == "__main__":
    import time

    # ── Scenario A: Subsidized ACA ────────────────────────────────────────────
    # Standard case: health insurance premiums are income-linked before Medicare.
    # The 8.5% ACA marginal surcharge limits Roth conversions at ages 60–64.
    print(f"Running Scenario A: Subsidized ACA  ({SIMS:,} sims)...")
    USE_ACA_SUBSIDY = True
    t0 = time.time()
    df_a = run_simulation()
    print(f"  Done in {time.time()-t0:.0f}s")

    # Build summary statistics (percentiles + survival rate at each age)
    sum_a = df_a.groupby("Age")["Portfolio"].agg(
        P10      = lambda x: np.percentile(x, 10),
        P25      = lambda x: np.percentile(x, 25),
        Median   = "median",
        Mean     = "mean",
        P75      = lambda x: np.percentile(x, 75),
        P90      = lambda x: np.percentile(x, 90),
        Survival = lambda x: (x > 0).mean(),
    ).reset_index()

    # Median path: the single simulation whose terminal value is closest to
    # the 50th percentile of all terminal values
    # Sort by (Portfolio - Roth) = IRA + Taxable + Cash, which is unaffected
    # by ROTH_START. Sorting by total Portfolio would select a different sim
    # for different ROTH_START values, making comparisons misleading.
    non_roth_a = (df_a.groupby("Sim")[["Portfolio","Roth"]].last()
                  .eval("NonRoth = Portfolio - Roth")["NonRoth"]
                  .sort_values())
    med_id_a = non_roth_a.index[len(non_roth_a) // 2]
    df_med_a = df_a[df_a["Sim"] == med_id_a].copy()

    # ── Scenario B: No ACA Subsidy (full-price ACA) ───────────────────────────
    # Alternative case: you pay the full benchmark premium regardless of income.
    # No marginal ACA surcharge on conversions → much larger Roth window at 60–64.
    # Costs $18k/yr in health premiums before 65 vs. income-linked amount in Scenario A.
    print(f"Running Scenario B: No ACA Subsidy  ({SIMS:,} sims)...")
    USE_ACA_SUBSIDY = False
    t0 = time.time()
    df_b = run_simulation()
    print(f"  Done in {time.time()-t0:.0f}s")

    sum_b = df_b.groupby("Age")["Portfolio"].agg(
        P10      = lambda x: np.percentile(x, 10),
        P25      = lambda x: np.percentile(x, 25),
        Median   = "median",
        Mean     = "mean",
        P75      = lambda x: np.percentile(x, 75),
        P90      = lambda x: np.percentile(x, 90),
        Survival = lambda x: (x > 0).mean(),
    ).reset_index()

    non_roth_b = (df_b.groupby("Sim")[["Portfolio","Roth"]].last()
                  .eval("NonRoth = Portfolio - Roth")["NonRoth"]
                  .sort_values())
    med_id_b = non_roth_b.index[len(non_roth_b) // 2]
    df_med_b = df_b[df_b["Sim"] == med_id_b].copy()

    label_a = "Subsidized ACA"
    label_b = "No ACA Subsidy"

    # ── Build all charts ──────────────────────────────────────────────────────
    print("Building charts and Excel...")
    chart1_fan(sum_a)
    chart2_median(df_med_a,
                  filename="chart2_median_subsidized_aca.png",
                  subtitle="Subsidized ACA")
    chart2_median(df_med_b,
                  filename="chart2_median_no_aca_subsidy.png",
                  subtitle="No ACA Subsidy")
    chart3_paths(df_a)
    chart4_comparison(df_a, df_b, sum_a, sum_b, label_a, label_b)

    # ── Write Excel workbook ──────────────────────────────────────────────────
    # Contains four data sheets (one summary + one median path per scenario)
    # plus a Parameters sheet for full reproducibility.
    if os.path.exists(os.path.abspath(OUTPUT_FILE)):
        os.remove(os.path.abspath(OUTPUT_FILE))

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as w:
        sum_a.to_excel(w,    sheet_name="Summary (Subsidized ACA)", index=False)
        df_med_a.to_excel(w, sheet_name="Median Path (Subsidized)",  index=False)
        sum_b.to_excel(w,    sheet_name="Summary (No Subsidy)",       index=False)
        df_med_b.to_excel(w, sheet_name="Median Path (No Subsidy)",   index=False)
        params = [
            ("SCENARIO A",           "Subsidized ACA (USE_ACA_SUBSIDY=True)"),
            ("SCENARIO B",           "Full-price ACA (USE_ACA_SUBSIDY=False)"),
            ("", ""),
            ("Initial Cash",          CASH_START),
            ("Initial Taxable",       TAXABLE_START),
            ("Initial IRA",           IRA_START),
            ("Initial Roth IRA",       ROTH_START),
            ("Mean Real Return",      MEAN_RETURN),
            ("Return Volatility",     VOL_RETURN),
            ("Crash Floor",           CRASH_FLOOR),
            ("Dividend Yield",        DIV_YIELD),
            ("Cost Basis %",          COST_BASIS_PCT),
            ("Qualified Div %",       QUAL_DIV_PCT),
            ("Base Expenses",         BASE_EXPENSES),
            ("Inflation (brackets)",  INFLATION),
            ("SS Start Age",          SS_START_AGE),
            ("SS Amount",             SS_AMOUNT),
            ("Roth End Age",          ROTH_END_AGE),
            ("Marginal Stop",         MARGINAL_STOP),
            ("Benchmark Premium",     BENCHMARK_PREMIUM),
            ("Medicare Base",         MEDICARE_BASE),
            ("Simulations",           SIMS),
            ("Random Seed",           SEED),
        ]
        pd.DataFrame(params, columns=["Parameter", "Value"]).to_excel(
            w, sheet_name="Parameters", index=False)
    print(f"Excel saved: {os.path.abspath(OUTPUT_FILE)}")

    # ── Print summary comparison to console ───────────────────────────────────
    print_comparison(df_med_a, sum_a, label_a, df_med_b, sum_b, label_b)
