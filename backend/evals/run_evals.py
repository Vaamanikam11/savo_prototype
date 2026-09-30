"""Eval harness for the scoring pipeline.

Metrics
  groundedness   share of model-proposed quotes that really appear in a participant turn
  abstention     dimensions that must abstain actually abstain
  coverage       dimensions that must be scored actually get a score
  consistency    share of dimensions that get the same score across repeated runs

Usage
  python -m evals.run_evals                      # deterministic mock
  LLM_PROVIDER=anthropic python -m evals.run_evals --runs 3
"""
import argparse
import json
import pathlib
import sys
from collections import defaultdict

from app.framework import ADAPTABILITY
from app.grounding import ground
from app.llm import get_llm
from app.schemas import Turn

CASES = pathlib.Path(__file__).with_name("cases.json")


def build_turns(participant_turns: list[str]) -> list[Turn]:
    turns, idx = [Turn(index=0, role="interviewer", text=ADAPTABILITY.opening_question)], 1
    for text in participant_turns:
        turns.append(Turn(index=idx, role="participant", text=text))
        idx += 1
    return turns


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()
    llm = get_llm()
    keys = [d.key for d in ADAPTABILITY.dimensions]

    proposed = kept = 0
    abstain_ok = abstain_total = cover_ok = cover_total = 0
    stable = stable_total = 0
    rows = []

    for case in json.loads(CASES.read_text()):
        turns = build_turns(case["participant_turns"])
        scores_by_dim = defaultdict(list)
        last = None
        for _ in range(args.runs):
            raw = llm.extract(ADAPTABILITY, turns)
            sigs = ground(raw, turns, keys)
            for d in raw.dimensions:
                proposed += len(d.quotes)
            kept += sum(len(s.evidence) for s in sigs)
            for s in sigs:
                scores_by_dim[s.dimension].append(s.score)
            last = sigs
        by_key = {s.dimension: s for s in last}
        for k in case["must_abstain"]:
            abstain_total += 1
            abstain_ok += by_key[k].status == "insufficient_evidence"
        for k in case["must_score"]:
            cover_total += 1
            cover_ok += by_key[k].status == "scored"
        for k in keys:
            stable_total += 1
            stable += len(set(scores_by_dim[k])) == 1
        rows.append((case["id"], {k: by_key[k].score for k in keys}))

    def pct(a, b):
        return "n/a" if b == 0 else f"{100 * a / b:.0f}% ({a}/{b})"

    print(f"provider: {type(llm).__name__}   runs/case: {args.runs}\n")
    print(f"groundedness : {pct(kept, proposed)}  (quotes kept / quotes proposed)")
    print(f"abstention   : {pct(abstain_ok, abstain_total)}")
    print(f"coverage     : {pct(cover_ok, cover_total)}")
    print(f"consistency  : {pct(stable, stable_total)}\n")
    for cid, scores in rows:
        cells = "  ".join(f"{k.split('_')[0]}={'-' if v is None else v}" for k, v in scores.items())
        print(f"  {cid:<36} {cells}")
    ok = abstain_ok == abstain_total and cover_ok == cover_total
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
