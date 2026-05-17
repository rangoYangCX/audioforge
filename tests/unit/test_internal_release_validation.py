from __future__ import annotations

import json
from pathlib import Path

from tools.run_internal_release_validation import parse_args, write_release_signoff


def test_internal_release_validation_parse_args_accepts_existing_export_dir(tmp_path: Path) -> None:
    export_dir = tmp_path / "Export"
    args = parse_args(["--existing-export-dir", str(export_dir)])

    assert args.source_dir is None
    assert args.existing_export_dir == export_dir


def test_internal_release_validation_write_release_signoff_supports_existing_export_mode(tmp_path: Path) -> None:
    report_root = tmp_path / "report"
    checks_root = report_root / "checks"
    checks_root.mkdir(parents=True, exist_ok=True)
    (checks_root / "full_chain_report.json").write_text(
        json.dumps({"passed": True, "checks": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    write_release_signoff(
        report_root=report_root,
        project_path=None,
        export_root=tmp_path / "Export",
        checks_root=checks_root,
        selected_files=[],
        warning_count=0,
        passed=True,
        validation_mode="existing_export",
    )

    signoff_md = (report_root / "release_signoff.md").read_text(encoding="utf-8")
    signoff_json = json.loads((report_root / "release_signoff.json").read_text(encoding="utf-8"))

    assert "- Validation Mode: existing_export" in signoff_md
    assert "(existing export mode; no smoke project generated)" in signoff_md
    assert signoff_json["validation_mode"] == "existing_export"
    assert signoff_json["project_path"] == "(existing export mode; no smoke project generated)"