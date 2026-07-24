import streamlit as st
import pandas as pd
import numpy as np
import retirement_planning_simulator as sim

# Import existing functions
from retirement_planning_simulator import (
    run_simulation,
    chart1_fan,
    chart2_median,
    chart3_paths,
    chart4_comparison,
	chart5_grid,
)

# =========================================================
# PAGE CONFIG
# =========================================================
st.set_page_config(layout="wide")
st.title("📊 Retirement Monte Carlo Simulator")

# =========================================================
# SIDEBAR — USER INPUTS (Sections 1–8)
# =========================================================
st.sidebar.header("Simulation Controls")

START_AGE = st.sidebar.number_input("Start Age", 50, 70, 60)
END_AGE = st.sidebar.number_input("End Age", 80, 100, 95)
SIMS = st.sidebar.slider("Number of Simulations", 500, 5000, 2000, step=500)
SEED = st.sidebar.number_input("Random Seed", value=54)

st.sidebar.header("Roth Conversion Strategy")

MARGINAL_STOP = st.sidebar.slider("Max Marginal Rate for Roth Conversion", 0.20, 0.50, 0.35, step=0.01)

st.sidebar.header("Timing Strategy")

START_AGE = st.sidebar.slider("Retirement Age", 55, 70, 60)
SS_START_AGE = st.sidebar.slider("Social Security Start Age", 62, 70, 70)

st.sidebar.header("Initial Portfolio")

CASH_START = st.sidebar.number_input("Cash", value=100_000)
TAXABLE_START = st.sidebar.number_input("Taxable", value=1_000_000)
IRA_START = st.sidebar.number_input("IRA", value=1_000_000)
ROTH_START = st.sidebar.number_input("Roth", value=000_000)

st.sidebar.header("Returns")

MEAN_RETURN = st.sidebar.slider("Mean Return", 0.03, 0.10, 0.07)
VOL_RETURN = st.sidebar.slider("Volatility", 0.05, 0.30, 0.15)
DIV_YIELD = st.sidebar.slider("Dividend Yield", 0.0, 0.05, 0.03)

st.sidebar.header("Spending")

BASE_EXPENSES = st.sidebar.number_input("Annual Expenses", value=100_000)

st.sidebar.header("Spending Smile Adjustments")

smile_early = st.sidebar.slider("Age 60–65 (Go-Go Years)", -0.02, 0.02, 0.005, step=0.001, format="%.3f")
smile_mid = st.sidebar.slider("Age 65–75", -0.02, 0.02, -0.005, step=0.001, format="%.3f")
smile_slow = st.sidebar.slider("Age 75–85 (Slow-Go Years)", -0.03, 0.0, -0.010, step=0.001,format="%.3f")
smile_late = st.sidebar.slider("Age 85+ (No-Go Years)", -0.02, 0.01, -0.005, step=0.001, format="%.3f")

smile_scale = st.sidebar.slider("Smile Intensity Multiplier", 0.0, 2.0, 1.0, step=0.1)

SMILE_REAL_CHANGE = {
    (60, 65): smile_early * smile_scale,
    (65, 75): smile_mid * smile_scale,
    (75, 85): smile_slow * smile_scale,
    (85, 96): smile_late * smile_scale,
}

st.sidebar.header("Inflation")

INFLATION = st.sidebar.slider("Inflation Rate", 0.01, 0.06, 0.035)

st.markdown("""
    <style>
    section[data-testid="stSidebar"] .stSelectbox > label {
        font-size: 40px !important;
        font-weight: bold !important;
        color: #fff !important;
    }
    </style>
    """, unsafe_allow_html=True)

VA_BRACKETS = st.sidebar.selectbox(
    "State Taxes", 
    ["VA"],
    label_visibility="visible"  # or "hidden", "collapsed"
)   

st.sidebar.header("Social Security")

SS_START_AGE = st.sidebar.number_input("SS Start Age", value=70)
SS_AMOUNT = st.sidebar.number_input("SS Annual Amount", value=100_000)

st.sidebar.header("Healthcare")

USE_ACA_SUBSIDY = st.sidebar.checkbox("Use ACA Subsidy", value=True)
BENCHMARK_PREMIUM = st.sidebar.number_input("ACA Premium", value=18_000)

# =========================================================
# SPENDING CURVE PREVIEW
# =========================================================
def preview_smile_curve():
    ages = list(range(START_AGE, END_AGE + 1))
    expenses = [sim.smile_expenses(age, BASE_EXPENSES) for age in ages]

    import plotly.graph_objects as go
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=ages,
        y=expenses,
        name="Real Spending with Smile Adjustments",
        line=dict(width=3)
    ))

    fig.update_layout(
        title="Spending Curve with Smile Adjustments (Real $)",
        xaxis_title="Age",
        yaxis_title="Annual Spending",
        height=350
    )
    return fig

