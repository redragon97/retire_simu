"""
streamlit_app.py — Retirement Monte Carlo Simulator
=====================================================
Run with:  streamlit run streamlit_app.py

Bugs fixed vs previous version
-------------------------------
1.  START_AGE defined twice — consolidated to one slider
2.  SS_START_AGE defined twice — consolidated to one slider
3.  run_simulation() called with positional str args — removed
4.  build_median_df() used groupby().median() which drops spaced column names
    on newer pandas — replaced with simulator's _build_median_df()
5.  sim.USE_ACA_SUBSIDY = flag only updates attribute, not internal globals()
    — replaced with sim.__dict__["USE_ACA_SUBSIDY"]
6.  chart5_grid(df_b) passed raw simulation DataFrame — chart5_grid requires
    output of _run_grid_analysis(); grid section added correctly
7.  PRICE_RETURN and ROTH_END_AGE not patched after user changes return inputs
    — now derived and patched in _patch_sim()
8.  SCENARIO_MODE never set on sim module — now patched
9.  _build_summary, _build_median_df, _run_grid_analysis not imported — added
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

import retirement_planning_simulator as sim
from retirement_planning_simulator import (
    run_simulation,
    _build_summary,
    _build_median_df,
    _run_grid_analysis,
    chart1_fan,
    chart2_median,
    chart3_paths,
    chart4_comparison,
    chart5_grid,
    smile_expenses,
)

st.set_page_config(layout="wide")
st.title("📊 Retirement Monte Carlo Simulator")

# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.header("Simulation Controls")
START_AGE = st.sidebar.slider("Retirement Start Age", 55, 70, 60)
END_AGE   = st.sidebar.slider("End Age", 80, 100, 95)
SIMS      = st.sidebar.slider("Simulations", 500, 5_000, 2_000, step=500)
SEED      = st.sidebar.number_input("Random Seed", value=54, step=1)

st.sidebar.header("Roth Conversion Strategy")
MARGINAL_STOP = st.sidebar.slider("Max Marginal Rate", 0.20, 0.50, 0.35, step=0.01)

st.sidebar.header("Initial Portfolio")
CASH_START    = st.sidebar.number_input("Cash ($)",     value=100_000,   step=50_000)
TAXABLE_START = st.sidebar.number_input("Taxable ($)",  value=1_000_000, step=100_000)
IRA_START     = st.sidebar.number_input("IRA ($)",      value=1_000_000, step=100_000)
ROTH_START    = st.sidebar.number_input("Roth IRA ($)", value=0,         step=100_000)

st.sidebar.header("Investment Returns")
MEAN_RETURN = st.sidebar.slider("Mean Real Return", 0.03, 0.10, 0.07, step=0.005, format="%.3f")
VOL_RETURN  = st.sidebar.slider("Volatility",       0.05, 0.30, 0.15, step=0.01,  format="%.2f")
DIV_YIELD   = st.sidebar.slider("Dividend Yield",   0.00, 0.05, 0.03, step=0.005, format="%.3f")

st.sidebar.header("Spending")
BASE_EXPENSES = st.sidebar.number_input("Annual Expenses ($)", value=100_000, step=10_000)

st.sidebar.header("Spending Smile")
smile_early = st.sidebar.slider("Age 60-65 (Go-Go)",   -0.02, 0.02,  0.005, step=0.001, format="%.3f")
smile_mid   = st.sidebar.slider("Age 65-75",            -0.02, 0.02, -0.005, step=0.001, format="%.3f")
smile_slow  = st.sidebar.slider("Age 75-85 (Slow-Go)", -0.03, 0.00, -0.010, step=0.001, format="%.3f")
smile_late  = st.sidebar.slider("Age 85+ (No-Go)",     -0.02, 0.01, -0.005, step=0.001, format="%.3f")
smile_scale = st.sidebar.slider("Smile Intensity Multiplier", 0.0, 2.0, 1.0, step=0.1)
SMILE_REAL_CHANGE = {
    (60, 65): smile_early * smile_scale,
    (65, 75): smile_mid   * smile_scale,
    (75, 85): smile_slow  * smile_scale,
    (85, 96): smile_late  * smile_scale,
}

st.sidebar.header("Inflation")
INFLATION = st.sidebar.slider("Inflation Rate", 0.01, 0.06, 0.035, step=0.005, format="%.3f")

st.sidebar.header("State Taxes")
_state = st.sidebar.selectbox("State Tax Profile", ["Virginia (VA)"])

st.sidebar.header("Social Security")
SS_START_AGE = st.sidebar.slider("SS Claim Age", 62, 70, 70)
SS_AMOUNT    = st.sidebar.number_input("Annual SS Benefit ($)", value=100_000, step=5_000)

st.sidebar.header("Healthcare / ACA")
SCENARIO_MODE = st.sidebar.selectbox(
    "ACA Scenario Mode",
    ["single_original", "single_enhanced", "aca_comparison"],
    index=0,
    help="single_original=2026+ rules | single_enhanced=expired 2025 | aca_comparison=both",
)
BENCHMARK_PREMIUM = st.sidebar.number_input("Benchmark ACA Premium ($)", value=18_000, step=500)

st.sidebar.header("Grid Analysis (Chart 5)")
RUN_GRID        = st.sidebar.checkbox("Run Grid Analysis", value=True)
GRID_SIMS       = st.sidebar.slider("Grid Sims per Cell", 100, 1_000, 500, step=100)
grid_tax_input  = st.sidebar.text_input("Taxable levels ($M)", value="0, 1, 2, 3")
grid_ira_input  = st.sidebar.text_input("IRA levels ($M)",     value="1, 2, 3, 4, 5, 6")

def _parse_millions(text):
    try:
        return [int(float(x.strip()) * 1_000_000) for x in text.split(",")]
    except ValueError:
        return []

# ── Spending curve preview ────────────────────────────────────────────────────
def preview_smile_curve():
    sim.START_AGE = START_AGE
    sim.SMILE_REAL_CHANGE = SMILE_REAL_CHANGE
    ages     = list(range(START_AGE, END_AGE + 1))
    expenses = [smile_expenses(age, BASE_EXPENSES) for age in ages]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=ages, y=expenses, name="Real Spending",
                             line=dict(width=3, color="#1F497D"),
                             fill="tozeroy", fillcolor="rgba(31,73,125,0.10)"))
    fig.update_layout(title="Spending Curve Preview (Real $)",
                      xaxis_title="Age", yaxis_title="Annual Spending ($)",
                      height=300, margin=dict(t=40, b=20))
    return fig

st.plotly_chart(preview_smile_curve(), use_container_width=True)

# ── Module patcher ────────────────────────────────────────────────────────────
def _patch_sim():
    sim.START_AGE         = START_AGE
    sim.END_AGE           = END_AGE
    sim.SIMS              = SIMS
    sim.SEED              = int(SEED)
    sim.MARGINAL_STOP     = MARGINAL_STOP
    sim.CASH_START        = CASH_START
    sim.TAXABLE_START     = TAXABLE_START
    sim.IRA_START         = IRA_START
    sim.ROTH_START        = ROTH_START
    sim.MEAN_RETURN       = MEAN_RETURN
    sim.VOL_RETURN        = VOL_RETURN
    sim.DIV_YIELD         = DIV_YIELD
    sim.PRICE_RETURN      = MEAN_RETURN - DIV_YIELD
    sim.BASE_EXPENSES     = BASE_EXPENSES
    sim.SMILE_REAL_CHANGE = SMILE_REAL_CHANGE
    sim.INFLATION         = INFLATION
    sim.SS_START_AGE      = SS_START_AGE
    sim.SS_AMOUNT         = SS_AMOUNT
    sim.BENCHMARK_PREMIUM = BENCHMARK_PREMIUM
    sim.SCENARIO_MODE     = SCENARIO_MODE
    sim.ROTH_END_AGE      = sim.RMD_START_AGE - 1
    sim.GRID_SIMS         = GRID_SIMS
    sim.GRID_TAXABLE      = _parse_millions(grid_tax_input)
    sim.GRID_IRA          = _parse_millions(grid_ira_input)

def _set_aca(flag: bool):
    """Write USE_ACA_SUBSIDY into the simulator's actual globals() dict."""
    sim.__dict__["USE_ACA_SUBSIDY"] = flag

