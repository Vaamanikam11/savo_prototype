"""LLM access behind a small interface so the app, tests and evals can run
with a deterministic mock (no API key) or with Claude."""
import os
import re
from typing import Protocol

from .framework import Framework
from .schemas import RawDimension, RawExtraction, Turn


class LLM(Protocol):
    def next_question(self, fw: Framework, turns: list[Turn]) -> str: ...
    def extract(self, fw: Framework, turns: list[Turn]) -> RawExtraction: ...


def _participant_count(turns: list[Turn]) -> int:
    return sum(1 for t in turns if t.role == "participant")


def _framework_brief(fw: Framework) -> str:
    lines = []
    for d in fw.dimensions:
        anchors = "; ".join(f"{k}={v}" for k, v in sorted(d.anchors.items()))
        lines.append(f"- {d.key}: {d.definition} Anchors: {anchors}")
    return "\n".join(lines)


SCORING_RULES = (
    "You score an interview transcript against a FIXED framework. Rules:\n"
    "1. Score each dimension 0-4 using the anchors, or return score=null.\n"
    "2. score=null is REQUIRED when the participant did not describe anything relevant to that "
    "dimension. Silence, vague replies ('it was fine') and off-topic content are NOT evidence.\n"
    "3. A score of 0 is only for when the participant DESCRIBED behaviour matching the 0 anchor "
    "(for example, explicitly resisting or blaming others). A score of 0 never means 'nothing was said'.\n"
    "4. Only described actions, decisions and reflections count. Statements about oneself "
    "('I am adaptable', 'people say I am flexible', 'I just roll with it') are claims, not behaviour: "
    "do not score on them.\n"
    "5. Every score must be supported by quotes copied VERBATIM from PARTICIPANT turns, and each quote "
    "must itself show the behaviour for THAT dimension. Never paraphrase inside a quote. "
    "Never quote the interviewer.\n"
    "6. When in doubt, return null. Prefer abstaining to guessing."
)


class AnthropicLLM:
    """Claude via tool use, so extraction always comes back as schema-shaped JSON."""

    def __init__(self, model: str | None = None):
        import anthropic

        self.client = anthropic.Anthropic()
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")

    def next_question(self, fw: Framework, turns: list[Turn]) -> str:
        transcript = "\n".join(f"{t.role.upper()}: {t.text}" for t in turns)
        system = (
            "You are a structured narrative interviewer. Ask exactly ONE short, open, "
            "neutral follow-up question. Probe for concrete behaviour (what they did, said, "
            "learned) and never suggest an answer or judge. Cover, over the interview: "
            + "; ".join(fw.follow_ups)
        )
        msg = self.client.messages.create(
            model=self.model, max_tokens=150, system=system,
            messages=[{"role": "user", "content": f"Transcript so far:\n{transcript}\n\nNext question:"}],
        )
        return msg.content[0].text.strip()

    def extract(self, fw: Framework, turns: list[Turn]) -> RawExtraction:
        transcript = "\n".join(f"[{t.index}] {t.role.upper()}: {t.text}" for t in turns)
        system = (
            "You score an interview transcript against a FIXED framework. Rules:\n"
            f"{SCORING_RULES}\n\nFramework:\n{_framework_brief(fw)}"
        )
        tool = {
            "name": "record_signals",
            "description": "Record one result per framework dimension.",
            "input_schema": RawExtraction.model_json_schema(),
        }
        msg = self.client.messages.create(
            model=self.model, max_tokens=1500, temperature=0, system=system,
            tools=[tool], tool_choice={"type": "tool", "name": "record_signals"},
            messages=[{"role": "user", "content": transcript}],
        )
        block = next(b for b in msg.content if b.type == "tool_use")
        return RawExtraction.model_validate(block.input)


# --- deterministic mock ------------------------------------------------------

_KEYWORDS = {
    "response_to_change": r"\b(immediately|right away|first thing|reprioriti[sz]ed|pivot|switched|started by|re-?planned)\b",
    "learning_agility": r"\b(learn(ed|t|ing)?|picked up|studied|new tool|unlearn|dropped|stopped using)\b",
    "collaboration_under_change": r"\b(team|stakeholders?|we (agreed|met|aligned)|told|synced|walked .* through|shared)\b",
    "reflection": r"\b(next time|in hindsight|looking back|i would|lesson|differently)\b",
}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


