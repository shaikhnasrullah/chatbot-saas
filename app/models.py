from dataclasses import dataclass, field


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list = field(default_factory=list)


@dataclass
class Phrase:
    text: str
    start: float
    end: float


@dataclass
class ClipPlan:
    start: float
    end: float
    title: str = ""
    reason: str = ""
    score: float = 0.0
    target: int = 60  # the length bucket (seconds) this clip belongs to
