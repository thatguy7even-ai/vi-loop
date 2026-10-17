#!/usr/bin/env python3
"""VI loop — batch review of pending quarantines (INN-130).

Walks quarantine_log.jsonl, presents each pending item with context and age,
takes the operator's verdict. Same verdict set as interrupt mode, so the two
modes are directly comparable via `bind.py --report`.

Usage:
  python3 review.py            # review all pending
  python3 review.py --max 10   # review at most 10
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bind import QLOG, prompt_verdict, apply_verdict


def age_str(ts):
    now = datetime.now(timezone.utc)
    secs = (now - datetime.fromisoformat(ts)).total_seconds()
    if secs < 3600:
        return f"{int(secs // 60)}m"
    if secs < 86400:
        return f"{secs / 3600:.1f}h"
    return f"{secs / 86400:.1f}d"


def main():
    ap = argparse.ArgumentParser(description="batch-review pending quarantines")
    ap.add_argument("--max", type=int, default=0, help="review at most N items")
    args = ap.parse_args()

    if not os.path.exists(QLOG):
        print("no quarantine log yet")
        return
    with open(QLOG, encoding="utf-8") as f:
        recs = [json.loads(l) for l in f if l.strip()]
    pending = [r for r in recs if r["status"] == "pending"]
    # force batch mode on anything reviewed here
    for r in pending:
        r["mode"] = "batch"
    if args.max:
        pending = pending[:args.max]
    print(f"{len(pending)} pending quarantines (batch review)")
    n = 0
    for rec in pending:
        print(f"\n--- [{n+1}/{len(pending)}] quarantined {age_str(rec['ts'])} ago ---")
        verdict, correction, op_s = prompt_verdict(rec)
        if verdict is None:
            print("  skipped (stays pending)")
            continue
        apply_verdict(rec, verdict, correction, op_s)
        print(f"  recorded: {verdict}" + (f" -> {correction}" if correction else ""))
        n += 1
    print(f"\ndone: {n} verdicts recorded")


if __name__ == "__main__":
    main()
