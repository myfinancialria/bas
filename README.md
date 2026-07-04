# Correlated Strategies Pre-Market Report

Automated pre-market report generator for defined-risk NIFTY and SENSEX option-selling trade candidates.

The report is designed around correlation-aware option selling:

- volatility first: India VIX, IV/HV, premium richness, event risk
- option surface and OI: ATM context, support/resistance strikes, PCR, OI buildup
- cross-market confirmation: BANKNIFTY/FINNIFTY lead-lag, sector strength, breadth, FII/DII, USDINR and global cues
- defined-risk execution: credit spreads and iron condors instead of naked option selling

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

This repository currently uses public data sources where available. NSE option-chain endpoints can occasionally block automated requests; when that happens, the report clearly marks option-chain fields as unavailable and uses conservative placeholder strike logic from index levels.

## Risk Note

This project generates research and educational analysis only. It is not personalized financial advice. Option selling can create large losses, even with high-probability setups. Use defined-risk structures, fixed position sizing, and never average a losing short option position.
