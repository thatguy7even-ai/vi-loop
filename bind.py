#!/usr/bin/env python3
"""VI talk-to-text loop — Tier 1/2 binding post-processor (INN-130 prototype).

The binding rule: every emitted word must be bound to a lexical entry.
  Tier 1 (global lexicon)  -> bound, passes.
  Tier 2 (personal lexicon) -> bound-personal, passes.
  Tier 3 (neither)          -> QUARANTINE + phone home (logged here; dispatch later).

Prototype scope: post-processor on decoder text output. No audio pipeline yet.
Measures the load-bearing number: quarantine rate per tier on real transcripts.

Usage:
  python3 bind.py transcript.txt            # full report
  python3 bind.py transcript.txt --json     # machine-readable quarantine log
  python3 bind.py --promote WORD            # confirm a word -> personal lexicon
  python3 bind.py --quarantine-log          # show pending quarantines

Quarantine log: lexicon/quarantine_log.jsonl (status: pending/confirmed/rejected).
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
LEXDIR = os.path.join(HERE, "lexicon")
GLOBAL_LEX = os.path.join(LEXDIR, "words_alpha.txt")
PERSONAL_LEX = os.path.join(LEXDIR, "personal_lexicon.txt")
QLOG = os.path.join(LEXDIR, "quarantine_log.jsonl")


def load_words(path):
    words = set()
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            words.add(line.lower())
    return words


def normalize_token(tok):
    """Lowercase, strip surrounding punctuation. Keep internal hyphens/apostrophes."""
    tok = tok.lower().strip()
    tok = re.sub(r"^[^a-z0-9']+|[^a-z0-9']+$", "", tok)
    return tok


PATTERNS = [
    (re.compile(r"^inn-\d+$"), "issue-ref"),
    (re.compile(r"^\d+(st|nd|rd|th)$"), "ordinal"),
    (re.compile(r"^message_break$"), None),  # markup artifact: drop, don't quarantine
]

CAMEL = re.compile(r"[a-z][A-Z]")


def split_camel(tok):
    return re.sub(r"([a-z])([A-Z])", r"\1 \2", tok).lower().split()


def bind_token(tok, glob, pers):
    """Return (tier, form) where tier in {1, 2, None}.
    (0, None) means: drop silently (markup, not a word)."""
    if not tok:
        return None, tok
    if tok.isdigit() or re.fullmatch(r"[0-9][0-9.,]*", tok):
        return 1, tok  # numbers bind trivially
    for pat, label in PATTERNS:
        if pat.match(tok):
            if label is None:
                return 0, None  # drop markup artifacts
            return 1, label
    if tok in glob:
        return 1, tok
    if tok in pers:
        return 2, tok
    # apostrophe variants: don't -> dont, then don+t
    nosq = tok.replace("'", "")
    if nosq != tok:
        if nosq in glob:
            return 1, nosq
        if nosq in pers:
            return 2, nosq
        parts = [p for p in tok.split("'") if p]
        if parts and all(p in glob or p in pers for p in parts):
            return 1, "+".join(parts)
    # hyphen variants: talk-to-text -> check parts
    if "-" in tok:
        parts = [p for p in tok.split("-") if p]
        if parts and all(p in glob or p in pers for p in parts):
            return 1, "+".join(parts)
    return None, tok


def bind_text(text, glob, pers, source="<stdin>"):
    # personal multi-word entries, longest first
    phrases = sorted(
        (p for p in pers if " " in p), key=lambda p: -len(p.split())
    )
    raw_tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9'_-]*", text)
    tokens = [normalize_token(t) for t in raw_tokens]
    tokens = [t for t in tokens if t]
    # keep raw forms aligned for camelCase fallback (whole-token lookup first)
    raws = [rt for rt in raw_tokens]
    raws = [rt for rt, t in zip(raw_tokens, [normalize_token(x) for x in raw_tokens]) if t]
    assert len(raws) == len(tokens)

    results = []  # (token, tier, form)
    skip = set()
    lowered = " " + " ".join(tokens) + " "
    for i, tok in enumerate(tokens):
        if i in skip:
            continue
        matched = False
        for ph in phrases:
            pw = ph.split()
            if tokens[i:i + len(pw)] == pw:
                results.append((ph, 2, ph))
                skip.update(range(i, i + len(pw)))
                matched = True
                break
        if not matched:
            tier, form = bind_token(tok, glob, pers)
            if tier is None and CAMEL.search(raws[i]):
                # camelCase fallback AFTER whole-token lookup: createdAt -> created+at
                parts = [normalize_token(p)
                         for p in re.sub(r"([a-z])([A-Z])", r"\1 \2", raws[i]).split()]
                parts = [p for p in parts if p]
                if parts and all(p in glob or p in pers for p in parts):
                    tier, form = 1, "+".join(parts)
            if tier == 0:
                continue  # markup artifact: not a word, not quarantined
            results.append((tok, tier, form))
    return tokens, results


def report(tokens, results, source):
    total = len(results)
    t1 = sum(1 for _, t, _ in results if t == 1)
    t2 = sum(1 for _, t, _ in results if t == 2)
    q = [(tok, i) for i, (tok, t, _) in enumerate(results) if t is None]
    print(f"source: {source}")
    print(f"tokens: {total}")
    print(f"  tier1 (global)   : {t1:5d}  ({t1/total*100:5.2f}%)")
    print(f"  tier2 (personal) : {t2:5d}  ({t2/total*100:5.2f}%)")
    print(f"  QUARANTINE       : {len(q):5d}  ({len(q)/total*100:5.2f}%)")
    if q:
        print("\nquarantined (word | context):")
        seen = {}
        for tok, i in q:
            seen[tok] = seen.get(tok, 0) + 1
        for tok, i in q:
            if seen[tok] > 1:
                pass  # listed once below with count
        for tok in dict.fromkeys(t for t, _ in q):
            idx = next(i for t, i in q if t == tok)
            lo = max(0, idx - 5)
            hi = min(len(tokens), idx + 6)
            ctx = " ".join(tokens[lo:hi])
            print(f"  x{seen[tok]:3d}  {tok:20s} ...{ctx}...")
    return q


def log_quarantines(q, tokens, results, source, mode="batch"):
    now = datetime.now(timezone.utc).isoformat()
    recs = []
    for tok in dict.fromkeys(t for t, _ in q):
        idx = next(i for t, i in q if t == tok)
        lo = max(0, idx - 5)
        hi = min(len(tokens), idx + 6)
        rec = {
            "ts": now,
            "word": tok,
            "context": " ".join(tokens[lo:hi]),
            "source": source,
            "mode": mode,
            "status": "pending",      # pending | confirmed | corrected | rejected | unsure
            "verdict_ts": None,
            "latency_s": None,        # verdict_ts - ts
            "correction": None,       # the true word, if verdict == corrected
            "operator_s": None,       # seconds the operator spent on this verdict
        }
        recs.append(rec)
    with open(QLOG, "a", encoding="utf-8") as f:
        for rec in recs:
            f.write(json.dumps(rec) + "\n")
    return recs


def apply_verdict(rec, verdict, correction=None, operator_s=None):
    """Record a verdict on a quarantine record; confirm promotes to Tier 2."""
    now = datetime.now(timezone.utc).isoformat()
    rec["status"] = verdict
    rec["verdict_ts"] = now
    t0 = datetime.fromisoformat(rec["ts"])
    t1 = datetime.fromisoformat(now)
    rec["latency_s"] = round((t1 - t0).total_seconds(), 1)
    rec["operator_s"] = operator_s
    if correction:
        rec["correction"] = correction
    if verdict == "confirmed":
        promote(rec["word"])
    rewrite_qlog(rec)


def rewrite_qlog(updated):
    """Replace the matching pending record in the log with the updated one."""
    if not os.path.exists(QLOG):
        return
    out = []
    with open(QLOG, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if (rec["word"] == updated["word"] and rec["ts"] == updated["ts"]
                    and rec["status"] == "pending"):
                out.append(updated)
            else:
                out.append(rec)
    with open(QLOG, "w", encoding="utf-8") as f:
        for rec in out:
            f.write(json.dumps(rec) + "\n")


def prompt_verdict(rec):
    print(f"\n[QUARANTINE] '{rec['word']}'")
    print(f"  context: ...{rec['context']}...")
    print("  [c]onfirm (it's his word -> Tier 2) / [f]ix (type the true word)")
    print("  [r]eject (true confabulation) / [u]nsure / [s]kip")
    import time
    t0 = time.time()
    while True:
        try:
            ans = input("  verdict> ").strip().lower()
        except EOFError:
            print("\n  (input closed — remaining items stay pending)")
            return None, None, None
        if ans in ("c", "confirm"):
            return "confirmed", None, round(time.time() - t0, 1)
        if ans in ("r", "reject"):
            return "rejected", None, round(time.time() - t0, 1)
        if ans in ("u", "unsure"):
            return "unsure", None, round(time.time() - t0, 1)
        if ans in ("s", "skip"):
            return None, None, None
        if ans in ("f", "fix"):
            corr = input("  true word> ").strip().lower()
            if corr:
                return "corrected", corr, round(time.time() - t0, 1)
            continue
        # bare text = correction
        if ans and " " not in ans:
            return "corrected", ans, round(time.time() - t0, 1)
        print("  c / f / r / u / s, or type the correction directly")


def promote(word):
    word = word.strip().lower()
    pers = load_words(PERSONAL_LEX)
    if word in pers:
        print(f"already in personal lexicon: {word}")
        return
    with open(PERSONAL_LEX, "a", encoding="utf-8") as f:
        f.write(word + "\n")
    print(f"promoted to personal lexicon: {word}")


def print_report():
    """Empirical mode comparison. Pre-registered decision rule (see README):
    batch wins if verdict agreement holds, time-cost is lower, and no
    significant context decay (unsure rate flat with staleness).
    Interrupt wins if batch unsure rate climbs with age, or splice-back
    latency (detection->verdict) matters for the deployment."""
    if not os.path.exists(QLOG):
        print("no quarantine data yet")
        return
    recs = []
    with open(QLOG, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    print(f"quarantine records: {len(recs)}")
    for mode in ("batch", "interrupt"):
        m = [r for r in recs if r.get("mode") == mode]
        done = [r for r in m if r["status"] != "pending"]
        pend = [r for r in m if r["status"] == "pending"]
        print(f"\n== {mode} ==  n={len(m)}  resolved={len(done)}  pending={len(pend)}")
        if not done:
            continue
        from collections import Counter
        dist = Counter(r["status"] for r in done)
        print("  verdicts:", dict(dist))
        lat = sorted(r["latency_s"] for r in done if r.get("latency_s") is not None)
        if lat:
            med = lat[len(lat) // 2]
            print(f"  detection->verdict latency: median {med}s  max {lat[-1]}s")
        ops = [r["operator_s"] for r in done if r.get("operator_s") is not None]
        if ops:
            print(f"  operator time/verdict: median {sorted(ops)[len(ops)//2]}s "
                  f"total {round(sum(ops),1)}s")
        # context decay: unsure rate by staleness bucket (batch mode)
        if mode == "batch":
            buckets = {"<1h": [], "1-24h": [], ">24h": []}
            now = datetime.now(timezone.utc)
            for r in done:
                age_h = (now - datetime.fromisoformat(r["ts"])).total_seconds() / 3600
                b = "<1h" if age_h < 1 else ("1-24h" if age_h < 24 else ">24h")
                buckets[b].append(r["status"] == "unsure")
            for b, flags in buckets.items():
                if flags:
                    print(f"  unsure rate @staleness {b}: "
                          f"{sum(flags)}/{len(flags)} = {sum(flags)/len(flags)*100:.0f}%")
    # agreement check: same word verdict in both modes
    words = {}
    for r in recs:
        if r["status"] not in ("pending", "unsure"):
            words.setdefault(r["word"], {})[r.get("mode")] = r["status"]
    both = {w: v for w, v in words.items() if "batch" in v and "interrupt" in v}
    if both:
        agree = sum(1 for v in both.values() if v["batch"] == v["interrupt"])
        print(f"\ncross-mode agreement: {agree}/{len(both)} words")


def show_qlog():
    if not os.path.exists(QLOG):
        print("no quarantines logged yet")
        return
    with open(QLOG, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            print(f"[{rec['status']:9s}] {rec['word']:20s} {rec['ts'][:16]}  {rec['source']}")


def main():
    ap = argparse.ArgumentParser(description="VI loop tiered binder (INN-130 prototype)")
    ap.add_argument("transcript", nargs="?", help="text file to bind")
    ap.add_argument("--json", action="store_true", help="emit quarantine log as JSON")
    ap.add_argument("--promote", metavar="WORD", help="confirm word -> personal lexicon")
    ap.add_argument("--quarantine-log", action="store_true", help="show pending quarantines")
    ap.add_argument("--no-log", action="store_true", help="don't append to quarantine log")
    ap.add_argument("--mode", choices=["batch", "interrupt"], default="batch",
                    help="quarantine handling: batch (log, review later) or "
                         "interrupt (prompt immediately). Default: batch.")
    ap.add_argument("--report", action="store_true",
                    help="empirical mode comparison from the quarantine log")
    args = ap.parse_args()

    if args.report:
        print_report()
        return

    if args.promote:
        promote(args.promote)
        return
    if args.quarantine_log:
        show_qlog()
        return

    glob = load_words(GLOBAL_LEX)
    pers = load_words(PERSONAL_LEX)

    if args.transcript:
        with open(args.transcript, encoding="utf-8", errors="replace") as f:
            text = f.read()
        source = args.transcript
    else:
        text = sys.stdin.read()
        source = "<stdin>"

    tokens, results = bind_text(text, glob, pers, source)
    q = report(tokens, results, source)
    if q and not args.no_log:
        recs = log_quarantines(q, tokens, results, source, mode=args.mode)
        print(f"\nlogged {len(recs)} unique quarantines -> {QLOG}  [mode={args.mode}]")
        if args.mode == "interrupt":
            for rec in recs:
                verdict, correction, op_s = prompt_verdict(rec)
                if verdict is None:
                    print("  skipped (stays pending)")
                    continue
                apply_verdict(rec, verdict, correction, op_s)
                print(f"  recorded: {verdict}" + (f" -> {correction}" if correction else ""))
    if args.json:
        print(json.dumps(
            [{"word": t, "status": "pending"} for t in dict.fromkeys(t for t, _ in q)],
            indent=1))


if __name__ == "__main__":
    main()
