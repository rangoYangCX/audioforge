from __future__ import annotations

from pathlib import Path

from audioforge.app.utils.constants import APP_VERSION


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_current_version_release_note_exists() -> None:
    workspace = _workspace_root()
    release_note = workspace / "docs" / "releases" / f"v{APP_VERSION}-github-release.md"

    assert release_note.exists()


def test_documentation_workflow_baseline_is_indexed() -> None:
    workspace = _workspace_root()
    workflow_doc = workspace / "docs" / "internal" / "architecture" / "audioforge_开发完成定义与文档同步基线.md"
    docs_index = (workspace / "docs" / "README.md").read_text(encoding="utf-8")
    dev_doc = (workspace / "开发文档.md").read_text(encoding="utf-8")
    repo_readme = (workspace / "README.md").read_text(encoding="utf-8")

    assert workflow_doc.exists()
    assert "audioforge_开发完成定义与文档同步基线.md" in docs_index
    assert "audioforge_开发完成定义与文档同步基线.md" in dev_doc
    assert "audioforge_开发完成定义与文档同步基线.md" in repo_readme