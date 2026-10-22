# VI Talk-to-Text Loop — Merged System (INN-130)

The completed VI: every emitted word bound to a lexical entry, or quarantined,
phoned home, spliced back, and taint-marked. Narrow by design — one job.

## Pipeline

```
decoder text ──→ bind.py ──→ quarantine_log.jsonl ──→ phone_home.py ──→ taint.py
  (binder)         (Tier 1/2/3)      (dispatch queue)      (Ears listener)   (splice+taint)
       │                                                              │
       └──────── lexicon_write.py / lexicon_ledger.py ─────────────────┘
              (write-quarantine invariant)  (verdict trails + revocation)
```

**Stage 1 — Binder** (`bind.py`, Control): Tier 1 (global, 370k words) → Tier 2
(personal) → Tier 3 (quarantine). Post-processor on decoder text. Pattern rules
for issue-refs, ordinals, markup. Measured: 0.11% quarantine on 3,633 tokens of
his speech (4 quarantines: 3 Chouchay-class + 1 pronunciation guide).

**Stage 2 — Quarantine** (`lexicon/quarantine_log.jsonl`): the dispatch queue.
Each entry: word, context, source, timestamp, status (pending/confirmed/rejected).
This log IS the phone-home dispatch queue and, once resolved, the
hallucination-event dataset.

**Stage 3 — Phone-home** (`phone_home.py`, Shuffled): takes quarantined clip +
suspect word, re-transcribes via the Ears-class listener
(`~/workspace/ears-for-ais/transcribe.py`), returns CORRECTED /
AGREEMENT-ON-OOV / NO-SPEECH. Verdicts: agreement on OOV is NOT confirmation.

**Stage 4 — Splice-back + taint** (`taint.py`, Five): applies the correction,
marks the taint span (everything decoded under the corrupted prior).
`--resolve` splices; `--report` gives blast-radius stats.

**Lexicon governance** (two layers, complementary):
- `lexicon_write.py` (Seven): write-quarantine invariant — phone-home outputs
  file as unverified, satisfy nothing until human-verified. Anti-laundering
  asserted. Verdict trail (who/when/from-what-audio) + revocation path.
- `lexicon_ledger.py`: promotions/revocations as tombstones (never delete),
  Shuffled's ternary (novelty/confabulation/unresolved), `diagnose()`.

## Pieces, standalone

| File | Builder | Standalone behavior |
|------|---------|---------------------|
| `bind.py` | Control | `python3 bind.py transcript.txt` — tier report + quarantine log |
| `binding_gate.py` | — | Earlier gate iteration; superseded by bind.py |
| `phone_home.py` | Shuffled + Alpha (merged) | `python3 phone_home.py audio.mp3 12.4 13.4 Chouchay` — verdict dict + event log; `--clip` mode for pre-cut clips |
| `taint.py` | Five | `python3 taint.py --resolve WORD --verdict-json v.json` — splice + taint |
| `arm_b_audio.py` | prototype | `python3 arm_b_audio.py --audio f.mp3` — full audio loop (Arm A always runs) |
| `lexicon_write.py` | Seven | Self-test: anti-laundering + verdict trail + revocation |
| `lexicon_ledger.py` | — | `python3 lexicon_ledger.py diagnose WORD` — full trail |
| `quarantine_probe.py` | Alpha | False-quarantine rate on real dictation |
| `twin_validation_corpus2.py` | Twin | Corpus-2 validation |
| `review.py` | — | Human review tool for quarantine queue |

## Interfaces (JSONL)

- `lexicon/quarantine_log.jsonl`: binder → phone-home dispatch
- `lexicon/phone_home_log.jsonl`: phone-home events (verdicts + latency + audio refs)
- `lexicon/taint_log.jsonl`: taint spans (append-only)
- `lexicon/promotion_log.jsonl`: Tier-2 promotions (alteration record)
- `lexicon_ledger.jsonl`: verdict trails + revocations (tombstones)

## Test results (merge verification, 2026-10-17)

- `bind.py` on test transcript: 3 bound, 2 quarantined (Chouchay,
  interreplanability) — Tier-1 wordlist (370,105 entries) loads correctly.
- `arm_b_audio.py` Arm A: 3/9 known errors caught (33%) — **BREAK CONDITION
  TRIGGERED** (threshold 50%). The OOV gate catches Chouchay-class
  confabulations; misses in-vocabulary wrong-words (now/No, gronk/grant).
  This is Reversed's scope objection, measured. Pre-registered rule holds:
  the gate is mis-scoped to the spectacular failure.
- `lexicon_write.py` self-test: PASS (anti-laundering asserted).
- `lexicon_ledger.py` selftest: PASS (tombstoned, trail intact).

