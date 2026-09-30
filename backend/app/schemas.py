from pydantic import BaseModel, Field


class Evidence(BaseModel):
    quote: str = Field(description="Verbatim text copied from a PARTICIPANT turn.")
    turn_index: int | None = None
    start: int | None = None
    end: int | None = None


class DimensionSignal(BaseModel):
    dimension: str
    score: int | None = Field(default=None, ge=0, le=4)
    status: str = Field(description="scored | insufficient_evidence")
    rationale: str = ""
    evidence: list[Evidence] = []
    dropped_quotes: int = 0


class RawDimension(BaseModel):
    """What the model is asked to return, before grounding checks."""
    dimension: str
    score: int | None = Field(default=None, ge=0, le=4)
    rationale: str = ""
    quotes: list[str] = []


class RawExtraction(BaseModel):
    dimensions: list[RawDimension]


class Turn(BaseModel):
    index: int
    role: str
    text: str


class TurnIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class SessionOut(BaseModel):
    id: str
    status: str
    framework_id: str
    turns: list[Turn]
    signals: list[DimensionSignal] = []
    next_question: str | None = None
    done: bool = False
