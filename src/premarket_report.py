from __future__ import annotations

import datetime as dt
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
import yaml
import yfinance as yf


ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"
HOLIDAYS_FILE = ROOT / "config" / "trading_holidays_2026.yml"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


@dataclass
class MarketPoint:
    name: str
    symbol: str
    last: float | None
    previous_close: float | None
    change_pct: float | None


def today_ist() -> dt.date:
    return dt.datetime.now(IST).date()


def load_holidays() -> set[dt.date]:
    if not HOLIDAYS_FILE.exists():
        return set()
    data = yaml.safe_load(HOLIDAYS_FILE.read_text()) or {}
    return {dt.date.fromisoformat(str(value)) for value in data.get("holidays", [])}


def is_trading_day(day: dt.date) -> bool:
    return day.weekday() < 5 and day not in load_holidays()


def round_to_step(value: float, step: int) -> int:
    return int(round(value / step) * step)


def fetch_yahoo_point(name: str, symbol: str) -> MarketPoint:
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="5d", interval="1d", auto_adjust=False)
        if hist.empty:
            return MarketPoint(name, symbol, None, None, None)
        closes = hist["Close"].dropna()
        last = float(closes.iloc[-1])
        previous = float(closes.iloc[-2]) if len(closes) > 1 else None
        change_pct = ((last - previous) / previous * 100) if previous else None
        return MarketPoint(name, symbol, last, previous, change_pct)
    except Exception:
        return MarketPoint(name, symbol, None, None, None)


def nse_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/",
        }
    )
    try:
        session.get("https://www.nseindia.com", timeout=10)
    except Exception:
        pass
    return session


def fetch_nse_json(path: str) -> dict[str, Any] | None:
    try:
        response = nse_session().get(f"https://www.nseindia.com{path}", timeout=20)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def fetch_option_chain(symbol: str) -> dict[str, Any] | None:
    return fetch_nse_json(f"/api/option-chain-indices?symbol={symbol}")


def summarize_chain(chain: dict[str, Any] | None) -> dict[str, Any]:
    if not chain:
        return {"available": False}
    records = chain.get("records", {})
    underlying = records.get("underlyingValue")
    expiry_dates = records.get("expiryDates") or []
    data = records.get("data") or []
    expiry = expiry_dates[0] if expiry_dates else None
    rows = [row for row in data if not expiry or row.get("expiryDate") == expiry]
    call_oi = sum((row.get("CE") or {}).get("openInterest", 0) for row in rows)
    put_oi = sum((row.get("PE") or {}).get("openInterest", 0) for row in rows)
    pcr = round(put_oi / call_oi, 2) if call_oi else None

    def top_side(side: str) -> list[int]:
        ranked = sorted(
            rows,
            key=lambda row: (row.get(side) or {}).get("openInterest", 0),
            reverse=True,
        )
        return [int(row["strikePrice"]) for row in ranked[:3] if row.get(side)]

    return {
        "available": True,
        "underlying": underlying,
        "expiry": expiry,
        "pcr": pcr,
        "top_call_oi": top_side("CE"),
        "top_put_oi": top_side("PE"),
    }


def score_regime(points: dict[str, MarketPoint], nifty_chain: dict[str, Any]) -> tuple[int, str]:
    score = 50
    reasons: list[str] = []
    nifty = points.get("NIFTY 50")
    sensex = points.get("SENSEX")
    bank = points.get("BANKNIFTY")
    vix = points.get("India VIX")

    if nifty and nifty.change_pct is not None:
        if nifty.change_pct > 0.25:
            score += 10
            reasons.append("NIFTY momentum positive")
        elif nifty.change_pct < -0.25:
            score -= 10
            reasons.append("NIFTY momentum weak")

    if sensex and sensex.change_pct is not None:
        score += 5 if sensex.change_pct > 0 else -5

    if bank and nifty and bank.change_pct is not None and nifty.change_pct is not None:
        if bank.change_pct > nifty.change_pct:
            score += 8
            reasons.append("BANKNIFTY leading NIFTY")
        else:
            score -= 3
            reasons.append("BANKNIFTY not leading")

    if vix and vix.change_pct is not None:
        if vix.change_pct < -1:
            score += 12
            reasons.append("India VIX cooling")
        elif vix.change_pct > 3:
            score -= 15
            reasons.append("India VIX expanding")

    if nifty_chain.get("pcr"):
        pcr = float(nifty_chain["pcr"])
        if 0.8 <= pcr <= 1.3:
            score += 5
            reasons.append("NIFTY PCR balanced")
        elif pcr > 1.5:
            score -= 5
            reasons.append("NIFTY PCR crowded on puts")

    return max(0, min(100, score)), "; ".join(reasons) or "Mixed signals"


