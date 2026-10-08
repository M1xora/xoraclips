"""
Issue #99 stage 3: does quote anchoring hold up on real answers?

Not a test — a measuring script, run by hand:

    venv\\Scripts\\python backend\\tests\\gate_quote_anchor.py

It scores every quote Gemini wrote against the transcript it was taken from
and prints the table the issue's gate is decided on. The thresholds were set
before any data was seen, so the numbers decide rather than the reading of
them:

    opening_line matched inside the window   >= 70%   -> stage 4 goes ahead
    ending_line matched                      >= 50%
    quotes found nowhere in the transcript   <  15%

Three outcomes are counted separately, because two of them are not failures
of the same kind:

    in window   the quote sits where Gemini said -> anchoring works
    elsewhere   the quote is real but Gemini's timestamp drifted -> the
                window is too narrow, which is an argument for widening it,
                not for dropping the quotes
    missing     the quote is nowhere in the transcript -> Gemini invented it,
                and anchoring cannot help

By default it reads the recorded answers in fixtures/gemini_answers. Those
were recorded before the quote fields existed, so it falls back to scoring
`key_quotes` and simulated openings, which bounds what the real fields can do
but does not replace them. Pass --answers DIR to score fresh answers that do
carry opening_line / payoff_line / ending_line.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.quote_anchor import (  # noqa: E402
    MIN_SCORE, WINDOW_SECONDS, WordIndex, find_quote, find_quote_anywhere,
)

FIXTURES = Path(__file__).parent / "fixtures"
TRANSCRIPTS = FIXTURES / "transcripts"
ANSWERS = FIXTURES / "gemini_answers"

# The gate, fixed before the data was looked at (issue #99).
GATE_OPENING = 0.70
GATE_ENDING = 0.50
GATE_INVENTED = 0.15

VIDEOS = [
    ("kesehatan_YGjXfLsuG8k", "60s"),
    ("komedi_qedBB492cQY", "30s"),
    ("debat_Mwmex7kDaaE", "180s"),
]


def load_lines(name: str):
    data = json.loads((TRANSCRIPTS / f"{name}.json").read_text(encoding="utf-8"))
    raw = data.get("transcript") or data.get("lines") or data
    return [{"start": l["start"], "end": l["start"] + l.get("duration", 0.0), "text": l["text"]}
            for l in raw]


def load_clips(answers: Path, name: str, duration: str):
    path = answers / f"{name}_{duration}.json"
    if not path.exists():
        return []
    recorded = json.loads(path.read_text(encoding="utf-8"))
    text = recorded["text"] if isinstance(recorded, dict) and "text" in recorded else recorded
    answer = json.loads(text) if isinstance(text, str) else text
    return answer.get("clips", [])


def score(quote, index, near, *, tail=False):
    """'window', 'elsewhere' or 'missing'."""
    if not quote or len(str(quote).split()) < 3:
        return None
    if find_quote(quote, index, near=near, tail=tail):
        return "window"
    return "elsewhere" if find_quote_anywhere(quote, index, tail=tail) else "missing"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--answers", type=Path, default=ANSWERS,
                    help="directory of recorded Gemini answers")
    args = ap.parse_args()

    print(f"Quote anchoring gate — threshold {MIN_SCORE}, window ±{WINDOW_SECONDS:.0f}s")
    print(f"Answers: {args.answers}\n")

    totals = {"opening": {}, "ending": {}, "payoff": {}, "key_quotes": {}, "simulated": {}}
    have_real_fields = False

    for name, duration in VIDEOS:
        lines = load_lines(name)
        index = WordIndex(lines)
        clips = load_clips(args.answers, name, duration)
        if not clips:
            print(f"{name:28} (no recorded answer)")
            continue

        counts = {k: {} for k in totals}
        for clip in clips:
            start, end = clip.get("start_time", 0.0), clip.get("end_time", 0.0)
            for field, near, tail in (("opening", start, False),
                                      ("payoff", (start + end) / 2, False),
                                      ("ending", end, True)):
                verdict = score(clip.get(f"{field}_line"), index, near, tail=tail)
                if verdict:
                    have_real_fields = True
                    counts[field][verdict] = counts[field].get(verdict, 0) + 1
            for quote in clip.get("key_quotes") or []:
                verdict = score(quote, index, start)
                if verdict:
                    counts["key_quotes"][verdict] = counts["key_quotes"].get(verdict, 0) + 1
            # What a quote copied from the clip's own opening would score: the
            # ceiling for opening_line, since it is the transcript's own words.
            opening = [l["text"] for l in lines if start - 0.5 <= l["start"] <= start + 6]
            if len(opening) >= 2:
                verdict = score(" ".join(opening[:3]), index, start)
                if verdict:
                    counts["simulated"][verdict] = counts["simulated"].get(verdict, 0) + 1

        print(f"{name} ({duration}, {len(clips)} clips)")
        for field, c in counts.items():
            n = sum(c.values())
            if not n:
                continue
            print(f"   {field:12} n={n:3}  in window {c.get('window', 0):3}"
                  f"  elsewhere {c.get('elsewhere', 0):3}  missing {c.get('missing', 0):3}"
                  f"   ({c.get('window', 0) / n * 100:5.1f}% in window)")
            for k, v in c.items():
                totals[field][k] = totals[field].get(k, 0) + v
        print()

    print("TOTAL")
    share = {}
    for field, c in totals.items():
        n = sum(c.values())
        if not n:
            continue
        share[field] = (c.get("window", 0) / n, c.get("missing", 0) / n)
        print(f"   {field:12} n={n:3}  in window {c.get('window', 0):3}"
              f"  elsewhere {c.get('elsewhere', 0):3}  missing {c.get('missing', 0):3}"
              f"   ({share[field][0] * 100:5.1f}% in window)")

    print("\nGATE")
    if not have_real_fields:
        print("   INCONCLUSIVE — these answers carry no opening_line/ending_line.")
        print("   key_quotes and the simulated openings above bound what the matcher")
        print("   can do, but only a fresh answer decides whether Gemini copies exactly.")
        return 2

    opening_ok = share.get("opening", (0, 1))[0] >= GATE_OPENING
    ending_ok = share.get("ending", (0, 1))[0] >= GATE_ENDING
    invented_ok = max(s[1] for s in share.values()) < GATE_INVENTED
    for label, ok, got, want in (
        ("opening_line in window", opening_ok, share.get("opening", (0,))[0], GATE_OPENING),
        ("ending_line in window", ending_ok, share.get("ending", (0,))[0], GATE_ENDING),
    ):
        print(f"   {'PASS' if ok else 'FAIL'}  {label:24} {got * 100:5.1f}%  (need {want * 100:.0f}%)")
    worst = max(s[1] for s in share.values())
    print(f"   {'PASS' if invented_ok else 'FAIL'}  {'invented quotes':24} {worst * 100:5.1f}%"
          f"  (need <{GATE_INVENTED * 100:.0f}%)")

    passed = opening_ok and ending_ok and invented_ok
    print(f"\n   -> stage 4 {'GOES AHEAD' if passed else 'IS DROPPED'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
