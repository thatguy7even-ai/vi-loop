#!/usr/bin/env python3
"""VI talk-to-text loop — splice-back (INN-130).

The phone-home listener returns the true word; this module splices it back
into the transcript at the quarantined position and hands the downstream
span to taint.py.

Extracted as a standalone component during the VI merge (2026-10-17):
previously inline in Blink's Arm B. Friction F3 — the design named
splice-back but nobody had built it separately.

Contract:
  IN:  transcript tokens (list), quarantine index, correction word,
       event_id (links to quarantine_log.jsonl / events)
  OUT: spliced tokens, splice record {event_id, index, was, now, ts}

Usage:
  python3 splice.py --transcript t.txt --index 12 --correction touché --event-id abc123
  python3 splice.py --demo
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def splice(tokens, index, correction, event_id):
    """Replace tokens[index] with correction. Returns (new_tokens, record)."""
    if not (0 <= index < len(tokens)):
        raise IndexError(f"quarantine index {index} out of range for {len(tokens)} tokens")
    was = tokens[index]
    new_tokens = tokens[:index] + [correction] + tokens[index + 1:]
    record = {
        "event_id": event_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "index": index,
        "was": was,
        "now": correction,
        "downstream_from": index + 1,  # taint.py marks [index+1, ...]
    }
    return new_tokens, record


def main():
    ap = argparse.ArgumentParser(description="splice a correction back into a transcript")
    ap.add_argument("--transcript", help="text file to splice into")
    ap.add_argument("--index", type=int, help="token index of the quarantined word")
    ap.add_argument("--correction", help="the true word from phone-home / operator")
    ap.add_argument("--event-id", default=None, help="links to the quarantine event")
    ap.add_argument("--demo", action="store_true", help="run a demo splice")
    args = ap.parse_args()

    if args.demo:
        tokens = "the chouchay incident was a test".split()
        new_tokens, rec = splice(tokens, 1, "touché", "demo-001")
        print("before:", " ".join(tokens))
        print("after: ", " ".join(new_tokens))
        print("record:", json.dumps(rec, indent=1))
        return

    with open(args.transcript, encoding="utf-8") as f:
        tokens = f.read().split()
    new_tokens, rec = splice(tokens, args.index, args.correction, args.event_id)
    print(" ".join(new_tokens))
    print(json.dumps(rec), file=sys.stderr)


if __name__ == "__main__":
    main()
