from app.grounding import ground, locate
from app.schemas import RawDimension, RawExtraction, Turn

TURNS = [
    Turn(index=0, role="interviewer", text="Tell me about a change."),
    Turn(index=1, role="participant",
         text="Our launch date moved up by a month.  I immediately re-planned the sprint. Then I told the team."),
]


def test_quote_found_despite_whitespace_and_case():
    ev = locate("i immediately RE-PLANNED the sprint", TURNS)
    assert ev is not None
    assert ev.turn_index == 1
    assert TURNS[1].text[ev.start:ev.end] == ev.quote


def test_interviewer_text_is_never_evidence():
    assert locate("Tell me about a change.", TURNS) is None


def test_fabricated_quote_is_dropped_and_dimension_abstains():
    raw = RawExtraction(dimensions=[RawDimension(dimension="reflection", score=3, quotes=["I learned a huge lesson"])])
    [sig] = ground(raw, TURNS, ["reflection"])
    assert sig.status == "insufficient_evidence"
    assert sig.score is None
    assert sig.dropped_quotes == 1


def test_grounded_quote_keeps_score():
    raw = RawExtraction(dimensions=[RawDimension(dimension="response_to_change", score=4,
                                                 quotes=["I immediately re-planned the sprint."])])
    [sig] = ground(raw, TURNS, ["response_to_change"])
    assert sig.status == "scored" and sig.score == 4
    assert len(sig.evidence) == 1


def test_missing_dimension_abstains():
    [sig] = ground(RawExtraction(dimensions=[]), TURNS, ["learning_agility"])
    assert sig.status == "insufficient_evidence"


def test_very_short_quote_is_rejected():
    assert locate("the", TURNS) is None
