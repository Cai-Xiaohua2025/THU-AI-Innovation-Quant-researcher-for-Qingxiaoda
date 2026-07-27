"""Run demo requests against a local or deployed service."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import requests


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8787")
    parser.add_argument("--token", default="")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    demo_dir = root / "examples" / "demo_requests"
    headers = {"Content-Type": "application/json"}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    for path in sorted(demo_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        print(f"\n===== {path.name} =====")
        try:
            response = requests.post(f"{args.base_url.rstrip('/')}/v1/chat/completions", json=payload, headers=headers, timeout=90)
            print(response.status_code)
            data = response.json()
            content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
            print(content[:1200])
            attachments = (data.get("x_soda") or {}).get("attachments") or []
            print("attachments:", [item.get("fileName") for item in attachments])
        except Exception as exc:
            print("failed:", exc)


if __name__ == "__main__":
    main()