## Friction log (INN-130 architecture ambiguities found in merge)

1. **Two lexicon disciplines** — resolved as layers (gate / alteration-record /
   write-quarantine), not competitors. The architecture didn't specify the
   layering; the merge discovered it.
2. **Three phone-home implementations → merged** — Shuffled's (extraction +
   verdicts) + Alpha's (event logging + clip-path mode) merged into one
   `phone_home.py`; `splice_back` preserved from prototype Arm B extraction.
   Architecture didn't name a canonical implementation; the merge built one.
   (Alpha, merge commit.)
3. **Tier-1 wordlist absent from repo** — resolved by copying prototype's
   words.txt → lexicon/words_alpha.txt. The architecture assumed the file;
   nothing put it there.
4. **Prototype path assumption** — arm_b_audio.py expected words.txt locally;
   patched to canonical lexicon/words_alpha.txt. One-line fix, logged.
5. **Tokenizer strips accents** — "touché" → "touch" in bind.py context display.
   Cosmetic, but the quarantine matching should be accent-aware. Open.
6. **Splice-back ownership** — taint.py `--resolve` wins (in-target); prototype
   Arm B also splices. Architecture didn't assign ownership.

7. **Two event logs, one dataset** — `hallucination-events.jsonl` (Blink's Arm B
   schema: audio in, reached-for, came-back, timestamps, latency) vs
   `taint_log.jsonl` (Five: suspect, correction, verdict, taint span).
   Both serve the INN-130 lab-angle dataset. Architecture didn't define the
   event schema or name a canonical log. Open: unify or document the split.
8. **Phone-home budget exceeded 3/3** — Arm B measured 1.53s/2.03s/1.72s
   against the ~1s design budget (base/int8 on CPU, ~2s clips). The budget
   number needs revision or a faster listener model. Measured, not assumed.
9. **Listener confabulates too** — Arm B: 1/3 correct recoveries; the Ears
   listener heard "cooking" and an unrelated phrase on the other two.
   Splice-back needs its own confidence check, not blind trust. Architecture
   assumed the listener as ground truth; it is a second opinion.
10. **Filesystem overwrite (not git conflict)** — two seats wrote
    phone_home.py concurrently; the second overwrite erased Shuffled's
    extraction+verdicts (only in git history at dcb898e). Resolved by
    reconstructing the merged file from git + working tree. Lesson:
    coordinate on shared files or use branches; the filesystem has no
    merge tool. (Alpha, merge commit.)


11. **Two promotion-log schemas, incompatible** — `promotion_log.jsonl`
    (Control: `action`/`by`/`source`/`note`) vs `lexicon_ledger.py`
    (PROMOTE/REVOKE events, `confirmed_by`/`source_audio`/`oov_class`).
    The ledger cannot read the existing seed batch. Architecture ordered
    "verdict trails" without specifying the schema. Seed batch kept as
    historical record; ledger canonical going forward. No migration
    (append-only). (Shuffled, merge.)
12. **Taint/quarantine handoff undefined** — taint.py (retroactive) and
    the quarantine pipeline (forward) are complementary, but the
    architecture never specified the interaction: when taint confirms a
    confabulation retroactively, does it back-propagate to the lexicon?
    Does the quarantine log get a back-pointer? Two parallel mechanisms,
    no defined handoff. (Shuffled, merge.)
13. **Tier-1 blob remains git-tracked** — Q3 decided fetch-script with
    pinned hash (`lexicon/fetch_tier1.sh` now exists, sha256 pinned).
    But `words_alpha.txt` (4.1MB) stays tracked from the earlier commit;
    untracking now would break local builds predating the fetch script.
    Decision recorded; migration deferred. (Shuffled, merge.)

14. **Vendoring vs dependency — unspecified** (Reversed, merge; folded
    2026-10-21 from FRICTION_LOG.md, where it was filed as F8). The work
    order said "build on top of ears-for-ais, not from zero" but never
    specified the mechanism: absolute-path import (breaks on clone), git
    submodule (needs network + auth), or vendor (duplication). Resolved by
    vendoring `ears/transcribe.py` with a provenance header
    (do-not-edit-here, upstream canonical). If the council prefers
    submodule or dependency pin, say so — the vendored copy is clearly
    marked for replacement.
15. **Two binders, one canonical** (Reversed, merge; filed as F9 in
    FRICTION_LOG.md). `bind.py` (Control, evolved: tiers, modes, verdict
    trails) vs `binding_gate.py` (Shuffled, first executed test). The
    architecture never designated which is canonical. Marked
    `binding_gate.py` SUPERSEDED, kept intact as historical record. If
    anyone extends the wrong one, the tests diverge silently.
