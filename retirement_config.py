"""
retirement_config.py
====================
All user-configurable parameters for the Retirement Monte Carlo Simulator.

HOW TO USE
----------
1. Edit the values in this file to match your situation.
2. Run:  python retirement_planning_simulator.py
   The simulator imports everything it needs from this file automatically.

SECTIONS
--------
  1.  Simulation Controls       — number of runs, age range, random seed
  2.  Portfolio Balances         — starting account balances
  3.  Investment Returns         — real return, volatility, dividend assumptions
  4.  Spending                   — base expenses and spending-smile curve
  5.  Inflation                  — used only for bracket/SS indexing
  6.  Social Security            — claim age and benefit amount
  7.  Roth Conversion Strategy   — RMD age, conversion window, marginal stop rate
  8.  Healthcare                 — ACA scenario mode, Medicare, IRMAA, NIIT
  9.  Tax Tables (2025)          — federal/LTCG/Virginia brackets, RMD factors
  10. Output                     — file names and chart colors

IMPORTANT: Do NOT edit retirement_planning_simulator.py to change parameters.
           All tunable values live here. The simulator file should never need
           to be touched for normal planning use.
"""


# =============================================================================
# SECTION 1 — SIMULATION CONTROLS
# =============================================================================
# Increasing SIMS improves statistical precision but takes longer to run.
# SEED ensures reproducible results; change it to get a different random draw.

START_AGE = 60      # age at start of retirement simulation
END_AGE   = 95      # age at end of simulation
SIMS      = 2_000   # number of independent random scenarios
SEED      = 54      # random seed for reproducibility


# =============================================================================
# SECTION 2 — INITIAL PORTFOLIO BALANCES  (today's dollars)
# =============================================================================

CASH_START    =   300_000   # money market / savings — earns no return in model
TAXABLE_START = 1_000_000   # brokerage account — invested, generates dividends + gains
IRA_START     = 3_000_000   # traditional IRA / 401(k) — pre-tax, subject to RMDs
ROTH_START    =         0   # Roth IRA — after-tax, grows and withdraws tax-free


# =============================================================================
# SECTION 3 — INVESTMENT RETURN ASSUMPTIONS  (real, inflation-adjusted)
# =============================================================================
# MEAN_RETURN = 7% is a standard long-run equity real return assumption.
# Returns follow a lognormal distribution parameterized to exactly match
# MEAN_RETURN and VOL_RETURN as the arithmetic mean and standard deviation.
#
# The taxable account grows at PRICE_RETURN (= MEAN_RETURN - DIV_YIELD)
# because dividends are extracted as taxable income each year.
# IRA and Roth grow at MEAN_RETURN (dividends reinvested internally).

MEAN_RETURN    = 0.07   # real total return on IRA and Roth
VOL_RETURN     = 0.15   # annual return volatility (standard deviation)
CRASH_FLOOR    = -0.40  # single-year loss floor (lognormal already prevents < -100%)
DIV_YIELD      = 0.03   # annual dividend yield on the taxable account
QUAL_DIV_PCT   = 0.80   # fraction of dividends that are qualified (taxed at LTCG rates)
COST_BASIS_PCT = 0.70   # fraction of taxable account that is original cost basis
                        # (the remaining 30% is unrealized gain — taxed as LTCG when sold)


# =============================================================================
# SECTION 4 — SPENDING ASSUMPTIONS  (today's dollars)
# =============================================================================
# BASE_EXPENSES covers all lifestyle costs EXCEPT healthcare premiums,
# which are modeled separately via ACA/Medicare in Section 8.
#
# The spending smile adjusts BASE_EXPENSES each year based on Blanchett (2013):
#   Positive rate → real spending rises (active early retirement)
#   Negative rate → real spending falls (slow-go / no-go years)
# Set all rates to 0.0 for flat real spending throughout retirement.

BASE_EXPENSES = 250_000   # annual lifestyle spending in today's dollars

SMILE_REAL_CHANGE = {
    (60, 65): +0.005,   # +0.5%/yr — go-go years, active travel
    (65, 75): -0.005,   # -0.5%/yr — go-go years tapering
    (75, 85): -0.010,   # -1.0%/yr — slow-go years
    (85, 96): -0.005,   # -0.5%/yr — no-go years
}


