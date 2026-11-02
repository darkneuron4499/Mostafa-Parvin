"""Business logic."""

from __future__ import annotations

from .models import Priority, Task
from .storage import Storage


class TaskNotFoundError(KeyError):
    """Raised when a task id does not exist."""


class TaskManager:
    """Create, list, complete and remove tasks."""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage
        self._tasks: list[Task] = storage.load()

    def add(self, title: str, priority: Priority = Priority.MEDIUM) -> Task:
        if not title.strip():
            raise ValueError("Title must not be empty.")
        next_id = max((t.id for t in self._tasks), default=0) + 1
        task = Task(id=next_id, title=title.strip(), priority=priority)
        self._tasks.append(task)
        self._storage.save(self._tasks)
        return task

    def get(self, task_id: int) -> Task:
        for task in self._tasks:
            if task.id == task_id:
                return task
        raise TaskNotFoundError(f"Task #{task_id} not found.")

    def complete(self, task_id: int) -> Task:
        task = self.get(task_id)
        task.mark_done()
        self._storage.save(self._tasks)
        return task

    def remove(self, task_id: int) -> None:
        self._tasks.remove(self.get(task_id))
        self._storage.save(self._tasks)

    def list(self, *, only_pending: bool = False) -> list[Task]:
        tasks = [t for t in self._tasks if not (only_pending and t.done)]
        return sorted(tasks, key=lambda t: (t.done, list(Priority).index(t.priority) * -1, t.id))

    def stats(self) -> dict[str, int]:
        done = sum(t.done for t in self._tasks)
        return {"total": len(self._tasks), "done": done, "pending": len(self._tasks) - done}
