# Correlated Strategies Pre-Market Report

Automated pre-market report generator for defined-risk NIFTY and SENSEX option-selling trade candidates.

The report is designed around correlation-aware option selling:

- volatility first: India VIX, IV/HV, premium richness, event risk
- option surface and OI: ATM context, support/resistance strikes, PCR, OI buildup
- cross-market confirmation: BANKNIFTY/FINNIFTY lead-lag, sector strength, breadth, FII/DII, USDINR and global cues
- defined-risk execution: credit spreads and iron condors instead of naked option selling

## Live Data via Fyers API

The report pulls **live market data from the Fyers API (v3)** when credentials are
configured, and falls back to Yahoo Finance / NSE public data otherwise.

What comes from Fyers:

- **Index quotes** — NIFTY 50, SENSEX, BANKNIFTY, FINNIFTY, India VIX
  (last price, previous close, change %).
- **Cross-market cues** — USDINR, Crude Oil and Gold, resolved to the
  nearest-expiry future from the Fyers symbol master.
- **Option chains** — NIFTY and SENSEX OI, PCR, nearest expiry and the top
  call/put OI strikes (replaces the fragile NSE web scraping).

The `Source` column in each report's Data Snapshot and the `Chain source` line
make it explicit whether a value came from `fyers`, `yahoo` or `nse`.

### Setup

1. Create an app at https://myapi.fyers.in/dashboard (App ID + Secret).
2. Enable **External 2FA TOTP** at https://myaccount.fyers.in/ManageAccount.
3. Copy `.env.example` to `.env` and fill in the Fyers values.
4. Generate an access token (headless, no browser):

   ```bash
   python src/fyers_login.py
   ```

   The token is written back to `.env` and expires at the next login-day
   rollover, so re-run it daily (the GitHub Action does this automatically).

The relevant modules:

- `src/fyers_login.py` — headless TOTP login → writes `FYERS_ACCESS_TOKEN`.
- `src/fyers_client.py` — quotes, option-chain summary, nearest-future resolution.
- `src/envtools.py` — tiny `.env` reader/writer (CI secrets override the file).

### GitHub Actions

Add these repository secrets so the scheduled workflow can log in and fetch live
data (without them the report still runs on public-data fallback):

`FYERS_APP_ID`, `FYERS_SECRET_KEY`, `FYERS_REDIRECT_URI`, `FYERS_FY_ID`,
`FYERS_PIN`, `FYERS_TOTP_SECRET`.

## Schedule

The GitHub Actions workflow runs on Indian market weekdays at **9:21 AM IST**.

GitHub cron uses UTC, so the workflow is configured for:

```text
51 3 * * 1-5
```

The script also checks the configured Indian trading-holiday list and exits with a holiday note when markets are closed.

## Outputs

Reports are written to:

```text
reports/YYYY-MM-DD-premarket-report.md
```

The workflow commits the generated report back to the repository.

## Local Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python src/premarket_report.py
```

## GitHub Setup

1. Create a new GitHub repository.
2. Push this folder to it.
3. Enable GitHub Actions.
4. Optional: add secrets if you later connect broker/data APIs.

This repository uses the **Fyers API for live data** when credentials are configured (see "Live Data via Fyers API" above), and falls back to public sources otherwise. When Fyers is unavailable and the NSE option-chain endpoints block automated requests, the report clearly marks option-chain fields as unavailable and uses conservative placeholder strike logic from index levels.

## Risk Note

This project generates research and educational analysis only. It is not personalized financial advice. Option selling can create large losses, even with high-probability setups. Use defined-risk structures, fixed position sizing, and never average a losing short option position.
