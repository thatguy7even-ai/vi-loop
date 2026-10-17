#!/usr/bin/env python3
"""Quarantine probe: measure lexicon-binding failure rate on real dictation.

INN-130 validation tool. Tests the VI loop's binding rule
("every emitted word must be bound to a lexical entry") against
Dakota's actual talk-to-text output from the workshop record.

Two questions:
  1. FALSE QUARANTINES: how many of his real words fail a static lexicon?
     (names, terms, neologisms — the usability threat)
  2. MISSED CONFABULATIONS: how many of his known mishearings PASS the
     lexicon? (wrong-words-that-bind — the semantic gap)

Lexicon: wordlist from /usr/share/dict/words if present, else a
downloaded SCOWL wordlist, else a minimal built-in set (marked).

Usage:
  python quarantine_probe.py --lexicon <path> [--words w1 w2 ...]
  python quarantine_probe.py --demo   # runs the known-case battery
"""
import argparse
import os
import sys
import urllib.request

# Known cases from the workshop record (MEMORY.md talk-to-text quirks + INN-130).
# Each: (emitted_word, true_word_or_None, expected_binding, notes)
KNOWN_CASES = [
    # Chouchay-class: non-word confabulations. SHOULD fail binding (true quarantine).
    ("Chouchay", "touché", False, "INN-130 incident: fluent non-word, no lexical entry"),
    # Dim-Z-class: wrong-words-that-bind. WILL pass binding (the semantic gap).
    ("dim", "Demis", True, "talk-to-text: 'dim Z' for Demis — binds, wrong referent"),
    ("Z", "Demis", True, "single letter binds; semantically wrong"),
    ("art", "archives", True, "'art guys' for archives — both bind"),
    ("guys", "archives", True, "see above"),
    ("count", "account", True, "dropped leading syllable — binds, wrong word"),
    ("grant", "gronk", True, "'grant'/'Grok' for gronk — binds, wrong word"),
    # False-quarantine class: his real vocabulary, OOV on static lexicon.
    ("gronk", "gronk", False, "his spelling; not in standard lexicons — false quarantine"),
    ("Demis", "Demis", False, "proper noun — false quarantine on static lexicon"),
    ("Hassabis", "Hassabis", False, "proper noun — false quarantine on static lexicon"),
    # Controls: ordinary words. Should bind.
    ("the", "the", True, "control: common word binds"),
    ("hello", "hello", True, "control: common word binds"),
]


def load_lexicon(path=None):
    """Load a wordlist. Returns (set_of_words, source_description)."""
    if path and os.path.exists(path):
        with open(path, encoding="utf-8", errors="ignore") as f:
            words = {w.strip().lower() for w in f if w.strip() and not w.startswith("#")}
        return words, f"file:{path} ({len(words)} entries)"
    sys_path = "/usr/share/dict/words"
    if os.path.exists(sys_path):
        with open(sys_path, encoding="utf-8", errors="ignore") as f:
            words = {w.strip().lower() for w in f if w.strip()}
        return words, f"system:{sys_path} ({len(words)} entries)"
    # Minimal fallback — marked as inadequate for real measurement.
    minimal = {
        "the", "a", "an", "and", "or", "not", "is", "are", "was", "were",
        "hello", "world", "dim", "art", "guys", "count", "grant", "z",
        "account", "archives", "touché", "touche",
    }
    return minimal, "BUILT-IN MINIMAL (inadequate — install a real wordlist)"


def check(word, lexicon):
    """Lexicon binding check. Returns True if bound (passes), False if OOV."""
    w = word.strip().lower().strip(".,!?;:\"'")
    return w in lexicon


def run_battery(lexicon, source):
    print(f"Lexicon: {source}\n")
    print(f"{'word':<12} {'binds?':<8} {'expected':<10} {'verdict':<14} notes")
    print("-" * 80)
    true_quarantines = 0
    false_quarantines = 0
    missed = 0
    correct_pass = 0
    for emitted, true_w, expected_bind, notes in KNOWN_CASES:
        binds = check(emitted, lexicon)
        exp_str = "bind" if expected_bind else "OOV"
        if binds == expected_bind:
            verdict = "CORRECT"
            if not binds and true_w == emitted:
                # OOV and it IS the true word -> false quarantine
                false_quarantines += 1
            elif not binds:
                true_quarantines += 1
            else:
                correct_pass += 1
        else:
            if binds and not expected_bind:
                # Passed but shouldn't have... actually for dim-Z class,
                # expected_bind=True (they DO bind) — the "miss" is semantic.
                verdict = "UNEXPECTED"
            else:
                verdict = "UNEXPECTED"
        # Special marking for the semantic gap:
        if emitted in ("dim", "Z", "art", "guys", "count", "grant") and binds:
            verdict = "BINDS (semantic gap)"
            missed += 1
        print(f"{emitted:<12} {str(binds):<8} {exp_str:<10} {verdict:<14} {notes}")
    print("-" * 80)
    print(f"True quarantines (Chouchay-class caught): {true_quarantines}")
    print(f"False quarantines (his words flagged):    {false_quarantines}")
    print(f"Semantic-gap misses (bind but wrong):     {missed}")
    print(f"Correct passes (ordinary words):          {correct_pass}")
    return {
        "true_quarantines": true_quarantines,
        "false_quarantines": false_quarantines,
        "semantic_gap_misses": missed,
        "correct_pass": correct_pass,
    }


def main():
    ap = argparse.ArgumentParser(description="Quarantine probe for INN-130.")
    ap.add_argument("--lexicon", default=None, help="path to wordlist file")
    ap.add_argument("--demo", action="store_true",
                    help="run the known-case battery from the workshop record")
    ap.add_argument("--words", nargs="*", default=[],
                    help="words to check against the lexicon")
    args = ap.parse_args()

    lexicon, source = load_lexicon(args.lexicon)

    if args.demo:
        run_battery(lexicon, source)
    elif args.words:
        for w in args.words:
            print(f"{w}: {'BINDS' if check(w, lexicon) else 'OOV -> QUARANTINE'}")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
