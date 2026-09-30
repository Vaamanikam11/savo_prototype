"""The measurement framework is defined BEFORE the interview starts.

Every score the system produces is relative to these dimensions and anchors,
never to whatever the model happens to find interesting in the conversation.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Dimension:
    key: str
    label: str
    definition: str
    anchors: dict[int, str]  # score -> behavioural anchor


@dataclass(frozen=True)
class Framework:
    id: str
    title: str
    opening_question: str
    follow_ups: list[str]
    dimensions: list[Dimension] = field(default_factory=list)
    max_participant_turns: int = 5


ADAPTABILITY = Framework(
    id="adaptability-v1",
    title="Adaptability in a change-at-work story",
    opening_question=(
        "Tell me about a time at work when the goal, the plan, or the priorities "
        "changed on you partway through. What was happening?"
    ),
    follow_ups=[
        "What did you do first, once you realised things had changed?",
        "Was there anything you had to learn or unlearn to keep going?",
        "Who else was affected, and how did you work with them?",
        "Looking back, what would you do differently?",
    ],
    dimensions=[
        Dimension(
            key="response_to_change",
            label="Response to change",
            definition="How the person reacts in the moment when the situation shifts.",
            anchors={
                0: "Resists or stalls; focuses on what was lost.",
                2: "Accepts the change and adjusts after some delay.",
                4: "Reorients quickly and takes concrete first steps toward the new goal.",
            },
        ),
        Dimension(
            key="learning_agility",
            label="Learning agility",
            definition="Whether the person picked up new skills or dropped old approaches.",
            anchors={
                0: "Sticks to familiar methods regardless of fit.",
                2: "Learns what is required when asked.",
                4: "Seeks out new knowledge and explicitly drops approaches that no longer fit.",
            },
        ),
        Dimension(
            key="collaboration_under_change",
            label="Collaboration under change",
            definition="How the person brings others along while things are shifting.",
            anchors={
                0: "Works alone or blames others.",
                2: "Informs others of what is happening.",
                4: "Actively aligns others, shares context and adjusts plans together.",
            },
        ),
        Dimension(
            key="reflection",
            label="Reflection",
            definition="Whether the person draws lessons from the experience.",
            anchors={
                0: "Explicitly dismisses the experience or declines to draw any lesson.",
                2: "General lesson stated.",
                4: "Specific, actionable lesson tied to what happened.",
            },
        ),
    ],
)

FRAMEWORKS = {ADAPTABILITY.id: ADAPTABILITY}
