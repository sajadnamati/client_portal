import pandas as pd
import json
from datetime import datetime
import numpy as np
from dateutil import parser
from scipy.optimize import newton
import os
from datetime import datetime
import math
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# --- XIRR function ---
def xirr(cashflows, dates):
    """Compute annualized IRR for irregular cashflows"""
    if len(cashflows) != len(dates):
        raise ValueError("Cashflows and dates must be same length")
    
    days = [(d - dates[0]).days for d in dates]

    def npv(rate):
        return sum(cf / (1 + rate) ** (t/365) for cf, t in zip(cashflows, days))

    return newton(npv, 0.1)  # start guess 10%


# --- Main function ---
def performance_metrics(email, json_file="investors.json"):
    # Load investor parameters
    json_path = os.path.join(BASE_DIR, "static", "investors.json")
    with open(json_path, "r", encoding="utf-8") as f:
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

    # Load CSV (resolve inside static/)
    #csv_path = os.path.join(BASE_DIR, "static", inv["performance_file"])
    #if not os.path.exists(csv_path):
    #    raise FileNotFoundError(f"CSV not found: {csv_path}")

    #df = pd.read_csv(csv_path, skip_blank_lines=True)
    
    
    df = _load_csv(inv)
    
    
    
    
    df = df.dropna(how="all")
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
        today_row = df[df["Date"] == sys_today].iloc[0]

        # 🔧 If today's asset value is missing/non-numeric, fall back to latest valid before today
        if not pd.notna(today_row["Historical Asset Value"]):
            df_actual = df[(df["Date"] < sys_today) & df["Historical Asset Value"].notna()]
            if df_actual.empty:
                raise ValueError("No valid asset values available up to system today")
            today_row = df_actual.iloc[-1]

    else:
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
                R = (1 + Ret_today) / (1 + RetA) - 1
            except Exception as e:
                print(f"⚠️ Ret calc error at row {i}: RetA={RetA}, Err={e}")
                R = float("nan")

            # T = today - contribution_date
            T = (today - dateA).days
            MgFee = ((1 + Mg) ** (T / 365) - 1) * contrib
            yearH = (1 + H) ** (T / 365) - 1

            if R > yearH:
                PerfFee = (R - max(yearH, (1 - Pf) * R)) * contrib
            else:
                PerfFee = 0

            mgmt_fees.append(MgFee)
            perf_fees.append(PerfFee)
            cashflows.append(-contrib)
            dates.append(dateA)

            print(f"\nRow {i}: Date={dateA.date()}, Contrib={contrib}, RetA={RetA}, "
                  f"R={R:.4f}, T={T}, MgFee={MgFee:.2f}, PerfFee={PerfFee:.2f}, yearH={yearH:.2f}")

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
    print("Ret_today:", Ret_today)
    print("Ret_future:", Ret_future)
    if T_locked > 0:
        gross_ann = (1 + locked_in) ** (365 / T_locked) - 1
        hurdle_ann = H   # already annual rate from JSON
        if gross_ann > hurdle_ann:
            investor_share = max(hurdle_ann, (1 - Pf) * gross_ann)
        else:
            investor_share = gross_ann
        locked_in_return = investor_share - Mg
    else:
        locked_in_return = None
        print("DEBUG locked_in_after_fee:", date_future)

    print(f"\nYTD return={ytd_return}, Locked-in return={locked_in_return}")

    # --- Build cashflow_chart dict ---
    cf_contributions = []
    for d, cf in zip(dates[:-1], cashflows[:-1]):  # contributions only
        try:
            val = float(cf)
        except (TypeError, ValueError):
            val = 0.0
        cf_contributions.append({
            "date": d.strftime("%Y-%m-%d"),
            "value": val   # ✅ match JS field name
        })

    cashflow_chart = {
        "valuation_date": today.strftime("%Y-%m-%d"),
        "xirr": irr_value,
        "contributions": cf_contributions,
        "terminal": {
            "investor_share": portfolio_value_nav,
            "perf_fee": total_perf,
            "mgmt_fee": total_mgmt,
        }
    }
    total_fees = total_mgmt + total_perf

    return {
        "portfolio_value_nav": portfolio_value_nav,
        "management_fees_total": total_mgmt,
        "performance_fees_total": total_perf,
        "total_fees": total_fees, 
        "irr": irr_value,
        "ytd_return": ytd_return,
        "locked_in_return": locked_in_return,
        "locked_in_after_fee": locked_in_return,        # alias for projection API

        "cashflow_chart": cashflow_chart
    }

