from __future__ import annotations

import json
from pathlib import Path

from tools.run_main_controller_stability_batches import DEFAULT_BATCHES, BatchResult, render_markdown_report


def test_main_controller_stability_batches_cover_expected_slices() -> None:
    assert list(DEFAULT_BATCHES.keys()) == [
        "experiment_guards",
        "layout_experiment",
        "layout_preview_gamesync",
        "layout_preview_transport",
        "layout_preview_recent",
        "layout_build",
        "full_flow_build",
    ]
    assert DEFAULT_BATCHES["experiment_guards"] == ["tests/unit/test_main_controller_experiment_guards.py"]
    assert DEFAULT_BATCHES["layout_experiment"] == ["tests/unit/test_main_controller_layout.py", "-k", "experiment"]
    assert DEFAULT_BATCHES["layout_preview_gamesync"] == [
        "tests/unit/test_main_controller_layout.py",
        "-k",
        "preview_gamesync or preview_current_event",
    ]
    assert DEFAULT_BATCHES["layout_preview_transport"] == [
        "tests/unit/test_main_controller_layout.py",
        "-k",
        "tree_preview or preview_transport",
    ]
    assert DEFAULT_BATCHES["layout_preview_recent"] == ["tests/unit/test_main_controller_layout.py", "-k", "recent_preview"]
    assert DEFAULT_BATCHES["layout_build"] == ["tests/unit/test_main_controller_layout.py", "-k", "build"]
    assert DEFAULT_BATCHES["full_flow_build"] == ["tests/unit/test_main_controller_full_flow.py", "-k", "build"]


def test_main_controller_stability_markdown_report_includes_batch_details(tmp_path: Path) -> None:
    report = render_markdown_report(
        tmp_path,
        [
            BatchResult(
                name="layout_preview_gamesync",
                passed=True,
                duration_seconds=12.5,
                command=["python", "-m", "pytest", "tests/unit/test_main_controller_layout.py", "-k", "preview_gamesync or preview_current_event", "-q"],
                stdout_tail=["11 passed in 12.5s"],
                stderr_tail=[],
            )
        ],
    )

    assert "# MainController Stability Batches" in report
    assert "- Overall: PASS" in report
    assert "### layout_preview_gamesync" in report
    assert "11 passed in 12.5s" in report


def test_main_controller_stability_json_payload_shape(tmp_path: Path) -> None:
    payload = {
        "workspace": str(tmp_path),
        "passed": True,
        "results": [
            BatchResult(
                name="layout_build",
                passed=True,
                duration_seconds=8.39,
                command=["python", "-m", "pytest"],
                stdout_tail=["2 passed"],
                stderr_tail=[],
            ).to_dict()
        ],
    }

    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    decoded = json.loads(json_text)

    assert decoded["passed"] is True
    assert decoded["results"][0]["name"] == "layout_build"
    assert decoded["results"][0]["stdout_tail"] == ["2 passed"]