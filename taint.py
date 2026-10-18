#!/usr/bin/env python3
"""VI talk-to-text loop — taint-marking (Five, INN-130).

The load-bearing weak point: quarantine -> phone-home -> splice corrects the
token but not the context the token poisoned. Words decoded after a
confabulation were chosen with the confabulation in the LM's context window.
Splicing the true word back repairs the token; the downstream span stays
tainted — decoded under a corrupted prior, confidence discounted.

This module marks that span. On resolution of a quarantine, it records a
taint record covering [quarantine, resolution]: the suspect word, the
correction, the phone-home verdict, the span (token positions now,
wall-clock times when the audio pipeline provides them), and the latency.
If budget allows, the span is re-decoded with the correction forced in
context (repair pass); otherwise the taint mark travels downstream with the
transcript so the relay and the workshop know the span's provenance.

Prototype scope: the binder is currently a batch text post-processor
(bind.py), so spans are positional (token indices). The schema carries
span_time for the streaming audio pipeline when it lands. In batch mode the
span runs from the quarantined token to the end of the transcript — the
honest bound, since everything after was decoded under the corrupted prior.
Streaming will narrow it to [quarantine_t, resolve_t].

Taint log: lexicon/taint_log.jsonl (append-only).

Usage:
  python3 taint.py --resolve WORD --verdict-json verdict.json --transcript transcript.txt
      Apply a phone-home verdict: splice the correction, mark the taint span.
      verdict.json: {"verdict": "CORRECTED", "correction": "touché", ...}
                    (as returned by phone_home.py)
  python3 taint.py --report
      Blast-radius stats: span-length distribution, latencies, verdict mix.
      This is the measurement the design calls for: confabulation blast
      radius over real dictation.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bind

TLOG = os.path.join(HERE, "lexicon", "taint_log.jsonl")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def find_quarantine(word):
    """Latest pending quarantine record for word, or None."""
    if not os.path.exists(bind.QLOG):
        return None
    latest = None
    with open(bind.QLOG, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec["word"] == word and rec["status"] == "pending":
                latest = rec
    return latest


def mark_taint(qrec, verdict, correction, tokens, q_idx, verdict_data=None):
    """Build and append a taint record. Returns the record dict."""
    # Batch prototype: span runs quarantine_idx -> end of transcript.
    # Streaming pipeline will narrow to [quarantine_t, resolve_t].
    span = [q_idx, len(tokens)]
    rec = {
        "ts": now_iso(),
        "event_id": verdict_data.get("event_id"),  # phone-home event, join key
        "quarantine_ref": {"word": qrec["word"], "ts": qrec["ts"]},
        "quarantine_word": qrec["word"],
        "quarantine_ts": qrec["ts"],
        "correction": correction,
        "verdict": verdict,
        "span_tokens": span,
        "span_time": None,  # filled by the streaming audio pipeline
        "span_len_tokens": span[1] - span[0],
        "latency_s": qrec.get("latency_s"),
        "status": "tainted",  # tainted | repaired | unresolved
        "mode": "batch-positional",
        "note": ("words after the confabulation were decoded with it in the "
                 "LM context; correction spliced at index %d, span to end "
                 "marked tainted" % q_idx),
    }
    with open(TLOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def splice(tokens, q_idx, correction):
    """Return a new token list with the correction spliced at q_idx."""
    out = list(tokens)
    out[q_idx] = correction
    return out


def resolve(word, verdict_data, transcript_path):
    """Full resolution flow: verdict -> splice -> taint mark."""
    qrec = find_quarantine(word)
    if not qrec:
        print(f"no pending quarantine for {word!r}", file=sys.stderr)
        sys.exit(1)
    with open(transcript_path, encoding="utf-8") as f:
        text = f.read()
    glob = bind.load_words(bind.GLOBAL_LEX)
    pers = bind.load_words(bind.PERSONAL_LEX)
    tokens, results = bind.bind_text(text, glob, pers, source=transcript_path)
    # find the quarantined token index
    q_idx = next((i for i, (tok, t, _) in enumerate(results)
                  if t is None and tok == word), None)
    if q_idx is None:
        print(f"{word!r} not quarantined in {transcript_path}", file=sys.stderr)
        sys.exit(1)

    verdict = verdict_data.get("verdict", "UNKNOWN")
    correction = verdict_data.get("correction")
    # record the verdict on the quarantine log (bind.py's own flow)
    status_map = {"CORRECTED": "corrected", "AGREEMENT-ON-OOV": "unsure",
                  "NO-SPEECH": "rejected"}
    bind.apply_verdict(qrec, status_map.get(verdict, "unsure"),
                       correction=correction)
    # re-read to get latency_s filled in
    qrec = find_quarantine(word) or qrec
    # find again post-verdict (status changed); match by word+ts
    if not os.path.exists(bind.QLOG):
        pass

    corrected_tokens = splice(tokens, q_idx, correction) if correction else tokens
    trec = mark_taint(qrec, verdict, correction, tokens, q_idx, verdict_data)

    corrected_text = " ".join(corrected_tokens)
    print(f"spliced: {word!r} -> {correction!r} at token {q_idx}")
    print(f"taint span: tokens {trec['span_tokens']} "
          f"({trec['span_len_tokens']} tokens downstream)")
    print(f"status: {trec['status']} | latency: {trec['latency_s']}s")
    return corrected_text, trec


def report():
    """Blast-radius stats over the taint log."""
    if not os.path.exists(TLOG):
        print("no taint records yet")
        return
    recs = [json.loads(l) for l in open(TLOG, encoding="utf-8")]
    spans = [r["span_len_tokens"] for r in recs if r["span_len_tokens"]]
    lats = [r["latency_s"] for r in recs if r["latency_s"] is not None]
    from collections import Counter
    verdicts = Counter(r["verdict"] for r in recs)
    print(f"taint records: {len(recs)}")
    print(f"verdicts: {dict(verdicts)}")
    if spans:
        spans.sort()
        print(f"blast radius (tokens downstream of confabulation): "
              f"min={spans[0]} p50={spans[len(spans)//2]} max={spans[-1]} "
              f"mean={sum(spans)/len(spans):.1f}")
    if lats:
        print(f"quarantine->resolution latency_s: "
              f"min={min(lats):.1f} max={max(lats):.1f} "
              f"mean={sum(lats)/len(lats):.1f}")
    print("status counts:", dict(Counter(r["status"] for r in recs)))


def main():
    ap = argparse.ArgumentParser(description="taint-marking for the VI loop")
    ap.add_argument("--resolve", metavar="WORD",
                    help="resolve a pending quarantine for WORD")
    ap.add_argument("--verdict-json", metavar="FILE",
                    help="phone_home.py verdict JSON")
    ap.add_argument("--transcript", metavar="FILE",
                    help="transcript the quarantine came from")
    ap.add_argument("--report", action="store_true",
                    help="blast-radius stats")
    args = ap.parse_args()
    if args.report:
        report()
    elif args.resolve and args.verdict_json and args.transcript:
        with open(args.verdict_json, encoding="utf-8") as f:
            verdict_data = json.load(f)
        text, _ = resolve(args.resolve, verdict_data, args.transcript)
        print("--- corrected transcript ---")
        print(text)
    else:
        ap.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
