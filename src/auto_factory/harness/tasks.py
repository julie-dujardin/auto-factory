from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Status = Literal["open", "done", "failed"]


@dataclass(eq=False)
class Approach:
    plan: str
    failure: str | None = None


@dataclass(eq=False)
class Task:
    id: str
    title: str
    done_when: str
    parent: Task | None = None
    children: list[Task] = field(default_factory=list)
    approaches: list[Approach] = field(default_factory=list)
    status: Status = "open"
    result: str | None = None

    @property
    def approach(self) -> Approach | None:
        return next((a for a in self.approaches if a.failure is None), None)

    @property
    def label(self) -> str:
        return "the goal" if self.parent is None else f"{self.id}. {self.title}"


class TaskTree:
    """The agent's plan: tasks run depth-first, and closing one moves to the next."""

    def __init__(self, goal: str) -> None:
        self.root = Task("goal", goal, "the goal is achieved")
        self._current: Task | None = self.root

    @property
    def current(self) -> Task:
        if self._current is None:
            raise ValueError("the goal is already closed")
        return self._current

    @property
    def finished(self) -> bool:
        return self.root.status != "open"

    @property
    def outcome(self) -> str:
        result = self.root.result or ""
        return result if self.root.status == "done" else f"Failed: {result}"

    def handle(self, name: str, arguments: dict[str, Any]) -> str:
        if name == "add_tasks":
            return self.add_tasks(arguments["tasks"])
        if name == "propose_approaches":
            return self.propose_approaches(arguments["approaches"])
        if name == "complete_task":
            return self.complete(str(arguments["result"]))
        if name == "fail_task":
            return self.fail(str(arguments["reason"]))
        raise ValueError(f"unknown task tool: {name}")

    def add_tasks(self, specs: list[dict[str, str]]) -> str:
        if not specs:
            raise ValueError("add at least one task")
        task = self.current
        prefix = "" if task.parent is None else f"{task.id}."
        start = len(task.children)
        for index, spec in enumerate(specs, start + 1):
            child = Task(
                f"{prefix}{index}", spec["title"], spec["done_when"], parent=task
            )
            task.children.append(child)
        self._current = task.children[start]
        return f"ok; current task: {self.current.label}"

    def propose_approaches(self, plans: list[str]) -> str:
        task = self.current
        if task.approaches:
            raise ValueError(
                f"{task.label} already has approaches; fail_task moves to the next one"
            )
        if len(plans) < 2:
            raise ValueError("propose at least two different approaches")
        task.approaches = [Approach(plan) for plan in plans]
        return f"ok; trying: {plans[0]}"

    def complete(self, result: str) -> str:
        task = self.current
        task.status = "done"
        task.result = result
        return self._advance(task)

    def fail(self, reason: str) -> str:
        task = self.current
        approach = task.approach
        if approach is not None:
            approach.failure = reason
            # The children belonged to the failed approach; its failure sums them up.
            task.children.clear()
            if task.approach is not None:
                return f"ok; {task.label} now tries: {task.approach.plan}"
        task.status = "failed"
        task.result = reason
        parent = task.parent
        if parent is None:
            self._current = None
            return "ok; the goal failed"
        # Later siblings assumed this task would succeed, so the parent replans.
        parent.children = [c for c in parent.children if c.status != "open"]
        self._current = parent
        return (
            f"ok; back to {parent.label}: add_tasks to replan, or fail_task if it "
            "cannot be done this way"
        )

    def _advance(self, task: Task) -> str:
        parent = task.parent
        if parent is None:
            self._current = None
            return "ok; the goal is complete"
        following = (c for c in parent.children if c.status == "open")
        self._current = next(following, parent)
        if self._current is parent:
            return (
                f"ok; subtasks of {parent.label} are closed: complete_task if its "
                "done_when holds, otherwise add_tasks"
            )
        return f"ok; current task: {self.current.label}"

    def render(self) -> str:
        lines = [f"Goal: {self.root.title}"]
        lines.extend(self._approach_lines(self.root, "  "))
        for child in self.root.children:
            self._render(child, "", lines)
        if self._current is not None:
            lines.append(f"Current task: {self.current.label}")
            if self.current.approach is None:
                lines.append(
                    "It has no approach: inspect the game with api_scan, "
                    "api_find, and api_resources, look up recipes, entities, and "
                    "IDs with api_recipe, api_entity_info, and api_search, then "
                    "call add_tasks or propose_approaches before using other game "
                    "tools."
                )
        return "\n".join(lines)

    def _render(self, task: Task, indent: str, lines: list[str]) -> None:
        if task.status == "done":
            lines.append(f"{indent}[x] {task.id}. {task.title} -> {task.result}")
            return
        if task.status == "failed":
            lines.append(
                f"{indent}[!] {task.id}. {task.title} -> failed: {task.result}"
            )
            return
        marker = ">" if task is self._current else " "
        lines.append(
            f"{indent}[{marker}] {task.id}. {task.title} (done when: {task.done_when})"
        )
        lines.extend(self._approach_lines(task, indent + "    "))
        for child in task.children:
            self._render(child, indent + "    ", lines)

    def _approach_lines(self, task: Task, indent: str) -> list[str]:
        active = task.approach
        lines = []
        for approach in task.approaches:
            if approach.failure is not None:
                text = f"tried: {approach.plan} -> failed: {approach.failure}"
            elif approach is active:
                text = f"approach: {approach.plan}"
            else:
                text = f"fallback: {approach.plan}"
            lines.append(indent + text)
        return lines
