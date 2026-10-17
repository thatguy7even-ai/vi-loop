#!/usr/bin/env python3
"""lexicon.py — write-quarantined lexicon for the INN-130 VI talk-to-text loop.

The binding rule (every emitted word must be bound to a lexical entry)
assumes the lexicon is trustworthy. It isn't — it's writeable, and the
phone-home loop writes to it. Without write provenance, the loop launders
its own confabulations: "Chouchay" phones home, the listener returns
"Chouchay," it gets filed, the binding rule passes it next time.

This module quarantines the *writes*, not just the emissions:
- Append-only log. Every entry: {word, source, verified, timestamp, evidence}.
- source ∈ {bootstrap-seed, human-verified, phone-home}.
- Binding passes iff entry exists AND (source == bootstrap-seed OR verified).
- Phone-home outputs enter as source=phone-home, verified=False.
  They satisfy NOTHING until a human (or second independent listener) verifies.
- The hallucination-event log records every interception:
  {audio_ref, word_reached_for, phone_home_returned, filed_as}.

Sits alongside ears-for-ais/transcribe.py (the Ears-class listener).
The phone-home side calls phone_home_event(); the on-device decoder
calls check_word() per emission.
"""
from __future__ import annotations
import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

SOURCES = ("bootstrap-seed", "human-verified", "phone-home")


@dataclass
class LexiconEntry:
    word: str
    source: str
    verified: bool
    timestamp: float
    evidence: str = ""

    def __post_init__(self):
        assert self.source in SOURCES, f"bad source: {self.source}"
        if self.source in ("bootstrap-seed", "human-verified"):
            assert self.verified, "seed/verified entries must be verified=True"

    def binds(self) -> bool:
        """The binding rule: does this entry let the word pass?"""
        return self.verified


@dataclass
class HallucinationEvent:
    timestamp: float
    audio_ref: str
    word_reached_for: str   # what the on-device decoder emitted
    phone_home_returned: str  # what the Ears listener heard
    filed_as: str           # lexicon source it was filed under (always phone-home)


class Lexicon:
    """Append-only, provenance-marked. Backed by a JSONL file."""

    def __init__(self, path: str):
        self.path = path
        self.entries: Dict[str, LexiconEntry] = {}
        self.events: List[HallucinationEvent] = []
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    d = json.loads(line)
                    if d.get("type") == "event":
                        d.pop("type")
                        self.events.append(HallucinationEvent(**d))
                    else:
                        d.pop("type", None)
                        e = LexiconEntry(**d)
                        self.entries[e.word.lower()] = e

    def _append(self, obj: dict, kind: str):
        obj = dict(obj, type=kind)
        with open(self.path, "a") as f:
            f.write(json.dumps(obj) + "\n")

    def seed(self, words, evidence="bootstrap"):
        for w in words:
            e = LexiconEntry(word=w, source="bootstrap-seed", verified=True,
                             timestamp=time.time(), evidence=evidence)
            self.entries[w.lower()] = e
            self._append(asdict(e), "entry")

    def check_word(self, word: str):
        """Binding check per emission. Returns (bound: bool, reason: str)."""
        e = self.entries.get(word.lower())
        if e is None:
            return False, f"'{word}': no lexical entry — QUARANTINE + phone home"
        if e.binds():
            return True, f"'{word}': bound ({e.source}) — passes"
        return False, (f"'{word}': entry exists but unverified "
                       f"(source={e.source}) — QUARANTINE + phone home")

    def check_text(self, text: str):
        import re
        words = re.findall(r"[A-Za-zÀ-ÿ']+", text)
        return [(w, *self.check_word(w)) for w in words]

    def phone_home_event(self, audio_ref: str, word_reached_for: str,
                         listener_returned: str):
        """Log the interception; file the listener's output as UNVERIFIED.
        This is the anti-laundering rule: the loop's own output never
        satisfies the binding rule."""
        ev = HallucinationEvent(
            timestamp=time.time(), audio_ref=audio_ref,
            word_reached_for=word_reached_for,
            phone_home_returned=listener_returned, filed_as="phone-home")
        self.events.append(ev)
        self._append(asdict(ev), "event")
        key = listener_returned.lower()
        if key not in self.entries:
            e = LexiconEntry(word=listener_returned, source="phone-home",
                             verified=False, timestamp=time.time(),
                             evidence=f"phone-home from {audio_ref}")
            self.entries[key] = e
            self._append(asdict(e), "entry")
        return ev

    def verify(self, word: str, by: str = "human", audio_ref: str = ""):
        """Human (or second independent listener) promotes an entry.
        Verdict trail: who confirmed, when, from what audio.
        audio_ref grounds the promotion in a specific clip — required
        per the operator's alteration-record ruling (INN-130 Q2 lift)."""
        e = self.entries.get(word.lower())
        if e is None:
            raise KeyError(f"no entry for '{word}' — nothing to verify")
        prior = f"{e.source}/verified={e.verified}"
        e.source = "human-verified"
        e.verified = True
        e.evidence = (f"verified by {by} at {time.time():.0f} "
                      f"from audio={audio_ref or 'n/a'}; was {prior}")
        self._append(asdict(e), "entry")
        return e

    def revoke(self, word: str, reason: str, by: str = "human"):
        """Revocation path (operator ruling): if a promotion was wrong,
        revoke it — append-only, never delete. The entry stays in the log
        with its full history; binds() goes False. Diagnosability: the
        trail shows what was promoted, why, and why it was pulled."""
        e = self.entries.get(word.lower())
        if e is None:
            raise KeyError(f"no entry for '{word}' — nothing to revoke")
        prior = f"{e.source}/verified={e.verified}"
        e.verified = False
        e.evidence = (f"REVOKED by {by} at {time.time():.0f}: {reason}; "
                      f"was {prior}; original evidence: {e.evidence[:80]}")
        self._append(asdict(e), "entry")
        return e

    def quarantine_report(self):
        q = [e for e in self.entries.values() if not e.binds()]
        return {"n_entries": len(self.entries), "n_quarantined": len(q),
                "quarantined": [e.word for e in q],
                "n_events": len(self.events)}


