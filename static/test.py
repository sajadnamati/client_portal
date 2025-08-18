import pandas as pd
import json
from datetime import datetime
import numpy as np
from dateutil import parser

from scipy.optimize import newton




# --- XIRR function ---
def xirr(cashflows, dates):
    """Compute annualized IRR for irregular cashflows"""
    if len(cashflows) != len(dates):
        raise ValueError("Cashflows and dates must be same length")
    
    days = [(d - dates[0]).days for d in dates]

    def npv(rate):
        return sum(cf / (1 + rate) ** (t/365) for cf, t in zip(cashflows, days))

    return newton(npv, 0.1)  # start guess 10%

import pandas as pd
import json
from datetime import datetime
from scipy.optimize import newton

# --- XIRR function ---
def xirr(cashflows, dates):
    """Compute annualized IRR for irregular cashflows"""
    if len(cashflows) != len(dates):
        raise ValueError("Cashflows and dates must be same length")
    
    days = [(d - dates[0]).days for d in dates]

    def npv(rate):
        return sum(cf / (1 + rate) ** (t/365) for cf, t in zip(cashflows, days))

    return newton(npv, 0.1)  # initial guess 10%

# --- Main function ---
def performance_metrics(email, json_file):
    # Load investor parameters
    with open(json_file, "r") as f:
        config = json.load(f)
    if email not in config:
        raise ValueError(f"Investor {email} not found in JSON config")

    inv = config[email]
    fees = inv.get("fees", {})
    H = fees.get("hurdle_rate", 0.5)
    Mg = fees.get("management_fee", 0.02)
    Pf = fees.get("performance_fee", 0.25)

    print(f"\n--- Investor {email} ---")
    print(f"Using file: {inv['performance_file']}")
    print(f"Hurdle={H}, MgmtFee={Mg}, PerfFee={Pf}")

    # Load CSV
    df = pd.read_csv(inv["performance_file"])
    print("\nCSV columns:", df.columns.tolist())
    print("First 5 rows:\n", df.head())

    # Parse dates safely
    try:
        df["Date"] = pd.to_datetime(df["Date"], format="%d-%b-%y")
    except Exception as e:
        print("⚠️ Date parsing failed, falling back to auto-parse:", e)
        df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)

    # --- Handle actual today vs available data ---
    sys_today = pd.to_datetime(datetime.now().date())

    if sys_today in df["Date"].values:
        # if today exactly in CSV
        today_row = df[df["Date"] == sys_today].iloc[0]
    else:
        # else use the latest available date <= today
        df_actual = df[df["Date"] <= sys_today]
        if df_actual.empty:
            raise ValueError("No actual data available up to system today")
        today_row = df_actual.iloc[-1]

    today = today_row["Date"]
    Ret_today = today_row["Ret"]
    Asset_today = today_row["Historical Asset Value"]

    print(f"\nSystem today={sys_today.date()}, Using CSV today={today.date()}, Ret_today={Ret_today}, Asset_today={Asset_today}")

    # --- Last row (projection) ---
    last_row = df.iloc[-1]
    Ret_future  = last_row["Ret"]
    date_future = last_row["Date"]
    print(f"Last row in CSV: {date_future.date()}, Ret_future={Ret_future}")

    mgmt_fees, perf_fees, cashflows, dates = [], [], [], []

    # --- Loop over contributions (only actual rows, up to CSV 'today') ---
    df_until_today = df[df["Date"] <= today]
    for i, row in df_until_today.iterrows():
        contrib = row["Contribution"]
        if contrib != 0:
            dateA = row["Date"]
            RetA = row["Ret"]

            try:
                R = (1 + Ret_today) / (1 + RetA)-1
            except Exception as e:
                print(f"⚠️ Ret calc error at row {i}: RetA={RetA}, Err={e}")
                R = float("nan")

            # T = today - contribution_date (both from CSV)
            T = (today - dateA).days
            MgFee = ((1 + Mg) ** (T / 365) - 1) * contrib
            yearH=(1+H)**(T/365)-1
            if R > yearH:
                PerfFee = (R-max(yearH, (1-Pf) * R)) * contrib
            else:
                PerfFee = 0

            mgmt_fees.append(MgFee)
            perf_fees.append(PerfFee)
            cashflows.append(-contrib)
            dates.append(dateA)

            print(f"\nRow {i}: Date={dateA.date()}, Contrib={contrib}, RetA={RetA}, "
                  f"R={R:.4f}, T={T}, MgFee={MgFee:.2f}, PerfFee={PerfFee:.2f},yearH={yearH:.2f}")

    total_mgmt = sum(mgmt_fees)
    total_perf = sum(perf_fees)
    total_fees = total_mgmt + total_perf
    portfolio_value_nav = Asset_today - total_fees

    print(f"\nTotal MgmtFee={total_mgmt:.2f}, Total PerfFee={total_perf:.2f}, NAV={portfolio_value_nav:.2f}")

    # --- Cashflows for IRR ---
    cashflows.append(portfolio_value_nav)
    dates.append(today)

    print("\nCashflows + Dates for IRR:")
    for d, cf in zip(dates, cashflows):
        print(f"{d.date()} : {cf}")

    # --- Compute IRR ---
    try:
        irr_value = xirr(cashflows, dates)
    except Exception as e:
        print("⚠️ XIRR failed:", e)
        irr_value = None

    # --- YTD return (before fees, annualized) ---
    first_date = df_until_today["Date"].iloc[0]
    T_total = (today - first_date).days
    Ret_cum = (1 + Ret_today) / (1 + df_until_today["Ret"].iloc[0]) - 1
    ytd_return = (1 + Ret_cum) ** (365 / T_total) - 1 if T_total > 0 else None

    # --- Locked-in return (today → last CSV date) ---
    T_locked = (date_future - today).days
    locked_in = ((1 + Ret_future) / (1 + Ret_today)) - 1
    locked_in_return = (1 + locked_in) ** (365 / T_locked) - 1 if T_locked > 0 else None

    print(f"\nYTD return={ytd_return}, Locked-in return={locked_in_return}")

    return {
        "portfolio_value_nav": portfolio_value_nav,
        "management_fees_total": total_mgmt,
        "performance_fees_total": total_perf,
        "irr": irr_value,
        "ytd_return": ytd_return,
        "locked_in_return": locked_in_return
    }

result = performance_metrics("investor@example.com", "investors.json")

print(result)








