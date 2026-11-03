import pytest

from auto_factory.harness.tasks import TaskTree


def tasks(*titles: str) -> list[dict[str, str]]:
    return [{"title": title, "done_when": f"{title} works"} for title in titles]


def test_subtasks_run_in_order_then_return_to_parent() -> None:
    tree = TaskTree("red science")
    tree.add_tasks(tasks("fuel", "iron"))
    assert tree.current.label == "1. fuel"

    tree.add_tasks(tasks("coal"))
    assert tree.current.id == "1.1"
    tree.complete("coal at 3,4")
    assert tree.current.label == "1. fuel"

    tree.complete("fuel ready")
    assert tree.current.label == "2. iron"


def test_failing_an_approach_moves_to_the_fallback() -> None:
    tree = TaskTree("goal")
    tree.add_tasks(tasks("fuel"))
    tree.propose_approaches(["burner drill on coal", "chop trees"])
    tree.add_tasks(tasks("place drill"))
    tree.fail("no drill in inventory")

    assert tree.current.label == "1. fuel"
    tree.fail("drill cannot be crafted yet")

    fuel = tree.current
    assert fuel.approach is not None and fuel.approach.plan == "chop trees"
    assert fuel.children == []
    assert "tried: burner drill on coal -> failed: drill cannot" in tree.render()


def test_failure_without_fallback_drops_later_siblings() -> None:
    tree = TaskTree("goal")
    tree.add_tasks(tasks("a", "b", "c"))
    tree.complete("a done")
    tree.fail("b impossible")

    assert tree.current is tree.root
    assert [(c.title, c.status) for c in tree.root.children] == [
        ("a", "done"),
        ("b", "failed"),
    ]
    tree.add_tasks(tasks("b2"))
    assert tree.current.id == "3"


def test_closing_the_goal_finishes() -> None:
    tree = TaskTree("goal")
    tree.complete("lab built")
    assert tree.finished and tree.outcome == "lab built"

    failed = TaskTree("goal")
    failed.fail("no ore")
    assert failed.outcome == "Failed: no ore"


def test_approaches_are_proposed_once() -> None:
    tree = TaskTree("goal")
    with pytest.raises(ValueError, match="at least two"):
        tree.propose_approaches(["only"])
    tree.propose_approaches(["a", "b"])
    with pytest.raises(ValueError, match="already has approaches"):
        tree.propose_approaches(["c", "d"])


def test_render_marks_current_and_collapses_closed_tasks() -> None:
    tree = TaskTree("red science")
    tree.add_tasks(tasks("fuel", "lab"))
    tree.add_tasks(tasks("coal"))
    tree.complete("coal at 3,4")

    assert tree.render() == "\n".join(
        [
            "Goal: red science",
            "[>] 1. fuel (done when: fuel works)",
            "    [x] 1.1. coal -> coal at 3,4",
            "[ ] 2. lab (done when: lab works)",
            "Current task: 1. fuel",
            "It has no approach: inspect the game with api_scan, api_find, and "
            "api_resources, "
            "look up recipes, entities, technologies, and IDs with api_recipe, "
            "api_entity_info, api_technology, and api_search, then call add_tasks or "
            "propose_approaches before using other game tools.",
        ]
    )
