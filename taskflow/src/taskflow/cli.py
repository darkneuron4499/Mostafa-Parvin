"""Command-line interface."""

from __future__ import annotations

import argparse
import sys

from .manager import TaskManager, TaskNotFoundError
from .models import Priority
from .storage import JsonStorage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="taskflow", description="A tiny task manager.")
    parser.add_argument("--file", default="tasks.json", help="path to the tasks file")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="add a task")
    add.add_argument("title")
    add.add_argument("-p", "--priority", choices=[p.value for p in Priority], default="medium")

    ls = sub.add_parser("list", help="list tasks")
    ls.add_argument("--pending", action="store_true", help="hide completed tasks")

    done = sub.add_parser("done", help="mark a task as done")
    done.add_argument("id", type=int)

    rm = sub.add_parser("remove", help="delete a task")
    rm.add_argument("id", type=int)

    sub.add_parser("stats", help="show summary")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manager = TaskManager(JsonStorage(args.file))

    try:
        if args.command == "add":
            print(f"Added: {manager.add(args.title, Priority(args.priority))}")
        elif args.command == "list":
            tasks = manager.list(only_pending=args.pending)
            print("\n".join(map(str, tasks)) if tasks else "No tasks yet.")
        elif args.command == "done":
            print(f"Completed: {manager.complete(args.id)}")
        elif args.command == "remove":
            manager.remove(args.id)
            print(f"Removed task #{args.id}")
        elif args.command == "stats":
            s = manager.stats()
            print(f"Total: {s['total']} | Done: {s['done']} | Pending: {s['pending']}")
    except (TaskNotFoundError, ValueError) as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
