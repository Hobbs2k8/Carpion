"""
Portfolio Volatility & Portfolio Builder Analyzer

This desktop tool preserves the original CSV-driven portfolio analyzer and adds
a portfolio builder workflow that can:

1. Parse model portfolio templates from the model workbook.
2. Parse historical return series and benchmark data from the VaR workbook.
3. Match funds across both sources with tolerant alias handling.
4. Recommend an allocation for a target risk level under user constraints.
5. Run editable macro stress tests and export client-ready reports.

The portfolio builder intentionally keeps the risk model transparent:
- historical covariance / volatility come from historical monthly return series
- expected returns come from either historical annualized return or user input
- stress tests apply editable shock assumptions by fund or style bucket
"""

from __future__ import annotations

import csv
import json
import os
import re
from math import sqrt
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
import pandas as pd

try:
    import matplotlib

    matplotlib.use("TkAgg")
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure

    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

try:
    from scipy.optimize import minimize

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


APP_DIR = Path(__file__).resolve().parent
SCENARIO_PRESETS_FILE = APP_DIR / "portfolio_builder_scenarios.json"
ANN_FACTOR_DEFAULT = 12
OPTIMIZER_SINGLE_ASSET_CAP = 0.5

MODE_MANUAL = "Manual"
MODE_MIN_VOL = "Min Volatility"
MODE_BEST_GAIN_VOL = "Best Gain / Volatility"
MODE_MAX_RET_TARGET_RISK = "Max Return at Target Risk"

BUILDER_OBJECTIVE_MATCH_RISK = "Match Target Risk"
BUILDER_OBJECTIVE_MAX_RETURN_UNDER_RISK = "Maximize Expected Return Under Target Risk"
BUILDER_OBJECTIVE_MIN_VOL = "Minimize Volatility Using Selected Universe"
BUILDER_OBJECTIVE_BLEND = "Blend Model Portfolio With Optimized Allocation"
BUILDER_OBJECTIVE_STRESS_ONLY = "Stress Test Only"

RETURN_BASIS_HISTORICAL = "Historical Annualized Returns"
RETURN_BASIS_USER = "User Expected Returns"

RISK_PROFILE_TO_MODEL = {
    "Conservative": "Cons",
    "Moderate": "MA",
    "Growth": "Agg",
    "Aggressive": "Agg",
}

FALLBACK_PROFILE_VOLS = {
    "Cons": 0.08,
    "MA": 0.10,
    "Agg": 0.12,
    "Aggressive": 0.14,
}

BUILDER_STEPS = [
    "Load Data",
    "Choose Risk Profile",
    "Review / Edit Fund Setup",
    "Build Allocation",
    "Stress Test & Export",
]

BENCHMARK_AUTO = "Auto"
BENCHMARK_NONE = "None"


FUND_ALIAS_MAP = {
    "putman": "Putnam Large Cap Value",
    "putnamlargecapvalue": "Putnam Large Cap Value",
    "davis": "Davis All Cap",
    "davisallcap": "Davis All Cap",
    "clrbrd": "Clearbridge",
    "clearbridge": "Clearbridge",
    "jpmg": "J.P. Morgan Large Cap Growth",
    "jpmorganlargecapgrowth": "J.P. Morgan Large Cap Growth",
    "jpmlargecapgrowth": "J.P. Morgan Large Cap Growth",
    "qqq": "QQQ",
    "zacks": "QQQ",
    "eic": "EIC Mid Cap",
    "eicmidcap": "EIC Mid Cap",
    "reinhart": "Reinhart",
    "airr": "AIRR",
    "capgrint": "Capital Group International",
    "capitalgroupinternational": "Capital Group International",
    "bandesint": "Brandes International",
    "brandesinternational": "Brandes International",
    "brdintsc": "Brandes International Small Cap",
    "branintsc": "Brandes International Small Cap",
    "dxj": "MSCI Japan (EWJ) yen unhedged",
    "ewj": "MSCI Japan (EWJ) yen unhedged",
    "scj": "MSCI Japan (EWJ) yen unhedged",
    "clse": "Convergence Long/Short (CLSE)",
    "convergencelongshortclse": "Convergence Long/Short (CLSE)",
    "bxpe": "Blackstone PE (BXPE)",
    "blackstonepebxpe": "Blackstone PE (BXPE)",
    "spring": "Stepstone VC (SPRING)",
    "stepstonevcspring": "Stepstone VC (SPRING)",
    "ares": "Ares",
    "bowriv": "BowRiver",
    "flex": "FT Lexington (FLEX)",
    "ftlexingtonflex": "FT Lexington (FLEX)",
    "sp500": "SP 500",
    "sp600": "SP 600",
    "spx": "SP 500",
}


FUND_METADATA = {
    "Putnam Large Cap Value": {
        "style": "US Large Cap Value",
        "market_cap": "Large Cap",
        "benchmark": "SP 500",
        "stress_bucket": "Large Cap Value",
        "notes": "Value-oriented large-cap US equity strategy.",
    },
    "Davis All Cap": {
        "style": "US All Cap",
        "market_cap": "All Cap",
        "benchmark": "SP 500",
        "stress_bucket": "Large Cap Value",
        "notes": "Concentrated all-cap US equity strategy.",
    },
    "Clearbridge": {
        "style": "US Large Cap Value",
        "market_cap": "Large Cap",
        "benchmark": "SP 500",
        "stress_bucket": "Large Cap Value",
        "notes": "Large-cap value exposure.",
    },
    "J.P. Morgan Large Cap Growth": {
        "style": "US Large Cap Growth",
        "market_cap": "Large Cap",
        "benchmark": "SP 500",
        "stress_bucket": "Large Cap Growth",
        "notes": "US growth equity exposure.",
    },
    "QQQ": {
        "style": "US Mega Cap Growth",
        "market_cap": "Large Cap",
        "benchmark": "SP 500",
        "stress_bucket": "Tech Growth",
        "notes": "Nasdaq-oriented growth / tech concentration.",
    },
    "EIC Mid Cap": {
        "style": "US Mid Cap",
        "market_cap": "Mid Cap",
        "benchmark": "SP 600",
        "stress_bucket": "Small/Mid Cap",
        "notes": "Mid-cap growth / core equity exposure.",
    },
    "Reinhart": {
        "style": "US Small/Mid Cap",
        "market_cap": "Small/Mid Cap",
        "benchmark": "SP 600",
        "stress_bucket": "Small/Mid Cap",
        "notes": "Small and mid-cap equity exposure.",
    },
    "AIRR": {
        "style": "Real Assets / Industrials",
        "market_cap": "Mid Cap",
        "benchmark": "SP 600",
        "stress_bucket": "Industrials / Real Assets",
        "notes": "Industrials / infrastructure-leaning sleeve.",
    },
    "Brandes International": {
        "style": "International Value",
        "market_cap": "International",
        "benchmark": "MSCI ACWI ex US",
        "stress_bucket": "International Equity",
        "notes": "Non-US value equity strategy.",
    },
    "Capital Group International": {
        "style": "International Core",
        "market_cap": "International",
        "benchmark": "MSCI ACWI ex US",
        "stress_bucket": "International Equity",
        "notes": "International core / growth blend.",
    },
    "MSCI Japan (EWJ) yen unhedged": {
        "style": "Japan Equity",
        "market_cap": "International",
        "benchmark": "EWJ",
        "stress_bucket": "Japan Equity",
        "notes": "Japan equity sleeve.",
    },
    "Convergence Long/Short (CLSE)": {
        "style": "Long/Short Equity",
        "market_cap": "Alternatives",
        "benchmark": "SP 500",
        "stress_bucket": "Long/Short",
        "notes": "Hedged equity / long-short sleeve.",
    },
    "Blackstone PE (BXPE)": {
        "style": "Private Equity",
        "market_cap": "Alternatives",
        "benchmark": "SP 500",
        "stress_bucket": "Private Equity",
        "notes": "Private equity sleeve.",
    },
    "FT Lexington (FLEX)": {
        "style": "Private Equity Secondaries",
        "market_cap": "Alternatives",
        "benchmark": "SP 500",
        "stress_bucket": "Private Equity",
        "notes": "Private markets / secondary exposure.",
    },
    "Stepstone VC (SPRING)": {
        "style": "Venture Capital",
        "market_cap": "Alternatives",
        "benchmark": "SP 500",
        "stress_bucket": "Venture Capital",
        "notes": "Venture capital sleeve.",
    },
    "Ares": {
        "style": "Private Credit",
        "market_cap": "Alternatives",
        "benchmark": "I:10YTR",
        "stress_bucket": "Private Credit",
        "notes": "Private credit / direct lending proxy.",
    },
}


def normalize_identifier(value):
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = text.replace("&", " and ")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def canonicalize_fund_name(value):
    text = str(value).strip()
    key = normalize_identifier(text)
    if key in FUND_ALIAS_MAP:
        return FUND_ALIAS_MAP[key]
    return text.rstrip(":").strip()


def is_numeric(value):
    return isinstance(value, (int, float, np.integer, np.floating)) and not pd.isna(value)


def is_benchmark_name(name):
    key = normalize_identifier(name)
    return key in {"sp500", "sp600", "spx", "sandp500", "sandp600"}


def infer_stress_bucket(fund_name, category="", source_sheet=""):
    meta = FUND_METADATA.get(fund_name, {})
    if meta.get("stress_bucket"):
        return meta["stress_bucket"]
    cat = f"{category} {source_sheet} {fund_name}".lower()
    if "growth" in cat or "qqq" in cat or "tech" in cat:
        return "Tech Growth"
    if "value" in cat:
        return "Large Cap Value"
    if "mid" in cat or "small" in cat:
        return "Small/Mid Cap"
    if "international" in cat:
        return "International Equity"
    if "japan" in cat or "ewj" in cat or "dxj" in cat:
        return "Japan Equity"
    if "long/short" in cat or "clse" in cat:
        return "Long/Short"
    if "private credit" in cat or "ares" in cat:
        return "Private Credit"
    if "venture" in cat or "spring" in cat:
        return "Venture Capital"
    if "private" in cat or "pe" in cat or "bxpe" in cat or "lexington" in cat:
        return "Private Equity"
    if "treasury" in cat or "bond" in cat:
        return "Treasury"
    return "US Equity"


def scenario_defaults():
    scenarios = {
        "Inflationary Environment": {
            "Large Cap Value": (-0.04, 1.10, 1.05, "Value holds up better than duration-sensitive growth."),
            "Large Cap Growth": (-0.09, 1.20, 1.10, "Growth multiples compress."),
            "Tech Growth": (-0.12, 1.25, 1.15, "Long-duration tech reprices lower."),
            "Small/Mid Cap": (-0.08, 1.20, 1.10, "Smaller companies face tighter financing."),
            "International Equity": (-0.06, 1.10, 1.05, "Broad non-US equity drawdown."),
            "Private Equity": (-0.08, 1.10, 1.05, "Private marks soften with valuation lag."),
            "Private Credit": (-0.04, 1.10, 1.05, "Spreads widen modestly."),
            "Treasury": (-0.05, 1.20, 1.10, "Rates up / bond prices down."),
        },
        "Rising Rates": {
            "Large Cap Value": (-0.03, 1.05, 1.00, "Value mildly pressured."),
            "Large Cap Growth": (-0.08, 1.15, 1.10, "Growth de-rates."),
            "Tech Growth": (-0.11, 1.20, 1.15, "Tech valuation reset."),
            "Private Equity": (-0.07, 1.10, 1.05, "Private valuation multiples compress."),
            "Private Credit": (-0.03, 1.05, 1.05, "Credit spreads and financing costs rise."),
            "Treasury": (-0.06, 1.25, 1.10, "Rates shock."),
        },
        "Recession": {
            "US Equity": (-0.12, 1.20, 1.15, "Broad US equity selloff."),
            "Large Cap Value": (-0.10, 1.15, 1.10, "Defensives help but still fall."),
            "Large Cap Growth": (-0.13, 1.20, 1.15, "Earnings pressure."),
            "Small/Mid Cap": (-0.16, 1.30, 1.20, "Cyclicals underperform."),
            "International Equity": (-0.11, 1.15, 1.10, "Global slowdown."),
            "Long/Short": (-0.05, 1.10, 1.05, "Lower beta cushion."),
            "Private Equity": (-0.12, 1.15, 1.10, "Lagged markdowns."),
            "Private Credit": (-0.07, 1.20, 1.15, "Default risk widens spreads."),
        },
        "Geopolitical Conflict": {
            "US Equity": (-0.08, 1.15, 1.10, "Risk-off environment."),
            "International Equity": (-0.10, 1.20, 1.15, "Cross-border risk premium increases."),
            "Japan Equity": (-0.09, 1.18, 1.12, "Regional uncertainty spills over."),
            "Private Equity": (-0.06, 1.10, 1.08, "Private marks drift lower."),
            "Private Credit": (-0.04, 1.08, 1.08, "Spread widening."),
        },
        "Equity Selloff": {
            "US Equity": (-0.15, 1.25, 1.20, "Broad equity drawdown."),
            "Large Cap Growth": (-0.17, 1.30, 1.25, "Growth beta leads losses."),
            "Large Cap Value": (-0.12, 1.20, 1.15, "Value falls less."),
            "Small/Mid Cap": (-0.18, 1.35, 1.25, "Higher beta / liquidity stress."),
            "International Equity": (-0.14, 1.20, 1.15, "Global correlation spike."),
            "Long/Short": (-0.07, 1.10, 1.05, "Hedges offset some losses."),
        },
        "Tech Drawdown": {
            "Tech Growth": (-0.20, 1.35, 1.25, "Tech-specific valuation unwind."),
            "Large Cap Growth": (-0.14, 1.25, 1.20, "Growth adjacency suffers."),
            "US Equity": (-0.07, 1.10, 1.05, "Index drag from mega-cap tech."),
            "Long/Short": (-0.04, 1.08, 1.05, "Hedged equity absorbs shock better."),
        },
        "Small-Cap Underperformance": {
            "Small/Mid Cap": (-0.12, 1.25, 1.20, "Small-cap risk-off regime."),
            "US Equity": (-0.04, 1.08, 1.04, "Broader risk drag."),
            "Large Cap Value": (-0.03, 1.05, 1.02, "Large caps outperform relatively."),
        },
        "Value vs Growth Rotation": {
            "Large Cap Value": (0.05, 1.05, 1.00, "Value leadership."),
            "Large Cap Growth": (-0.06, 1.10, 1.05, "Growth trails in rotation."),
            "Tech Growth": (-0.09, 1.15, 1.08, "Tech multiple compression."),
            "US Equity": (-0.01, 1.02, 1.00, "Market roughly flat overall."),
        },
    }

    rows = []
    for scenario_name, buckets in scenarios.items():
        for bucket, values in buckets.items():
            shock, vol_mult, corr_mult, notes = values
            rows.append(
                {
                    "scenario": scenario_name,
                    "target": bucket,
                    "shock_pct": shock * 100.0,
                    "vol_multiplier": vol_mult,
                    "corr_multiplier": corr_mult,
                    "notes": notes,
                }
            )
    return rows


