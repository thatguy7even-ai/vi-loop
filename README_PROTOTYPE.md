# VI talk-to-text loop — binding-rule prototype (INN-130)

The binding rule: every emitted word must be bound to a lexical entry.
Bound → passes. Unbound → quarantine + phone home.

## Tiers

- **Tier 1 — global lexicon** (`lexicon/words_alpha.txt`, 370k words): standard vocabulary.
- **Tier 2 — personal lexicon** (`lexicon/personal_lexicon.txt`): the operator's
  vocabulary. Seeded from council record; grows by confirmation
  (`bind.py --promote WORD`). Multi-word entries ("pixel capsule",
  "shunt firewall") match longest-first.
- **Tier 3 — quarantine**: neither tier binds → logged to
  `lexicon/quarantine_log.jsonl` with context, source, timestamp, status
  (pending/confirmed/rejected). This log IS the phone-home dispatch queue
  and, once resolved, the hallucination-event dataset.

## Pattern rules (not wordlists)

- `inn-\d+` → issue references bind (Tier 1, pattern-labeled)
- `\d+(st|nd|rd|th)` → ordinals bind
- camelCase splits only AFTER whole-token lookup fails
  (createdAt → created+at; TikTok stays whole)
- `message_break`-class markup → dropped silently (not words, not quarantined)

## Measured (2026-10-17)

On 3,633 tokens of the operator's verbatim relay-packet speech:

| tier | tokens | pct |
|---|---|---|
| Tier 1 (global) | 3,607 | 99.28% |
| Tier 2 (personal) | 22 | 0.61% |
| **Quarantine** | **4** | **0.11%** |

The 4 quarantines: `interreplanability`, `interplatability`,
`interpliability` — his three failed reaches for "interpretability"
(Chouchay-class: fluent, confident, no lexical entry) — plus mother's
pronunciation guide `in-ter-pret-uh-bil-ih-tee` (correctly quarantined:
not a word).

**Load-bearing finding:** the phone-home queue does NOT flood. Quarantine
rate 0.11%, every item a genuine target. The lexicon-flood weak point is
empirically refuted on this sample.

**Lexicon-quality finding:** the 370k global list lacks common modern words
(meme, onboarding, repo, github, deconstruction). Either upgrade the global
list or let Tier 2 absorb the slack — currently the latter.

## Modes (operator decision 2026-10-17: build both, let the prototype decide)

- **Batch** (`bind.py --mode batch`, default): quarantines log as pending;
  `review.py` walks them later with context + age shown.
- **Interrupt** (`bind.py --mode interrupt`): each quarantine prompts
  immediately — `[c]onfirm` / `[f]ix` (type the true word) / `[r]eject` /
  `[u]nsure` / `[s]kip`. Bare text at the prompt counts as a correction.

Verdict set is identical across modes so they're directly comparable.
`bind.py --report` prints the empirical comparison:
per-mode verdict distribution, detection→verdict latency, operator
seconds/verdict, batch unsure-rate by staleness bucket (<1h / 1–24h / >24h),
and cross-mode agreement for words verdict in both.

**Pre-registered decision rule.** Batch wins if verdict agreement holds,
time-cost is lower, and unsure rate stays flat with staleness. Interrupt
wins if batch unsure rate climbs with age (context decay) or splice-back
latency matters for the deployment. The prototype decides; we don't.

## Next steps (not yet built)

1. Wire quarantine dispatch to the Ears listener (`~/workspace/ears-for-ais`):
   send the audio clip + quarantined word, splice the true word back in.
   Interrupt mode's splice-back path is where the ~1s budget gets tested.
2. `--json` output is ready for the dispatch wire format.
3. Run both modes on real transcripts; read `bind.py --report`.

## Honest bounds

- Prototype is a post-processor on decoder *text*, not a live audio loop.
- Test corpus is post-transcription (talk-to-text output), so the measured
  0.11% is a lower bound on decoder-level confabulation — but the binder
  only ever sees decoder output, so this is the right level to measure.
- Personal lexicon seed is council-curated, not operator-confirmed.
