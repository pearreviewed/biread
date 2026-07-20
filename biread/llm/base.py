from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Completion:
    text: str
    #: The model hit the output ceiling — `text` is cut off mid-thought.
    truncated: bool


class LLMClient(ABC):
    """One system+user turn at a time, against a single model.

    Implementations accumulate token usage so callers can price a run without
    threading usage through every return value.
    """

    def __init__(self, model: str) -> None:
        self.model = model
        self.input_tokens = 0
        self.output_tokens = 0

    @abstractmethod
    def complete(self, system: str, user: str, max_tokens: int) -> Completion:
        """Send one turn and return the model's raw text response."""