def load_scenario_presets():
    if SCENARIO_PRESETS_FILE.exists():
        try:
            with open(SCENARIO_PRESETS_FILE, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass
    return scenario_defaults()


def save_scenario_presets(rows):
    with open(SCENARIO_PRESETS_FILE, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2)


def parse_ycharts_csv(filepath):
    with open(filepath, "r", newline="") as handle:
        reader = list(csv.reader(handle))

    header_idx = None
    for idx, row in enumerate(reader):
        if row and row[0].strip() == "Symbol":
            header_idx = idx
            break
    if header_idx is None:
        raise ValueError("Could not find a 'Symbol' header row in the CSV.")

    headers = reader[header_idx]
    date_cols = headers[3:]
    dates = pd.to_datetime(date_cols, format="mixed", errors="coerce")
    if dates.isna().any():
        raise ValueError("Some CSV date columns could not be parsed.")

    data = {}
    names = {}
    for row in reader[header_idx + 1 :]:
        if len(row) < 4 or not row[0].strip():
            continue
        symbol = row[0].strip()
        names[symbol] = row[1].strip()
        values = []
        for item in row[3:]:
            item = item.strip()
            if item in ("", "N/A"):
                values.append(np.nan)
            else:
                values.append(float(item))
        data[symbol] = pd.Series(values, index=dates, name=symbol)

    df = pd.DataFrame(data).sort_index().dropna(how="all")
    if df.empty:
        raise ValueError("CSV parsed successfully but contained no usable return data.")
    return df, names


def calc_expected_portfolio_return(weights, expected_returns):
    return float(np.array(weights, dtype=float) @ np.array(expected_returns, dtype=float))


def calc_portfolio_volatility(weights, cov_annual):
    weights = np.array(weights, dtype=float)
    variance = float(weights @ cov_annual.values @ weights)
    return float(sqrt(max(variance, 0.0)))


def calc_drawdown_series(monthly_returns):
    cumulative = (1.0 + monthly_returns).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max
    return cumulative, drawdown


def calc_max_drawdown(monthly_returns):
    _, drawdown = calc_drawdown_series(monthly_returns)
    return float(drawdown.min()) if len(drawdown) else 0.0


def calc_historical_metrics(returns_df, ann_factor=ANN_FACTOR_DEFAULT):
    clean = returns_df.dropna()
    if clean.empty:
        raise ValueError("Not enough overlapping data after removing missing values.")

    symbols = list(clean.columns)
    n_clean = len(clean)
    per_stock = {}

    for sym in symbols:
        monthly = clean[sym].dropna()
        cumulative = (1.0 + monthly).prod()
        ann_return = cumulative ** (ann_factor / len(monthly)) - 1.0 if len(monthly) else 0.0
        ann_vol = monthly.std(ddof=1) * sqrt(ann_factor) if len(monthly) > 1 else 0.0
        _, drawdown = calc_drawdown_series(monthly)
        max_dd = float(drawdown.min()) if len(drawdown) else 0.0
        per_stock[sym] = {
            "historical_ann_return": float(ann_return),
            "historical_volatility": float(ann_vol),
            "historical_total_return": float(cumulative - 1.0),
            "historical_max_drawdown": max_dd,
            "n_periods": len(monthly),
        }

    return {
        "clean_returns": clean,
        "per_stock": per_stock,
        "corr_matrix": clean.corr(),
        "cov_annual": clean.cov() * ann_factor,
        "n_periods": n_clean,
    }


def build_pairwise_risk_model(returns_df, ann_factor=ANN_FACTOR_DEFAULT, min_periods=6):
    if returns_df is None or returns_df.empty:
        raise ValueError("No return history is available for risk modeling.")

    clean = returns_df.sort_index().dropna(how="all")
    symbols = list(clean.columns)
    per_stock = {}
    monthly_vols = {}

    for sym in symbols:
        series = clean[sym].dropna()
        if len(series) == 0:
            ann_return = 0.0
            ann_vol = 0.0
            total_return = 0.0
            max_dd = 0.0
        else:
            cumulative = (1.0 + series).prod()
            ann_return = cumulative ** (ann_factor / len(series)) - 1.0 if len(series) else 0.0
            ann_vol = series.std(ddof=1) * sqrt(ann_factor) if len(series) > 1 else 0.0
            total_return = cumulative - 1.0
            max_dd = calc_max_drawdown(series)
        per_stock[sym] = {
            "historical_ann_return": float(ann_return),
            "historical_volatility": float(ann_vol),
            "historical_total_return": float(total_return),
            "historical_max_drawdown": float(max_dd),
            "n_periods": int(len(series)),
        }
        monthly_vols[sym] = float(series.std(ddof=1)) if len(series) > 1 else 0.0

    corr = clean.corr(min_periods=min_periods)
    corr = corr.reindex(index=symbols, columns=symbols)
    monthly_cov = clean.cov(min_periods=min_periods).reindex(index=symbols, columns=symbols)

    for i, si in enumerate(symbols):
        for j, sj in enumerate(symbols):
            if i == j:
                monthly_cov.loc[si, sj] = monthly_vols[si] ** 2
                corr.loc[si, sj] = 1.0
            else:
                if pd.isna(corr.loc[si, sj]):
                    corr.loc[si, sj] = 0.0
                if pd.isna(monthly_cov.loc[si, sj]):
                    monthly_cov.loc[si, sj] = corr.loc[si, sj] * monthly_vols[si] * monthly_vols[sj]

    cov_annual = monthly_cov * ann_factor
    return {
        "returns": clean,
        "per_stock": per_stock,
        "corr_matrix": corr.astype(float),
        "cov_annual": cov_annual.astype(float),
        "n_periods": int(clean.dropna(how="all").shape[0]),
    }


def calc_portfolio_historical_metrics(returns_df, weights, ann_factor=ANN_FACTOR_DEFAULT):
    weights = np.array(weights, dtype=float)
    active_cols = [col for idx, col in enumerate(returns_df.columns) if abs(weights[idx]) > 1e-12]
    working = returns_df[active_cols] if active_cols else returns_df.copy()
    clean = working.dropna()
    if clean.empty:
        clean = working.fillna(0.0)
    port_monthly = (clean * weights[[returns_df.columns.get_loc(col) for col in clean.columns]]).sum(axis=1)
    cumulative, drawdown = calc_drawdown_series(port_monthly)
    total_return = float(cumulative.iloc[-1] - 1.0) if len(cumulative) else 0.0
    n = len(port_monthly)
    ann_return = (1.0 + total_return) ** (ann_factor / n) - 1.0 if n > 0 else 0.0
    ann_vol = port_monthly.std(ddof=1) * sqrt(ann_factor) if n > 1 else 0.0
    return {
        "historical_ann_return": float(ann_return),
        "volatility": float(ann_vol),
        "historical_total_return": total_return,
        "historical_max_drawdown": float(drawdown.min()) if len(drawdown) else 0.0,
        "cumulative_series": cumulative,
        "drawdown_series": drawdown,
        "monthly_returns": port_monthly,
        "n_periods": n,
    }


def calc_forward_portfolio_metrics(weights, expected_returns, cov_annual):
    exp_ret = calc_expected_portfolio_return(weights, expected_returns)
    vol = calc_portfolio_volatility(weights, cov_annual)
    ratio = exp_ret / vol if vol > 0 else 0.0
    variance = float(np.array(weights, dtype=float) @ cov_annual.values @ np.array(weights, dtype=float))
    return {
        "expected_ann_return": exp_ret,
        "volatility": vol,
        "expected_return_over_volatility": ratio,
        "variance": variance,
    }


def calc_portfolio_var_95(volatility, ann_factor=ANN_FACTOR_DEFAULT):
    monthly_vol = volatility / sqrt(ann_factor) if ann_factor > 0 else volatility
    return 1.65 * monthly_vol


def build_variance_decomposition(symbols, weights, cov_annual):
    decomposition = {}
    weights = np.array(weights, dtype=float)
    for idx, sym in enumerate(symbols):
        decomposition[f"{sym} (w^2 * var)"] = float(weights[idx] ** 2 * cov_annual.iloc[idx, idx])
    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            decomposition[f"{symbols[i]}-{symbols[j]} (2*wi*wj*cov)"] = float(
                2.0 * weights[i] * weights[j] * cov_annual.iloc[i, j]
            )
    return decomposition


def calc_risk_contributions(symbols, weights, cov_annual):
    weights = np.array(weights, dtype=float)
    sigma_w = cov_annual.values @ weights
    portfolio_var = float(weights @ sigma_w)
    portfolio_vol = sqrt(max(portfolio_var, 0.0))
    rows = []
    for idx, sym in enumerate(symbols):
        marginal_risk = sigma_w[idx] / portfolio_vol if portfolio_vol > 0 else 0.0
        component_risk = weights[idx] * marginal_risk
        variance_contribution = weights[idx] * sigma_w[idx]
        pct_risk = component_risk / portfolio_vol if portfolio_vol > 0 else 0.0
        pct_var = variance_contribution / portfolio_var if portfolio_var > 0 else 0.0
        rows.append(
            {
                "symbol": sym,
                "weight": float(weights[idx]),
                "marginal_risk": float(marginal_risk),
                "component_risk": float(component_risk),
                "percent_risk": float(pct_risk),
                "variance_contribution": float(variance_contribution),
                "percent_variance": float(pct_var),
            }
        )
    return rows


def validate_bounds(min_weights, max_weights, current_weights=None, tol=1e-9):
    min_weights = np.array(min_weights, dtype=float)
    max_weights = np.array(max_weights, dtype=float)
    if len(min_weights) != len(max_weights):
        raise ValueError("Min/Max bounds length mismatch.")
    if np.any(min_weights < 0):
        raise ValueError("Minimum weights cannot be negative.")
    if np.any(max_weights < 0):
        raise ValueError("Maximum weights cannot be negative.")
    if np.any(min_weights > max_weights + tol):
        raise ValueError("Each asset must satisfy Min Weight <= Max Weight.")
    if min_weights.sum() > 1.0 + tol:
        raise ValueError("Sum of minimum weights cannot exceed 100%.")
    if max_weights.sum() < 1.0 - tol:
        raise ValueError("Sum of maximum weights must be at least 100%.")

    if current_weights is not None:
        current_weights = np.array(current_weights, dtype=float)
        if len(current_weights) != len(min_weights):
            raise ValueError("Current weight length mismatch.")
        for idx, weight in enumerate(current_weights):
            if weight < min_weights[idx] - tol or weight > max_weights[idx] + tol:
                raise ValueError(
                    f"Current weight for asset #{idx + 1} ({weight:.4f}) is outside "
                    f"[{min_weights[idx]:.4f}, {max_weights[idx]:.4f}]."
                )


def adjust_weights_to_bounds(weights, min_weights, max_weights, tol=1e-9, max_iter=1000):
    min_weights = np.array(min_weights, dtype=float)
    max_weights = np.array(max_weights, dtype=float)
    validate_bounds(min_weights, max_weights)

    weights = np.array(weights, dtype=float)
    if len(weights) != len(min_weights):
        raise ValueError("Weights length mismatch.")
    weights = np.clip(weights, min_weights, max_weights)

    for _ in range(max_iter):
        weight_sum = weights.sum()
        diff = 1.0 - weight_sum
        if abs(diff) <= tol:
            return weights
        if diff > 0:
            slack = max_weights - weights
            total_slack = slack.sum()
            if total_slack <= tol:
                break
            weights += np.minimum(slack, diff * (slack / total_slack))
        else:
            room = weights - min_weights
            total_room = room.sum()
            if total_room <= tol:
                break
            weights -= np.minimum(room, (-diff) * (room / total_room))

    weights = np.clip(weights, min_weights, max_weights)
    if abs(weights.sum() - 1.0) > 1e-6:
        raise ValueError("Could not construct feasible weights for the provided bounds.")
    return weights


def optimize_portfolio(
    mode,
    expected_returns,
    cov_annual,
    min_weights,
    max_weights,
    target_volatility=None,
    initial_weights=None,
    max_single_weight=OPTIMIZER_SINGLE_ASSET_CAP,
):
    if not HAS_SCIPY:
        raise RuntimeError("scipy is required for optimization. Install with: pip install scipy")

    exp_ret = np.array(expected_returns, dtype=float)
    min_weights = np.array(min_weights, dtype=float)
    user_max = np.array(max_weights, dtype=float)
    eff_max = np.minimum(user_max, max_single_weight)
    validate_bounds(min_weights, eff_max)

    n_assets = len(exp_ret)
    if initial_weights is None:
        initial_weights = np.full(n_assets, 1.0 / n_assets)
    x0 = adjust_weights_to_bounds(initial_weights, min_weights, eff_max)
    bounds = list(zip(min_weights, eff_max))

    def variance(weight_vector):
        return float(np.array(weight_vector) @ cov_annual.values @ np.array(weight_vector))

    def volatility(weight_vector):
        return sqrt(max(variance(weight_vector), 0.0))

    def expected_return(weight_vector):
        return float(np.array(weight_vector) @ exp_ret)

    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

    if mode == MODE_MIN_VOL:
        objective = variance
    elif mode == MODE_BEST_GAIN_VOL:
        def objective(weight_vector):
            port_vol = volatility(weight_vector)
            if port_vol <= 1e-12:
                return 1e9
            return -expected_return(weight_vector) / port_vol
    elif mode == MODE_MAX_RET_TARGET_RISK:
        if target_volatility is None or target_volatility <= 0:
            raise ValueError("Target volatility must be > 0 for this mode.")
        constraints.append({"type": "ineq", "fun": lambda w: target_volatility - volatility(w)})
        objective = lambda w: -expected_return(w)
    else:
        raise ValueError(f"Unsupported optimization mode: {mode}")

    result = minimize(
        objective,
        x0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 600, "ftol": 1e-9},
    )
    if not result.success:
        raise RuntimeError(f"Optimization failed: {result.message}")

    weights = adjust_weights_to_bounds(result.x, min_weights, eff_max)
    forward = calc_forward_portfolio_metrics(weights, exp_ret, cov_annual)
    return {
        "weights": weights,
        "expected_ann_return": forward["expected_ann_return"],
        "volatility": forward["volatility"],
        "expected_return_over_volatility": forward["expected_return_over_volatility"],
        "variance": forward["variance"],
        "effective_max_weights": eff_max,
        "cap_enforced": bool(np.any(user_max > eff_max + 1e-12)),
    }


def optimize_builder_portfolio(
    objective_name,
    expected_returns,
    cov_annual,
    min_weights,
    max_weights,
    target_volatility=None,
    initial_weights=None,
    max_single_weight=OPTIMIZER_SINGLE_ASSET_CAP,
):
    if objective_name == BUILDER_OBJECTIVE_MAX_RETURN_UNDER_RISK:
        return optimize_portfolio(
            MODE_MAX_RET_TARGET_RISK,
            expected_returns,
            cov_annual,
            min_weights,
            max_weights,
            target_volatility=target_volatility,
            initial_weights=initial_weights,
            max_single_weight=max_single_weight,
        )

    if objective_name == BUILDER_OBJECTIVE_MIN_VOL:
        return optimize_portfolio(
            MODE_MIN_VOL,
            expected_returns,
            cov_annual,
            min_weights,
            max_weights,
            initial_weights=initial_weights,
            max_single_weight=max_single_weight,
        )

    if objective_name != BUILDER_OBJECTIVE_MATCH_RISK:
        raise ValueError(f"Unsupported builder objective: {objective_name}")

    if not HAS_SCIPY:
        raise RuntimeError("scipy is required for optimization. Install with: pip install scipy")
    if target_volatility is None or target_volatility <= 0:
        raise ValueError("Target volatility must be > 0 to match target risk.")

    exp_ret = np.array(expected_returns, dtype=float)
    min_weights = np.array(min_weights, dtype=float)
    user_max = np.array(max_weights, dtype=float)
    eff_max = np.minimum(user_max, max_single_weight)
    validate_bounds(min_weights, eff_max)

    if initial_weights is None:
        initial_weights = np.full(len(exp_ret), 1.0 / len(exp_ret))
    x0 = adjust_weights_to_bounds(initial_weights, min_weights, eff_max)
    bounds = list(zip(min_weights, eff_max))

    def variance(weight_vector):
        return float(np.array(weight_vector) @ cov_annual.values @ np.array(weight_vector))

    def volatility(weight_vector):
        return sqrt(max(variance(weight_vector), 0.0))

    def expected_return(weight_vector):
        return float(np.array(weight_vector) @ exp_ret)

    def objective(weight_vector):
        vol_gap = (volatility(weight_vector) - target_volatility) / max(target_volatility, 1e-6)
        # Match target volatility first, then prefer higher return among near-equal risk fits.
        return vol_gap ** 2 - 0.05 * expected_return(weight_vector)

    result = minimize(
        objective,
        x0,
        method="SLSQP",
        bounds=bounds,
        constraints=[{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}],
        options={"maxiter": 700, "ftol": 1e-9},
    )
    if not result.success:
        raise RuntimeError(f"Target-risk optimization failed: {result.message}")

    weights = adjust_weights_to_bounds(result.x, min_weights, eff_max)
    forward = calc_forward_portfolio_metrics(weights, exp_ret, cov_annual)
    return {
        "weights": weights,
        "expected_ann_return": forward["expected_ann_return"],
        "volatility": forward["volatility"],
        "expected_return_over_volatility": forward["expected_return_over_volatility"],
        "variance": forward["variance"],
        "effective_max_weights": eff_max,
        "cap_enforced": bool(np.any(user_max > eff_max + 1e-12)),
        "target_gap": float(forward["volatility"] - target_volatility),
    }


def build_efficient_frontier(expected_returns, cov_annual, min_weights, max_weights, points=20, max_single_weight=OPTIMIZER_SINGLE_ASSET_CAP):
    if not HAS_SCIPY:
        return []
    try:
        min_vol = optimize_portfolio(
            MODE_MIN_VOL,
            expected_returns,
            cov_annual,
            min_weights,
            max_weights,
            max_single_weight=max_single_weight,
        )
    except Exception:
        return []

    exp_ret = np.array(expected_returns, dtype=float)
    min_weights = np.array(min_weights, dtype=float)
    eff_max = np.minimum(np.array(max_weights, dtype=float), max_single_weight)
    bounds = list(zip(min_weights, eff_max))

    def variance(weight_vector):
        return float(np.array(weight_vector) @ cov_annual.values @ np.array(weight_vector))

    def volatility(weight_vector):
        return sqrt(max(variance(weight_vector), 0.0))

    def expected_return(weight_vector):
        return float(np.array(weight_vector) @ exp_ret)

    x0 = adjust_weights_to_bounds(np.full(len(exp_ret), 1.0 / len(exp_ret)), min_weights, eff_max)
    result = minimize(
        lambda w: -expected_return(w),
        x0,
        method="SLSQP",
        bounds=bounds,
        constraints=[{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}],
        options={"maxiter": 600, "ftol": 1e-9},
    )
    if not result.success:
        return []

    max_ret_weights = adjust_weights_to_bounds(result.x, min_weights, eff_max)
    min_vol_value = min_vol["volatility"]
    max_vol_value = max(volatility(max_ret_weights), min_vol_value * 1.05)
    target_vols = np.linspace(min_vol_value, max_vol_value, points)

    frontier = []
    for target in target_vols:
        try:
            result = optimize_portfolio(
                MODE_MAX_RET_TARGET_RISK,
                expected_returns,
                cov_annual,
                min_weights,
                max_weights,
                target_volatility=float(target),
                initial_weights=min_vol["weights"],
                max_single_weight=max_single_weight,
            )
            frontier.append((result["volatility"], result["expected_ann_return"]))
        except Exception:
            continue
    return frontier


def choose_benchmark_name(selection, model_info, benchmark_candidates, available_series):
    if selection and selection not in {BENCHMARK_AUTO, BENCHMARK_NONE}:
        return selection if selection in available_series else None
    if selection == BENCHMARK_NONE:
        return None

    preferred = model_info.get("benchmark")
    if preferred and preferred in available_series:
        return preferred

    for candidate in benchmark_candidates:
        if candidate in available_series:
            return candidate
    for fallback in ("SP 500", "SP 600"):
        if fallback in available_series:
            return fallback
    return None


def parse_model_workbook(path):
    import openpyxl

    workbook = openpyxl.load_workbook(path, data_only=True)
    models = {}
    warnings = []

    for sheet_name in workbook.sheetnames:
        sheet = workbook[sheet_name]
        funds = []
        current_category = ""

        portfolio_label = str(sheet["A4"].value).strip() if sheet["A4"].value else sheet_name
        benchmark_reference = str(sheet["C8"].value).strip() if sheet["C8"].value else "SP 500"
        portfolio_return = float(sheet["D7"].value) if is_numeric(sheet["D7"].value) else None
        portfolio_volatility = float(sheet["F7"].value) if is_numeric(sheet["F7"].value) else None
        portfolio_return_over_vol = float(sheet["H7"].value) if is_numeric(sheet["H7"].value) else None

        for row in range(1, sheet.max_row + 1):
            category_cell = sheet.cell(row, 1).value
            fund_name = sheet.cell(row, 3).value
            weight = sheet.cell(row, 4).value

            if isinstance(category_cell, str) and category_cell.strip():
                label = category_cell.strip().rstrip(":")
                if label and label.lower() not in {"model portfolios"}:
                    current_category = label

            if not fund_name or not is_numeric(weight):
                continue
            fund_name = str(fund_name).strip()
            if fund_name in {"Portfolio", "SP 500", "Subtotal"}:
                continue

            canonical = canonicalize_fund_name(fund_name)
            funds.append(
                {
                    "name": canonical,
                    "display_name": fund_name,
                    "weight": float(weight),
                    "category": current_category or FUND_METADATA.get(canonical, {}).get("style", ""),
                    "benchmark": FUND_METADATA.get(canonical, {}).get("benchmark", benchmark_reference),
                }
            )

        total_weight = sum(item["weight"] for item in funds)
        if total_weight <= 0:
            warnings.append(f"{sheet_name}: no usable fund rows were found.")
            continue

        for item in funds:
            item["weight"] = item["weight"] / total_weight

        models[sheet_name] = {
            "sheet_name": sheet_name,
            "portfolio_label": portfolio_label,
            "benchmark": benchmark_reference,
            "portfolio_return": portfolio_return,
            "portfolio_volatility": portfolio_volatility,
            "portfolio_return_over_volatility": portfolio_return_over_vol,
            "funds": funds,
        }

    if not models:
        raise ValueError("No model portfolios were parsed from the workbook.")
    return models, warnings