# =============================================================================
# SECTION 5 — INFLATION
# =============================================================================
# Used ONLY for:
#   (a) indexing federal and Virginia tax brackets (models bracket creep)
#   (b) SS COLA — keeps SS benefits flat in real purchasing-power terms
# NOT applied to living expenses (simulation is in real dollars throughout).

INFLATION = 0.035   # 3.5% annual inflation


# =============================================================================
# SECTION 6 — SOCIAL SECURITY INCOME
# =============================================================================
# SS_AMOUNT is in today's dollars. The simulator applies SS COLA each year
# (via INFLATION) so the real purchasing power stays constant — matching how
# actual Social Security COLA adjustments work.
# Delaying to age 70 maximizes the monthly benefit.

SS_START_AGE = 70          # age at which SS benefits begin
SS_AMOUNT    = 100_000     # annual combined SS benefit in today's dollars (couple)


# =============================================================================
# SECTION 7 — ROTH CONVERSION STRATEGY
# =============================================================================
# The optimizer converts from IRA to Roth each year from START_AGE through
# ROTH_END_AGE, stopping when the marginal all-in cost exceeds MARGINAL_STOP.
#
# MARGINAL_STOP = 35% rationale:
#   Pre-Medicare with ACA (ages 60-64):  12% fed + 15% LTCG push + 8.5% ACA = 35.5%
#     → 35% allows conversion through the full 12% federal bracket
#   Post-Medicare (ages 65-74):  22% fed + 5.75% VA = 27.75%
#     → 35% comfortably covers the full 22% bracket before RMDs begin
#
# RMD_START_AGE per SECURE 2.0:
#   Born 1960 or later  → 75   (default below)
#   Born 1951-1959      → 73   (change RMD_START_AGE to 73)

RMD_START_AGE = 75                        # age when RMDs become mandatory
ROTH_END_AGE  = RMD_START_AGE - 1        # last year for strategic Roth conversions
MARGINAL_STOP = 0.35                      # stop converting when marginal all-in rate exceeds this


# =============================================================================
# SECTION 8 — HEALTHCARE
# =============================================================================

# ── ACA scenario mode ─────────────────────────────────────────────────────────
# Controls which ACA rules are applied and whether one or two scenarios run.
#
#   "single_original"  — ONE scenario: current 2026+ ACA rules.
#                        400% FPL cliff (~$81,760 for a couple): zero subsidy
#                        above that income. Correct for planning from 2026 onward.
#                        Produces charts 1, 2, 3.
#
#   "single_enhanced"  — ONE scenario: expired enhanced subsidy rules (2021-2025).
#                        8.5% flat cap, no income ceiling. Expired Dec 31 2025.
#                        Useful for historical comparison only.
#                        Produces charts 1, 2, 3.
#
#   "aca_comparison"   — TWO scenarios side by side (enhanced vs original).
#                        Produces all 5 charts including the 4-panel comparison.
#
SCENARIO_MODE = "single_original"

# ── Medicare ──────────────────────────────────────────────────────────────────
MEDICARE_AGE      = 65
MEDICARE_BASE     = 6_000     # approximate base Part B + Part D (couple/year)

# ── ACA ───────────────────────────────────────────────────────────────────────
ACA_FPL_2         = 20_440    # 2025 federal poverty level for a 2-person household
BENCHMARK_PREMIUM = 18_000    # full-cost ACA benchmark silver plan (couple/year)

# ── Net Investment Income Tax (IRC §1411) ─────────────────────────────────────
# 3.8% federal surtax on NII (LTCG + dividends) when MAGI > threshold.
# Threshold is NOT inflation-adjusted — erodes in real value each year.
# Excludes: IRA withdrawals, RMDs, Roth conversions, Social Security.
NIIT_RATE          = 0.038
NIIT_THRESHOLD_MFJ = 250_000


