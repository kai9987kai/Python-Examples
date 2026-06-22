#!/usr/bin/env python3
"""Manage a tiny to-do list using plain Python data structures."""


def add_task(tasks, title):
    """Add a task and return the updated task list."""
    tasks.append({"title": title, "done": False})
    return tasks


def complete_task(tasks, title):
    """Mark the first task with a matching title as complete."""
    for task in tasks:
        if task["title"] == title:
            task["done"] = True
            break
    return tasks


def print_tasks(tasks):
    """Print tasks with checkbox-style status markers."""
    for task in tasks:
        marker = "x" if task["done"] else " "
        print(f"[{marker}] {task['title']}")


def main():
    tasks = []
    add_task(tasks, "Write example script")
    add_task(tasks, "Run the example")
    complete_task(tasks, "Write example script")
    print_tasks(tasks)


if __name__ == "__main__":
    main()