def _detect_transposed_block(sheet):
    best = None
    for date_col in range(2, min(sheet.max_column, 15) + 1):
        date_rows = []
        for row in range(1, min(sheet.max_row, 60) + 1):
            value = sheet.cell(row, date_col).value
            if isinstance(value, pd.Timestamp) or hasattr(value, "year"):
                date_rows.append(row)
        if len(date_rows) < 6:
            continue
        first_date_row = min(date_rows)
        header_candidates = []
        for row in range(max(1, first_date_row - 4), first_date_row):
            count = 0
            for col in range(date_col + 1, min(sheet.max_column, date_col + 25) + 1):
                cell = sheet.cell(row, col).value
                if isinstance(cell, str) and cell.strip():
                    count += 1
            if count >= 2:
                header_candidates.append((count, row))
        if header_candidates:
            count, header_row = sorted(header_candidates)[-1]
            score = (len(date_rows), count)
            if best is None or score > best["score"]:
                best = {
                    "date_col": date_col,
                    "header_row": header_row,
                    "first_date_row": first_date_row,
                    "score": score,
                }
    return best


def _extract_transposed_returns(sheet, sheet_name):
    block = _detect_transposed_block(sheet)
    if not block:
        return pd.DataFrame(), {}

    date_col = block["date_col"]
    header_row = block["header_row"]
    first_date_row = block["first_date_row"]

    dates = []
    date_rows = []
    row = first_date_row
    while row <= sheet.max_row:
        date_value = sheet.cell(row, date_col).value
        if not (isinstance(date_value, pd.Timestamp) or hasattr(date_value, "year")):
            break
        dates.append(pd.to_datetime(date_value))
        date_rows.append(row)
        row += 1

    data = {}
    metadata = {}
    for col in range(date_col + 1, sheet.max_column + 1):
        header = sheet.cell(header_row, col).value
        if not isinstance(header, str) or not header.strip():
            continue
        raw_name = header.strip()
        values = []
        numeric_count = 0
        for data_row in date_rows:
            cell_value = sheet.cell(data_row, col).value
            if is_numeric(cell_value):
                values.append(float(cell_value))
                numeric_count += 1
            else:
                values.append(np.nan)
        if numeric_count < 4:
            continue
        canonical = canonicalize_fund_name(raw_name)
        series = pd.Series(values, index=dates, name=canonical)
        if canonical in data:
            if series.notna().sum() > data[canonical].notna().sum():
                data[canonical] = series
        else:
            data[canonical] = series
        metadata.setdefault(
            canonical,
            {
                "raw_name": raw_name,
                "source_sheet": sheet_name,
                "style": FUND_METADATA.get(canonical, {}).get("style", sheet_name),
                "benchmark": FUND_METADATA.get(canonical, {}).get("benchmark", ""),
                "stress_bucket": infer_stress_bucket(canonical, source_sheet=sheet_name),
                "notes": FUND_METADATA.get(canonical, {}).get("notes", ""),
            },
        )

    frame = pd.DataFrame(data).sort_index() if data else pd.DataFrame()
    return frame, metadata


def parse_var_workbook(path):
    import openpyxl

    workbook = openpyxl.load_workbook(path, data_only=True)
    preferred_sheet = None
    for sheet_name in workbook.sheetnames:
        if sheet_name.strip().lower() == "equity var mar 26":
            preferred_sheet = sheet_name
            break

    if preferred_sheet is None:
        raise ValueError("Could not find a sheet named 'Equity VaR Mar 26'.")

    ordered_sheet_names = [preferred_sheet] + [name for name in workbook.sheetnames if name != preferred_sheet]
    merged = pd.DataFrame()
    fund_info = {}
    benchmark_series = {}
    warnings = []

    for sheet_name in ordered_sheet_names:
        sheet = workbook[sheet_name]
        frame, metadata = _extract_transposed_returns(sheet, sheet_name)
        if frame.empty:
            continue

        for column in list(frame.columns):
            if is_benchmark_name(column):
                benchmark_series[column] = frame[column]
            if column in merged.columns:
                if frame[column].notna().sum() > merged[column].notna().sum():
                    merged[column] = frame[column]
            else:
                merged[column] = frame[column]
            if column not in fund_info:
                fund_info[column] = metadata.get(column, {})
            else:
                existing = fund_info[column]
                existing.update({k: v for k, v in metadata.get(column, {}).items() if v})

    merged = merged.sort_index()
    merged = merged.loc[:, merged.notna().sum() >= 4]
    if merged.empty:
        raise ValueError("No usable fund return history rows were detected in the VaR workbook.")

    benchmark_candidates = [name for name in merged.columns if is_benchmark_name(name)]
    investable_columns = [name for name in merged.columns if not is_benchmark_name(name)]

    for column in investable_columns:
        fund_info.setdefault(column, {})
        fund_info[column].setdefault("raw_name", column)
        fund_info[column].setdefault("source_sheet", preferred_sheet)
        fund_info[column].setdefault("style", FUND_METADATA.get(column, {}).get("style", ""))
        fund_info[column].setdefault("benchmark", FUND_METADATA.get(column, {}).get("benchmark", ""))
        fund_info[column].setdefault("stress_bucket", infer_stress_bucket(column, source_sheet=fund_info[column].get("source_sheet", "")))
        fund_info[column].setdefault("notes", FUND_METADATA.get(column, {}).get("notes", ""))

    if "SP 500" in merged.columns and "SP 500" not in benchmark_series:
        benchmark_series["SP 500"] = merged["SP 500"]
    if "SP 600" in merged.columns and "SP 600" not in benchmark_series:
        benchmark_series["SP 600"] = merged["SP 600"]

    return {
        "returns": merged[investable_columns],
        "all_series": merged,
        "fund_info": fund_info,
        "benchmark_series": benchmark_series,
        "benchmark_candidates": benchmark_candidates,
        "preferred_sheet": preferred_sheet,
        "warnings": warnings,
    }


def build_model_weight_vector(model_info, universe):
    mapping = {item["name"]: float(item["weight"]) for item in model_info.get("funds", [])}
    weights = np.array([mapping.get(name, 0.0) for name in universe], dtype=float)
    matched = [name for name in universe if mapping.get(name, 0.0) > 0]
    unmatched = [item["name"] for item in model_info.get("funds", []) if item["name"] not in universe]
    total = weights.sum()
    if total > 0:
        weights = weights / total
    return weights, matched, unmatched


def compute_benchmark_metrics(benchmark_name, benchmark_series, ann_factor=ANN_FACTOR_DEFAULT):
    if not benchmark_name:
        return None
    series = benchmark_series.get(benchmark_name)
    if series is None:
        return None
    clean = series.dropna()
    if clean.empty:
        return None
    cumulative, drawdown = calc_drawdown_series(clean)
    total_return = float(cumulative.iloc[-1] - 1.0) if len(cumulative) else 0.0
    ann_return = (1.0 + total_return) ** (ann_factor / len(clean)) - 1.0 if len(clean) > 0 else 0.0
    ann_vol = clean.std(ddof=1) * sqrt(ann_factor) if len(clean) > 1 else 0.0
    return {
        "benchmark": benchmark_name,
        "historical_ann_return": float(ann_return),
        "volatility": float(ann_vol),
        "historical_total_return": float(total_return),
        "historical_max_drawdown": float(drawdown.min()) if len(drawdown) else 0.0,
        "cumulative_series": cumulative,
    }


def select_return_vector(symbols, per_stock_history, row_expected, return_basis):
    if return_basis == RETURN_BASIS_HISTORICAL:
        return np.array([per_stock_history[s]["historical_ann_return"] for s in symbols], dtype=float)
    return np.array(row_expected, dtype=float)


def build_builder_explanation(result, warnings):
    if result is None:
        return "No builder result is available yet."

    explanation = [
        f"The tool used the selected model portfolio '{result['model_name']}' as the reference allocation.",
        f"The requested risk profile was '{result['risk_profile']}' with a target annualized volatility of {result['target_volatility']:.2%}.",
        f"The optimization objective was '{result['objective']}', using '{result['return_basis']}' as the return vector while keeping covariance and volatility historical.",
    ]

    if result["objective"] == BUILDER_OBJECTIVE_MATCH_RISK:
        gap = abs(result["recommended"]["volatility"] - result["target_volatility"])
        explanation.append(
            f"The recommended allocation landed at {result['recommended']['volatility']:.2%} volatility, "
            f"which is {gap:.2%} away from the requested target."
        )
    elif result["objective"] == BUILDER_OBJECTIVE_MAX_RETURN_UNDER_RISK:
        explanation.append(
            "The optimizer maximized expected return while keeping portfolio volatility at or below the selected target."
        )
    elif result["objective"] == BUILDER_OBJECTIVE_MIN_VOL:
        explanation.append(
            "The optimizer searched the full matched universe for the lowest-volatility feasible allocation under the user bounds."
        )
    elif result["objective"] == BUILDER_OBJECTIVE_BLEND:
        explanation.append(
            f"The final allocation blends {result['blend_ratio']:.0%} optimized weights with {1 - result['blend_ratio']:.0%} model weights."
        )
    else:
        explanation.append("No optimization was run; the stress-test view uses the selected model allocation as the baseline.")

    if warnings:
        explanation.append("Warnings: " + " | ".join(warnings))

    return "\n".join(explanation)


def stress_covariance(base_cov, corr_matrix, symbols, bucket_map, scenario_rows):
    stds = pd.Series(np.sqrt(np.maximum(np.diag(base_cov.values), 0.0)), index=symbols)
    vol_mult = pd.Series(1.0, index=symbols)
    corr_mult = pd.Series(1.0, index=symbols)

    for row in scenario_rows:
        target = row["target"]
        for symbol in symbols:
            if target in {"All", bucket_map[symbol], symbol}:
                vol_mult[symbol] *= float(row["vol_multiplier"])
                corr_mult[symbol] *= float(row["corr_multiplier"])

    new_cov = pd.DataFrame(index=symbols, columns=symbols, dtype=float)
    for si in symbols:
        for sj in symbols:
            if si == sj:
                new_cov.loc[si, sj] = float((stds[si] * vol_mult[si]) ** 2)
            else:
                base_corr = float(corr_matrix.loc[si, sj])
                adjusted_corr = np.clip(base_corr * sqrt(corr_mult[si] * corr_mult[sj]), -0.99, 0.99)
                new_cov.loc[si, sj] = float(adjusted_corr * stds[si] * vol_mult[si] * stds[sj] * vol_mult[sj])
    return new_cov


def run_stress_tests(
    scenario_rows,
    symbols,
    baseline_weights,
    recommended_weights,
    fund_info,
    cov_annual,
    corr_matrix,
    investment_amount,
    ann_factor=ANN_FACTOR_DEFAULT,
):
    rows = pd.DataFrame(scenario_rows)
    if rows.empty:
        return []

    scenario_results = []
    bucket_map = {sym: fund_info.get(sym, {}).get("stress_bucket", infer_stress_bucket(sym)) for sym in symbols}

    for scenario_name, group in rows.groupby("scenario"):
        group_records = group.to_dict("records")
        shock_map = {sym: 0.0 for sym in symbols}
        for record in group_records:
            target = record["target"]
            for sym in symbols:
                if target in {"All", bucket_map[sym], sym}:
                    shock_map[sym] += float(record["shock_pct"]) / 100.0

        baseline_impact = float(np.dot(baseline_weights, [shock_map[sym] for sym in symbols]))
        rec_impact = float(np.dot(recommended_weights, [shock_map[sym] for sym in symbols])) if recommended_weights is not None else baseline_impact

        stressed_cov = stress_covariance(cov_annual, corr_matrix, symbols, bucket_map, group_records)
        baseline_stressed_vol = calc_portfolio_volatility(baseline_weights, stressed_cov)
        rec_stressed_vol = calc_portfolio_volatility(recommended_weights, stressed_cov) if recommended_weights is not None else baseline_stressed_vol

        baseline_var = calc_portfolio_var_95(baseline_stressed_vol, ann_factor=ann_factor)
        rec_var = calc_portfolio_var_95(rec_stressed_vol, ann_factor=ann_factor)

        rec_contributions = {
            sym: float(recommended_weights[idx] * shock_map[sym]) if recommended_weights is not None else 0.0
            for idx, sym in enumerate(symbols)
        }
        baseline_contributions = {sym: float(baseline_weights[idx] * shock_map[sym]) for idx, sym in enumerate(symbols)}

        worst_baseline = min(baseline_contributions, key=baseline_contributions.get) if baseline_contributions else ""
        worst_recommended = min(rec_contributions, key=rec_contributions.get) if rec_contributions else ""

        scenario_results.append(
            {
                "scenario": scenario_name,
                "model_impact": baseline_impact,
                "recommended_impact": rec_impact,
                "model_end_value": investment_amount * (1.0 + baseline_impact),
                "recommended_end_value": investment_amount * (1.0 + rec_impact),
                "model_stressed_vol": baseline_stressed_vol,
                "recommended_stressed_vol": rec_stressed_vol,
                "model_var_95": baseline_var,
                "recommended_var_95": rec_var,
                "worst_model_fund": worst_baseline,
                "worst_recommended_fund": worst_recommended,
                "notes": "; ".join(sorted({record["notes"] for record in group_records if record.get("notes")})),
            }
        )

    return sorted(scenario_results, key=lambda item: item["recommended_impact"])


def export_to_csv(path, analyzer_metrics=None, builder_payload=None):
    rows = []

    if builder_payload:
        rows.append({"Section": "Builder Summary", "Metric": "Selected Model", "Value": builder_payload["model_name"]})
        rows.append({"Section": "Builder Summary", "Metric": "Risk Profile", "Value": builder_payload["risk_profile"]})
        rows.append({"Section": "Builder Summary", "Metric": "Objective", "Value": builder_payload["objective"]})
        rows.append({"Section": "Builder Summary", "Metric": "Return Basis", "Value": builder_payload["return_basis"]})
        rows.append({"Section": "Builder Summary", "Metric": "Target Volatility", "Value": builder_payload["target_volatility"]})
        rows.append({})
        for row in builder_payload["allocation_rows"]:
            rows.append(
                {
                    "Section": "Recommended Allocation",
                    "Fund": row["symbol"],
                    "Category": row["category"],
                    "Benchmark": row["benchmark"],
                    "Model Weight": row["model_weight"],
                    "Recommended Weight": row["recommended_weight"],
                    "Expected Return": row["expected_ann_return"],
                    "Historical Return": row["historical_ann_return"],
                    "Volatility": row["volatility"],
                    "Min Weight": row["min_weight"],
                    "Max Weight": row["max_weight"],
                }
            )

    if analyzer_metrics:
        rows.append({})
        for row in analyzer_metrics["asset_rows"]:
            rows.append(
                {
                    "Section": "Analyzer Asset",
                    "Fund": row["symbol"],
                    "Name": row["name"],
                    "Weight": row["weight"],
                    "Expected Return": row["expected_ann_return"],
                    "Historical Return": row["historical_ann_return"],
                    "Volatility": row["volatility"],
                }
            )

    pd.DataFrame(rows).to_csv(path, index=False)


