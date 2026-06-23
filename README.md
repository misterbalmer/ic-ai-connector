# IC AI Connector

Local AI trading desk for **Binance USD-M Futures**. Pairs with [Institutional Charts](https://institutionalcharts.com) Konsole (optional) or any client that POSTs the analyze contract.

```
IC Konsole ──15m snapshot──► AI Connector ──► LLM / Binance / AI Desk
```

## Requirements

- **Python 3.11+** ([python.org](https://www.python.org/downloads/) — Windows: check *Add python.exe to PATH*)
- **macOS / Linux:** `python3` in PATH (`brew install python@3.12` on Mac)
- Binance **USD-M Futures** API key (Futures permission; IP whitelist if enabled)

---

## Install (3 steps)

### Windows

```powershell
git clone https://github.com/misterbalmer/ic-ai-connector.git
cd ic-ai-connector
.\install.ps1
.\start.ps1
```

Open **http://127.0.0.1:8080/** → AI Desk. Add your **AI API key** in Settings.

### macOS / Linux

```bash
git clone https://github.com/misterbalmer/ic-ai-connector.git
cd ic-ai-connector
chmod +x install.sh start.sh stop.sh scripts/setup-ic-egress.sh
./install.sh
./start.sh
```

Open **http://127.0.0.1:8080/** → AI Desk. Add your **AI API key** in Settings.

`install.ps1` / `install.sh` will:

1. Create an isolated `.venv` and install dependencies  
2. Run the setup wizard (Binance keys + auto `CONNECTOR_TOKEN`)  
3. Verify config with `scripts/doctor.py --binance`

---

## Pair with Institutional Charts (optional)

1. Connector running (`start.ps1` or `./start.sh`)  
2. One-time pairing:

   **Windows:** `.\scripts\setup-ic-egress.ps1`  
   **Mac/Linux:** `./scripts/setup-ic-egress.sh`

3. Restart IC Konsole — on each **15m bar close**, IC POSTs snapshots automatically.

---

## Daily use

| Action | Windows | Mac/Linux |
|--------|---------|-----------|
| Start | `.\start.ps1` | `./start.sh` |
| Stop | `.\stop.ps1` | `./stop.sh` |
| Health check | `python scripts/doctor.py` | same |
| Test API | `python scripts/test_connection.py` | same |

---

## Orchestrator

1. Client sends 15m snapshot → `POST /api/ui/konsole/analyze`  
2. Server compiles prompt + account state, calls LLM  
3. `brief` → **AI Desk**; trades per `TRADE_MODE`

Static rules: `agents/trader_system.md`. Live data appended each cycle.

---

## Safety defaults

| Setting | Default | Meaning |
|---------|---------|---------|
| `TRADE_MODE` | `auto` | Executes on LLM trade signal (`confirm` = queue for approval) |
| `MAX_NOTIONAL_PER_ORDER` | 200 USDT | Per-order cap |
| `MAX_OPEN_POSITIONS` | 5 | Position cap |
| `MAX_LEVERAGE` | 20 | Leverage cap |
| `MAX_DAILY_LOSS` | 100 USDT | Kill switch |

---

## API (local)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | No auth — server status |
| POST | `/api/ui/konsole/analyze` | Konsole snapshot → LLM cycle |
| GET | `/api/ui/ai-feed` | AI Desk feed |
| POST | `/trade/open` | Entry + SL + TP |

Auth: `Authorization: Bearer YOUR_CONNECTOR_TOKEN` (generated at install)

---

## Logs

- `connector.log` — server log  
- `audit.jsonl` — trades and proposals  
- `ai-feed.jsonl` — AI Desk messages  

---

## Disclaimer

Futures trading with leverage can result in total loss of capital. You are responsible for every trade and configuration. Not financial advice.