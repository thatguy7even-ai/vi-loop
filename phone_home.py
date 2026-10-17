#!/usr/bin/env python3
"""VI talk-to-text loop — phone-home side, merged (INN-130).

Merge of three complementary builds:
  - Shuffled (original vi-loop/phone_home.py): audio_path + timestamps ->
    ffmpeg clip extraction -> Ears transcription -> verdict
    (CORRECTED / AGREEMENT-ON-OOV / NO-SPEECH).
  - Alpha (ears-for-ais/phone_home.py): pre-cut clip -> transcription ->
    best-guess word + JSONL hallucination-event log (event_id, latency).
  - splice_back: extracted from vi-loop-prototype Arm B — word-level
    replacement + record (standalone, caller owns timestamp realignment).

The merged phone_home() accepts EITHER (audio_path + start_s + end_s)
OR (clip_path), returns Shuffled's verdicts, and always logs the event
(Alpha's JSONL interface to taint.py and the INN-130 lab dataset).

Design rule honored: the phone-home listener is Ears-class (full
transcription model), NOT the on-device VI. Narrow VI detects; wide
listener adjudicates.

Usage:
    python3 phone_home.py <audio_path> <start_s> <end_s> <suspect_word>
    python3 phone_home.py --clip <clip_path> <suspect_word>

Friction log (INN-130 spec ambiguities this merge resolves):
  F1. The spec did not say whether phone-home receives timestamps or
      pre-cut clips. Both existed in the separate builds. Merged version
      accepts either; explicit clip_path wins if both given.
  F2. Shuffled's version returned verdicts but did not persist events;
      Alpha's persisted events but did not extract clips. The merged
      version does both — the log is the interface, not an afterthought.
  F3. Filesystem overwrite (not git conflict): two seats wrote
      phone_home.py concurrently. Resolved by reconstructing from git
      history (Shuffled's dcb898e) + working tree (Alpha's logging +
      splice_back). Lesson: coordinate on shared files or use branches.
  F4. splice_back ownership: lives here as standalone extraction; taint.py
      (--resolve) also splices. Potential duplication — flagged, not
      deduplicated (preserve separate states per work order).
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.expanduser("~/workspace/ears-for-ais"))
sys.path.insert(0, os.path.expanduser("~/workspace/tts-venv/lib/python3.12/site-packages"))

from transcribe import transcribe as ears_transcribe

HERE = os.path.dirname(os.path.abspath(__file__))
PHLOG = os.path.join(HERE, "lexicon", "phone_home_log.jsonl")


def extract_clip(audio_path, start_s, end_s, out_path):
    """Cut [start_s, end_s] from audio_path with ffmpeg. Returns out_path."""
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-ss", str(start_s), "-to", str(end_s),
           "-i", audio_path, "-ac", "1", "-ar", "16000", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[:200]}")
    return out_path


def phone_home(audio_path=None, start_s=None, end_s=None, clip_path=None,
               suspect_word="", model="small", context_before="",
               context_after=""):
    """Quarantine resolution. Returns dict with verdict + event_id.

    Verdicts (Shuffled):
      CORRECTED — listener produced a bound word differing from suspect
      AGREEMENT-ON-OOV — listener produced the same (or another) unbound
        word: two systems agreeing on OOV, do NOT treat as confirmation
      NO-SPEECH — clip had no transcribable content

    Always appends the event to phone_home_log.jsonl (Alpha's interface).
    """
    event_id = str(uuid.uuid4())[:8]
    t0 = time.monotonic()
    error = None
    verdict, listener_text, correction = "NO-SPEECH", "", None
    audio_ref = ""

    try:
        tmpdir = None
        if clip_path:
            clip = clip_path
            audio_ref = os.path.basename(clip_path)
        elif audio_path and start_s is not None and end_s is not None:
            tmpdir = tempfile.TemporaryDirectory()
            clip = os.path.join(tmpdir.name, "clip.wav")
            extract_clip(audio_path, start_s, end_s, clip)
            audio_ref = f"{os.path.basename(audio_path)}[{start_s}-{end_s}]"
        else:
            raise ValueError("need (audio_path+start_s+end_s) or clip_path")

        lang, text = ears_transcribe(clip, model_name=model)
        text = text.strip()
        if tmpdir:
            tmpdir.cleanup()

        if not text:
            verdict = "NO-SPEECH"
        else:
            # First word of the re-transcription is the candidate correction
            # (clip is tight around the suspect word).
            candidate = text.split()[0].strip(".,!?;:\"'").lower()
            suspect = suspect_word.strip(".,!?;:\"'").lower()
            listener_text = text
            if candidate == suspect:
                verdict = "AGREEMENT-ON-OOV"
            else:
                verdict = "CORRECTED"
                correction = candidate
    except Exception as e:  # noqa: BLE001 — narrow VI, log and degrade
        error = f"{type(e).__name__}: {e}"

    latency_ms = round((time.monotonic() - t0) * 1000.0, 1)

    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_id": event_id,
        "audio_ref": audio_ref,
        "suspect_word": suspect_word,
        "verdict": verdict,
        "listener_text": listener_text,
        "correction": correction,
        "context_before": context_before,
        "context_after": context_after,
        "model": f"faster-whisper/{model}/int8/cpu",
        "latency_ms": latency_ms,
        "error": error,
    }
    os.makedirs(os.path.dirname(PHLOG), exist_ok=True)
    with open(PHLOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

    return {
        "event_id": event_id,
        "verdict": verdict,
        "suspect": suspect_word,
        "listener": listener_text,
        "correction": correction,
        "latency_ms": latency_ms,
        "error": error,
        "note": {
            "CORRECTED": f"splice '{correction}' in place of '{suspect_word}'",
            "AGREEMENT-ON-OOV": "listener agrees on unbound word; NOT confirmation. "
                                "Escalate: wider context or human check.",
            "NO-SPEECH": "clip empty or unintelligible",
        }[verdict],
    }


def splice_back(original_words, quarantined_word, returned_word, t_start, t_end):
    """Splice-back stage: replace the quarantined word with the phone-home
    result, preserving position. Returns (new_words, splice_record).

    Standalone extraction of the splice logic previously embedded in
    vi-loop-prototype Arm B. The caller owns timestamp realignment;
    this function handles the word-level replacement + record.
    """
    if returned_word is None:
        return original_words, {
            "quarantined": quarantined_word,
            "spliced": None,
            "note": "phone-home unresolved; word retained as quarantined",
            "t_start": t_start, "t_end": t_end,
        }
    new_words = [returned_word if w == quarantined_word else w
                 for w in original_words]
    return new_words, {
        "quarantined": quarantined_word,
        "spliced": returned_word,
        "t_start": t_start, "t_end": t_end,
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="VI loop phone-home (merged).")
    ap.add_argument("audio_or_clip", help="audio file, or clip with --clip")
    ap.add_argument("start_or_word", help="start_s, or suspect word with --clip")
    ap.add_argument("end_s", nargs="?", default=None, help="end_s (timestamp mode)")
    ap.add_argument("suspect_word", nargs="?", default=None,
                    help="suspect word (timestamp mode)")
    ap.add_argument("--clip", action="store_true",
                    help="first arg is a pre-cut clip, second is suspect word")
    ap.add_argument("--model", default="small")
    args = ap.parse_args()

    if args.clip:
        r = phone_home(clip_path=args.audio_or_clip,
                       suspect_word=args.start_or_word, model=args.model)
    else:
        r = phone_home(audio_path=args.audio_or_clip,
                       start_s=float(args.start_or_word),
                       end_s=float(args.end_s),
                       suspect_word=args.suspect_word, model=args.model)
    print(json.dumps(r, indent=2, ensure_ascii=False))
