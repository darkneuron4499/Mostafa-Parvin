"""Persistence layer (swap the backend without touching business logic)."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

from .models import Task


class Storage(ABC):
    """Abstract storage interface."""

    @abstractmethod
    def load(self) -> list[Task]: ...

    @abstractmethod
    def save(self, tasks: list[Task]) -> None: ...


class JsonStorage(Storage):
    """Stores tasks in a JSON file."""

    def __init__(self, path: str | Path = "tasks.json") -> None:
        self.path = Path(path)

    def load(self) -> list[Task]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            return [Task.from_dict(item) for item in json.load(f)]

    def save(self, tasks: list[Task]) -> None:
        with self.path.open("w", encoding="utf-8") as f:
            json.dump([t.to_dict() for t in tasks], f, indent=2, ensure_ascii=False)
