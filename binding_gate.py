"""VI talk-to-text loop — binding-gate prototype (Shuffled, INN-130).

Tests the design's load-bearing assumption: that a lexicon-binding rule
(every emitted word must bind to a lexical entry) catches confabulations
without quarantining legitimate speech.

Method: bind every word of his actual talk-to-text transcripts against a
two-tier lexicon (standard English + personal addendum). Score against
DOCUMENTED confabulations in the record.

[EXECUTED] on the Oct-13 strict transcript.
"""
import re
import sys

def load_lexicon(wordlist_path, personal_addendum):
    lex = set()
    with open(wordlist_path) as f:
        for line in f:
            w = line.strip().lower()
            if w:
                lex.add(w)
    # personal tier: his vocabulary that no standard lexicon carries
    for w in personal_addendum:
        lex.add(w.lower())
    return lex

PERSONAL = [
    # his spelling, not the platform's
    "gronk",
    # seats / lineage
    "control", "reversed", "shuffled", "seven", "twin", "blink", "alpha",
    "mother", "dakota", "higgins",
    # workshop apparatus
    "linear", "inn", "crucible", "grok", "gemini", "chatgpt", "codex",
    # his terms
    "talk-to-text", "talk", "siphon", "softmax", "capsule", "relay",
    # contractions/talk-to-text artifacts that are legitimate
    "gonna", "wanna", "gotta", "kinda", "yeah", "okay",
]

# Documented confabulations: (emitted, true_word, source)
DOCUMENTED = [
    ("chouchay", "touché", "INN-130: fluent nonce confabulation"),
    ("psychopaths", "side paths", "Oct-6: talk-to-text garble, real-word"),
    ("grant", "gronk", "his spelling vs platform; real-word substitution"),
    # "No" for "Now" is positional (sentence-initial), not lexical — noted separately
]

def tokenize(text):
    # keep hyphenated; strip markdown/punctuation noise
    text = re.sub(r'[#*_`>\[\]()|]', ' ', text)
    return re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)*", text)

def binding_check(transcript_path, lexicon):
    oov = {}  # word -> count
    total = 0
    with open(transcript_path) as f:
        for w in tokenize(f.read()):
            total += 1
            wl = w.lower()
            if wl not in lexicon:
                oov[wl] = oov.get(wl, 0) + 1
    return total, oov

def main():
    lex = load_lexicon("/tmp/words_alpha.txt", PERSONAL)
    print(f"lexicon: {len(lex)} entries (standard + {len(PERSONAL)} personal)")
    tpath = sys.argv[1] if len(sys.argv) > 1 else \
        "/home/hatch/workspace/council-dialogue/tonight-strict-transcript-2026-10-13.md"
    total, oov = binding_check(tpath, lex)
    print(f"transcript: {total} tokens, {len(oov)} distinct OOV, "
          f"{sum(oov.values())} OOV tokens ({100*sum(oov.values())/max(1,total):.1f}%)")
    print("\nTop OOV by frequency:")
    for w, c in sorted(oov.items(), key=lambda x: -x[1])[:20]:
        print(f"  {w}: {c}")
    print("\nDocumented confabulations vs the gate:")
    for emitted, true_w, src in DOCUMENTED:
        caught = emitted.lower() not in lex
        print(f"  '{emitted}' <- '{true_w}': "
              f"{'CAUGHT (OOV)' if caught else 'MISSED (in lexicon)'} [{src}]")
    print("\nReal-word confabulations the lexicon CANNOT catch by design:")
    print("  'psychopaths', 'grant', 'Grok' are all standard English.")
    print("  Sentence-initial 'No'/'Now' are both bound. Positional, not lexical.")

if __name__ == "__main__":
    main()