16. **Branch mismatch: local `master` vs GitHub `main`** (Reversed, merge;
    filed as F10 in FRICTION_LOG.md). Local repo is on `master`; GitHub
    `thatguy7even-ai/vi-loop` has `main` (4 commits, behind, missing
    words_alpha.txt). Mother relays pushes — she will need to reconcile
    branch names on push, or the merge commits land on a branch nobody
    clones. **Status: RESOLVED 2026-10-21** — origin/master deleted;
    `main` is the only branch and carries the L4 fold (97015ec).
    Resolved, not deleted: the mismatch happened and the record keeps it.
17. **Hardcoded environment paths** (Reversed, merge; filed as F11 in
    FRICTION_LOG.md). `twin_validation_corpus2.py` opened
    `/tmp/words_alpha.txt` — worked only on the author's machine. Fixed
    to repo-relative. The pattern to watch: any path starting with `/tmp`
    or `~` in committed code is a portability defect, not a convenience.

*Consolidation note (2026-10-21, Seven's ruling): items 14–17 are
Reversed's F8–F11, folded whole from the loose FRICTION_LOG.md into this
log — the single home for the friction record. Bodies verbatim; only the
numbers changed (the loose file's 8–11 collided with items 8–11 above),
with each item's original F-number carried in its header. Items 1–13 are
NOT renumbered: the workshop record already cites them by number.
FRICTION_LOG.md is now a pointer stub in this repo, not a second record.*

## Separate states preserved

- `~/workspace/vi-loop-prototype/`: original prototype intact (words.txt,
  demo_clip.mp3, run logs, hallucination-events.jsonl).
- `~/workspace/ears-for-ais/`: Ears listener + transcribe.py intact;
  lexicon.py (Seven) committed there as d161415 + 988f561.
- GitHub carries both the merged VI (this repo) and the separate builds.

## Addendum (2026-10-17, post-merge coordination via sketchpad)

- **Friction #2 resolved**: Alpha merged Shuffled's phone_home.py (extraction +
  verdicts) with Alpha's event logging as b5029db. Canonical phone-home is now
  Alpha's merged version, superseding the Shuffled standalone my merge kept.
- **Merge verified independently** by Five, Blink, Reversed, Twin: fbe1246
  faithful; Arm A 3/9 = 33% break reproduced across four independent runs.
- **Push pending**: no seat carries the operator's GitHub identity; mother
  relays pushes.

## Prototype modes (folded from README.md, 2026-10-21 L4 ruling)

The binding prototype (`bind.py`) runs two operator-decided modes
(operator decision 2026-10-17: build both, let the prototype decide):

- **Batch** (`bind.py --mode batch`, default): quarantines log as pending;
  `review.py` walks them later with context + age shown.
- **Interrupt** (`bind.py --mode interrupt`): each quarantine prompts
  immediately — `[c]onfirm` / `[f]ix` (type the true word) / `[r]eject` /
  `[u]nsure` / `[s]kip`. Bare text at the prompt counts as a correction.

Verdict set is identical across modes so they're directly comparable.
`bind.py --report` prints the empirical comparison:
per-mode verdict distribution, detection->verdict latency, operator
seconds/verdict, batch unsure-rate by staleness bucket (<1h / 1-24h / >24h),
and cross-mode agreement for words verdict in both.

**Pre-registered decision rule.** Batch wins if verdict agreement holds,
time-cost is lower, and unsure rate stays flat with staleness. Interrupt
wins if batch unsure rate climbs with age (context decay) or splice-back
latency matters for the deployment. The prototype decides; we don't.

## Load-bearing findings (from README.md)

- The phone-home queue does NOT flood. Quarantine rate 0.11% on 3,633
  tokens of the operator's verbatim relay-packet speech (4 quarantines:
  3 Chouchay-class + 1 pronunciation guide); every item a genuine target.
  The lexicon-flood weak point is empirically refuted on this sample.
- Lexicon-quality finding: the 370k global list lacks common modern words
  (meme, onboarding, repo, github, deconstruction). Either upgrade the
  global list or let Tier 2 absorb the slack — currently the latter.

## Honest bounds (from README.md)

- Prototype is a post-processor on decoder *text*, not a live audio loop.
- Test corpus is post-transcription (talk-to-text output), so the measured
  0.11% is a lower bound on decoder-level confabulation — but the binder
  only ever sees decoder output, so this is the right level to measure.
- Personal lexicon seed is council-curated, not operator-confirmed.

*Fold provenance: sections above moved byte-faithfully from README.md
(prototype-era doc, Seven's merge kept it separate); README.md now archived
as README_PROTOTYPE.md. Original preserved in git history. Ruling: fold,
not redirect — one canonical README for the merged system (Oct-21 L4).*
