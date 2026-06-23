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
<img width="1887" height="857" alt="Screenshot 2026-06-23 155556" src="https://github.com/user-attachments/assets/53b9a350-bac8-4c0c-aca0-6deb70ac0325" />
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

DISCLAIMER AND TERMS OF USE
1. Not Financial Advice Institutional Charts and the IC Konsole are provided for informational, educational, and analytical purposes only. Nothing contained within this software constitutes financial, investment, legal, or tax advice. The statistical analysis, charts, and AI-generated insights do not represent a recommendation, endorsement, or solicitation to buy, sell, or hold any cryptocurrency, security, or financial instrument.

2. Beta Software & Provided "As-Is" This software is currently in a Beta development stage (Edition 2.2.0). It is provided on an "AS-IS" and "AS-AVAILABLE" basis without warranties of any kind, either express or implied. While we strive for stability, beta software may contain bugs, errors, or data inaccuracies that could cause unexpected behavior, crashes, or delayed market data.

3. No Liability for Financial Losses Cryptocurrency and perpetual futures trading involve a severe degree of risk and are not suitable for all investors. You are solely responsible for any trading decisions you make. Under no circumstances shall the developer(s), founders, or contributors of Institutional Charts be held liable for any direct, indirect, incidental, or consequential damages, including but not limited to trading losses, lost profits, or data loss arising from the use, or inability to use, this software.

4. Data Accuracy and AI Limitations The market data provided by the IC Konsole relies on third-party APIs and experimental AI modeling. We do not guarantee the accuracy, completeness, reliability, or timeliness of this data. AI-driven analysis is probabilistic and should never be relied upon as the sole indicator for financial decisions. Always verify market conditions through independent, real-time broker sources.

5. User Responsibility (DYOR) By using this software, you acknowledge that you understand the inherent risks associated with algorithmic tools and volatile financial markets. You agree to Do Your Own Research (DYOR) and evaluate all risks before deploying real capital.

By downloading, installing, or using Institutional Charts, you signify your absolute acceptance of this disclaimer.