# ── Run Simulation ────────────────────────────────────────────────────────────
if st.button("🚀 Run Simulation"):
    _patch_sim()

    with st.spinner("Running simulations..."):

        if SCENARIO_MODE in ("single_original", "single_enhanced"):
            is_enhanced = (SCENARIO_MODE == "single_enhanced")
            _set_aca(is_enhanced)
            df      = run_simulation()
            summary = _build_summary(df)
            df_med  = _build_median_df(df)
            label   = ("Enhanced ACA — expired 2025 rules" if is_enhanced
                       else "Original ACA — 2026+ rules")

            st.subheader("📈 Key Results")
            fin      = df_med.iloc[-1]
            surv_row = summary[summary["Age"] == END_AGE]
            surv_str = (f"{surv_row['Survival'].values[0]:.1%}"
                        if not surv_row.empty else "—")
            c1,c2,c3,c4,c5 = st.columns(5)
            c1.metric("Terminal Portfolio",     f"${fin['Portfolio']:,.0f}")
            c2.metric("Terminal Roth",          f"${fin['Roth']:,.0f}")
            c3.metric("Terminal IRA",           f"${fin['IRA']:,.0f}")
            c4.metric(f"Survival at {END_AGE}", surv_str)
            c5.metric("Total Conversions",      f"${df_med['Roth Conv'].sum():,.0f}")

            st.write("### Chart 1 — Monte Carlo Fan")
            st.pyplot(chart1_fan(summary))
            st.markdown("""
**What this shows:** The full range of possible portfolio outcomes across all Monte Carlo simulations.

**How to read it:** The middle line is the *median* outcome (50th percentile). Shaded bands show the
10th–90th percentile spread. A wider fan means more uncertainty. If lower bands approach zero, the
risk of portfolio depletion is elevated.

**Why it matters:** Shows *risk and uncertainty*, not just average outcomes.
""")

            st.write(f"### Chart 2 — Median Path  |  {label}")
            st.pyplot(chart2_median(df_med, subtitle=label))
            st.markdown("""
**What this shows:** The *median (typical)* retirement path broken into three panels: funding
sources, portfolio composition, and tax+healthcare costs.

**How to read it:** Panel 1 shows where money comes from each year (SS, taxable sales, Roth
conversions, IRA withdrawals, RMDs). Panel 2 shows account balances over time. Panel 3 shows
the annual tax+health burden and effective rates. Vertical dotted lines mark Medicare (65),
SS start, and RMDs (75).

**What to look for:** When the IRA is depleted, how Roth grows, whether expenses exceed income,
and any tax spikes from large RMDs.

**Why it matters:** Explains *why* the portfolio succeeds or fails — the mechanics behind the numbers.
""")

            st.write("### Chart 3 — Percentile Scenario Paths")
            st.pyplot(chart3_paths(df))
            st.markdown("""
**What this shows:** Five individual simulation paths at the 10th, 25th, 50th, 75th, and 90th
percentile of terminal portfolio value.

**How to read it:** Each line is a single internally consistent retirement trajectory. Lower
percentile lines show how bad sequences of returns compound over 35 years.

**Why it matters:** Provides concrete examples of pessimistic, typical, and optimistic outcomes
instead of just statistical bands.
""")

            if RUN_GRID and _parse_millions(grid_tax_input) and _parse_millions(grid_ira_input):
                st.write("### Chart 5 — Roth Conversion Grid Analysis")
                with st.spinner("Running grid analysis (1–2 minutes)..."):
                    grid_df = _run_grid_analysis()
                st.pyplot(chart5_grid(grid_df))
                st.markdown("""
**What this shows:** How Roth conversion effectiveness varies across different starting IRA and
taxable account balances — a map of where conversion strategy matters most.

**How to read it:**
- *Panel 1*: total Roth conversions (higher = more tax-efficient conversion activity)
- *Panel 2*: survival rate heatmap (green = high, red = low)
- *Panel 3*: terminal portfolio by IRA size
- *Panel 4*: total RMD tax paid after age 75 (darker red = heavier RMD tax burden)
- *Panel 5*: whether the IRA is fully converted before RMDs start (green ✓ = good;
  red ✗ = IRA residual remains, generating forced RMDs)
- *Panel 6*: lifetime tax + healthcare burden

**What to look for:** Cells marked ✗ in Panel 5 have the most potential benefit from
more aggressive conversion. These are the scenarios where raising MARGINAL_STOP or
extending the conversion window would reduce lifetime taxes most.

**Why it matters:** Identifies which balance combinations benefit most from strategic
Roth conversion versus which are already fully optimized.
""")

            st.subheader("📥 Download Results")
            st.download_button("Download Full Simulation CSV",
                               data=df.to_csv(index=False),
                               file_name="simulation.csv", mime="text/csv")
            st.download_button("Download Median Path CSV",
                               data=df_med.to_csv(index=False),
                               file_name="median_path.csv", mime="text/csv")

        elif SCENARIO_MODE == "aca_comparison":
            label_a = "Enhanced ACA (2025 expired)"
            label_b = "Original ACA (2026+)"

            _set_aca(True);  df_a = run_simulation()
            _set_aca(False); df_b = run_simulation()
            sum_a    = _build_summary(df_a);    df_med_a = _build_median_df(df_a)
            sum_b    = _build_summary(df_b);    df_med_b = _build_median_df(df_b)

            st.subheader("📈 Key Results")
            fin_a = df_med_a.iloc[-1]; fin_b = df_med_b.iloc[-1]
            surv_a = sum_a[sum_a["Age"]==END_AGE]["Survival"].values
            surv_b = sum_b[sum_b["Age"]==END_AGE]["Survival"].values
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**{label_a}**")
                st.metric("Terminal Portfolio",   f"${fin_a['Portfolio']:,.0f}")
                st.metric("Terminal Roth",        f"${fin_a['Roth']:,.0f}")
                st.metric(f"Survival at {END_AGE}",
                          f"{surv_a[0]:.1%}" if len(surv_a) else "—")
                st.metric("Total Conversions",    f"${df_med_a['Roth Conv'].sum():,.0f}")
            with col2:
                st.markdown(f"**{label_b}**")
                st.metric("Terminal Portfolio",   f"${fin_b['Portfolio']:,.0f}")
                st.metric("Terminal Roth",        f"${fin_b['Roth']:,.0f}")
                st.metric(f"Survival at {END_AGE}",
                          f"{surv_b[0]:.1%}" if len(surv_b) else "—")
                st.metric("Total Conversions",    f"${df_med_b['Roth Conv'].sum():,.0f}")

            st.write(f"### Chart 1 — Monte Carlo Fan  |  {label_a}")
            st.pyplot(chart1_fan(sum_a))
            st.markdown("""
**What this shows:** The full range of portfolio outcomes across all simulations for the
Enhanced ACA (expired 2025) scenario.

**How to read it:** Middle line = median; shaded bands = 10th–90th percentile spread.
Wider fan = more uncertainty. Lower bands near zero = higher depletion risk.

**Why it matters:** Shows *risk and uncertainty* for the Enhanced ACA scenario baseline.
""")

            st.write(f"### Chart 2A — Median Path  |  {label_a}")
            st.pyplot(chart2_median(df_med_a, subtitle=label_a))

            st.write(f"### Chart 2B — Median Path  |  {label_b}")
            st.pyplot(chart2_median(df_med_b, subtitle=label_b))
            st.markdown("""
**What this shows:** The *median* retirement path for each ACA scenario, showing funding
sources, portfolio composition, and tax+healthcare costs.

**How to read it:** Compare the two charts side-by-side to see how ACA rules affect Roth
conversion amounts (Panel 1), IRA drawdown pace (Panel 2), and late-life tax burden (Panel 3).

**What to look for:** Larger Roth conversion bars in Panel 1 indicate the ACA regime allows
more conversion. Lower late-life taxes in Panel 3 confirm the IRA was better depleted.

**Why it matters:** Explains the *mechanism* behind each scenario's outcome.
""")

            st.write("### Chart 3 — Percentile Scenario Paths")
            st.pyplot(chart3_paths(df_a))
            st.markdown("""
**What this shows:** Five individual simulation paths at key percentiles for the Enhanced ACA
scenario. Each line is a single internally consistent retirement trajectory.

**How to read it:** Lower percentile lines reveal how bad return sequences compound over time.
The spread between lines shows the range of realistic outcomes.

**Why it matters:** Provides concrete pessimistic, typical, and optimistic examples.
""")

            st.write("### Chart 4 — Scenario Comparison")
            st.pyplot(chart4_comparison(df_a, df_b, sum_a, sum_b, label_a, label_b))
            st.markdown("""
**What this shows:** A direct side-by-side comparison of the two ACA regimes across four
dimensions: median portfolio, Roth conversions, IRA balance, and annual tax+healthcare.

**How to read it:** Blue = Enhanced ACA (expired 2025); Red = Original ACA (2026+). Gaps
between lines show the financial impact of each regime. Differences typically emerge at
ages 60–64 before Medicare starts.

**What to look for:** Whether one strategy consistently dominates, and how early the
difference compounds into a meaningful portfolio advantage.

**Why it matters:** Quantifies the *real dollar impact* of ACA rules on your Roth
conversion strategy and long-term tax burden.
""")

            if RUN_GRID and _parse_millions(grid_tax_input) and _parse_millions(grid_ira_input):
                st.write("### Chart 5 — Roth Conversion Grid Analysis")
                with st.spinner("Running grid analysis (1–2 minutes)..."):
                    grid_df = _run_grid_analysis()
                st.pyplot(chart5_grid(grid_df))
                st.markdown("""
**What this shows:** How Roth conversion effectiveness varies across different starting IRA
and taxable account balances, under the Original ACA (2026+) rules.

**How to read it:** Panel 5 is the key diagnostic: green ✓ = IRA fully converted before
RMDs; red ✗ = IRA residual remains and generates forced taxable RMDs at age 75+. Red cells
in Panel 4 show where the RMD tax burden is heaviest.

**What to look for:** Cells marked ✗ have the most room for improvement. Raising
MARGINAL_STOP or starting conversions earlier would flip these to ✓ and eliminate
the late-life RMD tax spike.

**Why it matters:** Identifies which balance combinations benefit most from aggressive
Roth conversion versus which are already well-optimized.
""")

            st.subheader("📥 Download Results")
            c1, c2 = st.columns(2)
            c1.download_button(f"Download {label_a} CSV",
                               data=df_a.to_csv(index=False),
                               file_name="scenario_a.csv", mime="text/csv")
            c2.download_button(f"Download {label_b} CSV",
                               data=df_b.to_csv(index=False),
                               file_name="scenario_b.csv", mime="text/csv")