# =============================================================================
# SECTION 9 — TAX TABLES  (2025 BASE YEAR)
# =============================================================================
# ── These values reflect current-law 2025 IRS publications. ──────────────────
# ── Update annually when IRS publishes new inflation adjustments.  ────────────
#
# Federal brackets are Married Filing Jointly (MFJ).
# Brackets are indexed forward by INFLATION each year in the simulation.
# LTCG brackets stack ON TOP of ordinary income (see design notes in simulator).
# Virginia brackets are NOT inflation-indexed (fixed each year by statute).

# Federal ordinary income (MFJ) — IRS Rev. Proc. 2024-40
BASE_BRACKETS_2025 = [
    (0,        0.10),
    (23_200,   0.12),
    (94_300,   0.22),
    (201_050,  0.24),
    (383_900,  0.32),
    (487_450,  0.35),
    (731_200,  0.37),
]
STD_DED_2025 = 30_000    # MFJ standard deduction — IRS Rev. Proc. 2024-40

# Long-term capital gains / qualified dividends (MFJ) — IRS Rev. Proc. 2024-40
LTCG_BRACKETS_2025 = [
    (0,        0.00),
    (96_700,   0.15),
    (600_050,  0.20),
]

# IRS Uniform Lifetime Table (SECURE 2.0) — RMD divisors by age
RMD_TABLE = {
    75:24.6, 76:23.7, 77:22.9, 78:22.0,
    79:21.1, 80:20.2, 81:19.4, 82:18.5, 83:17.7, 84:16.8,
    85:16.0, 86:15.2, 87:14.4, 88:13.7, 89:12.9, 90:12.2,
    91:11.5, 92:10.8, 93:10.1, 94:9.5,  95:8.9,
}

# Virginia state income tax (MFJ)
# SS fully exempt. LTCG taxed as ordinary income. Brackets not inflation-indexed.
VA_STD_DED_MFJ = 18_000    # $9,000/person effective 2024
VA_BRACKETS = [
    (0,       0.0200),
    (3_000,   0.0300),
    (5_000,   0.0500),
    (17_000,  0.0575),    # top rate: 5.75%
]

# IRMAA surcharges (Medicare income-related adjustments, per couple/year)
# Thresholds are CPI-indexed annually; amounts reflect 2025 values.
# Update each year when SSA publishes new IRMAA brackets.
IRMAA_BRACKETS = [
    (212_000,      0),    # no surcharge at or below this MAGI
    (266_000,  2_000),
    (334_000,  4_000),
    (400_000,  6_400),
    (750_000, 11_200),
]
IRMAA_MAX_SURCHARGE = 11_200


# =============================================================================
# SECTION 10 — OUTPUT
# =============================================================================

OUTPUT_FILE = "retirement_results.xlsx"

# Chart colors
C_BLUE   = "#1F497D"    # portfolio, median path
C_GREEN  = "#2E7D32"    # Social Security, Roth balance
C_RED    = "#C0504D"    # federal tax, P10 scenario
C_ORANGE = "#E36C09"    # IRA balance, Virginia tax
C_PURPLE = "#8064A2"    # Roth conversion, healthcare
C_TEAL   = "#006464"    # taxable account, cash
C_CYAN   = "#17BECF"    # Roth withdrawals (tax-free)
C_GRAY   = "#595959"    # milestone annotations
GRID_CLR = "#CCCCCC"    # chart gridlines


# =============================================================================
# SECTION 11 — GRID ANALYSIS (optional, runs after main simulation)
# =============================================================================
# When RUN_GRID_ANALYSIS = True, the simulator runs an additional grid sweep
# across multiple starting IRA and taxable account balances, then produces
# chart5_grid_analysis.png showing where Roth conversion is most impactful.
#
# Note: this adds GRID_SIMS × len(GRID_TAXABLE) × len(GRID_IRA) simulations
# on top of the main run. With defaults below: 500 × 4 × 6 = 12,000 extra sims
# (~1-2 minutes). Reduce GRID_SIMS or the lists for faster runs.

RUN_GRID_ANALYSIS = True

GRID_SIMS    = 500   # sims per grid cell (fewer than main SIMS for speed)
GRID_TAXABLE = [0, 1_000_000, 2_000_000, 3_000_000]   # taxable starting balances
GRID_IRA     = [1_000_000, 2_000_000, 3_000_000,
                4_000_000, 5_000_000, 6_000_000]        # IRA starting balances
