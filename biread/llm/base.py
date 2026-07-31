from abc import ABC, abstractmethod
from dataclasses import dataclass

#: How long one call may wait on a silent socket.
#:
#: Both cloud SDKs already default to a 600-second read timeout, and it is not
#: enough: the timeout is per *read operation*, so a connection that dribbles a
#: byte now and then resets it forever. A gloss run stopped like that after 52
#: of 469 paragraphs and sat for three hours — no error, no retry, no progress,
#: and from the outside indistinguishable from a long run still working.
#:
#: Two minutes is well past any real completion and short enough that the SDK's
#: own retries get their turn. It narrows the window rather than closing it:
#: a server that keeps trickling bytes can still hold a call open, and only a
#: whole-call deadline would stop that.
REQUEST_TIMEOUT_SECONDS = 120


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
