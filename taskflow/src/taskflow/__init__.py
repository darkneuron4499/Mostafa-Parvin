"""TaskFlow - a tiny, clean task manager built with OOP principles."""

from .manager import TaskManager, TaskNotFoundError
from .models import Priority, Task
from .storage import JsonStorage, Storage

__all__ = ["Priority", "Task", "TaskManager", "TaskNotFoundError", "Storage", "JsonStorage"]
__version__ = "1.0.0"
