#!/usr/bin/env python3
"""VI loop — Arm A regression test (INN-130).

Adapted from vi-loop-prototype/vi_loop_prototype.py (Arm A), which used a
standalone words.txt. This version binds against the merged repo's own
lexicons (bind.py: Tier 1 global + Tier 2 personal) so the test measures
the system as shipped.

Pre-registered break condition (from the prototype): if the OOV gate
catches < 50% of known error instances, the design is mis-scoped to the
spectacular failure (Chouchay) instead of the common one.

Run:  python3 tests/test_arm_a.py
Exit 0 always; the break condition is reported, not asserted — the
prototype decides, we don't.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import bind

# (intended, rendered) pairs from the operator's talk-to-text correction
# record plus the Chouchay incident. `rendered` is what the decoder emitted.
KNOWN_ERRORS = [
    ("touché", "Chouchay"),      # the incident: fluent OOV confabulation
    ("now", "No"),               # sentence-initial now -> No
    ("four and five", "4 from"),  # dropped conjunction
    ("gronk", "grant"),          # in-vocab substitution
    ("gronk", "Grok"),           # proper-noun miss
    ("archives", "art guys"),    # in-vocab substitution
    ("account", "count"),        # dropped leading syllable
    ("Demis", "dim Z"),          # name -> words
    ("Demis", "dems"),           # name -> near-miss
]

BREAK_CATCH_RATE = 0.50


def main():
    glob = bind.load_words(bind.GLOBAL_LEX)
    pers = bind.load_words(bind.PERSONAL_LEX)
    print(f"lexicon: tier1={len(glob)} tier2={len(pers)}")

    caught, missed, partial = [], [], []
    for intended, rendered in KNOWN_ERRORS:
        tokens, results = bind.bind_text(rendered, glob, pers, source="<arm-a>")
        # results: (token, tier, form); tier None => quarantined
        toks = [t for t, _, _ in results]
        quar = [t for t, tier, _ in results if tier is None]
        if not toks:
            missed.append((intended, rendered, "empty"))
        elif len(quar) == len(toks):
            caught.append((intended, rendered))
        elif quar:
            partial.append((intended, rendered, quar))
        else:
            missed.append((intended, rendered, "all-bound"))

    n = len(KNOWN_ERRORS)
    rate = len(caught) / n
    print("=== ARM A — gate coverage over known error corpus ===")
    for intended, rendered in caught:
        print(f"  CAUGHT  {rendered!r:12} (intended {intended!r})")
    for intended, rendered, why in missed:
        print(f"  MISSED  {rendered!r:12} (intended {intended!r}) [{why}]")
    for intended, rendered, quar in partial:
        print(f"  PARTIAL {rendered!r:12} (intended {intended!r}) quarantined={quar}")
    print(f"  catch rate: {len(caught)}/{n} = {rate:.0%}")
    if rate < BREAK_CATCH_RATE:
        print(f"  BREAK CONDITION TRIGGERED: {rate:.0%} < {BREAK_CATCH_RATE:.0%} — "
              "the OOV gate is mis-scoped to the spectacular failure.")
    else:
        print("  break condition not triggered.")
    return {"caught": len(caught), "missed": len(missed),
            "partial": len(partial), "rate": rate,
            "break": rate < BREAK_CATCH_RATE}


if __name__ == "__main__":
    main()