def _to_num(s):
    """Coerce to float, accepting % and localized commas. Returns NaN on failure."""
    if pd.isna(s):
        return float('nan')
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace('\u00A0', '')  # nbsp
    is_pct = s.endswith('%')
    s = s.replace('%', '').replace(',', '')
    try:
        v = float(s)
    except Exception:
        return float('nan')
    return v/100.0 if is_pct else v

def _rebase(series):
    """Rebase (1+R_t)/(1+R_0)-1 with the first valid as base."""
    s = pd.to_numeric(series, errors='coerce')
    # find first valid base
    base_idx = s.first_valid_index()
    if base_idx is None:
        return s * float('nan')
    base = s.loc[base_idx]
    return ((1.0 + s) / (1.0 + base)) - 1.0


def _sanitize_list(arr):
    """Ensure all values are JSON-safe (no NaN/Inf)."""
    cleaned = []
    for x in arr:
        if x is None:
            cleaned.append(None)
        elif isinstance(x, (float, np.floating)):
            if math.isnan(x) or math.isinf(x):
                cleaned.append(None)
            else:
                cleaned.append(float(x))
        elif isinstance(x, (int, np.integer)):
            cleaned.append(int(x))
        else:
            cleaned.append(x)
    return cleaned










def compute_rebased_indices(
    csv_path: str,
    start_date: str,
    end_date: str,
    fixed: float = 0.02,          # e.g., 2% per year
    hurdle: float = 0.50,         # e.g., 50% per year
    perf_fee: float = 0.25        # e.g., 25% of profit
):
    """
    Read CSV and return rebased indices for columns 1..4 plus a 5th 'after-fee'
    series computed off column 1 using the provided fee rules.
    """
    # Load & parse
    df = pd.read_csv(csv_path)
    # Dates
    try:
        df['Date'] = pd.to_datetime(df['Date'], format='%d-%b-%y', errors='coerce')
    except Exception:
        df['Date'] = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce')
    df = df.dropna(subset=['Date']).sort_values('Date').reset_index(drop=True)

    # Coerce numeric returns for cols 1..4
    for col_idx in [1, 2, 3, 4]:
        col = df.columns[col_idx]
        df[col] = df[col].map(_to_num)

    # Window
    s_dt = pd.to_datetime(start_date)
    e_dt = pd.to_datetime(end_date)
    win = df[(df['Date'] >= s_dt) & (df['Date'] <= e_dt)].copy()
    if win.empty:
        return {"dates": [], "series_names": [], "series": {}}

    col1, col2, col3, col4 = df.columns[1:5]
    names = ["Fund (Before Fee)", "Bourse Index", "Gold Index", "Dollar Index"]
    rename_map = {col1: names[0], col2: names[1], col3: names[2], col4: names[3]}
    win = win.rename(columns=rename_map)
    order = ["Fund (Before Fee)", "Bourse Index", "Gold Index", "Dollar Index", "Fund (After Fee)"]

    # Rebase the 4 indices
    series = {}
    for nm in names:
        series[nm] = _sanitize_list(_rebase(win[nm]).tolist())

    # After-fee series from column-1 (rebased fund)
    rebased_fund = pd.Series(series[names[0]], index=win.index, dtype=float)

    # For fee accruals we need T since start (in days) per row:
    T_days = (win['Date'] - win['Date'].iloc[0]).dt.days.astype(float)
    m_T = (1.0 + fixed) ** (T_days / 365.0) - 1.0          # fixed component
    h_T = (1.0 + hurdle) ** (T_days / 365.0) - 1.0         # time-scaled hurdle

    # Performance component rule
    # Investor share rule: max(hurdle, (1 - perf_fee) * Ret) if Ret > hurdle
    Ret = rebased_fund
    investor_share = pd.Series(Ret, index=win.index)
    mask = (Ret > h_T)
    investor_share[mask] = pd.concat([
        h_T[mask],
        (1.0 - perf_fee) * Ret[mask]
    ], axis=1).max(axis=1)

    after_fee = (investor_share - m_T).tolist()

    series["Fund (After Fee)"] = _sanitize_list(after_fee)
    series_matrix = [series[k] for k in order]

    return {
        "dates": win['Date'].dt.strftime('%Y-%m-%d').tolist(),
        "series_names": order,                # ← labels and
        "series": series,                     # (kept for backwards-compat)
        "series_matrix": series_matrix        # ← data are built from same list
    }

 