def export_to_xlsx(path, analyzer_metrics=None, builder_payload=None):
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    workbook = openpyxl.Workbook()
    summary = workbook.active
    summary.title = "Summary"

    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    pct_fmt = "0.00%"
    num_fmt = "0.0000"
    money_fmt = "$#,##0"

    def write_headers(sheet, row, headers):
        for col, header in enumerate(headers, 1):
            cell = sheet.cell(row=row, column=col, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")

    current_row = 1
    if builder_payload:
        summary.cell(row=current_row, column=1, value="Portfolio Builder Summary").font = Font(bold=True, size=13)
        current_row += 1
        builder_rows = [
            ("Selected Model", builder_payload["model_name"]),
            ("Risk Profile", builder_payload["risk_profile"]),
            ("Optimization Objective", builder_payload["objective"]),
            ("Return Basis", builder_payload["return_basis"]),
            ("Target Volatility", builder_payload["target_volatility"]),
            ("Investment Amount", builder_payload["investment_amount"]),
            ("Selected Benchmark", builder_payload.get("benchmark_name") or "Unavailable"),
        ]
        for label, value in builder_rows:
            summary.cell(row=current_row, column=1, value=label).font = Font(bold=True)
            summary.cell(row=current_row, column=2, value=value)
            if isinstance(value, float) and "Amount" not in label:
                summary.cell(row=current_row, column=2).number_format = pct_fmt if abs(value) <= 1 else num_fmt
            if label == "Investment Amount":
                summary.cell(row=current_row, column=2).number_format = money_fmt
            current_row += 1
        current_row += 1

        write_headers(
            summary,
            current_row,
            [
                "Portfolio",
                "Expected Ann. Return",
                "Historical Ann. Return",
                "Volatility",
                "Expected Return / Volatility",
                "Historical Max Drawdown",
                "Estimated Monthly VaR (95%)",
            ],
        )
        current_row += 1
        for label, metrics in (("Model Portfolio", builder_payload["baseline"]), ("Recommended Allocation", builder_payload["recommended"])):
            summary.cell(row=current_row, column=1, value=label)
            summary.cell(row=current_row, column=2, value=metrics["expected_ann_return"]).number_format = pct_fmt
            summary.cell(row=current_row, column=3, value=metrics["historical_ann_return"]).number_format = pct_fmt
            summary.cell(row=current_row, column=4, value=metrics["volatility"]).number_format = pct_fmt
            summary.cell(row=current_row, column=5, value=metrics["expected_return_over_volatility"]).number_format = num_fmt
            summary.cell(row=current_row, column=6, value=metrics["historical_max_drawdown"]).number_format = pct_fmt
            summary.cell(row=current_row, column=7, value=metrics["var_95"]).number_format = pct_fmt
            current_row += 1

        alloc_sheet = workbook.create_sheet("Recommended Allocation")
        write_headers(
            alloc_sheet,
            1,
            [
                "Fund",
                "Category",
                "Benchmark",
                "Model Weight",
                "Recommended Weight",
                "Delta",
                "Expected Ann. Return",
                "Historical Ann. Return",
                "Historical Volatility",
                "Min Weight",
                "Max Weight",
            ],
        )
        row = 2
        for item in builder_payload["allocation_rows"]:
            alloc_sheet.cell(row=row, column=1, value=item["symbol"])
            alloc_sheet.cell(row=row, column=2, value=item["category"])
            alloc_sheet.cell(row=row, column=3, value=item["benchmark"])
            alloc_sheet.cell(row=row, column=4, value=item["model_weight"]).number_format = pct_fmt
            alloc_sheet.cell(row=row, column=5, value=item["recommended_weight"]).number_format = pct_fmt
            alloc_sheet.cell(row=row, column=6, value=item["delta_weight"]).number_format = pct_fmt
            alloc_sheet.cell(row=row, column=7, value=item["expected_ann_return"]).number_format = pct_fmt
            alloc_sheet.cell(row=row, column=8, value=item["historical_ann_return"]).number_format = pct_fmt
            alloc_sheet.cell(row=row, column=9, value=item["volatility"]).number_format = pct_fmt
            alloc_sheet.cell(row=row, column=10, value=item["min_weight"]).number_format = pct_fmt
            alloc_sheet.cell(row=row, column=11, value=item["max_weight"]).number_format = pct_fmt
            row += 1

        comparison_sheet = workbook.create_sheet("Model Portfolio Comparison")
        write_headers(
            comparison_sheet,
            1,
            [
                "Portfolio",
                "Expected Ann. Return",
                "Historical Ann. Return",
                "Volatility",
                "Expected Return / Volatility",
                "Historical Max Drawdown",
                "Estimated Monthly VaR (95%)",
            ],
        )
        for row_idx, (label, metrics) in enumerate(
            (("Model Portfolio", builder_payload["baseline"]), ("Recommended Allocation", builder_payload["recommended"])),
            start=2,
        ):
            comparison_sheet.cell(row=row_idx, column=1, value=label)
            comparison_sheet.cell(row=row_idx, column=2, value=metrics["expected_ann_return"]).number_format = pct_fmt
            comparison_sheet.cell(row=row_idx, column=3, value=metrics["historical_ann_return"]).number_format = pct_fmt
            comparison_sheet.cell(row=row_idx, column=4, value=metrics["volatility"]).number_format = pct_fmt
            comparison_sheet.cell(row=row_idx, column=5, value=metrics["expected_return_over_volatility"]).number_format = num_fmt
            comparison_sheet.cell(row=row_idx, column=6, value=metrics["historical_max_drawdown"]).number_format = pct_fmt
            comparison_sheet.cell(row=row_idx, column=7, value=metrics["var_95"]).number_format = pct_fmt

        risk_sheet = workbook.create_sheet("Risk Metrics")
        write_headers(
            risk_sheet,
            1,
            ["Fund", "Weight", "Marginal Risk", "Component Risk", "% Risk Contribution", "Variance Contribution", "% Variance"],
        )
        row = 2
        for item in builder_payload["risk_contributions"]:
            risk_sheet.cell(row=row, column=1, value=item["symbol"])
            risk_sheet.cell(row=row, column=2, value=item["weight"]).number_format = pct_fmt
            risk_sheet.cell(row=row, column=3, value=item["marginal_risk"]).number_format = pct_fmt
            risk_sheet.cell(row=row, column=4, value=item["component_risk"]).number_format = pct_fmt
            risk_sheet.cell(row=row, column=5, value=item["percent_risk"]).number_format = pct_fmt
            risk_sheet.cell(row=row, column=6, value=item["variance_contribution"]).number_format = "0.000000"
            risk_sheet.cell(row=row, column=7, value=item["percent_variance"]).number_format = pct_fmt
            row += 1

        benchmark_sheet = workbook.create_sheet("Benchmark Comparison")
        write_headers(
            benchmark_sheet,
            1,
            ["Benchmark", "Historical Ann. Return", "Volatility", "Historical Max Drawdown", "Total Return"],
        )
        if builder_payload.get("benchmark_metrics"):
            bm = builder_payload["benchmark_metrics"]
            benchmark_sheet.cell(row=2, column=1, value=bm["benchmark"])
            benchmark_sheet.cell(row=2, column=2, value=bm["historical_ann_return"]).number_format = pct_fmt
            benchmark_sheet.cell(row=2, column=3, value=bm["volatility"]).number_format = pct_fmt
            benchmark_sheet.cell(row=2, column=4, value=bm["historical_max_drawdown"]).number_format = pct_fmt
            benchmark_sheet.cell(row=2, column=5, value=bm["historical_total_return"]).number_format = pct_fmt
        else:
            benchmark_sheet.cell(row=2, column=1, value="Benchmark unavailable")

        stress_sheet = workbook.create_sheet("Stress Test Results")
        write_headers(
            stress_sheet,
            1,
            [
                "Scenario",
                "Model Impact",
                "Recommended Impact",
                "Model End Value",
                "Recommended End Value",
                "Model Stressed Vol",
                "Recommended Stressed Vol",
                "Model VaR 95",
                "Recommended VaR 95",
                "Worst Model Fund",
                "Worst Recommended Fund",
                "Notes",
            ],
        )
        row = 2
        for item in builder_payload.get("stress_results", []):
            stress_sheet.cell(row=row, column=1, value=item["scenario"])
            stress_sheet.cell(row=row, column=2, value=item["model_impact"]).number_format = pct_fmt
            stress_sheet.cell(row=row, column=3, value=item["recommended_impact"]).number_format = pct_fmt
            stress_sheet.cell(row=row, column=4, value=item["model_end_value"]).number_format = money_fmt
            stress_sheet.cell(row=row, column=5, value=item["recommended_end_value"]).number_format = money_fmt
            stress_sheet.cell(row=row, column=6, value=item["model_stressed_vol"]).number_format = pct_fmt
            stress_sheet.cell(row=row, column=7, value=item["recommended_stressed_vol"]).number_format = pct_fmt
            stress_sheet.cell(row=row, column=8, value=item["model_var_95"]).number_format = pct_fmt
            stress_sheet.cell(row=row, column=9, value=item["recommended_var_95"]).number_format = pct_fmt
            stress_sheet.cell(row=row, column=10, value=item["worst_model_fund"])
            stress_sheet.cell(row=row, column=11, value=item["worst_recommended_fund"])
            stress_sheet.cell(row=row, column=12, value=item["notes"])
            row += 1

        assumptions_sheet = workbook.create_sheet("Assumptions Used")
        write_headers(
            assumptions_sheet,
            1,
            ["Assumption", "Value"],
        )
        assumptions = [
            ("Scenario preset file", str(SCENARIO_PRESETS_FILE)),
            ("Return basis", builder_payload["return_basis"]),
            ("Max single-fund cap", builder_payload["max_single_weight"]),
            ("Blend ratio", builder_payload["blend_ratio"]),
            ("Builder warnings", " | ".join(builder_payload.get("warnings", [])) or "None"),
            ("Builder explanation", builder_payload.get("explanation", "")),
        ]
        for row_idx, (label, value) in enumerate(assumptions, start=2):
            assumptions_sheet.cell(row=row_idx, column=1, value=label)
            assumptions_sheet.cell(row=row_idx, column=2, value=value)

        scenario_sheet = workbook.create_sheet("Scenario Assumptions")
        write_headers(
            scenario_sheet,
            1,
            ["Scenario", "Target", "Return Shock %", "Volatility Multiplier", "Correlation Multiplier", "Notes"],
        )
        for row_idx, item in enumerate(builder_payload.get("scenario_rows", []), start=2):
            scenario_sheet.cell(row=row_idx, column=1, value=item["scenario"])
            scenario_sheet.cell(row=row_idx, column=2, value=item["target"])
            scenario_sheet.cell(row=row_idx, column=3, value=float(item["shock_pct"]) / 100.0).number_format = pct_fmt
            scenario_sheet.cell(row=row_idx, column=4, value=float(item["vol_multiplier"])).number_format = num_fmt
            scenario_sheet.cell(row=row_idx, column=5, value=float(item["corr_multiplier"])).number_format = num_fmt
            scenario_sheet.cell(row=row_idx, column=6, value=item["notes"])

        corr_sheet = workbook.create_sheet("Correlation Matrix")
        cov_sheet = workbook.create_sheet("Covariance Matrix")
        symbols = list(builder_payload["corr_matrix"].columns)
        corr_sheet.cell(row=1, column=1, value="Correlation").font = Font(bold=True)
        cov_sheet.cell(row=1, column=1, value="Covariance").font = Font(bold=True)
        for col_idx, sym in enumerate(symbols, start=2):
            corr_sheet.cell(row=1, column=col_idx, value=sym).font = Font(bold=True)
            corr_sheet.cell(row=col_idx, column=1, value=sym).font = Font(bold=True)
            cov_sheet.cell(row=1, column=col_idx, value=sym).font = Font(bold=True)
            cov_sheet.cell(row=col_idx, column=1, value=sym).font = Font(bold=True)
        for i, si in enumerate(symbols, start=2):
            for j, sj in enumerate(symbols, start=2):
                corr_sheet.cell(row=i, column=j, value=float(builder_payload["corr_matrix"].loc[si, sj])).number_format = num_fmt
                cov_sheet.cell(row=i, column=j, value=float(builder_payload["cov_matrix"].loc[si, sj])).number_format = "0.000000"

    if analyzer_metrics:
        analyzer_sheet = workbook.create_sheet("Analyzer Summary")
        write_headers(
            analyzer_sheet,
            1,
            [
                "Stock",
                "Name",
                "Weight",
                "Min Weight",
                "Max Weight",
                "Expected Ann. Return",
                "Historical Ann. Return",
                "Volatility",
            ],
        )
        row = 2
        for item in analyzer_metrics["asset_rows"]:
            analyzer_sheet.cell(row=row, column=1, value=item["symbol"])
            analyzer_sheet.cell(row=row, column=2, value=item["name"])
            analyzer_sheet.cell(row=row, column=3, value=item["weight"]).number_format = pct_fmt
            analyzer_sheet.cell(row=row, column=4, value=item["min_weight"]).number_format = pct_fmt
            analyzer_sheet.cell(row=row, column=5, value=item["max_weight"]).number_format = pct_fmt
            analyzer_sheet.cell(row=row, column=6, value=item["expected_ann_return"]).number_format = pct_fmt
            analyzer_sheet.cell(row=row, column=7, value=item["historical_ann_return"]).number_format = pct_fmt
            analyzer_sheet.cell(row=row, column=8, value=item["volatility"]).number_format = pct_fmt
            row += 1

    for sheet in workbook.worksheets:
        for col_idx in range(1, min(sheet.max_column, 20) + 1):
            sheet.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = 18

    workbook.save(path)


class PortfolioApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Portfolio Analyzer & Builder")
        self.geometry("1440x900")
        self.minsize(1200, 760)

        # Legacy analyzer state
        self.returns_df = None
        self.stock_names = {}
        self.stock_widgets = []
        self.metrics = None
        self.optimized_result = None
        self.frontier_points = []

        # Builder state
        self.model_workbook_path = None
        self.var_workbook_path = None
        self.model_portfolios = {}
        self.model_parse_warnings = []
        self.var_returns_df = None
        self.var_all_series_df = None
        self.var_fund_info = {}
        self.var_benchmark_series = {}
        self.var_benchmark_candidates = []
        self.var_parse_warnings = []
        self.builder_widgets = []
        self.builder_result = None
        self.builder_stress_results = []
        self.scenario_vars = []
        self.scenario_presets = load_scenario_presets()
        self.builder_step_index = 0
        self.builder_step_completed = [False] * len(BUILDER_STEPS)
        self.builder_step_messages = [""] * len(BUILDER_STEPS)
        self.builder_unmatched_funds = []
        self.builder_matched_funds = []
        self.builder_weights_renormalized = False

        self._configure_styles()
        self._build_ui()

    def _configure_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("App.TFrame", background="#F6F8FB")
        style.configure("AppHeader.TFrame", background="#E9EEF7")
        style.configure("Card.TLabelframe", padding=8)
        style.configure("Card.TLabelframe.Label", font=("Segoe UI", 10, "bold"))
        style.configure("Subtle.TLabel", foreground="#4E5D6B")
        style.configure("Treeview", rowheight=24, font=("Segoe UI", 9), foreground="#1B2733")
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        style.configure("Primary.TButton", padding=(10, 6))
        style.configure("Secondary.TButton", padding=(8, 5))

    def _build_ui(self):
        self.configure(bg="#F6F8FB")

        top = ttk.Frame(self, padding=(10, 8), style="AppHeader.TFrame")
        top.pack(fill="x")

        ttk.Button(top, text="Load CSV", command=self._load_csv, style="Secondary.TButton").grid(row=0, column=0, padx=(0, 6))
        ttk.Button(top, text="Load Model Workbook", command=self._load_model_workbook, style="Secondary.TButton").grid(row=0, column=1, padx=(0, 6))
        ttk.Button(top, text="Load VaR Workbook", command=self._load_var_workbook, style="Secondary.TButton").grid(row=0, column=2, padx=(0, 6))
        ttk.Button(top, text="Export XLSX / CSV", command=self._export, style="Secondary.TButton").grid(row=0, column=3, padx=(0, 6))

        self.lbl_csv_file = ttk.Label(top, text="CSV: none", style="Subtle.TLabel")
        self.lbl_csv_file.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.lbl_model_file = ttk.Label(top, text="Model workbook: none", style="Subtle.TLabel")
        self.lbl_model_file.grid(row=1, column=2, sticky="w", pady=(6, 0))
        self.lbl_var_file = ttk.Label(top, text="VaR workbook: none", style="Subtle.TLabel")
        self.lbl_var_file.grid(row=1, column=3, sticky="w", pady=(6, 0))

        self.main_notebook = ttk.Notebook(self)
        self.main_notebook.pack(fill="both", expand=True, padx=10, pady=(8, 10))

        self.analyzer_tab = ttk.Frame(self.main_notebook, style="App.TFrame")
        self.builder_tab = ttk.Frame(self.main_notebook, style="App.TFrame")
        self.main_notebook.add(self.analyzer_tab, text="Analyzer")
        self.main_notebook.add(self.builder_tab, text="Portfolio Builder")

        self._build_analyzer_tab()
        self._build_builder_tab()

    def _build_analyzer_tab(self):
        paned = ttk.PanedWindow(self.analyzer_tab, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.Frame(paned, padding=2, style="App.TFrame")
        right = ttk.Frame(paned, padding=2, style="App.TFrame")
        paned.add(left, weight=1)
        paned.add(right, weight=3)

        assets_card = ttk.LabelFrame(left, text="Assets, Weights, and Expected Returns", style="Card.TLabelframe")
        assets_card.pack(fill="both", expand=True, pady=(0, 8))

        outer = ttk.Frame(assets_card)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, width=430, highlightthickness=0, background="#FFFFFF")
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self.stock_frame = ttk.Frame(canvas)
        self.stock_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.stock_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        header = ttk.Frame(self.stock_frame)
        header.pack(fill="x", pady=(0, 4))
        for idx, (label, width) in enumerate(
            [("Use", 4), ("Asset", 10), ("Weight", 8), ("Expected Return %", 16), ("Min", 8), ("Max", 8)]
        ):
            ttk.Label(header, text=label, width=width, anchor="center", style="Subtle.TLabel").grid(row=0, column=idx)

        tools_card = ttk.LabelFrame(left, text="Weight Tools", style="Card.TLabelframe")
        tools_card.pack(fill="x", pady=(0, 8))
        btns = ttk.Frame(tools_card)
        btns.pack(fill="x")
        ttk.Button(btns, text="Equal Weight", command=self._equal_weight, style="Secondary.TButton").pack(side="left", padx=(0, 5))
        ttk.Button(btns, text="Normalize", command=self._normalize, style="Secondary.TButton").pack(side="left")
        self.lbl_wsum = ttk.Label(tools_card, text="Weight sum: -", style="Subtle.TLabel")
        self.lbl_wsum.pack(anchor="w", pady=(6, 0))

        settings_card = ttk.LabelFrame(left, text="Settings", style="Card.TLabelframe")
        settings_card.pack(fill="x", pady=(0, 8))
        sf = ttk.Frame(settings_card)
        sf.pack(fill="x")
        ttk.Label(sf, text="Ann. Factor:").grid(row=0, column=0, sticky="w")
        self.var_ann = tk.IntVar(value=ANN_FACTOR_DEFAULT)
        ttk.Spinbox(sf, from_=1, to=365, textvariable=self.var_ann, width=8).grid(row=0, column=1, padx=6, sticky="w")
        ttk.Label(sf, text="Risk-Free % (legacy):").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.var_rf = tk.DoubleVar(value=0.0)
        ttk.Spinbox(sf, from_=0.0, to=100.0, increment=0.1, textvariable=self.var_rf, width=8).grid(
            row=1, column=1, padx=6, sticky="w", pady=(6, 0)
        )

        optimizer_card = ttk.LabelFrame(left, text="Optimizer", style="Card.TLabelframe")
        optimizer_card.pack(fill="x", pady=(0, 8))
        of = ttk.Frame(optimizer_card)
        of.pack(fill="x")
        ttk.Label(of, text="Mode:").grid(row=0, column=0, sticky="w")
        self.var_mode = tk.StringVar(value=MODE_MANUAL)
        ttk.Combobox(
            of,
            textvariable=self.var_mode,
            state="readonly",
            values=[MODE_MANUAL, MODE_MIN_VOL, MODE_BEST_GAIN_VOL, MODE_MAX_RET_TARGET_RISK],
            width=24,
        ).grid(row=0, column=1, padx=6, sticky="w")
        ttk.Label(of, text="Target Vol %:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.var_target_vol = tk.DoubleVar(value=12.0)
        ttk.Entry(of, textvariable=self.var_target_vol, width=11).grid(row=1, column=1, padx=6, sticky="w", pady=(6, 0))

        ttk.Button(optimizer_card, text="Optimize Portfolio", command=self._optimize_portfolio, style="Primary.TButton").pack(fill="x", pady=(8, 4))
        ttk.Button(optimizer_card, text="Apply Optimized Weights", command=self._apply_optimized_weights, style="Secondary.TButton").pack(fill="x")
        self.lbl_opt_status = ttk.Label(optimizer_card, text="No optimization run yet.", style="Subtle.TLabel")
        self.lbl_opt_status.pack(anchor="w", pady=(6, 0))

        ttk.Button(left, text="Calculate", command=self._calculate, style="Primary.TButton").pack(fill="x", pady=(0, 4))

        self.analyzer_notebook = ttk.Notebook(right)
        self.analyzer_notebook.pack(fill="both", expand=True)
        self.summary_frame = ttk.Frame(self.analyzer_notebook)
        self.corr_frame = ttk.Frame(self.analyzer_notebook)
        self.decomp_frame = ttk.Frame(self.analyzer_notebook)
        self.chart_frame = ttk.Frame(self.analyzer_notebook)
        self.analyzer_notebook.add(self.summary_frame, text="Summary")
        self.analyzer_notebook.add(self.corr_frame, text="Correlation")
        self.analyzer_notebook.add(self.decomp_frame, text="Var. Decomposition")
        self.analyzer_notebook.add(self.chart_frame, text="Charts")

    def _build_builder_tab(self):
        self.builder_risk_profile = tk.StringVar(value="Moderate")
        self.builder_model_var = tk.StringVar(value="")
        self.builder_objective_var = tk.StringVar(value=BUILDER_OBJECTIVE_MATCH_RISK)
        self.builder_return_basis_var = tk.StringVar(value=RETURN_BASIS_HISTORICAL)
        self.builder_target_vol_var = tk.DoubleVar(value=10.0)
        self.builder_investment_var = tk.DoubleVar(value=1_000_000.0)
        self.builder_max_cap_var = tk.DoubleVar(value=50.0)
        self.builder_blend_ratio_var = tk.DoubleVar(value=50.0)
        self.builder_benchmark_var = tk.StringVar(value=BENCHMARK_AUTO)

        self._build_builder_wizard()
        self._bind_builder_traces()
        self._render_scenario_rows()
        self._render_builder_step()

    def _build_builder_wizard(self):
        self.builder_tab.columnconfigure(0, weight=1)

        header_card = ttk.LabelFrame(self.builder_tab, text="Portfolio Builder Wizard", style="Card.TLabelframe")
        header_card.pack(fill="x", pady=(0, 8))

        self.builder_step_title_label = ttk.Label(header_card, text="", font=("Segoe UI", 11, "bold"))
        self.builder_step_title_label.pack(anchor="w")
        self.builder_step_progress_label = ttk.Label(header_card, text="", style="Subtle.TLabel")
        self.builder_step_progress_label.pack(anchor="w", pady=(4, 0))

        self.builder_summary_strip = ttk.LabelFrame(self.builder_tab, text="Current Summary", style="Card.TLabelframe")
        self.builder_summary_strip.pack(fill="x", pady=(0, 8))
        self.builder_summary_label_top = ttk.Label(
            self.builder_summary_strip,
            text="Start in Step 1 by loading the model workbook and VaR workbook.",
            justify="left",
        )
        self.builder_summary_label_top.pack(anchor="w")

        self.builder_body = ttk.Frame(self.builder_tab, style="App.TFrame")
        self.builder_body.pack(fill="both", expand=True)

        self.builder_step_frames = []
        for _ in BUILDER_STEPS:
            frame = ttk.Frame(self.builder_body, style="App.TFrame")
            self.builder_step_frames.append(frame)

        self._build_builder_step_load_data(self.builder_step_frames[0])
        self._build_builder_step_settings(self.builder_step_frames[1])
        self._build_builder_step_fund_setup(self.builder_step_frames[2])
        self._build_builder_step_build(self.builder_step_frames[3])
        self._build_builder_step_stress(self.builder_step_frames[4])

        footer = ttk.Frame(self.builder_tab, style="App.TFrame")
        footer.pack(fill="x", pady=(8, 0))
        self.builder_back_button = ttk.Button(footer, text="Back", command=self._go_builder_back, style="Secondary.TButton")
        self.builder_back_button.pack(side="left")
        self.builder_next_button = ttk.Button(footer, text="Next", command=self._go_builder_next, style="Primary.TButton")
        self.builder_next_button.pack(side="left", padx=(6, 0))
        self.builder_status_label = ttk.Label(
            footer,
            text="Load a model workbook and VaR workbook to begin.",
            style="Subtle.TLabel",
        )
        self.builder_status_label.pack(side="left", padx=12)

    def _build_builder_step_load_data(self, parent):
        ttk.Label(
            parent,
            text="Step 1 of 5: Load the source workbooks before setting risk targets or editing funds.",
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        card = ttk.LabelFrame(parent, text="Data Inputs", style="Card.TLabelframe")
        card.pack(fill="x")
        buttons = ttk.Frame(card)
        buttons.pack(fill="x", pady=(0, 8))
        ttk.Button(buttons, text="Load Model Workbook", command=self._load_model_workbook, style="Primary.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Load VaR Workbook", command=self._load_var_workbook, style="Primary.TButton").pack(side="left")

        self.builder_load_model_label = ttk.Label(card, text="Model workbook: none", justify="left")
        self.builder_load_model_label.pack(anchor="w", pady=(2, 0))
        self.builder_load_var_label = ttk.Label(card, text="VaR workbook: none", justify="left")
        self.builder_load_var_label.pack(anchor="w", pady=(2, 0))
        self.builder_load_status_label = ttk.Label(card, text="No workbook data loaded yet.", style="Subtle.TLabel")
        self.builder_load_status_label.pack(anchor="w", pady=(8, 0))

        warning_card = ttk.LabelFrame(parent, text="Parsing Warnings", style="Card.TLabelframe")
        warning_card.pack(fill="both", expand=True, pady=(8, 0))
        self.builder_load_warning_text = tk.Text(warning_card, height=12, wrap="word", bg="#FFFFFF", relief="flat")
        self.builder_load_warning_text.pack(fill="both", expand=True)

    def _build_builder_step_settings(self, parent):
        ttk.Label(
            parent,
            text="Step 2 of 5: Choose the client risk profile, allocation objective, and portfolio-level assumptions.",
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        settings_card = ttk.LabelFrame(parent, text="Portfolio Settings", style="Card.TLabelframe")
        settings_card.pack(fill="x")
        grid = ttk.Frame(settings_card)
        grid.pack(fill="x")

        fields = [
            ("Risk Profile", self.builder_risk_profile, 0, 0, "combo", ["Conservative", "Moderate", "Growth", "Aggressive", "Custom"]),
            ("Target Vol %", self.builder_target_vol_var, 0, 2, "entry", None),
            ("Model Portfolio", self.builder_model_var, 0, 4, "combo", []),
            ("Objective", self.builder_objective_var, 1, 0, "combo", [
                BUILDER_OBJECTIVE_MATCH_RISK,
                BUILDER_OBJECTIVE_MAX_RETURN_UNDER_RISK,
                BUILDER_OBJECTIVE_MIN_VOL,
                BUILDER_OBJECTIVE_BLEND,
                BUILDER_OBJECTIVE_STRESS_ONLY,
            ]),
            ("Return Basis", self.builder_return_basis_var, 1, 2, "combo", [RETURN_BASIS_HISTORICAL, RETURN_BASIS_USER]),
            ("Investment Amount", self.builder_investment_var, 1, 4, "entry", None),
            ("Max Single Fund %", self.builder_max_cap_var, 2, 0, "entry", None),
            ("Benchmark", self.builder_benchmark_var, 2, 2, "combo", [BENCHMARK_AUTO, BENCHMARK_NONE]),
        ]

        self.builder_model_combo = None
        self.builder_benchmark_combo = None
        for label, variable, row, column, widget_type, values in fields:
            ttk.Label(grid, text=label + ":").grid(row=row, column=column, sticky="w", pady=(0, 6))
            if widget_type == "combo":
                combo = ttk.Combobox(grid, textvariable=variable, state="readonly", values=values, width=28)
                combo.grid(row=row, column=column + 1, sticky="w", padx=(6, 20), pady=(0, 6))
                if variable is self.builder_model_var:
                    self.builder_model_combo = combo
                if variable is self.builder_benchmark_var:
                    self.builder_benchmark_combo = combo
            else:
                ttk.Entry(grid, textvariable=variable, width=15).grid(row=row, column=column + 1, sticky="w", padx=(6, 20), pady=(0, 6))

        self.builder_blend_label = ttk.Label(grid, text="Blend Ratio %:")
        self.builder_blend_label.grid(row=2, column=4, sticky="w", pady=(0, 6))
        self.builder_blend_entry = ttk.Entry(grid, textvariable=self.builder_blend_ratio_var, width=15)
        self.builder_blend_entry.grid(row=2, column=5, sticky="w", padx=(6, 20), pady=(0, 6))

        self.builder_objective_help = ttk.LabelFrame(parent, text="Objective Guidance", style="Card.TLabelframe")
        self.builder_objective_help.pack(fill="x", pady=(8, 0))
        self.builder_objective_help_label = ttk.Label(self.builder_objective_help, text="", wraplength=980, justify="left")
        self.builder_objective_help_label.pack(anchor="w")

    def _build_builder_step_fund_setup(self, parent):
        ttk.Label(
            parent,
            text="Step 3 of 5: Review the investable universe, then edit expected returns and min/max constraints if needed.",
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        self.builder_fund_summary_label = ttk.LabelFrame(parent, text="Fund Setup Summary", style="Card.TLabelframe")
        self.builder_fund_summary_label.pack(fill="x")
        self.builder_fund_summary_text = ttk.Label(
            self.builder_fund_summary_label,
            text="Load both workbooks to populate the fund setup table.",
            justify="left",
        )
        self.builder_fund_summary_text.pack(anchor="w")

        universe_card = ttk.LabelFrame(parent, text="Fund Universe, Constraints, and Expected Returns", style="Card.TLabelframe")
        universe_card.pack(fill="both", expand=True, pady=(8, 0))
        universe_outer = ttk.Frame(universe_card)
        universe_outer.pack(fill="both", expand=True)
        self.builder_canvas = tk.Canvas(universe_outer, highlightthickness=0, background="#FFFFFF")
        builder_scroll = ttk.Scrollbar(universe_outer, orient="vertical", command=self.builder_canvas.yview)
        self.builder_rows_frame = ttk.Frame(self.builder_canvas)
        self.builder_rows_frame.bind("<Configure>", lambda e: self.builder_canvas.configure(scrollregion=self.builder_canvas.bbox("all")))
        self.builder_canvas.create_window((0, 0), window=self.builder_rows_frame, anchor="nw")
        self.builder_canvas.configure(yscrollcommand=builder_scroll.set)
        self.builder_canvas.pack(side="left", fill="both", expand=True)
        builder_scroll.pack(side="right", fill="y")

        header = ttk.Frame(self.builder_rows_frame)
        header.pack(fill="x", pady=(0, 4))
        headers = [
            ("Fund", 22),
            ("Model Weight (Workbook / Adjusted)", 26),
            ("Expected Return Input", 18),
            ("Min Weight", 12),
            ("Max Weight", 12),
            ("Category", 18),
            ("Benchmark", 16),
        ]
        for idx, (label, width) in enumerate(headers):
            ttk.Label(header, text=label, width=width, anchor="center", style="Subtle.TLabel").grid(row=0, column=idx)

    def _build_builder_step_build(self, parent):
        ttk.Label(
            parent,
            text="Step 4 of 5: Build the recommended allocation after reviewing your inputs.",
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        action_row = ttk.Frame(parent, style="App.TFrame")
        action_row.pack(fill="x", pady=(0, 8))
        ttk.Button(action_row, text="Build Allocation", command=self._build_portfolio_builder, style="Primary.TButton").pack(side="left")
        ttk.Button(action_row, text="Back to Edit Inputs", command=lambda: self._jump_to_builder_step(2), style="Secondary.TButton").pack(side="left", padx=(6, 0))

        self.builder_output_card = ttk.LabelFrame(parent, text="Recommended Allocation and Comparison", style="Card.TLabelframe")
        self.builder_output_card.pack(fill="both", expand=True, pady=(0, 8))
        summary_card = ttk.Frame(self.builder_output_card)
        summary_card.pack(fill="x", pady=(0, 6))
        self.builder_summary_label = ttk.Label(summary_card, text="No allocation has been built yet.", justify="left")
        self.builder_summary_label.pack(anchor="w")

        alloc_cols = ("Fund", "Model Weight", "Recommended Weight", "Delta", "Expected Return", "Hist Return", "Vol", "Category")
        self.builder_alloc_tree = ttk.Treeview(self.builder_output_card, columns=alloc_cols, show="headings", height=14)
        for col, width in zip(alloc_cols, [190, 90, 115, 80, 100, 100, 85, 140]):
            self.builder_alloc_tree.heading(col, text=col)
            self.builder_alloc_tree.column(col, width=width, anchor="center")
        self.builder_alloc_tree.pack(fill="both", expand=True, pady=(0, 6))

        comp_cols = ("Portfolio", "Expected Return", "Hist Return", "Volatility", "Return / Vol", "Max DD", "VaR 95", "Notes")
        self.builder_comp_tree = ttk.Treeview(self.builder_output_card, columns=comp_cols, show="headings", height=4)
        for col, width in zip(comp_cols, [140, 110, 110, 95, 100, 90, 90, 220]):
            self.builder_comp_tree.heading(col, text=col)
            self.builder_comp_tree.column(col, width=width, anchor="center")
        self.builder_comp_tree.pack(fill="x", pady=(0, 6))

        warnings_card = ttk.LabelFrame(parent, text="Warnings and Explanation", style="Card.TLabelframe")
        warnings_card.pack(fill="x")
        self.builder_explanation = tk.Text(warnings_card, height=9, wrap="word", bg="#FFFFFF", relief="flat")
        self.builder_explanation.pack(fill="both", expand=True)

    def _build_builder_step_stress(self, parent):
        ttk.Label(
            parent,
            text="Step 5 of 5: Optionally stress test the allocation, then export results for the client.",
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        action_row = ttk.Frame(parent, style="App.TFrame")
        action_row.pack(fill="x", pady=(0, 8))
        ttk.Button(action_row, text="Run Stress Tests", command=self._run_builder_stress_tests, style="Primary.TButton").pack(side="left")
        ttk.Button(action_row, text="Export Results", command=self._export, style="Secondary.TButton").pack(side="left", padx=(6, 0))

        stress_card = ttk.LabelFrame(parent, text="Stress Tests", style="Card.TLabelframe")
        stress_card.pack(fill="both", expand=False)

        stress_button_row = ttk.Frame(stress_card)
        stress_button_row.pack(fill="x", pady=(0, 6))
        ttk.Button(stress_button_row, text="Save Scenarios", command=self._save_scenarios, style="Secondary.TButton").pack(side="left", padx=(0, 5))
        ttk.Button(stress_button_row, text="Reset Defaults", command=self._reset_scenarios, style="Secondary.TButton").pack(side="left", padx=(0, 5))
        ttk.Label(stress_button_row, text=f"Scenario presets persist to {SCENARIO_PRESETS_FILE.name}", style="Subtle.TLabel").pack(side="left", padx=10)

        scenario_outer = ttk.Frame(stress_card)
        scenario_outer.pack(fill="both", expand=True)
        scenario_canvas = tk.Canvas(scenario_outer, height=190, highlightthickness=0, background="#FFFFFF")
        scenario_scroll = ttk.Scrollbar(scenario_outer, orient="vertical", command=scenario_canvas.yview)
        self.scenario_frame = ttk.Frame(scenario_canvas)
        self.scenario_frame.bind("<Configure>", lambda e: scenario_canvas.configure(scrollregion=scenario_canvas.bbox("all")))
        scenario_canvas.create_window((0, 0), window=self.scenario_frame, anchor="nw")
        scenario_canvas.configure(yscrollcommand=scenario_scroll.set)
        scenario_canvas.pack(side="left", fill="both", expand=True)
        scenario_scroll.pack(side="right", fill="y")

        header = ttk.Frame(self.scenario_frame)
        header.pack(fill="x", pady=(0, 4))
        for idx, (label, width) in enumerate(
            [("Scenario", 24), ("Target Bucket/Fund", 18), ("Shock %", 9), ("Vol x", 8), ("Corr x", 8), ("Notes", 40)]
        ):
            ttk.Label(header, text=label, width=width, anchor="center", style="Subtle.TLabel").grid(row=0, column=idx)

        stress_cols = ("Scenario", "Model Impact", "Recommended Impact", "Model End Value", "Recommended End Value", "Stressed Vol", "Worst Contributor")
        self.builder_stress_tree = ttk.Treeview(parent, columns=stress_cols, show="headings", height=8)
        for col, width in zip(stress_cols, [170, 110, 135, 125, 145, 110, 170]):
            self.builder_stress_tree.heading(col, text=col)
            self.builder_stress_tree.column(col, width=width, anchor="center")
        self.builder_stress_tree.pack(fill="x", pady=(8, 0))

    def _bind_builder_traces(self):
        self.builder_risk_profile.trace_add("write", lambda *_args: self._on_builder_profile_change())
        self.builder_model_var.trace_add("write", lambda *_args: self._on_builder_model_change())
        self.builder_objective_var.trace_add("write", lambda *_args: self._on_builder_settings_change(settings_only=True))
        self.builder_return_basis_var.trace_add("write", lambda *_args: self._on_builder_settings_change(settings_only=True))
        self.builder_target_vol_var.trace_add("write", lambda *_args: self._on_builder_settings_change(settings_only=True))
        self.builder_investment_var.trace_add("write", lambda *_args: self._on_builder_settings_change(settings_only=True))
        self.builder_max_cap_var.trace_add("write", lambda *_args: self._on_builder_settings_change(settings_only=False))
        self.builder_blend_ratio_var.trace_add("write", lambda *_args: self._on_builder_settings_change(settings_only=True))
        self.builder_benchmark_var.trace_add("write", lambda *_args: self._on_builder_settings_change(settings_only=True))

    def _render_scenario_rows(self):
        for widget in self.scenario_frame.winfo_children()[1:]:
            widget.destroy()
        self.scenario_vars = []

        for item in self.scenario_presets:
            row = ttk.Frame(self.scenario_frame)
            row.pack(fill="x", pady=1)
            values = {
                "scenario": tk.StringVar(value=item["scenario"]),
                "target": tk.StringVar(value=item["target"]),
                "shock_pct": tk.DoubleVar(value=float(item["shock_pct"])),
                "vol_multiplier": tk.DoubleVar(value=float(item["vol_multiplier"])),
                "corr_multiplier": tk.DoubleVar(value=float(item["corr_multiplier"])),
                "notes": tk.StringVar(value=item.get("notes", "")),
            }
            ttk.Entry(row, textvariable=values["scenario"], width=24).grid(row=0, column=0, padx=1)
            ttk.Entry(row, textvariable=values["target"], width=18).grid(row=0, column=1, padx=1)
            ttk.Entry(row, textvariable=values["shock_pct"], width=9, justify="center").grid(row=0, column=2, padx=1)
            ttk.Entry(row, textvariable=values["vol_multiplier"], width=8, justify="center").grid(row=0, column=3, padx=1)
            ttk.Entry(row, textvariable=values["corr_multiplier"], width=8, justify="center").grid(row=0, column=4, padx=1)
            ttk.Entry(row, textvariable=values["notes"], width=40).grid(row=0, column=5, padx=1)
            self.scenario_vars.append(values)

    def _builder_objective_help_text(self):
        objective = self.builder_objective_var.get()
        mapping = {
            BUILDER_OBJECTIVE_MATCH_RISK: "Match the requested annualized volatility as closely as possible, then prefer the higher-return solution among similar risk fits.",
            BUILDER_OBJECTIVE_MAX_RETURN_UNDER_RISK: "Maximize expected return while keeping portfolio volatility at or below the selected target.",
            BUILDER_OBJECTIVE_MIN_VOL: "Find the lowest-volatility feasible portfolio across the matched fund universe.",
            BUILDER_OBJECTIVE_BLEND: "Blend the selected model portfolio with an optimized target-risk portfolio using the chosen blend ratio.",
            BUILDER_OBJECTIVE_STRESS_ONLY: "Skip optimization and use the selected model portfolio only for stress testing and export.",
        }
        return mapping.get(objective, "")

    def _update_builder_objective_help(self):
        if hasattr(self, "builder_objective_help_label"):
            self.builder_objective_help_label.config(text=self._builder_objective_help_text())

    def _update_builder_blend_visibility(self):
        if not hasattr(self, "builder_blend_label"):
            return
        show_blend = self.builder_objective_var.get() == BUILDER_OBJECTIVE_BLEND
        if show_blend:
            self.builder_blend_label.grid()
            self.builder_blend_entry.grid()
        else:
            self.builder_blend_label.grid_remove()
            self.builder_blend_entry.grid_remove()

    def _on_builder_profile_change(self):
        self._sync_builder_profile_defaults()
        self._invalidate_builder_from(2)
        self._refresh_builder_summary()
        self._render_builder_step()

    def _on_builder_model_change(self):
        self._populate_builder_rows()
        self._invalidate_builder_from(2)
        self._refresh_builder_summary()
        self._render_builder_step()

    def _on_builder_settings_change(self, settings_only=True):
        self._update_builder_blend_visibility()
        self._update_builder_objective_help()
        self._invalidate_builder_from(3 if settings_only else 2)
        self._refresh_builder_summary()
        self._render_builder_step()

    def _invalidate_builder_from(self, step_index):
        if step_index <= 3:
            self.builder_result = None
        if step_index <= 4:
            self.builder_stress_results = []
        for idx in range(step_index, len(BUILDER_STEPS)):
            self.builder_step_completed[idx] = False
        if hasattr(self, "builder_alloc_tree"):
            self._show_builder_outputs()

    def _jump_to_builder_step(self, step_index):
        self.builder_step_index = max(0, min(step_index, len(BUILDER_STEPS) - 1))
        self._render_builder_step()

    def _go_builder_next(self):
        valid, message = self._validate_builder_step(self.builder_step_index)
        if not valid:
            self.builder_status_label.config(text=message, foreground="#9A6B00")
            return
        self._mark_builder_step_complete(self.builder_step_index)
        if self.builder_step_index < len(BUILDER_STEPS) - 1:
            self.builder_step_index += 1
        self._render_builder_step()

    def _go_builder_back(self):
        if self.builder_step_index > 0:
            self.builder_step_index -= 1
        self._render_builder_step()

    def _mark_builder_step_complete(self, step_index):
        self.builder_step_completed[step_index] = True

    def _validate_builder_step(self, step_index):
        message = ""
        if step_index == 0:
            valid = bool(self.model_workbook_path and self.var_workbook_path)
            message = "Load both the model workbook and the VaR workbook to continue." if not valid else "Both workbooks loaded."
        elif step_index == 1:
            valid = True
            try:
                if self.builder_model_var.get() not in self.model_portfolios:
                    raise ValueError("Select a valid model portfolio.")
                if float(self.builder_target_vol_var.get()) <= 0:
                    raise ValueError("Target volatility must be positive.")
                if float(self.builder_investment_var.get()) <= 0:
                    raise ValueError("Investment amount must be positive.")
                if float(self.builder_max_cap_var.get()) <= 0:
                    raise ValueError("Max single fund weight must be positive.")
                if self.builder_objective_var.get() == BUILDER_OBJECTIVE_BLEND:
                    blend_ratio = float(self.builder_blend_ratio_var.get())
                    if blend_ratio < 0 or blend_ratio > 100:
                        raise ValueError("Blend ratio must be between 0 and 100.")
                message = "Settings look good."
            except Exception as exc:
                valid = False
                message = str(exc)
        elif step_index == 2:
            valid = True
            try:
                self._collect_builder_inputs()
                message = "Fund-level constraints are feasible."
            except Exception as exc:
                valid = False
                message = str(exc)
        elif step_index == 3:
            valid = self.builder_result is not None
            message = "Run Build Allocation before moving to the stress-test step." if not valid else "Allocation built successfully."
        else:
            valid = self.builder_result is not None
            message = "Stress testing is optional. Export is available once an allocation has been built." if valid else "Build an allocation first."

        self.builder_step_messages[step_index] = message
        return valid, message

    def _refresh_builder_summary(self):
        model_text = os.path.basename(self.model_workbook_path) if self.model_workbook_path else "none"
        var_text = os.path.basename(self.var_workbook_path) if self.var_workbook_path else "none"
        try:
            target_vol_label = f"{float(self.builder_target_vol_var.get()):.2f}%"
        except Exception:
            target_vol_label = "invalid"
        self.builder_summary_label_top.config(
            text=(
                f"Model workbook: {model_text} | "
                f"VaR workbook: {var_text} | "
                f"Risk profile: {self.builder_risk_profile.get()} | "
                f"Model: {self.builder_model_var.get() or 'not selected'} | "
                f"Target vol: {target_vol_label}"
            )
        )

        if hasattr(self, "builder_load_model_label"):
            self.builder_load_model_label.config(text=f"Model workbook: {self.model_workbook_path or 'none'}")
            self.builder_load_var_label.config(text=f"VaR workbook: {self.var_workbook_path or 'none'}")

        load_notes = []
        if self.model_parse_warnings:
            load_notes.extend(self.model_parse_warnings)
        if self.var_parse_warnings:
            load_notes.extend(self.var_parse_warnings)
        if self.builder_unmatched_funds:
            load_notes.append("Unmatched model funds: " + ", ".join(self.builder_unmatched_funds))
        if not load_notes:
            load_notes.append("No parsing warnings. The builder is ready for the next step once both workbooks are loaded.")

        self.builder_load_warning_text.delete("1.0", tk.END)
        self.builder_load_warning_text.insert("1.0", "\n".join(load_notes))

        if self.model_workbook_path and self.var_workbook_path:
            self.builder_load_status_label.config(
                text=f"Matched funds: {len(self.builder_matched_funds)} | Unmatched model funds: {len(self.builder_unmatched_funds)}",
                foreground="green" if not self.builder_unmatched_funds else "#9A6B00",
            )
        else:
            self.builder_load_status_label.config(text="No workbook data loaded yet.", foreground="#4E5D6B")

        self.builder_fund_summary_text.config(
            text=(
                f"Matched funds: {len(self.builder_matched_funds)} | "
                f"Unmatched model funds: {len(self.builder_unmatched_funds)} | "
                f"Model weights renormalized: {'Yes' if self.builder_weights_renormalized else 'No'}"
            )
        )

    def _render_builder_step(self):
        for idx, frame in enumerate(self.builder_step_frames):
            if idx == self.builder_step_index:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()

        step_name = BUILDER_STEPS[self.builder_step_index]
        self.builder_step_title_label.config(text=f"Step {self.builder_step_index + 1} of {len(BUILDER_STEPS)}: {step_name}")

        step_parts = []
        for idx, label in enumerate(BUILDER_STEPS):
            if idx < self.builder_step_index:
                prefix = "✓"
            elif idx == self.builder_step_index:
                prefix = "→"
            else:
                prefix = "•"
            step_parts.append(f"{prefix} {idx + 1}. {label}")
        self.builder_step_progress_label.config(text="   |   ".join(step_parts))

        self._update_builder_blend_visibility()
        self._update_builder_objective_help()
        self._refresh_builder_summary()

        valid, message = self._validate_builder_step(self.builder_step_index)
        status_color = "green" if valid else "#9A6B00"
        self.builder_status_label.config(text=message, foreground=status_color)

        if self.builder_step_index == 0:
            self.builder_back_button.state(["disabled"])
        else:
            self.builder_back_button.state(["!disabled"])

        if self.builder_step_index >= len(BUILDER_STEPS) - 1:
            self.builder_next_button.state(["disabled"])
            self.builder_next_button.config(text="Done")
        else:
            self.builder_next_button.config(text="Next")
            if valid:
                self.builder_next_button.state(["!disabled"])
            else:
                self.builder_next_button.state(["disabled"])

    # ---------- Legacy CSV analyzer ----------

    def _load_csv(self):
        path = filedialog.askopenfilename(title="Select YCharts CSV", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.returns_df, self.stock_names = parse_ycharts_csv(path)
        except Exception as exc:
            messagebox.showerror("Parse Error", str(exc))
            return

        self.lbl_csv_file.config(text=f"CSV: {os.path.basename(path)}")
        self.optimized_result = None
        self.frontier_points = []
        self._populate_stocks()

    def _populate_stocks(self):
        children = self.stock_frame.winfo_children()
        header_widget = children[0] if children else None
        for widget in children[1:]:
            widget.destroy()
        self.stock_widgets = []

        symbols = list(self.returns_df.columns)
        equal_weight = 1.0 / len(symbols) if symbols else 0.0

        try:
            historical = calc_historical_metrics(self.returns_df, ann_factor=self.var_ann.get())
            hist_defaults = {symbol: historical["per_stock"][symbol]["historical_ann_return"] for symbol in symbols}
        except Exception:
            hist_defaults = {symbol: 0.0 for symbol in symbols}

        if header_widget is not None:
            header_widget.pack_forget()
            header_widget.pack(fill="x", pady=(0, 4))

        for symbol in symbols:
            row = ttk.Frame(self.stock_frame)
            row.pack(fill="x", pady=1)

            var_use = tk.BooleanVar(value=True)
            var_weight = tk.DoubleVar(value=equal_weight)
            var_expected = tk.DoubleVar(value=hist_defaults.get(symbol, 0.0) * 100.0)
            var_min = tk.DoubleVar(value=0.0)
            var_max = tk.DoubleVar(value=OPTIMIZER_SINGLE_ASSET_CAP)

            ttk.Checkbutton(row, variable=var_use, command=self._update_wsum).grid(row=0, column=0, padx=(0, 2))
            ttk.Label(row, text=symbol, width=10, anchor="center", font=("Consolas", 10)).grid(row=0, column=1)
            entry_weight = ttk.Entry(row, textvariable=var_weight, width=9, justify="center")
            entry_weight.grid(row=0, column=2, padx=1)
            entry_weight.bind("<KeyRelease>", lambda _e: self._update_wsum())
            ttk.Entry(row, textvariable=var_expected, width=16, justify="center").grid(row=0, column=3, padx=1)
            ttk.Entry(row, textvariable=var_min, width=9, justify="center").grid(row=0, column=4, padx=1)
            ttk.Entry(row, textvariable=var_max, width=9, justify="center").grid(row=0, column=5, padx=1)

            self.stock_widgets.append(
                {
                    "symbol": symbol,
                    "use": var_use,
                    "weight": var_weight,
                    "expected_return_pct": var_expected,
                    "min_weight": var_min,
                    "max_weight": var_max,
                }
            )
        self._update_wsum()

    def _collect_active_inputs(self, require_current_within_bounds=False):
        symbols, weights, expected_returns, min_weights, max_weights = [], [], [], [], []
        for row in self.stock_widgets:
            if not row["use"].get():
                continue
            symbol = row["symbol"]
            try:
                weight = float(row["weight"].get())
                exp_ret = float(row["expected_return_pct"].get()) / 100.0
                min_weight = float(row["min_weight"].get())
                max_weight = float(row["max_weight"].get())
            except tk.TclError:
                raise ValueError(f"Invalid numeric input for {symbol}.")

            symbols.append(symbol)
            weights.append(weight)
            expected_returns.append(exp_ret)
            min_weights.append(min_weight)
            max_weights.append(max_weight)

        if not symbols:
            raise ValueError("Select at least one asset.")

        validate_bounds(min_weights, max_weights, current_weights=weights if require_current_within_bounds else None)
        return {
            "symbols": symbols,
            "weights": np.array(weights, dtype=float),
            "expected_returns": np.array(expected_returns, dtype=float),
            "min_weights": np.array(min_weights, dtype=float),
            "max_weights": np.array(max_weights, dtype=float),
        }

    def _update_wsum(self):
        total = 0.0
        for row in self.stock_widgets:
            if row["use"].get():
                try:
                    total += float(row["weight"].get())
                except tk.TclError:
                    pass
        color = "green" if abs(total - 1.0) < 1e-3 else "red"
        self.lbl_wsum.config(text=f"Weight sum: {total:.4f}", foreground=color)

    def _equal_weight(self):
        try:
            data = self._collect_active_inputs(False)
            n_assets = len(data["symbols"])
            weights = adjust_weights_to_bounds(np.full(n_assets, 1.0 / n_assets), data["min_weights"], data["max_weights"])
        except Exception as exc:
            messagebox.showerror("Equal Weight Error", str(exc))
            return

        idx = 0
        for row in self.stock_widgets:
            if row["use"].get():
                row["weight"].set(float(weights[idx]))
                idx += 1
            else:
                row["weight"].set(0.0)
        self._update_wsum()

    def _normalize(self):
        try:
            data = self._collect_active_inputs(False)
            weights = data["weights"].copy()
            if weights.sum() <= 0:
                raise ValueError("Active weights must sum to a positive number to normalize.")
            weights = weights / weights.sum()
            weights = adjust_weights_to_bounds(weights, data["min_weights"], data["max_weights"])
        except Exception as exc:
            messagebox.showerror("Normalize Error", str(exc))
            return

        idx = 0
        for row in self.stock_widgets:
            if row["use"].get():
                row["weight"].set(float(weights[idx]))
                idx += 1
        self._update_wsum()

    def _calculate(self):
        if self.returns_df is None:
            messagebox.showinfo("Info", "Load a CSV file first.")
            return

        try:
            data = self._collect_active_inputs(require_current_within_bounds=True)
        except Exception as exc:
            messagebox.showerror("Input Error", str(exc))
            return

        symbols = data["symbols"]
        weights = data["weights"]
        expected = data["expected_returns"]
        min_weights = data["min_weights"]
        max_weights = data["max_weights"]

        if abs(weights.sum() - 1.0) > 0.01:
            if not messagebox.askyesno("Warning", f"Weights sum to {weights.sum():.4f}, not 1.0.\nNormalize and continue?"):
                return
            try:
                weights = adjust_weights_to_bounds(weights / weights.sum(), min_weights, max_weights)
            except Exception as exc:
                messagebox.showerror("Weight Error", str(exc))
                return
            idx = 0
            for row in self.stock_widgets:
                if row["use"].get():
                    row["weight"].set(float(weights[idx]))
                    idx += 1
            self._update_wsum()

        sub_df = self.returns_df[symbols]
        ann_factor = self.var_ann.get()
        try:
            hist = calc_historical_metrics(sub_df, ann_factor=ann_factor)
        except Exception as exc:
            messagebox.showerror("Calculation Error", str(exc))
            return

        clean = hist["clean_returns"]
        cov_annual = hist["cov_annual"]
        corr = hist["corr_matrix"]
        per_stock_hist = hist["per_stock"]

        asset_rows = []
        for idx, symbol in enumerate(symbols):
            item = per_stock_hist[symbol]
            vol = item["historical_volatility"]
            exp_return = float(expected[idx])
            asset_rows.append(
                {
                    "symbol": symbol,
                    "name": self.stock_names.get(symbol, ""),
                    "weight": float(weights[idx]),
                    "min_weight": float(min_weights[idx]),
                    "max_weight": float(max_weights[idx]),
                    "effective_max_weight": float(min(max_weights[idx], OPTIMIZER_SINGLE_ASSET_CAP)),
                    "expected_ann_return": exp_return,
                    "historical_ann_return": item["historical_ann_return"],
                    "volatility": vol,
                    "expected_return_over_volatility": (exp_return / vol if vol > 0 else 0.0),
                    "historical_total_return": item["historical_total_return"],
                    "historical_max_drawdown": item["historical_max_drawdown"],
                }
            )

        current_hist = calc_portfolio_historical_metrics(clean, weights, ann_factor=ann_factor)
        current_fwd = calc_forward_portfolio_metrics(weights, expected, cov_annual)
        current = {
            "weights": weights,
            "expected_ann_return": current_fwd["expected_ann_return"],
            "historical_ann_return": current_hist["historical_ann_return"],
            "volatility": current_fwd["volatility"],
            "expected_return_over_volatility": current_fwd["expected_return_over_volatility"],
            "historical_total_return": current_hist["historical_total_return"],
            "historical_max_drawdown": current_hist["historical_max_drawdown"],
            "variance": current_fwd["variance"],
            "cumulative_series": current_hist["cumulative_series"],
            "drawdown_series": current_hist["drawdown_series"],
            "var_95": calc_portfolio_var_95(current_fwd["volatility"], ann_factor=ann_factor),
        }
        current_decomp = build_variance_decomposition(symbols, weights, cov_annual)

        optimized_portfolio = None
        optimized_decomposition = None
        optimized_weights = None
        if self.optimized_result is not None and self.optimized_result.get("symbols") == symbols:
            optimized_weights = np.array(self.optimized_result["weights"], dtype=float)
            opt_hist = calc_portfolio_historical_metrics(clean, optimized_weights, ann_factor=ann_factor)
            opt_fwd = calc_forward_portfolio_metrics(optimized_weights, expected, cov_annual)
            optimized_portfolio = {
                "weights": optimized_weights,
                "mode_used": self.optimized_result.get("mode", ""),
                "target_volatility": self.optimized_result.get("target_volatility"),
                "expected_ann_return": opt_fwd["expected_ann_return"],
                "historical_ann_return": opt_hist["historical_ann_return"],
                "volatility": opt_fwd["volatility"],
                "expected_return_over_volatility": opt_fwd["expected_return_over_volatility"],
                "historical_total_return": opt_hist["historical_total_return"],
                "historical_max_drawdown": opt_hist["historical_max_drawdown"],
                "variance": opt_fwd["variance"],
                "cumulative_series": opt_hist["cumulative_series"],
                "drawdown_series": opt_hist["drawdown_series"],
                "var_95": calc_portfolio_var_95(opt_fwd["volatility"], ann_factor=ann_factor),
                "cap_enforced": bool(self.optimized_result.get("cap_enforced", True)),
                "effective_max_weights": self.optimized_result.get("effective_max_weights"),
            }
            optimized_decomposition = build_variance_decomposition(symbols, optimized_weights, cov_annual)
        elif self.optimized_result is not None:
            self.optimized_result = None
            self.frontier_points = []

        self.metrics = {
            "symbols": symbols,
            "asset_rows": asset_rows,
            "clean_returns": clean,
            "corr_matrix": corr,
            "cov_matrix": cov_annual,
            "current_portfolio": current,
            "optimized_portfolio": optimized_portfolio,
            "current_decomposition": current_decomp,
            "optimized_decomposition": optimized_decomposition,
            "selected_mode": self.var_mode.get(),
            "target_volatility": self.var_target_vol.get() / 100.0 if self.var_mode.get() == MODE_MAX_RET_TARGET_RISK else None,
            "n_periods": hist["n_periods"],
        }

        self._show_summary()
        self._show_correlation()
        self._show_decomposition()
        self._show_charts(expected, optimized_weights)

    def _optimize_portfolio(self):
        if self.returns_df is None:
            messagebox.showinfo("Info", "Load a CSV file first.")
            return
        mode = self.var_mode.get()
        if mode == MODE_MANUAL:
            messagebox.showinfo("Info", "Select an optimization mode other than Manual.")
            return
        if not HAS_SCIPY:
            messagebox.showerror("Optimization Unavailable", "scipy is not installed.\nInstall with: pip install scipy")
            return

        try:
            data = self._collect_active_inputs(False)
            symbols = data["symbols"]
            expected_returns = data["expected_returns"]
            min_weights = data["min_weights"]
            max_weights = data["max_weights"]
            initial_weights = data["weights"]
            hist = calc_historical_metrics(self.returns_df[symbols], ann_factor=self.var_ann.get())
            target_vol = float(self.var_target_vol.get()) / 100.0 if mode == MODE_MAX_RET_TARGET_RISK else None

            optimized = optimize_portfolio(
                mode,
                expected_returns,
                hist["cov_annual"],
                min_weights,
                max_weights,
                target_volatility=target_vol,
                initial_weights=initial_weights,
                max_single_weight=OPTIMIZER_SINGLE_ASSET_CAP,
            )
            self.optimized_result = {
                "symbols": symbols,
                "weights": optimized["weights"],
                "mode": mode,
                "target_volatility": target_vol,
                "cap_enforced": optimized["cap_enforced"],
                "effective_max_weights": optimized["effective_max_weights"],
            }
            self.frontier_points = build_efficient_frontier(expected_returns, hist["cov_annual"], min_weights, max_weights, points=22)
            self.lbl_opt_status.config(
                text=(
                    f"Optimized: {mode} | Exp Return {optimized['expected_ann_return']:.2%}, "
                    f"Vol {optimized['volatility']:.2%}, ExpRet/Vol {optimized['expected_return_over_volatility']:.3f}"
                ),
                foreground="green",
            )
            self._calculate()
        except Exception as exc:
            messagebox.showerror("Optimization Error", str(exc))

    def _apply_optimized_weights(self):
        if self.optimized_result is None:
            messagebox.showinfo("Info", "Run optimization first.")
            return
        symbol_to_weight = dict(zip(self.optimized_result.get("symbols", []), self.optimized_result.get("weights", [])))
        for row in self.stock_widgets:
            symbol = row["symbol"]
            if row["use"].get() and symbol in symbol_to_weight:
                row["weight"].set(float(symbol_to_weight[symbol]))
        self._update_wsum()
        self._calculate()

    def _show_summary(self):
        for widget in self.summary_frame.winfo_children():
            widget.destroy()
        if self.metrics is None:
            return

        ttk.Label(self.summary_frame, text="Asset Metrics (Historical vs Forward-Looking)", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        cols = (
            "Asset",
            "Name",
            "Weight",
            "Expected Ann Return",
            "Historical Ann Return",
            "Volatility",
            "Expected Return / Volatility",
            "Historical Total Return",
            "Historical Max DD",
            "Min W",
            "Max W",
            "Eff Max W",
        )
        tree = ttk.Treeview(self.summary_frame, columns=cols, show="headings", height=min(12, len(self.metrics["asset_rows"]) + 1))
        for col, width in zip(cols, [70, 150, 70, 120, 120, 95, 140, 115, 105, 70, 70, 90]):
            tree.heading(col, text=col)
            tree.column(col, width=width, anchor="center")
        for item in self.metrics["asset_rows"]:
            tree.insert(
                "",
                "end",
                values=(
                    item["symbol"],
                    item["name"],
                    f"{item['weight']:.2%}",
                    f"{item['expected_ann_return']:.2%}",
                    f"{item['historical_ann_return']:.2%}",
                    f"{item['volatility']:.2%}",
                    f"{item['expected_return_over_volatility']:.3f}",
                    f"{item['historical_total_return']:.2%}",
                    f"{item['historical_max_drawdown']:.2%}",
                    f"{item['min_weight']:.2%}",
                    f"{item['max_weight']:.2%}",
                    f"{item['effective_max_weight']:.2%}",
                ),
            )
        tree.pack(fill="x", pady=5)

        ttk.Label(self.summary_frame, text="Portfolio Comparison (Current vs Optimized)", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(8, 0))
        pcols = ("Portfolio", "Mode", "Expected Ann Return", "Historical Ann Return", "Volatility", "Return / Vol", "Historical Max DD", "VaR 95", "Cap Enforced")
        tree2 = ttk.Treeview(self.summary_frame, columns=pcols, show="headings", height=3)
        for col, width in zip(pcols, [140, 160, 120, 120, 95, 100, 100, 90, 100]):
            tree2.heading(col, text=col)
            tree2.column(col, width=width, anchor="center")
        cur = self.metrics["current_portfolio"]
        tree2.insert(
            "",
            "end",
            values=(
                "Current Portfolio",
                MODE_MANUAL,
                f"{cur['expected_ann_return']:.2%}",
                f"{cur['historical_ann_return']:.2%}",
                f"{cur['volatility']:.2%}",
                f"{cur['expected_return_over_volatility']:.3f}",
                f"{cur['historical_max_drawdown']:.2%}",
                f"{cur['var_95']:.2%}",
                "Yes",
            ),
        )
        opt = self.metrics.get("optimized_portfolio")
        if opt:
            tree2.insert(
                "",
                "end",
                values=(
                    "Optimized Portfolio",
                    opt["mode_used"],
                    f"{opt['expected_ann_return']:.2%}",
                    f"{opt['historical_ann_return']:.2%}",
                    f"{opt['volatility']:.2%}",
                    f"{opt['expected_return_over_volatility']:.3f}",
                    f"{opt['historical_max_drawdown']:.2%}",
                    f"{opt['var_95']:.2%}",
                    "Yes" if opt.get("cap_enforced", True) else "No",
                ),
                tags=("optimized",),
            )
            tree2.tag_configure("optimized", background="#DFF1DE")
        tree2.pack(fill="x", pady=5)

        target_vol = self.metrics["target_volatility"]
        target_vol_label = f"{target_vol:.2%}" if target_vol is not None else "N/A"
        ttk.Label(
            self.summary_frame,
            text=(
                f"Based on {self.metrics['n_periods']} monthly periods | "
                f"Mode: {self.metrics['selected_mode']} | Target vol: {target_vol_label}"
            ),
            foreground="gray",
        ).pack(anchor="w", pady=(4, 0))

    def _show_correlation(self):
        for widget in self.corr_frame.winfo_children():
            widget.destroy()
        if self.metrics is None:
            return
        symbols = self.metrics["symbols"]
        corr = self.metrics["corr_matrix"]
        cov = self.metrics["cov_matrix"]
        cols = [""] + symbols

        ttk.Label(self.corr_frame, text="Correlation Matrix", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tree = ttk.Treeview(self.corr_frame, columns=cols, show="headings", height=len(symbols))
        tree.heading("", text="")
        tree.column("", width=60, anchor="center")
        for symbol in symbols:
            tree.heading(symbol, text=symbol)
            tree.column(symbol, width=90, anchor="center")
        for row_symbol in symbols:
            tree.insert("", "end", values=[row_symbol] + [f"{corr.loc[row_symbol, col_symbol]:.4f}" for col_symbol in symbols])
        tree.pack(fill="x", pady=5)

        ttk.Label(self.corr_frame, text="Annualized Covariance Matrix", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(8, 0))
        tree2 = ttk.Treeview(self.corr_frame, columns=cols, show="headings", height=len(symbols))
        tree2.heading("", text="")
        tree2.column("", width=60, anchor="center")
        for symbol in symbols:
            tree2.heading(symbol, text=symbol)
            tree2.column(symbol, width=105, anchor="center")
        for row_symbol in symbols:
            tree2.insert("", "end", values=[row_symbol] + [f"{cov.loc[row_symbol, col_symbol]:.6f}" for col_symbol in symbols])
        tree2.pack(fill="x", pady=5)

    def _show_decomposition(self):
        for widget in self.decomp_frame.winfo_children():
            widget.destroy()
        if self.metrics is None:
            return
        cols = ("Portfolio", "Component", "Variance Contribution", "% of Total")
        tree = ttk.Treeview(self.decomp_frame, columns=cols, show="headings", height=20)
        for col, width in zip(cols, [130, 260, 160, 110]):
            tree.heading(col, text=col)
            tree.column(col, width=width, anchor="center")
        current_var = self.metrics["current_portfolio"]["variance"]
        for label, value in self.metrics["current_decomposition"].items():
            pct = value / current_var if current_var > 0 else 0.0
            tree.insert("", "end", values=("Current Portfolio", label, f"{value:.6f}", f"{pct:.2%}"))
        opt_decomp = self.metrics.get("optimized_decomposition")
        opt_port = self.metrics.get("optimized_portfolio")
        if opt_decomp and opt_port:
            tree.insert("", "end", values=("", "", "", ""))
            opt_var = opt_port["variance"]
            for label, value in opt_decomp.items():
                pct = value / opt_var if opt_var > 0 else 0.0
                tree.insert("", "end", values=("Optimized Portfolio", label, f"{value:.6f}", f"{pct:.2%}"), tags=("opt",))
            tree.tag_configure("opt", background="#E8F3FF")
        tree.pack(fill="both", expand=True, pady=5)

    def _show_charts(self, expected_returns, optimized_weights):
        for widget in self.chart_frame.winfo_children():
            widget.destroy()
        if not HAS_MATPLOTLIB:
            ttk.Label(self.chart_frame, text="Install matplotlib for charts:\npip install matplotlib", foreground="gray").pack(expand=True)
            return
        if self.metrics is None:
            return

        fig = Figure(figsize=(12, 8), dpi=96)
        clean = self.metrics["clean_returns"]
        symbols = self.metrics["symbols"]

        ax1 = fig.add_subplot(2, 2, 1)
        for symbol in symbols:
            cumulative = (1.0 + clean[symbol]).cumprod()
            ax1.plot(cumulative.index, cumulative.values, label=symbol, linewidth=1.0)
        current_cum = self.metrics["current_portfolio"]["cumulative_series"]
        ax1.plot(current_cum.index, current_cum.values, label="Current Portfolio", linewidth=2.1, color="black")
        if self.metrics.get("optimized_portfolio"):
            opt_cum = self.metrics["optimized_portfolio"]["cumulative_series"]
            ax1.plot(opt_cum.index, opt_cum.values, label="Optimized Portfolio", linewidth=2.0, linestyle="--", color="#0E7C86")
        ax1.set_title("Historical Cumulative Returns", fontsize=10)
        ax1.grid(True, alpha=0.3)
        ax1.legend(fontsize=7)

        ax2 = fig.add_subplot(2, 2, 2)
        vols = [item["volatility"] for item in self.metrics["asset_rows"]]
        exps = [expected_returns[idx] for idx in range(len(symbols))]
        ax2.scatter(vols, exps, s=45, c="#4472C4", label="Assets")
        for idx, symbol in enumerate(symbols):
            ax2.annotate(symbol, (vols[idx], exps[idx]), fontsize=8, xytext=(4, 2), textcoords="offset points")
        cur = self.metrics["current_portfolio"]
        ax2.scatter([cur["volatility"]], [cur["expected_ann_return"]], s=85, c="black", label="Current Portfolio")
        if optimized_weights is not None and self.metrics.get("optimized_portfolio"):
            opt = self.metrics["optimized_portfolio"]
            ax2.scatter([opt["volatility"]], [opt["expected_ann_return"]], s=90, c="#0E7C86", marker="D", label="Optimized Portfolio")
        if self.frontier_points:
            frontier_vols = [item[0] for item in self.frontier_points]
            frontier_returns = [item[1] for item in self.frontier_points]
            ax2.plot(frontier_vols, frontier_returns, color="#ED7D31", linewidth=1.5, label="Efficient Frontier")
        ax2.set_title("Expected Return vs Volatility", fontsize=10)
        ax2.grid(True, alpha=0.3)
        ax2.legend(fontsize=7)

        ax3 = fig.add_subplot(2, 2, 3)
        cur_dd = self.metrics["current_portfolio"]["drawdown_series"]
        ax3.plot(cur_dd.index, cur_dd.values, label="Current Portfolio", color="black", linewidth=1.8)
        if self.metrics.get("optimized_portfolio"):
            opt_dd = self.metrics["optimized_portfolio"]["drawdown_series"]
            ax3.plot(opt_dd.index, opt_dd.values, label="Optimized Portfolio", color="#0E7C86", linewidth=1.8, linestyle="--")
        ax3.set_title("Historical Drawdown", fontsize=10)
        ax3.grid(True, alpha=0.3)
        ax3.legend(fontsize=7)

        ax4 = fig.add_subplot(2, 2, 4)
        current_weights = [item["weight"] for item in self.metrics["asset_rows"]]
        x = np.arange(len(symbols))
        width = 0.38
        ax4.bar(x - width / 2, current_weights, width=width, label="Current", color="#7A8FA6")
        if optimized_weights is not None:
            ax4.bar(x + width / 2, optimized_weights, width=width, label="Optimized", color="#0E7C86")
        ax4.set_xticks(x)
        ax4.set_xticklabels(symbols, rotation=45, ha="right", fontsize=7)
        ax4.set_title("Weight Comparison", fontsize=10)
        ax4.legend(fontsize=7)
        ax4.grid(True, alpha=0.25, axis="y")

        fig.tight_layout()
        canvas = FigureCanvasTkAgg(fig, master=self.chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    # ---------- Workbook loading ----------

    def _load_model_workbook(self):
        path = filedialog.askopenfilename(
            title="Select Model Portfolio Workbook",
            initialdir=str(APP_DIR),
            filetypes=[("Excel files", "*.xlsx *.xlsm"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self.model_portfolios, self.model_parse_warnings = parse_model_workbook(path)
        except Exception as exc:
            messagebox.showerror("Model Workbook Error", str(exc))
            return
        self.model_workbook_path = path
        self.lbl_model_file.config(text=f"Model workbook: {os.path.basename(path)}")
        self._refresh_builder_options()

    def _load_var_workbook(self):
        path = filedialog.askopenfilename(
            title="Select VaR / Volatility Workbook",
            initialdir=str(APP_DIR),
            filetypes=[("Excel files", "*.xlsx *.xlsm"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            parsed = parse_var_workbook(path)
        except Exception as exc:
            messagebox.showerror("VaR Workbook Error", str(exc))
            return
        self.var_workbook_path = path
        self.var_returns_df = parsed["returns"]
        self.var_all_series_df = parsed["all_series"]
        self.var_fund_info = parsed["fund_info"]
        self.var_benchmark_series = parsed["benchmark_series"]
        self.var_benchmark_candidates = parsed["benchmark_candidates"]
        self.var_parse_warnings = parsed["warnings"]
        self.lbl_var_file.config(text=f"VaR workbook: {os.path.basename(path)}")
        self._refresh_builder_options()

    def _refresh_builder_options(self):
        model_names = list(self.model_portfolios.keys())
        if self.builder_model_combo is not None:
            self.builder_model_combo["values"] = model_names
        if model_names and not self.builder_model_var.get():
            default_model = RISK_PROFILE_TO_MODEL.get(self.builder_risk_profile.get(), model_names[0])
            self.builder_model_var.set(default_model if default_model in self.model_portfolios else model_names[0])

        benchmark_values = [BENCHMARK_AUTO, BENCHMARK_NONE] + sorted(set(self.var_benchmark_candidates + list(self.var_benchmark_series.keys())))
        if self.builder_benchmark_combo is not None:
            self.builder_benchmark_combo["values"] = benchmark_values

        self._sync_builder_profile_defaults()
        self._populate_builder_rows()
        self._invalidate_builder_from(1)
        self._refresh_builder_summary()
        self._render_builder_step()

    def _sync_builder_profile_defaults(self):
        profile = self.builder_risk_profile.get()
        model_name = self.builder_model_var.get()

        if profile in RISK_PROFILE_TO_MODEL:
            mapped = RISK_PROFILE_TO_MODEL[profile]
            if mapped in self.model_portfolios:
                model_name = mapped
                self.builder_model_var.set(mapped)

        if profile == "Custom" and self.builder_target_vol_var.get() > 0:
            return

        target_vol = None
        if model_name and model_name in self.model_portfolios:
            target_vol = self.model_portfolios[model_name].get("portfolio_volatility")
        if target_vol is None and model_name and self.var_returns_df is not None and model_name in self.model_portfolios:
            target_vol = self._estimate_model_volatility(model_name)
        if target_vol is None:
            fallback_key = model_name or profile
            target_vol = FALLBACK_PROFILE_VOLS.get(fallback_key, FALLBACK_PROFILE_VOLS.get("MA", 0.10))
            if profile == "Aggressive":
                target_vol = FALLBACK_PROFILE_VOLS["Aggressive"]
        self.builder_target_vol_var.set(round(target_vol * 100.0, 2))

    def _estimate_model_volatility(self, model_name):
        if self.var_returns_df is None or model_name not in self.model_portfolios:
            return None
        universe = list(self.var_returns_df.columns)
        model_weights, matched, _ = build_model_weight_vector(self.model_portfolios[model_name], universe)
        if not matched or model_weights.sum() <= 0:
            return None
        try:
            risk_model = build_pairwise_risk_model(self.var_returns_df[universe], ann_factor=self.var_ann.get())
            return calc_portfolio_volatility(model_weights, risk_model["cov_annual"])
        except Exception:
            return None

    # ---------- Builder UI helpers ----------

    def _populate_builder_rows(self):
        for widget in self.builder_rows_frame.winfo_children()[1:]:
            widget.destroy()
        self.builder_widgets = []
        self.builder_matched_funds = []
        self.builder_unmatched_funds = []
        self.builder_weights_renormalized = False

        if self.var_returns_df is None:
            self.builder_fund_summary_text.config(text="Load the VaR workbook to populate the fund setup table.")
            return

        model_name = self.builder_model_var.get()
        model_info = self.model_portfolios.get(model_name, {"funds": [], "benchmark": "SP 500"})
        universe = list(self.var_returns_df.columns)
        model_weights, matched, unmatched = build_model_weight_vector(model_info, universe)
        self.builder_matched_funds = matched
        self.builder_unmatched_funds = unmatched
        self.builder_weights_renormalized = bool(unmatched)

        try:
            risk_model = build_pairwise_risk_model(self.var_returns_df[universe], ann_factor=self.var_ann.get())
            hist_returns = {sym: risk_model["per_stock"][sym]["historical_ann_return"] for sym in universe}
        except Exception:
            hist_returns = {sym: 0.0 for sym in universe}

        ordered = sorted(
            universe,
            key=lambda name: (-model_weights[universe.index(name)], name),
        )

        for symbol in ordered:
            idx = universe.index(symbol)
            row = ttk.Frame(self.builder_rows_frame)
            row.pack(fill="x", pady=1)

            model_weight = float(model_weights[idx])
            metadata = self.var_fund_info.get(symbol, {})
            category = metadata.get("style") or metadata.get("source_sheet", "")
            benchmark = metadata.get("benchmark") or FUND_METADATA.get(symbol, {}).get("benchmark", "")

            var_model = tk.DoubleVar(value=round(model_weight * 100.0, 3))
            var_expected = tk.DoubleVar(value=round(hist_returns.get(symbol, 0.0) * 100.0, 3))
            var_min = tk.DoubleVar(value=0.0)
            var_max = tk.DoubleVar(value=round(min(OPTIMIZER_SINGLE_ASSET_CAP, 0.5) * 100.0, 2))

            for var in (var_model, var_expected, var_min, var_max):
                var.trace_add("write", lambda *_args: self._on_builder_fund_edit())

            ttk.Label(row, text=symbol, width=22, anchor="w").grid(row=0, column=0, sticky="w")
            ttk.Entry(row, textvariable=var_model, width=13, justify="center").grid(row=0, column=1, padx=1)
            ttk.Entry(row, textvariable=var_expected, width=12, justify="center").grid(row=0, column=2, padx=1)
            ttk.Entry(row, textvariable=var_min, width=10, justify="center").grid(row=0, column=3, padx=1)
            ttk.Entry(row, textvariable=var_max, width=10, justify="center").grid(row=0, column=4, padx=1)
            ttk.Label(row, text=category, width=18, anchor="w").grid(row=0, column=5, padx=1, sticky="w")
            ttk.Label(row, text=benchmark, width=14, anchor="w").grid(row=0, column=6, padx=1, sticky="w")

            self.builder_widgets.append(
                {
                    "symbol": symbol,
                    "model_weight_pct": var_model,
                    "expected_return_pct": var_expected,
                    "min_weight_pct": var_min,
                    "max_weight_pct": var_max,
                    "category": category,
                    "benchmark": benchmark,
                }
            )

        self._refresh_builder_summary()

    def _on_builder_fund_edit(self):
        self._invalidate_builder_from(3)
        if hasattr(self, "builder_step_index") and self.builder_step_index >= 2:
            self._render_builder_step()

    def _render_scenario_rows(self):
        for widget in self.scenario_frame.winfo_children()[1:]:
            widget.destroy()
        self.scenario_vars = []

        for item in self.scenario_presets:
            row = ttk.Frame(self.scenario_frame)
            row.pack(fill="x", pady=1)
            values = {
                "scenario": tk.StringVar(value=item["scenario"]),
                "target": tk.StringVar(value=item["target"]),
                "shock_pct": tk.DoubleVar(value=float(item["shock_pct"])),
                "vol_multiplier": tk.DoubleVar(value=float(item["vol_multiplier"])),
                "corr_multiplier": tk.DoubleVar(value=float(item["corr_multiplier"])),
                "notes": tk.StringVar(value=item.get("notes", "")),
            }
            ttk.Entry(row, textvariable=values["scenario"], width=24).grid(row=0, column=0, padx=1)
            ttk.Entry(row, textvariable=values["target"], width=18).grid(row=0, column=1, padx=1)
            ttk.Entry(row, textvariable=values["shock_pct"], width=9, justify="center").grid(row=0, column=2, padx=1)
            ttk.Entry(row, textvariable=values["vol_multiplier"], width=8, justify="center").grid(row=0, column=3, padx=1)
            ttk.Entry(row, textvariable=values["corr_multiplier"], width=8, justify="center").grid(row=0, column=4, padx=1)
            ttk.Entry(row, textvariable=values["notes"], width=40).grid(row=0, column=5, padx=1)
            self.scenario_vars.append(values)

    def _collect_scenario_rows(self):
        rows = []
        for item in self.scenario_vars:
            rows.append(
                {
                    "scenario": item["scenario"].get().strip(),
                    "target": item["target"].get().strip(),
                    "shock_pct": float(item["shock_pct"].get()),
                    "vol_multiplier": float(item["vol_multiplier"].get()),
                    "corr_multiplier": float(item["corr_multiplier"].get()),
                    "notes": item["notes"].get().strip(),
                }
            )
        rows = [row for row in rows if row["scenario"] and row["target"]]
        return rows

    def _save_scenarios(self):
        try:
            rows = self._collect_scenario_rows()
            save_scenario_presets(rows)
            self.scenario_presets = rows
            messagebox.showinfo("Saved", f"Scenario presets saved to {SCENARIO_PRESETS_FILE}")
        except Exception as exc:
            messagebox.showerror("Scenario Save Error", str(exc))

    def _reset_scenarios(self):
        self.scenario_presets = scenario_defaults()
        self._render_scenario_rows()

    # ---------- Builder calculations ----------

    def _collect_builder_inputs(self):
        if self.var_returns_df is None:
            raise ValueError("Load the VaR workbook first.")
        if not self.model_portfolios:
            raise ValueError("Load the model workbook first.")

        symbols = []
        model_weights = []
        expected_returns = []
        min_weights = []
        max_weights = []
        categories = []
        benchmarks = []

        max_single = float(self.builder_max_cap_var.get()) / 100.0
        if max_single <= 0:
            raise ValueError("Max single fund weight must be positive.")

        for row in self.builder_widgets:
            symbol = row["symbol"]
            symbols.append(symbol)
            model_weights.append(float(row["model_weight_pct"].get()) / 100.0)
            expected_returns.append(float(row["expected_return_pct"].get()) / 100.0)
            min_weights.append(float(row["min_weight_pct"].get()) / 100.0)
            max_weights.append(min(float(row["max_weight_pct"].get()) / 100.0, max_single))
            categories.append(row["category"])
            benchmarks.append(row["benchmark"])

        validate_bounds(min_weights, max_weights)

        model_weights = np.array(model_weights, dtype=float)
        if model_weights.sum() > 0:
            model_weights = model_weights / model_weights.sum()
            model_weights = adjust_weights_to_bounds(model_weights, min_weights, max_weights)
        else:
            model_weights = adjust_weights_to_bounds(np.full(len(symbols), 1.0 / len(symbols)), min_weights, max_weights)

        return {
            "symbols": symbols,
            "model_weights": model_weights,
            "expected_returns_user": np.array(expected_returns, dtype=float),
            "min_weights": np.array(min_weights, dtype=float),
            "max_weights": np.array(max_weights, dtype=float),
            "categories": categories,
            "benchmarks": benchmarks,
            "max_single_weight": max_single,
        }

    def _build_portfolio_builder(self):
        try:
            builder = self._compute_builder_result(run_stress=False)
        except Exception as exc:
            messagebox.showerror("Portfolio Builder Error", str(exc))
            return

        self.builder_result = builder
        self.builder_stress_results = []
        self.builder_step_completed[3] = True
        self.builder_step_completed[4] = False
        self._show_builder_outputs()
        self.builder_status_label.config(text="Recommended allocation built successfully. Continue to Stress Test & Export when ready.", foreground="green")
        self._render_builder_step()

    def _compute_builder_result(self, run_stress=False):
        inputs = self._collect_builder_inputs()
        symbols = inputs["symbols"]
        model_name = self.builder_model_var.get()
        if model_name not in self.model_portfolios:
            raise ValueError("Select a valid model portfolio.")

        risk_model = build_pairwise_risk_model(self.var_returns_df[symbols], ann_factor=self.var_ann.get())
        per_stock = risk_model["per_stock"]
        cov_annual = risk_model["cov_annual"]
        corr_matrix = risk_model["corr_matrix"]
        historical_expected = np.array([per_stock[sym]["historical_ann_return"] for sym in symbols], dtype=float)
        selected_return_basis = self.builder_return_basis_var.get()
        return_vector = select_return_vector(symbols, per_stock, inputs["expected_returns_user"], selected_return_basis)

        target_vol = float(self.builder_target_vol_var.get()) / 100.0
        if target_vol <= 0:
            raise ValueError("Target volatility must be positive.")
        investment_amount = float(self.builder_investment_var.get())
        objective = self.builder_objective_var.get()
        blend_ratio = float(self.builder_blend_ratio_var.get()) / 100.0
        blend_ratio = min(max(blend_ratio, 0.0), 1.0)

        model_weights = inputs["model_weights"]
        baseline_hist = calc_portfolio_historical_metrics(self.var_returns_df[symbols], model_weights, ann_factor=self.var_ann.get())
        baseline_forward = calc_forward_portfolio_metrics(model_weights, return_vector, cov_annual)
        baseline = {
            "weights": model_weights,
            "expected_ann_return": baseline_forward["expected_ann_return"],
            "historical_ann_return": baseline_hist["historical_ann_return"],
            "volatility": baseline_forward["volatility"],
            "expected_return_over_volatility": baseline_forward["expected_return_over_volatility"],
            "historical_total_return": baseline_hist["historical_total_return"],
            "historical_max_drawdown": baseline_hist["historical_max_drawdown"],
            "variance": baseline_forward["variance"],
            "cumulative_series": baseline_hist["cumulative_series"],
            "drawdown_series": baseline_hist["drawdown_series"],
            "var_95": calc_portfolio_var_95(baseline_forward["volatility"], ann_factor=self.var_ann.get()),
        }

        recommended_weights = model_weights.copy()
        notes = []
        if objective == BUILDER_OBJECTIVE_STRESS_ONLY:
            notes.append("Stress-test only mode used the selected model portfolio without a new optimization run.")
        elif objective == BUILDER_OBJECTIVE_BLEND:
            optimized = optimize_builder_portfolio(
                BUILDER_OBJECTIVE_MAX_RETURN_UNDER_RISK,
                return_vector,
                cov_annual,
                inputs["min_weights"],
                inputs["max_weights"],
                target_volatility=target_vol,
                initial_weights=model_weights,
                max_single_weight=inputs["max_single_weight"],
            )
            recommended_weights = (1.0 - blend_ratio) * model_weights + blend_ratio * optimized["weights"]
            recommended_weights = adjust_weights_to_bounds(recommended_weights, inputs["min_weights"], inputs["max_weights"])
            notes.append("Final allocation blends the optimized portfolio with the selected model template.")
        else:
            optimized = optimize_builder_portfolio(
                objective,
                return_vector,
                cov_annual,
                inputs["min_weights"],
                inputs["max_weights"],
                target_volatility=target_vol if objective in {BUILDER_OBJECTIVE_MATCH_RISK, BUILDER_OBJECTIVE_MAX_RETURN_UNDER_RISK} else None,
                initial_weights=model_weights,
                max_single_weight=inputs["max_single_weight"],
            )
            recommended_weights = optimized["weights"]
            if objective == BUILDER_OBJECTIVE_MATCH_RISK:
                notes.append(f"Target-risk gap: {optimized.get('target_gap', 0.0):.2%}.")

        recommended_hist = calc_portfolio_historical_metrics(self.var_returns_df[symbols], recommended_weights, ann_factor=self.var_ann.get())
        recommended_forward = calc_forward_portfolio_metrics(recommended_weights, return_vector, cov_annual)
        recommended = {
            "weights": recommended_weights,
            "expected_ann_return": recommended_forward["expected_ann_return"],
            "historical_ann_return": recommended_hist["historical_ann_return"],
            "volatility": recommended_forward["volatility"],
            "expected_return_over_volatility": recommended_forward["expected_return_over_volatility"],
            "historical_total_return": recommended_hist["historical_total_return"],
            "historical_max_drawdown": recommended_hist["historical_max_drawdown"],
            "variance": recommended_forward["variance"],
            "cumulative_series": recommended_hist["cumulative_series"],
            "drawdown_series": recommended_hist["drawdown_series"],
            "var_95": calc_portfolio_var_95(recommended_forward["volatility"], ann_factor=self.var_ann.get()),
        }

        risk_contributions = calc_risk_contributions(symbols, recommended_weights, cov_annual)
        model_info = self.model_portfolios[model_name]
        benchmark_name = choose_benchmark_name(self.builder_benchmark_var.get(), model_info, self.var_benchmark_candidates, self.var_benchmark_series)
        benchmark_metrics = compute_benchmark_metrics(benchmark_name, self.var_benchmark_series, ann_factor=self.var_ann.get())

        warnings = []
        missing_model_funds = [item["name"] for item in model_info["funds"] if item["name"] not in symbols]
        if missing_model_funds:
            warnings.append("Missing return history for some model funds: " + ", ".join(missing_model_funds[:6]) + ("..." if len(missing_model_funds) > 6 else ""))
        if benchmark_metrics is None:
            warnings.append("Benchmark comparison is unavailable for the selected benchmark.")

        high_concentration = [symbols[idx] for idx, weight in enumerate(recommended_weights) if weight >= 0.35]
        if high_concentration:
            warnings.append("High concentration in: " + ", ".join(high_concentration))

        high_corr_pairs = []
        for i, si in enumerate(symbols):
            for j in range(i + 1, len(symbols)):
                sj = symbols[j]
                if recommended_weights[i] > 0.05 and recommended_weights[j] > 0.05 and corr_matrix.loc[si, sj] >= 0.80:
                    high_corr_pairs.append(f"{si}/{sj} ({corr_matrix.loc[si, sj]:.2f})")
        if high_corr_pairs:
            warnings.append("Highly correlated funded pairs: " + ", ".join(high_corr_pairs[:4]))

        allocation_rows = []
        for idx, symbol in enumerate(symbols):
            history = per_stock[symbol]
            allocation_rows.append(
                {
                    "symbol": symbol,
                    "category": inputs["categories"][idx] or self.var_fund_info.get(symbol, {}).get("style", ""),
                    "benchmark": inputs["benchmarks"][idx] or self.var_fund_info.get(symbol, {}).get("benchmark", ""),
                    "model_weight": float(model_weights[idx]),
                    "recommended_weight": float(recommended_weights[idx]),
                    "delta_weight": float(recommended_weights[idx] - model_weights[idx]),
                    "expected_ann_return": float(return_vector[idx]),
                    "historical_ann_return": history["historical_ann_return"],
                    "volatility": history["historical_volatility"],
                    "min_weight": float(inputs["min_weights"][idx]),
                    "max_weight": float(inputs["max_weights"][idx]),
                }
            )

        allocation_rows.sort(key=lambda item: item["recommended_weight"], reverse=True)

        scenario_rows = self._collect_scenario_rows()
        stress_results = []
        if run_stress and scenario_rows:
            stress_results = run_stress_tests(
                scenario_rows,
                symbols,
                model_weights,
                recommended_weights,
                self.var_fund_info,
                cov_annual,
                corr_matrix,
                investment_amount,
                ann_factor=self.var_ann.get(),
            )

        result = {
            "model_name": model_name,
            "risk_profile": self.builder_risk_profile.get(),
            "objective": objective,
            "return_basis": selected_return_basis,
            "target_volatility": target_vol,
            "investment_amount": investment_amount,
            "blend_ratio": blend_ratio,
            "max_single_weight": inputs["max_single_weight"],
            "symbols": symbols,
            "baseline": baseline,
            "recommended": recommended,
            "allocation_rows": allocation_rows,
            "risk_contributions": risk_contributions,
            "benchmark_name": benchmark_name,
            "benchmark_metrics": benchmark_metrics,
            "warnings": warnings + notes + self.model_parse_warnings + self.var_parse_warnings,
            "corr_matrix": corr_matrix,
            "cov_matrix": cov_annual,
            "scenario_rows": scenario_rows,
            "stress_results": stress_results,
        }
        result["explanation"] = build_builder_explanation(result, result["warnings"])
        return result

    def _show_builder_outputs(self):
        for tree in (self.builder_alloc_tree, self.builder_comp_tree, self.builder_stress_tree):
            for child in tree.get_children():
                tree.delete(child)
        self.builder_explanation.delete("1.0", tk.END)

        if not self.builder_result:
            self.builder_summary_label.config(text="No allocation has been built yet.")
            return

        result = self.builder_result
        summary = (
            f"Selected model: {result['model_name']} | Risk profile: {result['risk_profile']} | "
            f"Target vol: {result['target_volatility']:.2%} | Objective: {result['objective']}\n"
            f"Model vol: {result['baseline']['volatility']:.2%} | Recommended vol: {result['recommended']['volatility']:.2%} | "
            f"Recommended expected return: {result['recommended']['expected_ann_return']:.2%}"
        )
        self.builder_summary_label.config(text=summary)

        for item in result["allocation_rows"]:
            self.builder_alloc_tree.insert(
                "",
                "end",
                values=(
                    item["symbol"],
                    f"{item['model_weight']:.2%}",
                    f"{item['recommended_weight']:.2%}",
                    f"{item['delta_weight']:.2%}",
                    f"{item['expected_ann_return']:.2%}",
                    f"{item['historical_ann_return']:.2%}",
                    f"{item['volatility']:.2%}",
                    item["category"],
                ),
            )

        baseline = result["baseline"]
        recommended = result["recommended"]
        benchmark_metrics = result.get("benchmark_metrics")
        self.builder_comp_tree.insert(
            "",
            "end",
            values=(
                "Model Portfolio",
                f"{baseline['expected_ann_return']:.2%}",
                f"{baseline['historical_ann_return']:.2%}",
                f"{baseline['volatility']:.2%}",
                f"{baseline['expected_return_over_volatility']:.3f}",
                f"{baseline['historical_max_drawdown']:.2%}",
                f"{baseline['var_95']:.2%}",
                result["model_name"],
            ),
        )
        self.builder_comp_tree.insert(
            "",
            "end",
            values=(
                "Recommended Allocation",
                f"{recommended['expected_ann_return']:.2%}",
                f"{recommended['historical_ann_return']:.2%}",
                f"{recommended['volatility']:.2%}",
                f"{recommended['expected_return_over_volatility']:.3f}",
                f"{recommended['historical_max_drawdown']:.2%}",
                f"{recommended['var_95']:.2%}",
                result["objective"],
            ),
            tags=("recommended",),
        )
        self.builder_comp_tree.tag_configure("recommended", background="#DFF1DE")
        if benchmark_metrics:
            self.builder_comp_tree.insert(
                "",
                "end",
                values=(
                    benchmark_metrics["benchmark"],
                    "",
                    f"{benchmark_metrics['historical_ann_return']:.2%}",
                    f"{benchmark_metrics['volatility']:.2%}",
                    "",
                    f"{benchmark_metrics['historical_max_drawdown']:.2%}",
                    "",
                    "Benchmark",
                ),
            )

        self.builder_explanation.insert("1.0", result["explanation"])

        for item in self.builder_stress_results:
            self.builder_stress_tree.insert(
                "",
                "end",
                values=(
                    item["scenario"],
                    f"{item['model_impact']:.2%}",
                    f"{item['recommended_impact']:.2%}",
                    f"${item['model_end_value']:,.0f}",
                    f"${item['recommended_end_value']:,.0f}",
                    f"{item['recommended_stressed_vol']:.2%}",
                    item["worst_recommended_fund"] or item["worst_model_fund"],
                ),
            )

    def _run_builder_stress_tests(self):
        try:
            self.builder_result = self._compute_builder_result(run_stress=True)
        except Exception as exc:
            messagebox.showerror("Stress Test Error", str(exc))
            return
        self.builder_stress_results = self.builder_result.get("stress_results", [])
        self.builder_step_completed[3] = True
        self.builder_step_completed[4] = True
        self._show_builder_outputs()
        if self.builder_stress_results:
            worst = min(self.builder_stress_results, key=lambda item: item["recommended_impact"])
            self.builder_status_label.config(
                text=f"Stress tests ran successfully. Worst scenario: {worst['scenario']} ({worst['recommended_impact']:.2%}).",
                foreground="green",
            )
        else:
            self.builder_status_label.config(text="Stress tests ran, but there were no scenario rows to evaluate.", foreground="#9A6B00")
        self._render_builder_step()

    # ---------- Export ----------

    def _export(self):
        if self.metrics is None and self.builder_result is None:
            messagebox.showinfo("Info", "Run the analyzer or build a portfolio first.")
            return

        path = filedialog.asksaveasfilename(
            title="Save Results",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx"), ("CSV", "*.csv")],
        )
        if not path:
            return

        try:
            if path.lower().endswith(".csv"):
                export_to_csv(path, analyzer_metrics=self.metrics, builder_payload=self.builder_result)
            else:
                export_to_xlsx(path, analyzer_metrics=self.metrics, builder_payload=self.builder_result)
            messagebox.showinfo("Exported", f"Saved to {path}")
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))


if __name__ == "__main__":
    app = PortfolioApp()
    app.mainloop()
