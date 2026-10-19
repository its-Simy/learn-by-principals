from __future__ import annotations

from core.providers.models.base import (
    ModelProvider,
    ModelRateLimited,
    ModelResult,
    ProviderState,
    TaskPackage,
    UsageHint,
)


class FakeModel(ModelProvider):
    """Answers every task with ``reply`` (or the next item of ``replies``)."""

    def __init__(self, name: str, reply: str = "ok", replies: list[str] | None = None) -> None:
        self.name = name
        self.reply = reply
        self.replies = list(replies or [])
        self.tasks: list[TaskPackage] = []
        self.state = ProviderState.AVAILABLE
        self.limited = False  # the next run hits the usage limit, like the real CLIs

    def run(self, task: TaskPackage) -> ModelResult:
        self.tasks.append(task)
        if self.limited or self.state is ProviderState.RATE_LIMITED:
            self.state = ProviderState.RATE_LIMITED
            raise ModelRateLimited(f"{self.name} usage limit reached")
        text = self.replies.pop(0) if self.replies else self.reply
        return ModelResult(text, self.name, f"{self.name}-model", 5, UsageHint(10, 2))

    def health(self) -> ProviderState:
        return self.state

    def usage_hint(self) -> UsageHint | None:
        return None