st.plotly_chart(preview_smile_curve(), width='stretch')

def build_summary(df):
    summary = df.groupby("Age")["Portfolio"].agg(
        Median="median",
        Mean="mean",
        P10=lambda x: x.quantile(0.10),
        P25=lambda x: x.quantile(0.25),
        P75=lambda x: x.quantile(0.75),
        P90=lambda x: x.quantile(0.90),
    ).reset_index()

    survival = df.groupby("Age")["Portfolio"].apply(lambda x: (x > 0).mean())
    summary["Survival"] = survival.values

    return summary


def build_median_df(df):
    return df.groupby("Age").median(numeric_only=True).reset_index()

# =========================================================
# RUN BUTTON
# =========================================================

if st.button("🚀 Run Simulation"):

    st.write("Running simulation...")

    # Inject values into module (quick method)
    #import retirement_planning_simulator as sim

    sim.START_AGE = START_AGE
    sim.END_AGE = END_AGE
    sim.SIMS = SIMS
    sim.SEED = SEED

    sim.MARGINAL_STOP = MARGINAL_STOP

    sim.CASH_START = CASH_START
    sim.TAXABLE_START = TAXABLE_START
    sim.IRA_START = IRA_START
    sim.ROTH_START = ROTH_START

    sim.MEAN_RETURN = MEAN_RETURN
    sim.VOL_RETURN = VOL_RETURN
    sim.DIV_YIELD = DIV_YIELD

    sim.BASE_EXPENSES = BASE_EXPENSES
    sim.INFLATION = INFLATION

    sim.SMILE_REAL_CHANGE = SMILE_REAL_CHANGE

    sim.SS_START_AGE = SS_START_AGE
    sim.SS_AMOUNT = SS_AMOUNT

    sim.USE_ACA_SUBSIDY = USE_ACA_SUBSIDY
    sim.BENCHMARK_PREMIUM = BENCHMARK_PREMIUM

    # =====================================================
    # RUN BOTH SCENARIOS
    # =====================================================
    sim.USE_ACA_SUBSIDY = True
    df_a = run_simulation("Subsidized ACA")

    sim.USE_ACA_SUBSIDY = False
    df_b = run_simulation("No ACA Subsidy")

    # =====================================================
    # SUMMARY
    # =====================================================
    st.subheader("📈 Summary")

    summary_a = df_a.groupby("Age")["Portfolio"].median()
    summary_b = df_b.groupby("Age")["Portfolio"].median()

    col1, col2 = st.columns(2)

    with col1:
        st.metric("Final Portfolio (Subsidy)", f"${summary_a.iloc[-1]:,.0f}")

    with col2:
        st.metric("Final Portfolio (No Subsidy)", f"${summary_b.iloc[-1]:,.0f}")


    # =====================================================
    # BUILD DATA FOR CHARTS
    # =====================================================
    summary_a = build_summary(df_a)
    summary_b = build_summary(df_b)

    df_med_a = build_median_df(df_a)
    df_med_b = build_median_df(df_b)

    # =====================================================
    # DISPLAY CHARTS
    # =====================================================
    st.subheader("📊 Detailed Charts")

    # ---------- Chart 1 ----------
    st.write("### Chart 1 — Monte Carlo Fan (Subsidized ACA)")
    fig1 = chart1_fan(summary_a)
    st.pyplot(fig1)
    st.markdown("""
    **What this shows:**  
    This chart visualizes the full range of possible portfolio outcomes across all Monte Carlo simulations.

    **How to read it:**  
    - The middle line represents the *median* outcome (50th percentile).  
    - The shaded bands show the spread of outcomes (e.g., 10th–90th percentiles).  
    - A wider fan means more uncertainty over time.  
    - If the lower bands approach zero, it indicates a higher risk of portfolio depletion.

    **Why it matters:**  
    This chart helps you understand *risk and uncertainty*, not just average outcomes.
    """)

    # ---------- Chart 2A ----------
    #st.write("### Interactive Chart 2 — Subsidized ACA")
    #fig_int_a = interactive_chart2(df_med_a)
    #st.plotly_chart(fig_int_a, use_container_width=True)

    st.write("### Chart 2A — Median Path (Subsidized ACA)")
    fig2a = chart2_median(df_med_a, subtitle="Subsidized ACA")
    st.pyplot(fig2a)

    # ---------- Chart 2B ----------
    st.write("### Chart 2B — Median Path (No ACA Subsidy)")
    fig2b = chart2_median(df_med_b, subtitle="No ACA Subsidy")
    st.pyplot(fig2b)
    #st.write("### Interactive Chart 2 — No ACA Subsidy")
    #fig_int_b = interactive_chart2(df_med_b)
    #st.plotly_chart(fig_int_b, use_container_width=True)

    st.markdown("""
    **What this shows:**  
    This dashboard displays the *median (typical)* retirement path, breaking down your portfolio and spending over time.

    **How to read it:**  
    - The stacked areas show how your assets are allocated (Cash, Taxable, IRA, Roth).  
    - The dashed line represents annual spending (inflation-adjusted).  
    - You can toggle components on/off using the legend to isolate specific behaviors.  
    - Hover over any age to see exact values.

    **What to look for:**  
    - When and how quickly IRA assets are drawn down  
    - Growth of Roth assets (often driven by conversions)  
    - Periods where expenses exceed portfolio growth  
    - Tax and healthcare spikes (if enabled)

    **Why it matters:**  
    This chart explains *why* your portfolio succeeds or fails—it reveals the mechanics behind the simulation.
    """)
    # ---------- Chart 3 ----------
    st.write("### Chart 3 — Percentile Scenarios")
    fig3 = chart3_paths(df_a)
    st.pyplot(fig3)

    st.markdown("""
    **What this shows:**  
    This chart highlights specific percentile scenarios (e.g., pessimistic, median, optimistic outcomes).

    **How to read it:**  
    - Each line represents a different percentile path (e.g., 10th, 50th, 90th).  
    - The spread between lines shows variability in outcomes.  
    - The lower percentile lines represent downside risk scenarios.

    **Why it matters:**  
    It provides concrete examples of “bad”, “typical”, and “good” outcomes instead of just statistical bands.
    """)
    # ---------- Chart 4 ----------
    st.write("### Chart 4 — Scenario Comparison")
    fig4 = chart4_comparison(
        df_a, df_b,
        summary_a, summary_b,
        "Subsidized ACA",
        "No ACA Subsidy"
    )
    st.pyplot(fig4)

    st.markdown("""
    **What this shows:**  
    This chart compares two strategies: with ACA subsidies vs without subsidies.

    **How to read it:**  
    - Each line represents the median portfolio outcome under a different scenario.  
    - The gap between lines shows the financial impact of ACA subsidies over time.  
    - Divergence later in retirement reflects compounding effects.

    **What to look for:**  
    - How early differences grow over time  
    - Whether one strategy consistently dominates  
    - Sensitivity to tax and income decisions

    **Why it matters:**  
    This helps quantify the *real dollar impact* of healthcare and tax strategy decisions.
    """)

    # ---------- Chart 5 ----------
    st.write("### Chart 5 — Grid Map")
    fig5 = chart5_grid(
		df_b
    )
    st.pyplot(fig5)

    st.markdown("""
    **What this shows:**  
    This chart compares two strategies: with ACA subsidies vs without subsidies.

    **How to read it:**  
    - Each line represents the median portfolio outcome under a different scenario.  
    - The gap between lines shows the financial impact of ACA subsidies over time.  
    - Divergence later in retirement reflects compounding effects.

    **What to look for:**  
    - How early differences grow over time  
    - Whether one strategy consistently dominates  
    - Sensitivity to tax and income decisions

    **Why it matters:**  
    This helps quantify the *real dollar impact* of healthcare and tax strategy decisions.
    """)
	
    # =====================================================
    # DOWNLOAD DATA
    # =====================================================
    st.subheader("📥 Download Results")

    csv = df_a.to_csv(index=False)
    st.download_button(
        label="Download Scenario A CSV",
        data=csv,
        file_name="scenario_a.csv",
        mime="text/csv",
    )

    csv_b = df_b.to_csv(index=False)
    st.download_button(
        label="Download Scenario B CSV",
        data=csv_b,
        file_name="scenario_b.csv",
        mime="text/csv",
    )

# =========================================================
# OPTIMAL SS BUTTON
# =========================================================

if st.button("Find Optimal SS Age"):
    best_age = None
    best_value = 0
    sim.SS_START_AGE = SS_START_AGE

    for ss_age in range(62, 71):
        sim.SS_START_AGE = ss_age
        df = run_simulation()
        final = df.groupby("Age")["Portfolio"].median().iloc[-1]

        if final > best_value:
            best_value = final
            best_age = ss_age

    st.write(f"Optimal SS Age: {best_age}")
    
