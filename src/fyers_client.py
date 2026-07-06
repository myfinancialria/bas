"""
Live market data via the Fyers API (v3).

This is the single data layer the pre-market report uses when Fyers credentials
are configured. It exposes:

    quotes(symbols)              -> {symbol: FyersQuote}         live LTP / prev-close / change%
    option_chain_summary(sym)    -> parsed OI / PCR / top strikes for an index
    resolve_nearest_future(...)  -> nearest-expiry FUT symbol from the Fyers master

All calls are best-effort: if the token is missing/expired the client tries a
one-shot headless TOTP re-login (fyers_login), and every public function returns
``None``/empty rather than raising so the report can fall back to public sources.
"""
from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from fyers_apiv3 import fyersModel

from envtools import load_env

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / ".cache"

# Fyers public symbol masters (segment -> url).
MASTER_URLS = {
    "NSE_CD": "https://public.fyers.in/sym_details/NSE_CD.csv",
    "MCX_COM": "https://public.fyers.in/sym_details/MCX_COM.csv",
}

# Column indices in the Fyers symbol-master CSV.
C_SYMBOL = 9        # e.g. NSE:USDINR26710FUT
C_EXPIRY = 8        # epoch seconds
C_UNDERLYING = 13   # e.g. USDINR / CRUDEOIL
C_OPTTYPE = 16      # CE / PE / XX (future)

_fyers: fyersModel.FyersModel | None = None
_relogin_tried = False


@dataclass
class FyersQuote:
    symbol: str
    last: float | None
    previous_close: float | None
    change_pct: float | None


def _build_model(env: dict) -> fyersModel.FyersModel | None:
    token = (env.get("FYERS_ACCESS_TOKEN") or "").strip()
    app_id = (env.get("FYERS_APP_ID") or "").strip()
    if not token or not app_id:
        return None
    return fyersModel.FyersModel(client_id=app_id, token=token, is_async=False)


def get_fyers() -> fyersModel.FyersModel | None:
    """Return a cached FyersModel, or None if credentials are unavailable."""
    global _fyers
    if _fyers is None:
        _fyers = _build_model(load_env())
    return _fyers


def _relogin() -> fyersModel.FyersModel | None:
    """One-shot headless TOTP re-login when the token looks invalid."""
    global _fyers, _relogin_tried
    if _relogin_tried:
        return _fyers
    _relogin_tried = True
    try:
        from fyers_login import generate_access_token

        generate_access_token(verbose=False)
    except Exception:
        return None
    _fyers = _build_model(load_env())
    return _fyers


def _invalid_token(resp: dict) -> bool:
    text = str(resp).lower()
    return any(k in text for k in ("token", "authenticate", "-16", "-17", "-15"))


def is_configured() -> bool:
    return get_fyers() is not None


def quotes(symbols) -> dict[str, FyersQuote]:
    """Return {symbol: FyersQuote} for one symbol or a list of them."""
    if isinstance(symbols, str):
        symbols = [symbols]
    symbols = [s for s in symbols if s]
    if not symbols:
        return {}
    fyers = get_fyers()
    if fyers is None:
        return {}

    resp = fyers.quotes({"symbols": ",".join(symbols)})
    if resp.get("s") != "ok" and _invalid_token(resp):
        fyers = _relogin()
        if fyers is None:
            return {}
        resp = fyers.quotes({"symbols": ",".join(symbols)})
    if resp.get("s") != "ok":
        return {}

    out: dict[str, FyersQuote] = {}
    for d in resp.get("d", []):
        v = d.get("v", {}) or {}
        last = v.get("lp")
        prev = v.get("prev_close_price")
        chp = v.get("chp")
        if chp is None and last is not None and prev:
            chp = (last - prev) / prev * 100
        out[d.get("n")] = FyersQuote(d.get("n"), last, prev, chp)
    return out