# ── Find Optimal SS Age ───────────────────────────────────────────────────────
st.divider()
if st.button("🔍 Find Optimal SS Claim Age"):
    _patch_sim()
    _set_aca(SCENARIO_MODE == "single_enhanced")

    best_age, best_value = None, 0.0
    results = {}
    progress_bar = st.progress(0, text="Testing SS claim ages 62–70...")

    with st.spinner(""):
        for k, ss_age in enumerate(range(62, 71)):
            sim.SS_START_AGE = ss_age
            df = run_simulation()
            median_terminal = df[df["Age"] == END_AGE]["Portfolio"].median()
            results[ss_age] = median_terminal
            if median_terminal > best_value:
                best_value = median_terminal
                best_age   = ss_age
            progress_bar.progress((k + 1) / 9,
                                   text=f"Age {ss_age} → median ${median_terminal:,.0f}")

    st.success(f"**Optimal SS Claim Age: {best_age}**  "
               f"(median terminal portfolio: ${best_value:,.0f})")
    result_df = pd.DataFrame([
        {"SS Claim Age": age, "Median Terminal Portfolio ($)": f"${val:,.0f}"}
        for age, val in sorted(results.items())
    ])
    st.dataframe(result_df.set_index("SS Claim Age"), use_container_width=True)