def format_num(value: float | int | None, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "N/A"
    return f"{value:,.{digits}f}"


def build_trade_candidates(
    points: dict[str, MarketPoint],
    nifty_chain: dict[str, Any],
    sensex_chain: dict[str, Any],
    score: int,
) -> list[dict[str, str]]:
    nifty_level = (
        float(nifty_chain["underlying"])
        if nifty_chain.get("underlying")
        else points["NIFTY 50"].last or 24000
    )
    sensex_level = (
        float(sensex_chain["underlying"])
        if sensex_chain.get("underlying")
        else points["SENSEX"].last or 78000
    )

    nifty_atm = round_to_step(nifty_level, 50)
    sensex_atm = round_to_step(sensex_level, 100)
    bullish = score >= 58
    defensive = score < 45

    if bullish:
        return [
            {
                "rank": "1",
                "instrument": "NIFTY",
                "strategy": "Bull put credit spread",
                "structure": f"Sell {nifty_atm - 200} PE / Buy {nifty_atm - 300} PE",
                "entry": f"After 9:21 IST, enter only if NIFTY holds above {nifty_atm - 100}, VIX is flat/down, and put OI remains firm near {nifty_atm - 200}.",
                "exit": "Book 50-65% of max credit, or exit if momentum fades by midday.",
                "stop": f"Exit if NIFTY sustains below {nifty_atm - 150}, spread premium doubles, or VIX rises more than 5-7%.",
                "why": "Best fit when index momentum and financial-sector lead-lag remain supportive.",
            },
            {
                "rank": "2",
                "instrument": "SENSEX",
                "strategy": "Bull put credit spread",
                "structure": f"Sell {sensex_atm - 700} PE / Buy {sensex_atm - 900} PE",
                "entry": f"Enter only if SENSEX holds above {sensex_atm - 300} and put OI builds below spot.",
                "exit": "Book 50-60% of max credit.",
                "stop": f"Exit if SENSEX sustains below {sensex_atm - 500} or spread premium doubles.",
                "why": "Defined-risk way to express a constructive index regime while avoiding naked option risk.",
            },
            {
                "rank": "3",
                "instrument": "NIFTY",
                "strategy": "Iron condor",
                "structure": f"Sell {nifty_atm - 250} PE / Buy {nifty_atm - 350} PE + Sell {nifty_atm + 350} CE / Buy {nifty_atm + 450} CE",
                "entry": "Enter after 9:35 IST only if price remains range-bound and VIX/IV is not expanding.",
                "exit": "Book 40-55% of combined credit.",
                "stop": f"Exit if NIFTY breaks below {nifty_atm - 200} or above {nifty_atm + 300}.",
                "why": "Works only if Monday opens stable and premium is rich enough on both sides.",
            },
        ]

    if defensive:
        return [
            {
                "rank": "1",
                "instrument": "NIFTY",
                "strategy": "Bear call credit spread",
                "structure": f"Sell {nifty_atm + 250} CE / Buy {nifty_atm + 350} CE",
                "entry": f"Enter only if NIFTY fails below {nifty_atm + 100}, breadth weakens, and VIX is not collapsing.",
                "exit": "Book 50-60% of max credit.",
                "stop": f"Exit if NIFTY sustains above {nifty_atm + 150} or spread premium doubles.",
                "why": "Defensive candidate when momentum and volatility signals deteriorate.",
            },
            {
                "rank": "2",
                "instrument": "SENSEX",
                "strategy": "Bear call credit spread",
                "structure": f"Sell {sensex_atm + 800} CE / Buy {sensex_atm + 1000} CE",
                "entry": "Enter after a failed bounce and only if call OI strengthens above spot.",
                "exit": "Book 50% of max credit.",
                "stop": f"Exit if SENSEX sustains above {sensex_atm + 500}.",
                "why": "Defined-risk hedge against weak breadth or rising volatility.",
            },
            {
                "rank": "3",
                "instrument": "NIFTY",
                "strategy": "Wide iron condor",
                "structure": f"Sell {nifty_atm - 350} PE / Buy {nifty_atm - 450} PE + Sell {nifty_atm + 350} CE / Buy {nifty_atm + 450} CE",
                "entry": "Only if IV is high but price stabilizes after the first 20 minutes.",
                "exit": "Book 35-50% of combined credit.",
                "stop": "Exit the threatened side quickly on range expansion.",
                "why": "Lower-conviction setup; use smaller size.",
            },
        ]

    return [
        {
            "rank": "1",
            "instrument": "NIFTY",
            "strategy": "Wide iron condor",
            "structure": f"Sell {nifty_atm - 300} PE / Buy {nifty_atm - 400} PE + Sell {nifty_atm + 300} CE / Buy {nifty_atm + 400} CE",
            "entry": "Enter after 9:35 IST only if price is range-bound and VIX is flat/down.",
            "exit": "Book 40-55% of combined credit.",
            "stop": "Exit if either short strike is threatened or combined premium expands 1.8-2.0x.",
            "why": "Neutral score favors range trading over directional conviction.",
        },
        {
            "rank": "2",
            "instrument": "NIFTY",
            "strategy": "Bull put credit spread",
            "structure": f"Sell {nifty_atm - 250} PE / Buy {nifty_atm - 350} PE",
            "entry": f"Enter only if NIFTY reclaims and holds {nifty_atm} with VIX cooling.",
            "exit": "Book 50% of max credit.",
            "stop": f"Exit below {nifty_atm - 150} or if spread premium doubles.",
            "why": "Secondary candidate if neutral regime resolves upward.",
        },
        {
            "rank": "3",
            "instrument": "SENSEX",
            "strategy": "Defined-risk credit spread",
            "structure": f"Use {sensex_atm - 700} PE / {sensex_atm - 900} PE for bullish confirmation or {sensex_atm + 800} CE / {sensex_atm + 1000} CE for failed upside.",
            "entry": "Pick side only after SENSEX confirms direction and option-chain liquidity is tight.",
            "exit": "Book 50% of max credit.",
            "stop": "Exit if the selected spread premium doubles.",
            "why": "Conditional candidate because neutral regime needs confirmation.",
        },
    ]


def report() -> str:
    day = today_ist()
    title = f"# NIFTY & SENSEX Options-Selling Pre-Market Report - {day.isoformat()}"

    if not is_trading_day(day):
        return (
            f"{title}\n\n"
            f"Generated at 9:21 AM IST target time.\n\n"
            "## Market Status\n\n"
            "Today is configured as a non-trading day for NSE/BSE or falls on a weekend. "
            "No new option-selling entries should be initiated.\n\n"
            "## Next Trading-Day Watchlist\n\n"
            "- Refresh NIFTY, SENSEX, BANKNIFTY, FINNIFTY, India VIX, FII/DII flows, USDINR, and option chains.\n"
            "- Recalculate the composite score before selecting strikes.\n"
            "- Prefer defined-risk credit spreads after post-open confirmation.\n"
        )

    symbols = {
        "NIFTY 50": "^NSEI",
        "SENSEX": "^BSESN",
        "BANKNIFTY": "^NSEBANK",
        "India VIX": "^INDIAVIX",
        "USDINR": "INR=X",
        "Crude Oil": "CL=F",
        "Gold": "GC=F",
    }
    points = {name: fetch_yahoo_point(name, symbol) for name, symbol in symbols.items()}
    nifty_chain = summarize_chain(fetch_option_chain("NIFTY"))
    sensex_chain = summarize_chain(fetch_option_chain("SENSEX"))
    score, score_reason = score_regime(points, nifty_chain)
    trades = build_trade_candidates(points, nifty_chain, sensex_chain, score)

    if score >= 60:
        regime = "mildly bullish to neutral-positive"
    elif score <= 44:
        regime = "defensive / bearish-neutral"
    else:
        regime = "neutral / range-bound"

    lines = [
        title,
        "",
        "Generated for the 9:21 AM IST trading-day workflow.",
        "",
        "> This is research and education, not personalized financial advice. Use defined-risk structures, fixed sizing, and never average a losing short option position.",
        "",
        "## Market Regime",
        "",
        f"- Composite score: **{score}/100**",
        f"- Bias: **{regime}**",
        f"- Score explanation: {score_reason}",
        "- Entry timing: wait for post-open confirmation. At 9:21, avoid chasing the opening move; confirm VIX/IV and OI behavior first.",
        "",
        "## Data Snapshot",
        "",
        "| Factor | Last | Change % | Interpretation |",
        "|---|---:|---:|---|",
    ]

    for name, point in points.items():
        interpretation = "Needs confirmation"
        if point.change_pct is not None:
            interpretation = "Positive" if point.change_pct > 0 else "Negative"
        lines.append(
            f"| {name} | {format_num(point.last)} | {format_num(point.change_pct)} | {interpretation} |"
        )

    lines.extend(
        [
            "",
            "## Option-Chain Context",
            "",
            f"- NIFTY chain available: {nifty_chain.get('available')}",
            f"- NIFTY expiry: {nifty_chain.get('expiry', 'N/A')}",
            f"- NIFTY PCR: {nifty_chain.get('pcr', 'N/A')}",
            f"- NIFTY top call OI strikes: {json.dumps(nifty_chain.get('top_call_oi', []))}",
            f"- NIFTY top put OI strikes: {json.dumps(nifty_chain.get('top_put_oi', []))}",
            f"- SENSEX chain available: {sensex_chain.get('available')}",
            f"- SENSEX expiry: {sensex_chain.get('expiry', 'N/A')}",
            f"- SENSEX PCR: {sensex_chain.get('pcr', 'N/A')}",
            "",
            "## Top 3 Trade Candidates",
            "",
        ]
    )

    for trade in trades:
        lines.extend(
            [
                f"### {trade['rank']}. {trade['instrument']} - {trade['strategy']}",
                "",
                f"- Structure: **{trade['structure']}**",
                f"- Entry: {trade['entry']}",
                f"- Exit: {trade['exit']}",
                f"- Stop / invalidation: {trade['stop']}",
                f"- Why ranked here: {trade['why']}",
                "",
            ]
        )

    lines.extend(
        [
            "## Trades To Avoid",
            "",
            "- Avoid naked short calls or puts.",
            "- Avoid selling premium when VIX is expanding aggressively against the trade.",
            "- Avoid illiquid strikes with wide bid-ask spreads.",
            "- Avoid entries around scheduled event risk unless the position is sized smaller and strictly defined-risk.",
            "",
            "## Final Entry Checklist",
            "",
            "- Confirm NIFTY/SENSEX level versus planned trigger.",
            "- Confirm India VIX is flat or favorable.",
            "- Confirm OI support/resistance and bid-ask spreads.",
            "- Confirm no major event is due during the holding window.",
            "- Keep risk per trade small and fixed before entry.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    REPORTS_DIR.mkdir(exist_ok=True)
    day = today_ist()
    output = REPORTS_DIR / f"{day.isoformat()}-premarket-report.md"
    output.write_text(report())
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
