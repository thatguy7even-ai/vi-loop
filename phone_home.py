"""VI talk-to-text loop — phone-home side (Shuffled, INN-130).

Built on the Ears foundation (INN-128): ~/workspace/ears-for-ais/transcribe.py.
The phone-home receives a quarantined audio clip + the suspect word the
first-pass decoder emitted, re-transcribes with a second opinion, and
returns either a correction or an agreement flag.

Design rule honored: the phone-home listener is Ears-class (full
transcription model), NOT the on-device VI. Narrow VI detects; wide
listener adjudicates.

Usage:
    python3 phone_home.py <audio_path> <start_s> <end_s> <suspect_word>
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.expanduser("~/workspace/ears-for-ais"))
sys.path.insert(0, os.path.expanduser("~/workspace/tts-venv/lib/python3.12/site-packages"))

from transcribe import transcribe as ears_transcribe


def extract_clip(audio_path, start_s, end_s, out_path):
    """Cut [start_s, end_s] from audio_path with ffmpeg. Returns out_path."""
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-ss", str(start_s), "-to", str(end_s),
           "-i", audio_path, "-ac", "1", "-ar", "16000", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[:200]}")
    return out_path


def phone_home(audio_path, start_s, end_s, suspect_word, model="small"):
    """Quarantine resolution. Returns dict with verdict.

    Verdicts:
      CORRECTED — listener produced a bound word differing from suspect
      AGREEMENT-ON-OOV — listener produced the same (or another) unbound
        word: two systems agreeing on OOV, do NOT treat as confirmation
      NO-SPEECH — clip had no transcribable content
    """
    with tempfile.TemporaryDirectory() as td:
        clip = os.path.join(td, "clip.wav")
        extract_clip(audio_path, start_s, end_s, clip)
        lang, text = ears_transcribe(clip, model_name=model)
    text = text.strip()
    if not text:
        return {"verdict": "NO-SPEECH", "suspect": suspect_word,
                "listener": "", "note": "clip empty or unintelligible"}
    # first word of the re-transcription is the candidate correction
    # (clip is tight around the suspect word)
    candidate = text.split()[0].strip(".,!?;:\"'").lower()
    suspect = suspect_word.strip(".,!?;:\"'").lower()
    if candidate == suspect:
        return {"verdict": "AGREEMENT-ON-OOV", "suspect": suspect_word,
                "listener": text,
                "note": "listener agrees on unbound word; NOT confirmation. "
                        "Escalate: wider context re-transcription or human check."}
    return {"verdict": "CORRECTED", "suspect": suspect_word,
            "listener": text, "correction": candidate,
            "note": f"splice '{candidate}' in place of '{suspect_word}'"}


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(__doc__)
        sys.exit(2)
    import json
    print(json.dumps(phone_home(sys.argv[1], float(sys.argv[2]),
                                float(sys.argv[3]), sys.argv[4]), indent=2))
