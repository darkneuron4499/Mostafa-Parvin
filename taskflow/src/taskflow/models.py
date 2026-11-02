"""Domain models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Priority(str, Enum):
    """Importance level of a task."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class Task:
    """A single to-do item."""

    id: int
    title: str
    priority: Priority = Priority.MEDIUM
    done: bool = False
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def mark_done(self) -> None:
        self.done = True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["priority"] = self.priority.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        return cls(**{**data, "priority": Priority(data["priority"])})

    def __str__(self) -> str:
        mark = "✔" if self.done else "○"
        return f"[{mark}] #{self.id:<3} {self.title}  ({self.priority.value})"