def compute_lockedin_projection(current_nav: float,
                                locked_in_after_fee: float,
                                years: float = 3):
    """
    Simple projection using already-computed locked-in after-fee return (annualized).
    """
    
    today = datetime.today().date()
    months = int(round(years * 12))
    monthly_rate = (1 + locked_in_after_fee) ** (1/12) - 1

    dates = [today + relativedelta(months=m) for m in range(months+1)]
    values = [current_nav * ((1 + monthly_rate) ** m) for m in range(months+1)]

    return {
        "dates": [d.isoformat() for d in dates],
        "series": {
            "Projection (After Fee)": _sanitize_list(values)
        },
        "locked_in_after_fee": locked_in_after_fee
    }


 
def compute_lockedin_projection(current_nav: float,
                                locked_in_after_fee: float,
                                years: float = 3):
    """
    Simple projection using already-computed locked-in after-fee return (annualized).
    """
    
    today = datetime.today().date()
    months = int(round(years * 12))
    monthly_rate = (1 + locked_in_after_fee) ** (1/12) - 1

    dates = [today + relativedelta(months=m) for m in range(months+1)]
    values = [current_nav * ((1 + monthly_rate) ** m) for m in range(months+1)]

    return {
        "dates": [d.isoformat() for d in dates],
        "series": {
            "Projection (After Fee)": _sanitize_list(values)
        },
        "locked_in_after_fee": locked_in_after_fee
    }


def compensation_chart_data(hurdle_rate=0.05, mgmt_fee=0.02, perf_fee=0.2, step=0.01):
    """
    Generate investor share and fund fee series for returns from 0 to 150%.
    
    Parameters
    ----------
    hurdle_rate : float
        Minimum return threshold (e.g., 0.05 for 5%)
    mgmt_fee : float
        Fixed management fee (e.g., 0.02 for 2%)
    perf_fee : float
        Performance fee fraction (e.g., 0.2 for 20%)
    step : float
        Step size for return increments (default = 0.01)
    
    Returns
    -------
    DataFrame with columns: Ret, Investor, Fund
    """
    # Return range from 0 to 150%
    Ret = np.arange(0, 1.51 + step, step)

    investor = []
    fund = []

    for r in Ret:
        if r > hurdle_rate:
            investor_share = max(hurdle_rate, (1 - perf_fee) * r) - mgmt_fee
            fund_fee = mgmt_fee + (r - max(hurdle_rate, (1 - perf_fee) * r))
        else:
            investor_share = r - mgmt_fee
            fund_fee = mgmt_fee
        # Clamp at 0 if investor share goes negative
        investor.append(max(investor_share, 0))
        fund.append(max(fund_fee, 0))

    return pd.DataFrame({
        "Ret": Ret,
        "Investor": investor,
        "Fund": fund
    })



def performance_metric_public(csv_path: str):
    """
    Compute public fund performance metrics:
      - YTD Fund Return (before fees)
      - Locked-in return (projection from current to last available forward date)

    Returns:
        dict with {"ytd_return": float, "locked_in_return": float}
    """

    df = pd.read_csv(csv_path)
    # Normalize date column
    if "Date" not in df.columns:
        raise ValueError("CSV must contain a 'Date' column")
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date")

    if "Fund" not in df.columns:
        raise ValueError("CSV must contain a 'Fund' column with cumulative returns")

    today = pd.Timestamp(datetime.today().date())

    # Split history vs projections
    df_hist = df[df["Date"] <= today]
    df_fut  = df[df["Date"] > today]

    if df_hist.empty:
        return {"ytd_return": None, "locked_in_return": None}

    # Current point (last available before today)
    ret_current = df_hist["Fund"].iloc[-1]
    date_begin  = df_hist["Date"].iloc[0]

    # --- YTD Return ---
    T_hist = (today - date_begin).days
    ytd_return = ((1 + ret_current) / (1 + df_hist["Fund"].iloc[0]))**(365 / T_hist) - 1 if T_hist > 0 else None

    # --- Locked-in return ---
    if not df_fut.empty:
        ret_future = df_fut["Fund"].iloc[-1]
        date_future = df_fut["Date"].iloc[-1]
        T_future = (date_future - today).days
        locked_in = ((1 + ret_future) / (1 + ret_current))**(365 / T_future) - 1 if T_future > 0 else None
    else:
        locked_in = None

    return {
        "ytd_return": ytd_return,
        "locked_in_return": locked_in
    }


def _load_csv(inv):
    """Return a DataFrame from either a Google Sheets link or a local CSV file."""
    if "link" in inv and inv["link"]:
        print(f"🌐 Loading from Google Sheets: {inv['link']}")
        df = pd.read_csv(inv["link"], skip_blank_lines=True)
    else:
        csv_path = os.path.join(BASE_DIR, "static", inv["performance_file"])
        print(f"📂 Loading local CSV: {csv_path}")
        df = pd.read_csv(csv_path, skip_blank_lines=True)
    return df