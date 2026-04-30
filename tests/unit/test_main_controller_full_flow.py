from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from audioforge.app.controllers.main_controller import MainController
from audioforge.app.services.recovery_service import RecoveryService
from audioforge.app.utils.constants import MAX_COMBO_MAX_STEP, MAX_MAX_INSTANCES
from tests.helpers import write_wav_fixture
from tools.run_full_chain_check import check_export_bundle, check_runtime_contract


def _apply_event_form(
    controller: MainController,
    *,
    event_id: str,
    display_name: str,
    bus: str,
    play_mode: str,
    steal_policy: str,
    volume_db: float,
    volume_rand_min_db: float,
    volume_rand_max_db: float,
    pitch_cents: float,
    pitch_rand_min_cents: int,
    pitch_rand_max_cents: int,
    cooldown_seconds: float,
    max_instances: int,
    combo_pitch_step_semitones: int,
    combo_reset_seconds: float,
    combo_max_step: int,
    avoid_immediate_repeat: bool,
    tags_text: str,
    notes_text: str,
) -> None:
    window = controller.window
    window.event_id_edit.setText(event_id)
    window.display_name_edit.setText(display_name)
    window.bus_combo.setCurrentText(bus)
    window.play_mode_combo.setCurrentText(play_mode)
    window.steal_policy_combo.setCurrentText(steal_policy)
    window.volume_spin.setValue(volume_db)
    window.volume_rand_min_spin.setValue(volume_rand_min_db)
    window.volume_rand_max_spin.setValue(volume_rand_max_db)
    window.pitch_spin.setValue(pitch_cents)
    window.pitch_rand_min_spin.setValue(pitch_rand_min_cents)
    window.pitch_rand_max_spin.setValue(pitch_rand_max_cents)
    window.cooldown_spin.setValue(cooldown_seconds)
    window.max_instances_spin.setValue(max_instances)
    window.combo_pitch_step_spin.setValue(combo_pitch_step_semitones)
    window.combo_reset_spin.setValue(combo_reset_seconds)
    window.combo_max_step_spin.setValue(combo_max_step)
    window.avoid_repeat_check.setChecked(avoid_immediate_repeat)
    window.tags_summary_edit.setText(tags_text)
    window.notes_edit.setPlainText(notes_text)
    controller.update_current_event_from_form()
    QApplication.processEvents()


