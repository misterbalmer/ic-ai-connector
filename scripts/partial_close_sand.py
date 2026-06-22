#!/usr/bin/env python3
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
BASE = f"http://{os.getenv('CONNECTOR_HOST', '127.0.0.1')}:{os.getenv('CONNECTOR_PORT', '8080')}"
TOKEN = os.getenv("CONNECTOR_TOKEN", "")
PCT = float(sys.argv[1]) if len(sys.argv) > 1 else 50.0

headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
with httpx.Client(timeout=60.0) as c:
    before = c.post(f"{BASE}/positions", headers=headers, json={}).json()
    print("Before:", before.get("active_positions"))
    r = c.post(f"{BASE}/partial_close", headers=headers, json={"symbol": "SANDUSDT", "percentage": PCT})
    body = r.json()
    print(f"Propose {PCT}%:", r.status_code, body.get("summary"))
    if r.status_code != 200:
        print(body)
        sys.exit(1)
    pid = body.get("proposal", {}).get("proposal_id")
    cr = c.post(f"{BASE}/trade/confirm", headers=headers, json={"proposal_id": pid})
    print("Confirm:", cr.status_code, cr.text[:400])
    after = c.post(f"{BASE}/positions", headers=headers, json={}).json()
    print("After:", after.get("active_positions"))
