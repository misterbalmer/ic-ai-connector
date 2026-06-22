"""IC AI Connector — configuration and paths."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def _bool(val: str | None, default: bool) -> bool:
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    binance_api_key: str
    binance_api_secret: str
    connector_token: str
    use_testnet: bool
    trade_mode: str  # confirm | auto
    host: str
    port: int
    max_notional_per_order: float
    max_open_positions: int
    max_daily_loss: float
    max_leverage: int
    max_margin_loss_on_stop: float
    min_notional_usdt: float
    proposal_ttl_seconds: int
    live_trading_ack: str
    log_file: Path
    audit_file: Path
    pending_file: Path
    risk_state_file: Path
    ai_feed_file: Path
    orchestrator_state_file: Path
    decision_interval_seconds: int


def load_settings() -> Settings:
    api_key = os.getenv("BINANCE_API_KEY", "").strip()
    api_secret = os.getenv("BINANCE_API_SECRET", "").strip()
    token = os.getenv("CONNECTOR_TOKEN", "").strip()
    use_testnet = _bool(os.getenv("USE_TESTNET"), False)
    live_ack = os.getenv("LIVE_TRADING_ACK", "").strip()

    if not api_key or not api_secret:
        raise ValueError("BINANCE_API_KEY and BINANCE_API_SECRET must be set in .env")
    if not token or len(token) < 32:
        raise ValueError("CONNECTOR_TOKEN must be set in .env and be at least 32 characters")

    if not use_testnet and live_ack != "I_ACCEPT_LIVE_RISK":
        raise ValueError(
            "Mainnet blocked: set USE_TESTNET=false AND LIVE_TRADING_ACK=I_ACCEPT_LIVE_RISK"
        )

    trade_mode = os.getenv("TRADE_MODE", "auto").strip().lower()
    if trade_mode not in ("confirm", "auto"):
        raise ValueError("TRADE_MODE must be 'confirm' or 'auto'")

    return Settings(
        root_dir=ROOT_DIR,
        binance_api_key=api_key,
        binance_api_secret=api_secret,
        connector_token=token,
        use_testnet=use_testnet,
        trade_mode=trade_mode,
        host=os.getenv("CONNECTOR_HOST", "127.0.0.1").strip(),
        port=int(os.getenv("CONNECTOR_PORT", "8080")),
        max_notional_per_order=float(os.getenv("MAX_NOTIONAL_PER_ORDER", "200")),
        max_open_positions=int(os.getenv("MAX_OPEN_POSITIONS", "5")),
        max_daily_loss=float(os.getenv("MAX_DAILY_LOSS", "100")),
        max_leverage=int(os.getenv("MAX_LEVERAGE", "20")),
        max_margin_loss_on_stop=float(os.getenv("MAX_MARGIN_LOSS_ON_STOP", "0.35")),
        min_notional_usdt=float(os.getenv("MIN_NOTIONAL_USDT", "5")),
        proposal_ttl_seconds=int(os.getenv("PROPOSAL_TTL_SECONDS", "300")),
        live_trading_ack=live_ack,
        log_file=ROOT_DIR / "connector.log",
        audit_file=ROOT_DIR / "audit.jsonl",
        pending_file=ROOT_DIR / "pending_trades.json",
        risk_state_file=ROOT_DIR / "risk-state.json",
        ai_feed_file=ROOT_DIR / "ai-feed.jsonl",
        orchestrator_state_file=ROOT_DIR / "orchestrator-state.json",
        decision_interval_seconds=int(os.getenv("DECISION_INTERVAL_SECONDS", "900")),
    )
