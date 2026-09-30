"""Grounding check: a quote only counts as evidence if it really appears in a
participant turn. Anything else is dropped, and a dimension left with no
grounded evidence is reported as insufficient_evidence instead of a score.
"""
import re

from .schemas import DimensionSignal, Evidence, RawExtraction, Turn

MIN_EVIDENCE = 1


def _norm_with_map(text: str) -> tuple[str, list[int]]:
    """Lowercase, collapse whitespace and map normalised offsets to original offsets."""
    out, idx_map, prev_space = [], [], False
    for i, ch in enumerate(text):
        if ch.isspace():
            if prev_space or not out:
                continue
            out.append(" ")
            idx_map.append(i)
            prev_space = True
        else:
            out.append(ch.lower())
            idx_map.append(i)
            prev_space = False
    return "".join(out), idx_map


def locate(quote: str, turns: list[Turn]) -> Evidence | None:
    q = re.sub(r"\s+", " ", quote).strip().lower().strip("\"'\u201c\u201d")
    if len(q) < 8:  # too short to be meaningful evidence
        return None
    for t in turns:
        if t.role != "participant":
            continue
        norm, m = _norm_with_map(t.text)
        pos = norm.find(q)
        if pos != -1:
            start = m[pos]
            end = m[pos + len(q) - 1] + 1
            return Evidence(quote=t.text[start:end], turn_index=t.index, start=start, end=end)
    return None


def ground(raw: RawExtraction, turns: list[Turn], dimension_keys: list[str]) -> list[DimensionSignal]:
    by_key = {d.dimension: d for d in raw.dimensions}
    signals: list[DimensionSignal] = []
    for key in dimension_keys:
        d = by_key.get(key)
        if d is None:
            signals.append(DimensionSignal(dimension=key, status="insufficient_evidence",
                                           rationale="Model returned no result for this dimension."))
            continue
        grounded, dropped, seen = [], 0, set()
        for quote in d.quotes:
            ev = locate(quote, turns)
            if ev is None:
                dropped += 1
            elif (ev.turn_index, ev.start) not in seen:
                seen.add((ev.turn_index, ev.start))
                grounded.append(ev)
        if d.score is None or len(grounded) < MIN_EVIDENCE:
            signals.append(DimensionSignal(
                dimension=key, score=None, status="insufficient_evidence",
                rationale=d.rationale or "Not enough grounded evidence to score this dimension.",
                evidence=grounded, dropped_quotes=dropped))
        else:
            signals.append(DimensionSignal(
                dimension=key, score=d.score, status="scored",
                rationale=d.rationale, evidence=grounded, dropped_quotes=dropped))
    return signals