class MockLLM:
    """Keyword heuristic. Not smart, but deterministic and offline: good for tests,
    CI and for demoing the flow without an API key."""

    def next_question(self, fw: Framework, turns: list[Turn]) -> str:
        n = _participant_count(turns)
        return fw.follow_ups[min(n - 1, len(fw.follow_ups) - 1)]

    def extract(self, fw: Framework, turns: list[Turn]) -> RawExtraction:
        out = []
        for d in fw.dimensions:
            pat = re.compile(_KEYWORDS[d.key], re.I)
            hits = [s for t in turns if t.role == "participant" for s in _sentences(t.text) if pat.search(s)]
            if not hits:
                out.append(RawDimension(dimension=d.key, score=None,
                                        rationale="No matching evidence found."))
                continue
            score = min(4, 1 + len(hits))
            out.append(RawDimension(dimension=d.key, score=score,
                                    rationale=f"{len(hits)} supporting statement(s) found.",
                                    quotes=hits[:3]))
        return RawExtraction(dimensions=out)


class OpenAILLM:
    """OpenAI chat completions with forced function calling for schema-shaped scoring."""

    def __init__(self, model: str | None = None, client=None):
        if client is None:
            from openai import OpenAI

            client = OpenAI()
        self.client = client
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def next_question(self, fw: Framework, turns: list[Turn]) -> str:
        transcript = "\n".join(f"{t.role.upper()}: {t.text}" for t in turns)
        system = (
            "You are a structured narrative interviewer. Ask exactly ONE short, open, "
            "neutral follow-up question. Probe for concrete behaviour (what they did, said, "
            "learned) and never suggest an answer or judge. Cover, over the interview: "
            + "; ".join(fw.follow_ups)
        )
        r = self.client.chat.completions.create(
            model=self.model, max_completion_tokens=150,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": f"Transcript so far:\n{transcript}\n\nNext question:"}],
        )
        return r.choices[0].message.content.strip()

    def extract(self, fw: Framework, turns: list[Turn]) -> RawExtraction:
        transcript = "\n".join(f"[{t.index}] {t.role.upper()}: {t.text}" for t in turns)
        system = (
            "You score an interview transcript against a FIXED framework. Rules:\n"
            f"{SCORING_RULES}\n\nFramework:\n{_framework_brief(fw)}"
        )
        tool = {"type": "function", "function": {
            "name": "record_signals",
            "description": "Record one result per framework dimension.",
            "parameters": RawExtraction.model_json_schema()}}
        r = self.client.chat.completions.create(
            model=self.model, max_completion_tokens=1500, temperature=0,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": transcript}],
            tools=[tool], tool_choice={"type": "function", "function": {"name": "record_signals"}},
        )
        call = r.choices[0].message.tool_calls[0]
        return RawExtraction.model_validate_json(call.function.arguments)


def provider_name() -> str:
    return os.getenv("LLM_PROVIDER", "mock").lower()


def describe_provider() -> str:
    p = provider_name()
    if p == "openai":
        return f"OpenAI {os.getenv('OPENAI_MODEL', 'gpt-4o-mini')}"
    if p == "anthropic":
        return f"Anthropic {os.getenv('ANTHROPIC_MODEL', 'claude-sonnet-5-5')}"
    return "Demo mode: keyword heuristic, not an AI model"


def get_llm() -> LLM:
    p = provider_name()
    if p == "mock":
        return MockLLM()
    needs = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
    if p not in needs:
        raise RuntimeError(f"Unknown LLM_PROVIDER '{p}'. Use mock, openai or anthropic.")
    if not os.getenv(needs[p]):
        # Fail loudly: silently falling back to the mock would be misleading.
        raise RuntimeError(f"LLM_PROVIDER={p} but {needs[p]} is not set.")
    return OpenAILLM() if p == "openai" else AnthropicLLM()