# --------------------------------------------------------------------------- #
# Nearest-expiry future resolution (USDINR / Crude / Gold live via Fyers)
# --------------------------------------------------------------------------- #
def _ensure_master(segment: str, max_age_sec: int = 86400) -> Path | None:
    url = MASTER_URLS.get(segment)
    if not url:
        return None
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / f"{segment}.csv"
    fresh = path.exists() and (time.time() - path.stat().st_mtime) < max_age_sec
    if not fresh:
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            path.write_bytes(resp.content)
        except Exception:
            return path if path.exists() else None
    return path


def resolve_nearest_future(underlying: str, segment: str) -> str | None:
    """Return the nearest-expiry FUT symbol for an underlying, or None.

    underlying : e.g. "USDINR", "CRUDEOIL", "GOLD"
    segment    : "NSE_CD" (currency) or "MCX_COM" (commodity)
    """
    path = _ensure_master(segment)
    if path is None or not path.exists():
        return None
    now = time.time()
    best_sym, best_exp = None, None
    try:
        with path.open(newline="") as f:
            for row in csv.reader(f):
                if len(row) <= C_OPTTYPE:
                    continue
                if row[C_UNDERLYING].strip().upper() != underlying.upper():
                    continue
                if row[C_OPTTYPE].strip().upper() != "XX":  # futures only
                    continue
                try:
                    exp = float(row[C_EXPIRY])
                except ValueError:
                    continue
                if exp < now - 86400:  # keep today's expiry, drop past ones
                    continue
                if best_exp is None or exp < best_exp:
                    best_exp, best_sym = exp, row[C_SYMBOL].strip()
    except Exception:
        return None
    return best_sym


# --------------------------------------------------------------------------- #
# Option chain (replaces NSE web scraping)
# --------------------------------------------------------------------------- #
def option_chain_summary(symbol: str, strikecount: int = 15) -> dict:
    """Summarize the Fyers option chain for an index symbol.

    symbol : e.g. "NSE:NIFTY50-INDEX", "BSE:SENSEX-INDEX"

    Returns a dict shaped like the report expects:
        available, underlying, expiry (DD-Mon-YYYY), pcr,
        top_call_oi[], top_put_oi[], source
    """
    fyers = get_fyers()
    if fyers is None:
        return {"available": False}

    payload = {"symbol": symbol, "strikecount": strikecount, "timestamp": ""}
    resp = fyers.optionchain(payload)
    if resp.get("s") != "ok" and _invalid_token(resp):
        fyers = _relogin()
        if fyers is None:
            return {"available": False}
        resp = fyers.optionchain(payload)
    if resp.get("s") != "ok":
        return {"available": False}

    data = resp.get("data", {}) or {}
    rows = data.get("optionsChain", []) or []
    call_oi = data.get("callOi")
    put_oi = data.get("putOi")
    pcr = round(put_oi / call_oi, 2) if call_oi else None

    underlying = None
    calls: list[tuple[int, int]] = []
    puts: list[tuple[int, int]] = []
    for r in rows:
        opt = (r.get("option_type") or "").upper()
        strike = r.get("strike_price")
        if strike in (None, -1):
            if underlying is None and r.get("ltp") is not None:
                underlying = r.get("ltp")
            continue
        oi = r.get("oi") or 0
        if opt == "CE":
            calls.append((int(strike), oi))
        elif opt == "PE":
            puts.append((int(strike), oi))

    def top(side: list[tuple[int, int]]) -> list[int]:
        return [s for s, _ in sorted(side, key=lambda x: x[1], reverse=True)[:3]]

    exp_list = data.get("expiryData") or []
    expiry = None
    if exp_list:
        raw = exp_list[0].get("date")  # "07-07-2026"
        try:
            expiry = time.strftime("%d-%b-%Y", time.strptime(raw, "%d-%m-%Y"))
        except Exception:
            expiry = raw

    return {
        "available": True,
        "underlying": underlying,
        "expiry": expiry,
        "pcr": pcr,
        "top_call_oi": top(calls),
        "top_put_oi": top(puts),
        "source": "fyers",
    }
