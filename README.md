# IC AI Connector

Local HTTP connector for **Binance USD-M Futures**. Works with **any AI assistant** (Claude, Grok, ChatGPT, Cursor, your own scripts) via a simple REST API on `127.0.0.1`.

Part of [Institutional Charts](https://institutionalcharts.com).

## Quick start

### 1. Install

```powershell
cd path\to\ic-ai-connector
python -m pip install -r requirements.txt
copy env.example .env
notepad .env
```

Fill in:

- `BINANCE_API_KEY` / `BINANCE_API_SECRET` — your **live** Binance USD-M Futures API keys
- `LIVE_TRADING_ACK=I_ACCEPT_LIVE_RISK` — required for live trading
- `CONNECTOR_TOKEN` — run `python -c "import secrets; print(secrets.token_urlsafe(32))"`

### 2. Run

```powershell
.\start.ps1
# or: python run.py
```

Open **http://127.0.0.1:8080/** for the dashboard.

### 3. Test

```powershell
python scripts/test_connection.py
python scripts/test_orchestrator_unit.py
python scripts/test_orchestrator_dry_run.py
python scripts/smoke_trade.py
```

## Institutional Charts Konsole (optional)

Pair with **Institutional Charts** so Konsole pushes a 15m snapshot into this connector automatically.

**Requirements**

- Valid IC license ([trial](https://institutionalcharts.com/trial/))
- IC beta build with Konsole egress (not the Microsoft Store build yet)
- This connector running on `127.0.0.1:8080` **before** you start IC Konsole

**Setup (one time)**

```powershell
.\scripts\setup-ic-egress.ps1
```

That script writes `%AppData%\InstitutionalCharts\connector.env` (from your `CONNECTOR_TOKEN`) and adds `127.0.0.1 ic.snapshot` to your hosts file (UAC prompt).

**Then**

1. `.\start.ps1` — connector must be up first
2. Start IC Konsole → open Konsole grid
3. On each **15m bar close**, IC POSTs to `http://ic.snapshot:8080/api/ui/konsole/analyze`
4. Watch **AI Desk** at [http://127.0.0.1:8080/](http://127.0.0.1:8080/)

If egress is silent after IC boot, restart IC Konsole once the connector is running (meta probe runs once per session).

Beta MSI download: *link coming in GitHub Releases* (Step 10).

## Orchestrator (Konsole → LLM → trade)

Static prompt in `agents/trader_system.txt`, live snapshot compiled server-side each cycle.

1. Konsole sends 15m snapshot → `POST /api/ui/konsole/analyze`
2. Server compiles prompt + account state, calls LLM (Settings → AI key)
3. Response `brief` → **AI Desk** feed; trades execute per `TRADE_MODE`

For YouTube / production: set `TRADE_MODE=auto`. Use `dry_run: true` in analyze body to test without LLM credits.

## Safety defaults

| Setting | Default | Meaning |
|---------|---------|---------|
| `TRADE_MODE` | `auto` | Trades execute when the LLM signals (set confirm to queue) |
| `MAX_NOTIONAL_PER_ORDER` | 200 USDT | Hard cap per order |
| `MAX_OPEN_POSITIONS` | 5 | Hard cap |
| `MAX_LEVERAGE` | 20 | Hard cap |
| `MAX_DAILY_LOSS` | 100 USDT | Trips kill switch |

On startup the connector verifies your API key works on **Binance Futures live** (`fapi.binance.com`).

## Trade modes

Default is `TRADE_MODE=auto` (see `env.example`). The orchestrator executes when the LLM returns a trade action.

Set `TRADE_MODE=confirm` in `.env` if you want proposals queued for manual `POST /trade/confirm` instead.

## API overview

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | No | Server status |
| GET | `/status` | Yes | Mode, risk, pending count |
| POST | `/test_connection` | Yes | Ping Binance + balance |
| GET | `/risk/status` | Yes | Limits and kill switch |
| POST | `/risk/reset_kill_switch` | Yes | Manual reset |
| POST | `/balance` | Yes | USDT wallet |
| POST | `/positions` | Yes | Open positions |
| POST | `/open_orders` | Yes | Pending orders |
| POST | `/trade/open` | Yes | Entry + SL + TP (propose or execute) |
| POST | `/place_trade` | Yes | Single market/limit order |
| POST | `/trade/propose` | Yes | Generic propose |
| GET | `/trade/pending` | Yes | Queued proposals |
| POST | `/trade/confirm` | Yes | Execute proposal |
| POST | `/trade/reject` | Yes | Cancel proposal |
| POST | `/set_sl` / `/set_tp` | Yes | Protective orders |
| POST | `/partial_close` | Yes | Close X% |
| POST | `/close_all` | Yes | Emergency (requires confirm phrase) |
| POST | `/cancel_orders` | Yes | Cancel orders |
| GET | `/symbols?q=BTC` | No | Symbol lookup |
| POST | `/api/ui/konsole/analyze` | Yes | Konsole snapshot → LLM cycle |
| GET | `/api/ui/ai-feed` | Yes | AI Desk message feed |
| GET | `/api/ui/orchestrator/status` | Yes | Last run, model, config |

All authenticated requests use header: `Authorization: Bearer YOUR_CONNECTOR_TOKEN`

## Agent prompt

Static rules: `agents/trader_system.txt`. Live Konsole + account data are appended each cycle by `connector/prompt_compiler.py` (not copy-pasted from Settings).

## Logs and audit

- `connector.log` — server log
- `audit.jsonl` — every proposal, confirm, reject, execute
- `pending_trades.json` — queued proposals
- `risk-state.json` — daily PnL / kill switch state

- `ai-feed.jsonl` — AI Desk one-way messages
- `orchestrator-state.json` — last LLM cycle metadata
- `ui-settings.json` — AI provider key (orchestrator)

## Disclaimer

Futures trading with leverage can result in total loss of capital. This software is provided as-is for personal use. You are responsible for every trade, bug, and configuration error. Not financial advice.
