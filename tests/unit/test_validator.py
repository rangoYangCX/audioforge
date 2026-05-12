from __future__ import annotations

from pathlib import Path

from audioforge.app.models.audio_project import BusConfig, ClipModel, EventModel, MASTER_BUS_NAME
from audioforge.app.services.validator import ProjectValidator

from tests.helpers import build_sample_project


def test_validator_reports_bus_route_cycle(tmp_path: Path) -> None:
    project, _ = build_sample_project(tmp_path)
    project.settings.bus_configs = [
        BusConfig(name=MASTER_BUS_NAME),
        BusConfig(name="SFX", parent_bus="UI"),
        BusConfig(name="UI", parent_bus="SFX"),
        BusConfig(name="BGM"),
    ]

    issues = ProjectValidator().validate(project)
    codes = {issue.code for issue in issues}

    assert "BUS_ROUTE_CYCLE" in codes


def test_validator_warns_when_reference_gain_exceeds_unity(tmp_path: Path) -> None:
    project, _ = build_sample_project(tmp_path, bus_volume_db=3.0, event_volume_db=1.0)

    issues = ProjectValidator().validate(project)
    codes = {issue.code for issue in issues}

    assert "BUS_GAIN_ABOVE_UNITY_REFERENCE" in codes
    assert "REFERENCE_GAIN_ABOVE_UNITY" in codes


def test_validator_allows_master_default_route(tmp_path: Path) -> None:
    project, _ = build_sample_project(tmp_path)

    issues = ProjectValidator().validate(project)
    error_codes = {issue.code for issue in issues if issue.severity == "Error"}

    assert "BUS_PARENT_SELF" not in error_codes


def test_validator_warns_when_same_source_is_exported_with_multiple_asset_keys(tmp_path: Path) -> None:
    project, wav_path = build_sample_project(tmp_path)
    root_event = project.events["UiClick"]
    root_event.clips.append(
        ClipModel(
            id="UiClickAlt",
            source_path=str(wav_path),
            export_path="ui/click_variant",
            asset_key="ui/click_variant",
            weight=1,
        )
    )
    project.touch()

    issues = ProjectValidator().validate(project)
    matching = [issue for issue in issues if issue.code == "SOURCE_REUSED_WITH_MULTIPLE_ASSET_KEYS"]

    assert len(matching) == 1
    assert matching[0].severity == "Warning"
    assert "ui/click_primary" in matching[0].message
    assert "ui/click_variant" in matching[0].message


def test_validator_reports_export_path_conflict_before_build(tmp_path: Path) -> None:
    project, wav_path = build_sample_project(tmp_path)
    root_event = project.events["UiClick"]
    root_event.clips.append(
        ClipModel(
            id="UiClickConflict",
            source_path=str(wav_path),
            export_path="ui/click_primary.wav",
            asset_key="ui/click_primary.wav",
            weight=1,
        )
    )
    project.touch()

    issues = ProjectValidator().validate(project)
    matching = [issue for issue in issues if issue.code == "ASSET_EXPORT_PATH_CONFLICT"]

    assert len(matching) == 1
    assert matching[0].severity == "Error"
    assert "ui/click_primary.wav" in matching[0].message
    assert "ui/click_primary" in matching[0].message


def test_validator_warns_for_placeholder_event_id_and_nonstandard_asset_key(tmp_path: Path) -> None:
    project, wav_path = build_sample_project(tmp_path)
    root_folder_id = project.root_folder_ids[0]
    project.remove_event("UiClick")
    project.add_event(
        root_folder_id,
        EventModel(
            id="New_Event",
            display_name="New Event",
            bus="UI",
            clips=[
                ClipModel(
                    id="ClipOne",
                    source_path=str(wav_path),
                    export_path="UI/Bad Asset",
                    asset_key="UI/Bad Asset",
                    weight=1,
                )
            ],
        ),
    )

    issues = ProjectValidator().validate(project)
    codes = {issue.code for issue in issues}

    assert "EVENT_ID_PLACEHOLDER_NAME" in codes
    assert "ASSET_KEY_STYLE_NON_STANDARD" in codes


def test_validator_suggests_bgm_bus_for_music_like_event_names(tmp_path: Path) -> None:
    project, wav_path = build_sample_project(tmp_path)
    root_folder_id = project.root_folder_ids[0]
    project.add_event(
        root_folder_id,
        EventModel(
            id="MusicThemeLoop",
            display_name="Music Theme Loop",
            bus="SFX",
            clips=[
                ClipModel(
                    id="music_theme_loop",
                    source_path=str(wav_path),
                    export_path="music/theme_loop",
                    asset_key="music/theme_loop",
                    weight=1,
                )
            ],
        ),
    )

    issues = ProjectValidator().validate(project)
    codes = {issue.code for issue in issues}

    assert "BUS_CLASSIFICATION_SUGGEST_BGM" in codes


def test_validator_warns_for_registered_but_unused_source_assets(tmp_path: Path) -> None:
    project, _ = build_sample_project(tmp_path)
    unused_source = tmp_path / "fixtures" / "unused.wav"
    unused_source.write_bytes(b"RIFF")
    project.register_source_asset(str(unused_source))

    issues = ProjectValidator().validate(project)
    matching = [issue for issue in issues if issue.code == "REGISTERED_SOURCE_UNUSED"]

    assert len(matching) == 1
    assert str(unused_source) in matching[0].message


def test_validator_warns_when_event_ids_only_differ_by_case(tmp_path: Path) -> None:
    project, wav_path = build_sample_project(tmp_path)
    root_folder_id = project.root_folder_ids[0]
    project.add_event(
        root_folder_id,
        EventModel(
            id="uiclick",
            display_name="ui click lowercase",
            bus="UI",
            clips=[
                ClipModel(
                    id="uiclick_clip",
                    source_path=str(wav_path),
                    export_path="ui/click_lowercase",
                    asset_key="ui/click_lowercase",
                    weight=1,
                )
            ],
        ),
    )

    issues = ProjectValidator().validate(project)
    matching = [issue for issue in issues if issue.code == "EVENT_ID_CASE_VARIANT_CONFLICT"]

    assert len(matching) == 2
    assert {issue.target for issue in matching} == {"UiClick", "uiclick"}


def test_validator_warns_for_inconsistent_asset_key_path_style(tmp_path: Path) -> None:
    project, wav_path = build_sample_project(tmp_path)
    root_event = project.events["UiClick"]
    root_event.clips[0].asset_key = "ui\\bad//path/"
    root_event.clips[0].export_path = "ui\\bad//path/"
    project.touch()

    issues = ProjectValidator().validate(project)
    matching = [issue for issue in issues if issue.code == "ASSET_KEY_PATH_STYLE_INCONSISTENT"]

    assert len(matching) == 1
    assert "backslashes" in matching[0].message
    assert "repeated '/'" in matching[0].message


def test_validator_reports_events_with_no_enabled_clips(tmp_path: Path) -> None:
    project, _ = build_sample_project(tmp_path)
    event = project.events["UiClick"]
    event.clips[0].enabled = False
    event.clips[0].active = False
    project.touch()

    issues = ProjectValidator().validate(project)
    codes = {issue.code for issue in issues}

    assert "EVENT_NO_ENABLED_CLIPS" in codes