def test_selected_build_preview_updates_scope_and_plan_labels(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.show()
    QApplication.processEvents()
    controller.new_project()
    QApplication.processEvents()

    export_root = tmp_path / "Export"
    controller.project.settings.export_root = str(export_root)
    controller.project.settings.source_audio_format = "wav"
    controller.project.settings.runtime_audio_format = "wav"

    primary_wav = write_wav_fixture(tmp_path / "wav" / "UI_Click_A.wav", frequency_hz=440.0, duration_seconds=0.2)
    secondary_wav = write_wav_fixture(tmp_path / "wav" / "UI_Click_B.wav", frequency_hz=660.0, duration_seconds=0.2)
    controller.import_audio_files_as_events(
        [str(primary_wav), str(secondary_wav)],
        template={
            "bus_name": "UI",
            "asset_prefix": "ui/preview",
            "tags": ["ui"],
        },
    )
    QApplication.processEvents()

    controller.select_node("event", "UI_Click_A")
    QApplication.processEvents()
    selection_index = controller.window.build_scope_combo.findData("selection")
    controller.window.build_scope_combo.setCurrentIndex(selection_index)

    controller.preview_export_diff()
    QApplication.processEvents()

    preview_text = controller.window.build_preview_output.toPlainText()

    assert controller.window.build_scope_target_label.text() == "当前范围：事件 UI_Click_A"
    assert "请求 选中构建" in controller.window.build_plan_summary_label.text()
    assert "请求范围：选中构建" in preview_text
    assert "实际执行：全量构建" in preview_text
    assert "构建目标：事件 UI_Click_A" in preview_text

    controller.is_dirty = False
    controller.window.close()


def test_full_authoring_flow_from_wav_import_to_export(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.show()
    QApplication.processEvents()
    controller.new_project()
    QApplication.processEvents()

    export_root = tmp_path / "Export"
    controller.project.settings.export_root = str(export_root)
    controller.project.settings.source_audio_format = "wav"
    controller.project.settings.runtime_audio_format = "wav"

    random_main = write_wav_fixture(tmp_path / "wav" / "UI_Click_Random.wav", frequency_hz=440.0, duration_seconds=0.25)
    random_alt = write_wav_fixture(tmp_path / "wav" / "UI_Click_Random_Alt.wav", frequency_hz=660.0, duration_seconds=0.25)
    sequence_main = write_wav_fixture(tmp_path / "wav" / "UI_Click_Sequence.wav", frequency_hz=550.0, duration_seconds=0.25)
    combo_main = write_wav_fixture(tmp_path / "wav" / "UI_Click_Combo.wav", frequency_hz=770.0, duration_seconds=0.25)

    controller.import_audio_files_as_events(
        [str(random_main), str(sequence_main), str(combo_main)],
        template={
            "bus_name": "UI",
            "asset_prefix": "ui/casual",
            "tags": ["ui", "casual"],
        },
    )
    QApplication.processEvents()

    controller.select_node("event", "UI_Click_Random")
    QApplication.processEvents()
    controller.import_clips([str(random_alt)])
    QApplication.processEvents()
    _apply_event_form(
        controller,
        event_id="UI_Click_Random_Main",
        display_name="UI Click Random Main",
        bus="SFX",
        play_mode="Random",
        steal_policy="StopOldest",
        volume_db=-2.5,
        volume_rand_min_db=-1.5,
        volume_rand_max_db=1.0,
        pitch_cents=100,
        pitch_rand_min_cents=-120,
        pitch_rand_max_cents=180,
        cooldown_seconds=0.35,
        max_instances=3,
        combo_pitch_step_semitones=1,
        combo_reset_seconds=1.5,
        combo_max_step=0,
        avoid_immediate_repeat=True,
        tags_text="ui, click, random",
        notes_text="Random event for export verification.",
    )
    random_event = controller.current_event
    assert random_event is not None
    controller.update_clip_field("UI_Click_Random", "asset_key", "sfx/ui_click_random_main")
    controller.update_clip_field("UI_Click_Random", "weight", "7")
    controller.update_clip_field("UI_Click_Random", "trim_start_ms", "5")
    controller.update_clip_field("UI_Click_Random", "trim_end_ms", "30")
    controller.update_clip_field("UI_Click_Random", "loop_start_ms", "10")
    controller.update_clip_field("UI_Click_Random", "loop_end_ms", "20")
    controller.update_clip_field("UI_Click_Random", "tags", "ui,primary")
    controller.update_clip_field("UI_Click_Random_Alt", "asset_key", "sfx/ui_click_random_alt")
    controller.update_clip_field("UI_Click_Random_Alt", "weight", "3")
    controller.update_clip_field("UI_Click_Random_Alt", "trim_start_ms", "2")
    controller.update_clip_field("UI_Click_Random_Alt", "trim_end_ms", "18")
    controller.update_clip_field("UI_Click_Random_Alt", "tags", "ui,alt")
    QApplication.processEvents()

    controller.select_node("event", "UI_Click_Sequence")
    QApplication.processEvents()
    _apply_event_form(
        controller,
        event_id="UI_Click_Sequence",
        display_name="UI Click Sequence",
        bus="UI",
        play_mode="Sequence",
        steal_policy="RejectNew",
        volume_db=-1.0,
        volume_rand_min_db=0.0,
        volume_rand_max_db=0.0,
        pitch_cents=0,
        pitch_rand_min_cents=0,
        pitch_rand_max_cents=0,
        cooldown_seconds=0.1,
        max_instances=1,
        combo_pitch_step_semitones=1,
        combo_reset_seconds=1.5,
        combo_max_step=0,
        avoid_immediate_repeat=False,
        tags_text="ui,sequence",
        notes_text="Sequence event",
    )
    controller.update_clip_field("UI_Click_Sequence", "asset_key", "ui/ui_click_sequence")
    controller.update_clip_field("UI_Click_Sequence", "weight", "2")
    QApplication.processEvents()

    controller.select_node("event", "UI_Click_Combo")
    QApplication.processEvents()
    _apply_event_form(
        controller,
        event_id="UI_Click_Combo",
        display_name="UI Click Combo",
        bus="UI",
        play_mode="Combo",
        steal_policy="RejectNew",
        volume_db=-0.5,
        volume_rand_min_db=-0.5,
        volume_rand_max_db=0.5,
        pitch_cents=50,
        pitch_rand_min_cents=-50,
        pitch_rand_max_cents=50,
        cooldown_seconds=0.0,
        max_instances=2,
        combo_pitch_step_semitones=2,
        combo_reset_seconds=1.2,
        combo_max_step=4,
        avoid_immediate_repeat=False,
        tags_text="ui,combo",
        notes_text="Combo event",
    )
    controller.update_clip_field("UI_Click_Combo", "asset_key", "ui/ui_click_combo")
    QApplication.processEvents()

    issues = controller.validator.validate(controller.project)
    issue_pairs = {(issue.code, issue.target) for issue in issues}
    assert ("CLIP_LOOP_NOT_IMPLEMENTED", "UI_Click_Random_Main") in issue_pairs
    assert ("SEQUENCE_SINGLE_CLIP", "UI_Click_Sequence") in issue_pairs

    controller.validate_project()
    QApplication.processEvents()
    assert controller.window.report_tabs.currentIndex() == 1
    assert controller.window.validation_issue_list.count() == len(issues)

    controller.build_project()
    QApplication.processEvents()
    assert controller.window.report_tabs.currentIndex() == 2

    audio_data_path = export_root / "AudioData.json"
    manifest_path = export_root / "AudioManifest.json"
    build_report_path = export_root / "BuildReport.json"
    enum_path = export_root / "AudioEventID.cs"
    assert audio_data_path.exists()
    assert manifest_path.exists()
    assert build_report_path.exists()
    assert enum_path.exists()

    audio_data = json.loads(audio_data_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    build_report = json.loads(build_report_path.read_text(encoding="utf-8"))
    event_enum = enum_path.read_text(encoding="utf-8")

    assert build_report["EventCount"] == 3
    assert build_report["ClipCount"] == 4
    assert build_report["ErrorCount"] == 0
    assert build_report["WarningCount"] == 2
    assert audio_data["RuntimeAudioFormat"] == "wav"
    assert sorted(audio_data["Events"].keys()) == ["UI_Click_Combo", "UI_Click_Random_Main", "UI_Click_Sequence"]
    assert "UI_Click_Random_Main" in event_enum
    assert "UI_Click_Sequence" in event_enum
    assert "UI_Click_Combo" in event_enum

    random_payload = audio_data["Events"]["UI_Click_Random_Main"]
    assert random_payload["Bus"] == "SFX"
    assert random_payload["PlayMode"] == "Random"
    assert random_payload["AvoidImmediateRepeat"] is True
    assert random_payload["VolumeDb"] == -2.5
    assert random_payload["VolumeRandDb"] == [-1.5, 1.0]
    assert random_payload["PitchCents"] == 100
    assert random_payload["PitchRandCents"] == [-120, 180]
    assert random_payload["CooldownSeconds"] == 0.35
    assert random_payload["MaxInstances"] == 3
    assert random_payload["StealPolicy"] == "StopOldest"
    assert random_payload["LoadPolicy"] == "OnDemand"
    assert len(random_payload["Clips"]) == 2

    random_clips = {clip["ClipId"]: clip for clip in random_payload["Clips"]}
    assert random_clips["UI_Click_Random"]["AssetKey"] == "sfx/ui_click_random_main"
    assert random_clips["UI_Click_Random"]["Weight"] == 7
    assert random_clips["UI_Click_Random"]["TrimStartMs"] == 5
    assert random_clips["UI_Click_Random"]["TrimEndMs"] == 30
    assert random_clips["UI_Click_Random"]["LoopStartMs"] == 10
    assert random_clips["UI_Click_Random"]["LoopEndMs"] == 20
    assert random_clips["UI_Click_Random_Alt"]["AssetKey"] == "sfx/ui_click_random_alt"
    assert random_clips["UI_Click_Random_Alt"]["Weight"] == 3
    assert random_clips["UI_Click_Random_Alt"]["TrimStartMs"] == 2
    assert random_clips["UI_Click_Random_Alt"]["TrimEndMs"] == 18

    sequence_payload = audio_data["Events"]["UI_Click_Sequence"]
    assert sequence_payload["PlayMode"] == "Sequence"
    assert sequence_payload["Bus"] == "UI"
    assert sequence_payload["MaxInstances"] == 1
    assert sequence_payload["CooldownSeconds"] == 0.1
    assert sequence_payload["Clips"][0]["AssetKey"] == "ui/ui_click_sequence"
    assert sequence_payload["Clips"][0]["Weight"] == 2

    combo_payload = audio_data["Events"]["UI_Click_Combo"]
    assert combo_payload["PlayMode"] == "Combo"
    assert combo_payload["ComboPitchStepCents"] == 200
    assert combo_payload["ComboResetSeconds"] == 1.2
    assert combo_payload["ComboMaxStep"] == 4
    assert combo_payload["PitchCents"] == 50
    assert combo_payload["PitchRandCents"] == [-50, 50]
    assert combo_payload["Clips"][0]["AssetKey"] == "ui/ui_click_combo"

    manifest_assets = {asset["AssetKey"]: asset for asset in manifest["Assets"]}
    assert len(manifest_assets) == 4
    assert manifest_assets["sfx/ui_click_random_main"]["ExportPath"] == "sfx/ui_click_random_main.wav"
    assert manifest_assets["sfx/ui_click_random_main"]["TrimStartMs"] == 5
    assert manifest_assets["sfx/ui_click_random_main"]["TrimEndMs"] == 30
    assert manifest_assets["sfx/ui_click_random_main"]["LoopStartMs"] == 10
    assert manifest_assets["sfx/ui_click_random_main"]["LoopEndMs"] == 20
    assert manifest_assets["sfx/ui_click_random_main"]["ReferencedByEvents"] == ["UI_Click_Random_Main"]
    assert manifest_assets["ui/ui_click_combo"]["ReferencedByEvents"] == ["UI_Click_Combo"]

    assert (export_root / "Assets" / "sfx" / "ui_click_random_main.wav").exists()
    assert (export_root / "Assets" / "sfx" / "ui_click_random_alt.wav").exists()
    assert (export_root / "Assets" / "ui" / "ui_click_sequence.wav").exists()
    assert (export_root / "Assets" / "ui" / "ui_click_combo.wav").exists()

    export_check = check_export_bundle(export_root)
    contract_check = check_runtime_contract(export_root)
    assert export_check.passed is True
    assert contract_check.passed is True

    controller.is_dirty = False
    controller.window.close()


def test_sequence_and_combo_multi_clip_boundary_flow_exports_cleanly(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.show()
    QApplication.processEvents()
    controller.new_project()
    QApplication.processEvents()

    export_root = tmp_path / "Export"
    controller.project.settings.export_root = str(export_root)
    controller.project.settings.source_audio_format = "wav"
    controller.project.settings.runtime_audio_format = "wav"

    sequence_main = write_wav_fixture(tmp_path / "wav" / "UI_Step_Sequence.wav", frequency_hz=500.0, duration_seconds=0.2)
    sequence_alt = write_wav_fixture(tmp_path / "wav" / "UI_Step_Sequence_Alt.wav", frequency_hz=620.0, duration_seconds=0.2)
    combo_main = write_wav_fixture(tmp_path / "wav" / "UI_Hit_Combo.wav", frequency_hz=720.0, duration_seconds=0.2)
    combo_alt = write_wav_fixture(tmp_path / "wav" / "UI_Hit_Combo_Alt.wav", frequency_hz=880.0, duration_seconds=0.2)

    controller.import_audio_files_as_events(
        [str(sequence_main), str(combo_main)],
        template={
            "bus_name": "UI",
            "asset_prefix": "ui/boundary",
            "tags": ["ui", "boundary"],
        },
    )
    QApplication.processEvents()

    controller.select_node("event", "UI_Step_Sequence")
    QApplication.processEvents()
    controller.import_clips([str(sequence_alt)])
    QApplication.processEvents()
    _apply_event_form(
        controller,
        event_id="UI_Step_Sequence",
        display_name="UI Step Sequence",
        bus="UI",
        play_mode="Sequence",
        steal_policy="RejectNew",
        volume_db=-1.0,
        volume_rand_min_db=-0.5,
        volume_rand_max_db=0.0,
        pitch_cents=0,
        pitch_rand_min_cents=0,
        pitch_rand_max_cents=0,
        cooldown_seconds=0.0,
        max_instances=MAX_MAX_INSTANCES,
        combo_pitch_step_semitones=1,
        combo_reset_seconds=1.0,
        combo_max_step=0,
        avoid_immediate_repeat=True,
        tags_text="ui,sequence,boundary",
        notes_text="Sequence multi-clip boundary flow.",
    )
    controller.update_clip_field("UI_Step_Sequence", "asset_key", "ui/boundary_sequence_main")
    controller.update_clip_field("UI_Step_Sequence", "weight", "4")
    controller.update_clip_field("UI_Step_Sequence_Alt", "asset_key", "ui/boundary_sequence_alt")
    controller.update_clip_field("UI_Step_Sequence_Alt", "weight", "5")
    QApplication.processEvents()

    controller.select_node("event", "UI_Hit_Combo")
    QApplication.processEvents()
    controller.import_clips([str(combo_alt)])
    QApplication.processEvents()
    _apply_event_form(
        controller,
        event_id="UI_Hit_Combo",
        display_name="UI Hit Combo",
        bus="UI",
        play_mode="Combo",
        steal_policy="RejectNew",
        volume_db=-1.5,
        volume_rand_min_db=-0.5,
        volume_rand_max_db=0.0,
        pitch_cents=25,
        pitch_rand_min_cents=-100,
        pitch_rand_max_cents=100,
        cooldown_seconds=0.0,
        max_instances=MAX_MAX_INSTANCES,
        combo_pitch_step_semitones=3,
        combo_reset_seconds=0.1,
        combo_max_step=MAX_COMBO_MAX_STEP,
        avoid_immediate_repeat=False,
        tags_text="ui,combo,boundary",
        notes_text="Combo multi-clip boundary flow.",
    )
    controller.update_clip_field("UI_Hit_Combo", "asset_key", "ui/boundary_combo_main")
    controller.update_clip_field("UI_Hit_Combo", "weight", "6")
    controller.update_clip_field("UI_Hit_Combo_Alt", "asset_key", "ui/boundary_combo_alt")
    controller.update_clip_field("UI_Hit_Combo_Alt", "weight", "8")
    QApplication.processEvents()

    issues = controller.validator.validate(controller.project)
    issue_pairs = {(issue.code, issue.target) for issue in issues}
    assert issues == []
    assert ("SEQUENCE_SINGLE_CLIP", "UI_Step_Sequence") not in issue_pairs
    assert ("AVOID_REPEAT_REDUNDANT", "UI_Step_Sequence") not in issue_pairs

    controller.validate_project()
    QApplication.processEvents()
    assert controller.window.report_tabs.currentIndex() == 1
    assert controller.window.validation_issue_list.count() == 0

    controller.build_project()
    QApplication.processEvents()
    assert controller.window.report_tabs.currentIndex() == 2

    audio_data = json.loads((export_root / "AudioData.json").read_text(encoding="utf-8"))
    build_report = json.loads((export_root / "BuildReport.json").read_text(encoding="utf-8"))

    assert build_report["EventCount"] == 2
    assert build_report["ClipCount"] == 4
    assert build_report["ErrorCount"] == 0
    assert build_report["WarningCount"] == 0

    sequence_payload = audio_data["Events"]["UI_Step_Sequence"]
    assert sequence_payload["PlayMode"] == "Sequence"
    assert sequence_payload["AvoidImmediateRepeat"] is True
    assert sequence_payload["MaxInstances"] == MAX_MAX_INSTANCES
    assert [clip["ClipId"] for clip in sequence_payload["Clips"]] == ["UI_Step_Sequence", "UI_Step_Sequence_Alt"]
    assert [clip["AssetKey"] for clip in sequence_payload["Clips"]] == [
        "ui/boundary_sequence_main",
        "ui/boundary_sequence_alt",
    ]

    combo_payload = audio_data["Events"]["UI_Hit_Combo"]
    assert combo_payload["PlayMode"] == "Combo"
    assert combo_payload["MaxInstances"] == MAX_MAX_INSTANCES
    assert combo_payload["ComboPitchStepCents"] == 300
    assert combo_payload["ComboResetSeconds"] == 0.1
    assert combo_payload["ComboMaxStep"] == MAX_COMBO_MAX_STEP
    assert [clip["ClipId"] for clip in combo_payload["Clips"]] == ["UI_Hit_Combo", "UI_Hit_Combo_Alt"]
    assert [clip["AssetKey"] for clip in combo_payload["Clips"]] == [
        "ui/boundary_combo_main",
        "ui/boundary_combo_alt",
    ]

    export_check = check_export_bundle(export_root)
    contract_check = check_runtime_contract(export_root)
    assert export_check.passed is True
    assert contract_check.passed is True

    controller.is_dirty = False
    controller.window.close()


def test_invalid_combo_and_instance_limits_block_build_consistently(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.show()
    QApplication.processEvents()
    controller.new_project()
    QApplication.processEvents()

    export_root = tmp_path / "Export"
    controller.project.settings.export_root = str(export_root)
    controller.project.settings.source_audio_format = "wav"
    controller.project.settings.runtime_audio_format = "wav"

    combo_main = write_wav_fixture(tmp_path / "wav" / "UI_Invalid_Combo.wav", frequency_hz=640.0, duration_seconds=0.2)

    controller.import_audio_files_as_events(
        [str(combo_main)],
        template={
            "bus_name": "UI",
            "asset_prefix": "ui/invalid",
            "tags": ["ui", "invalid"],
        },
    )
    QApplication.processEvents()

    controller.select_node("event", "UI_Invalid_Combo")
    QApplication.processEvents()
    _apply_event_form(
        controller,
        event_id="UI_Invalid_Combo",
        display_name="UI Invalid Combo",
        bus="UI",
        play_mode="Combo",
        steal_policy="RejectNew",
        volume_db=-1.0,
        volume_rand_min_db=-0.5,
        volume_rand_max_db=0.0,
        pitch_cents=0,
        pitch_rand_min_cents=0,
        pitch_rand_max_cents=0,
        cooldown_seconds=0.0,
        max_instances=1,
        combo_pitch_step_semitones=1,
        combo_reset_seconds=1.0,
        combo_max_step=1,
        avoid_immediate_repeat=False,
        tags_text="ui,invalid,combo",
        notes_text="Invalid combo should block build.",
    )
    QApplication.processEvents()

    invalid_event = controller.project.events["UI_Invalid_Combo"]
    invalid_event.max_instances = MAX_MAX_INSTANCES + 1
    invalid_event.combo_pitch_step_cents = 250
    invalid_event.combo_reset_seconds = 0.0

    issues = controller.validator.validate(controller.project)
    issue_pairs = {(issue.code, issue.target) for issue in issues}
    expected_pairs = {
        ("MAX_INSTANCES_OUT_OF_RANGE", "UI_Invalid_Combo"),
        ("COMBO_PITCH_STEP_NOT_SEMITONE", "UI_Invalid_Combo"),
        ("COMBO_RESET_INVALID", "UI_Invalid_Combo"),
    }
    assert issue_pairs == expected_pairs

    controller.validate_project()
    QApplication.processEvents()
    assert controller.window.report_tabs.currentIndex() == 1
    assert controller.window.validation_issue_list.count() == len(expected_pairs)
    assert controller.window.validation_summary_label.text() == "校验问题中心：错误 3 | 警告 0 | 信息 0。双击列表可跳转到对应对象。"
    validation_detail = controller.window.validation_report_output.toPlainText()
    assert "UI_Invalid_Combo" in validation_detail
    assert any(code in validation_detail for code in ["MAX_INSTANCES_OUT_OF_RANGE", "COMBO_PITCH_STEP_NOT_SEMITONE", "COMBO_RESET_INVALID"])

    controller.build_project()
    QApplication.processEvents()
    assert controller.window.report_tabs.currentIndex() == 1
    assert controller.window.validation_issue_list.count() == len(expected_pairs)
    assert "构建已中止，存在 3 个错误。" in controller.window.log_output.toPlainText()
    assert not (export_root / "AudioData.json").exists()
    assert controller.window.build_report_output.toPlainText() == ""

    controller.is_dirty = False
    controller.window.close()


def test_mixed_valid_invalid_import_flow_preserves_progress_and_logs_skips(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.show()
    QApplication.processEvents()
    controller.new_project()
    QApplication.processEvents()

    export_root = tmp_path / "Export"
    controller.project.settings.export_root = str(export_root)
    controller.project.settings.source_audio_format = "wav"
    controller.project.settings.runtime_audio_format = "wav"

    event_main = write_wav_fixture(tmp_path / "wav" / "UI_Mixed_Import.wav", frequency_hz=430.0, duration_seconds=0.2)
    clip_alt = write_wav_fixture(tmp_path / "wav" / "UI_Mixed_Import_Alt.wav", frequency_hz=530.0, duration_seconds=0.2)
    unsupported_path = tmp_path / "wav" / "readme.txt"
    unsupported_path.write_text("not audio", encoding="utf-8")
    missing_path = tmp_path / "wav" / "missing.wav"

    controller.import_audio_files_as_events(
        [str(event_main), str(unsupported_path), str(missing_path)],
        template={
            "bus_name": "UI",
            "asset_prefix": "ui/mixed",
            "tags": ["ui", "mixed"],
        },
    )
    QApplication.processEvents()

    assert "UI_Mixed_Import" in controller.project.events
    import_log = controller.window.log_output.toPlainText()
    assert "已导入 1 个音频并创建事件" in import_log
    assert "跳过 1 个不支持的文件" in import_log
    assert "跳过 1 个不存在的文件" in import_log

    controller.select_node("event", "UI_Mixed_Import")
    QApplication.processEvents()
    controller.import_clips([str(clip_alt), str(unsupported_path), str(missing_path)])
    QApplication.processEvents()

    mixed_event = controller.project.events["UI_Mixed_Import"]
    assert len(mixed_event.clips) == 2
    clip_log = controller.window.log_output.toPlainText()
    assert "已向 UI_Mixed_Import 导入 1 个片段" in clip_log
    assert clip_log.count("跳过 1 个不支持的文件") >= 2
    assert clip_log.count("跳过 1 个不存在的文件") >= 2

    _apply_event_form(
        controller,
        event_id="UI_Mixed_Import",
        display_name="UI Mixed Import",
        bus="UI",
        play_mode="Random",
        steal_policy="RejectNew",
        volume_db=-1.0,
        volume_rand_min_db=-0.5,
        volume_rand_max_db=0.0,
        pitch_cents=0,
        pitch_rand_min_cents=0,
        pitch_rand_max_cents=0,
        cooldown_seconds=0.0,
        max_instances=2,
        combo_pitch_step_semitones=1,
        combo_reset_seconds=1.0,
        combo_max_step=0,
        avoid_immediate_repeat=True,
        tags_text="ui,mixed",
        notes_text="Mixed valid-invalid import flow.",
    )
    controller.update_clip_field("UI_Mixed_Import", "asset_key", "ui/mixed_import_main")
    controller.update_clip_field("UI_Mixed_Import", "weight", "2")
    controller.update_clip_field("UI_Mixed_Import_Alt", "asset_key", "ui/mixed_import_alt")
    controller.update_clip_field("UI_Mixed_Import_Alt", "weight", "3")
    QApplication.processEvents()

    issues = controller.validator.validate(controller.project)
    assert issues == []

    controller.validate_project()
    QApplication.processEvents()
    assert controller.window.report_tabs.currentIndex() == 1
    assert controller.window.validation_issue_list.count() == 0

    controller.build_project()
    QApplication.processEvents()
    assert controller.window.report_tabs.currentIndex() == 2

    build_report = json.loads((export_root / "BuildReport.json").read_text(encoding="utf-8"))
    audio_data = json.loads((export_root / "AudioData.json").read_text(encoding="utf-8"))

    assert build_report["EventCount"] == 1
    assert build_report["ClipCount"] == 2
    assert build_report["ErrorCount"] == 0
    assert build_report["WarningCount"] == 0
    assert audio_data["Events"]["UI_Mixed_Import"]["AvoidImmediateRepeat"] is True
    assert [clip["AssetKey"] for clip in audio_data["Events"]["UI_Mixed_Import"]["Clips"]] == [
        "ui/mixed_import_main",
        "ui/mixed_import_alt",
    ]

    export_check = check_export_bundle(export_root)
    contract_check = check_runtime_contract(export_root)
    assert export_check.passed is True
    assert contract_check.passed is True

    controller.is_dirty = False
    controller.window.close()


def test_build_fails_when_export_parent_path_is_occupied_by_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    criticals: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda parent, title, message: criticals.append((title, message)),
    )

    controller = MainController()
    controller.window.show()
    QApplication.processEvents()
    controller.new_project()
    QApplication.processEvents()

    occupied_parent = tmp_path / "occupied_parent"
    occupied_parent.write_text("occupied", encoding="utf-8")
    export_root = occupied_parent / "Export"
    controller.project.settings.export_root = str(export_root)
    controller.project.settings.source_audio_format = "wav"
    controller.project.settings.runtime_audio_format = "wav"

    event_main = write_wav_fixture(tmp_path / "wav" / "UI_Export_Path_Failure.wav", frequency_hz=410.0, duration_seconds=0.2)
    controller.import_audio_files_as_events(
        [str(event_main)],
        template={
            "bus_name": "UI",
            "asset_prefix": "ui/export_failure",
            "tags": ["ui", "export_failure"],
        },
    )
    QApplication.processEvents()

    issues = controller.validator.validate(controller.project)
    assert issues == []

    controller.build_project()
    QApplication.processEvents()

    assert criticals
    assert criticals[0][0] == "构建失败"
    assert criticals[0][1]
    assert controller.window.report_tabs.currentIndex() == 2
    assert controller.window.build_issue_list.count() >= 1
    assert "构建失败" in controller.window.build_report_output.toPlainText()
    assert f"导出目录：{export_root}" in controller.window.build_preview_output.toPlainText()
    assert "构建失败：" in controller.window.log_output.toPlainText()
    assert not (export_root / "AudioData.json").exists()

    controller.is_dirty = False
    controller.window.close()


def test_rebuild_updates_export_bundle_and_diff_preview_consistently(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.show()
    QApplication.processEvents()
    controller.new_project()
    QApplication.processEvents()

    export_root = tmp_path / "Export"
    controller.project.settings.export_root = str(export_root)
    controller.project.settings.source_audio_format = "wav"
    controller.project.settings.runtime_audio_format = "wav"

    primary_wav = write_wav_fixture(tmp_path / "wav" / "UI_Rebuild_Primary.wav", frequency_hz=440.0, duration_seconds=0.2)
    removed_wav = write_wav_fixture(tmp_path / "wav" / "UI_Rebuild_Removed.wav", frequency_hz=520.0, duration_seconds=0.2)
    added_wav = write_wav_fixture(tmp_path / "wav" / "UI_Rebuild_Added.wav", frequency_hz=680.0, duration_seconds=0.2)

    controller.import_audio_files_as_events(
        [str(primary_wav)],
        template={
            "bus_name": "UI",
            "asset_prefix": "ui/rebuild",
            "tags": ["ui", "rebuild"],
        },
    )
    QApplication.processEvents()

    controller.select_node("event", "UI_Rebuild_Primary")
    QApplication.processEvents()
    controller.import_clips([str(removed_wav)])
    QApplication.processEvents()
    _apply_event_form(
        controller,
        event_id="UI_Rebuild_Primary",
        display_name="UI Rebuild Primary",
        bus="UI",
        play_mode="Random",
        steal_policy="RejectNew",
        volume_db=-1.0,
        volume_rand_min_db=0.0,
        volume_rand_max_db=0.0,
        pitch_cents=0,
        pitch_rand_min_cents=0,
        pitch_rand_max_cents=0,
        cooldown_seconds=0.0,
        max_instances=2,
        combo_pitch_step_semitones=1,
        combo_reset_seconds=1.0,
        combo_max_step=0,
        avoid_immediate_repeat=False,
        tags_text="ui,rebuild",
        notes_text="Rebuild diff verification.",
    )
    controller.update_clip_field("UI_Rebuild_Primary", "asset_key", "ui/rebuild_primary")
    controller.update_clip_field("UI_Rebuild_Removed", "asset_key", "ui/rebuild_removed")
    QApplication.processEvents()

    initial_issues = controller.validator.validate(controller.project)
    assert initial_issues == []
    controller.build_project()
    QApplication.processEvents()

    primary_asset_path = export_root / "Assets" / "ui" / "rebuild_primary.wav"
    removed_asset_path = export_root / "Assets" / "ui" / "rebuild_removed.wav"
    added_asset_path = export_root / "Assets" / "ui" / "rebuild_added.wav"
    assert primary_asset_path.exists()
    assert removed_asset_path.exists()
    assert not added_asset_path.exists()

    controller.select_node("event", "UI_Rebuild_Primary")
    QApplication.processEvents()
    controller.import_clips([str(added_wav)])
    QApplication.processEvents()
    controller.update_clip_field("UI_Rebuild_Added", "asset_key", "ui/rebuild_added")
    controller.update_clip_field("UI_Rebuild_Primary", "trim_end_ms", "15")
    controller.project.remove_clip_from_event("UI_Rebuild_Primary", "UI_Rebuild_Removed")
    controller.project.touch()
    controller.window.set_event_details(controller.project.events["UI_Rebuild_Primary"])
    QApplication.processEvents()

    updated_issues = controller.validator.validate(controller.project)
    updated_issue_pairs = {(issue.code, issue.target) for issue in updated_issues}
    assert updated_issue_pairs == {("REGISTERED_SOURCE_UNUSED", controller.project.name)}

    controller.preview_export_diff()
    QApplication.processEvents()
    diff_preview = controller.window.build_preview_output.toPlainText()
    assert controller.window.report_tabs.currentIndex() == 2
    assert "新增资源：1" in diff_preview
    assert "- ui/rebuild_added" in diff_preview
    assert "移除资源：1" in diff_preview
    assert "- ui/rebuild_removed" in diff_preview
    assert "变更资源：1" in diff_preview
    assert "- ui/rebuild_primary" in diff_preview

    controller.build_project()
    QApplication.processEvents()

    build_report = json.loads((export_root / "BuildReport.json").read_text(encoding="utf-8"))
    manifest = json.loads((export_root / "AudioManifest.json").read_text(encoding="utf-8"))
    audio_data = json.loads((export_root / "AudioData.json").read_text(encoding="utf-8"))

    assert build_report["EventCount"] == 1
    assert build_report["ClipCount"] == 2
    assert build_report["ErrorCount"] == 0
    assert build_report["WarningCount"] == 1

    manifest_assets = {asset["AssetKey"]: asset for asset in manifest["Assets"]}
    assert sorted(manifest_assets) == ["ui/rebuild_added", "ui/rebuild_primary"]
    assert manifest_assets["ui/rebuild_primary"]["TrimEndMs"] == 15
    assert manifest_assets["ui/rebuild_added"]["ReferencedByEvents"] == ["UI_Rebuild_Primary"]

    event_payload = audio_data["Events"]["UI_Rebuild_Primary"]
    assert [clip["AssetKey"] for clip in event_payload["Clips"]] == ["ui/rebuild_primary", "ui/rebuild_added"]
    assert event_payload["Clips"][0]["TrimEndMs"] == 15

    assert primary_asset_path.exists()
    assert not removed_asset_path.exists()
    assert added_asset_path.exists()

    export_check = check_export_bundle(export_root)
    contract_check = check_runtime_contract(export_root)
    assert export_check.passed is True
    assert contract_check.passed is True

    controller.is_dirty = False
    controller.window.close()