import pytest

from taskflow import JsonStorage, Priority, TaskManager, TaskNotFoundError


@pytest.fixture
def manager(tmp_path):
    return TaskManager(JsonStorage(tmp_path / "tasks.json"))


def test_add_and_list(manager):
    manager.add("Write README", Priority.HIGH)
    assert [t.title for t in manager.list()] == ["Write README"]


def test_empty_title_rejected(manager):
    with pytest.raises(ValueError):
        manager.add("   ")


def test_complete_and_stats(manager):
    task = manager.add("Ship it")
    manager.complete(task.id)
    assert manager.stats() == {"total": 1, "done": 1, "pending": 0}


def test_remove_missing_raises(manager):
    with pytest.raises(TaskNotFoundError):
        manager.remove(42)


def test_persistence(tmp_path):
    path = tmp_path / "tasks.json"
    TaskManager(JsonStorage(path)).add("Persist me")
    assert TaskManager(JsonStorage(path)).list()[0].title == "Persist me"