if __name__ == "__main__":
    import tempfile
    path = os.path.join(tempfile.mkdtemp(), "lexicon.jsonl")
    lex = Lexicon(path)
    # Bootstrap: a small seed vocabulary (the trusted core).
    lex.seed(["the", "a", "touché", "well", "played", "hello", "world"],
             evidence="bootstrap core vocab")

    print("### 1. On-device emission: '...well played, Chouchay!' ###")
    for w, bound, reason in lex.check_text("well played, Chouchay"):
        print(f"  {reason}")

    print("\n### 2. Phone-home: Ears listener hears the same clip ###")
    # The listener ALSO confabulates (shared acoustic ambiguity).
    ev = lex.phone_home_event(audio_ref="clip-042.wav",
                              word_reached_for="Chouchay",
                              listener_returned="Chouchay")
    print(f"  event logged: reached for '{ev.word_reached_for}', "
          f"listener returned '{ev.phone_home_returned}', "
          f"filed as '{ev.filed_as}' (unverified)")

    print("\n### 3. Recheck: does the loop launder its own output? ###")
    bound, reason = lex.check_word("Chouchay")
    print(f"  {reason}")
    assert not bound, "LAUNDERING BUG: unverified phone-home output passed binding"

    print("\n### 4. Human adjudicates: 'Chouchay' is not a word ###")
    # The human listens to clip-042.wav, confirms the speaker said "touché".
    # "Chouchay" is rejected as non-lexical: the entry is NOT verified,
    # so it stays quarantined permanently. The rejection is itself logged
    # as evidence on the entry (audit trail, not a promotion).
    e = lex.entries["chouchay"]
    e.evidence = "human rejected as non-lexical at %.0f; entry stays quarantined" % time.time()
    lex._append(asdict(e), "entry")
    print("  human rejects 'Chouchay': entry stays quarantined, rejection logged")

    print("\n### 5. Verdict trail + revocation path (Q2-lift ruling) ###")
    # A genuine novelty: human verifies a new word, grounded in audio.
    lex.phone_home_event(audio_ref="clip-043.wav",
                         word_reached_for="parp",
                         listener_returned="parp")
    lex.verify("parp", by="human", audio_ref="clip-043.wav")
    bound, reason = lex.check_word("parp")
    print(f"  after verify: {reason}")
    assert bound
    # The verification was wrong (listener misheard; speaker said "harp").
    # Revoke: append-only, trail preserved.
    lex.revoke("parp", reason="speaker said 'harp' (clip-043 re-listen)",
               by="human")
    bound, reason = lex.check_word("parp")
    print(f"  after revoke: {reason}")
    assert not bound
    e = lex.entries["parp"]
    assert "REVOKED" in e.evidence and "clip-043" in e.evidence
    print("  verdict trail intact: promotion + revocation both in the log")

    print("\n### 6. Quarantine report ###")
    rep = lex.quarantine_report()
    print(f"  entries={rep['n_entries']} quarantined={rep['n_quarantined']} "
          f"{rep['quarantined']} events={rep['n_events']}")
    print("\nWRITE-QUARANTINE PROTOTYPE: executed. [SEVEN / INN-130]")
    print("The loop cannot launder its own confabulations into the lexicon.")
