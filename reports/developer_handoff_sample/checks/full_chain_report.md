# AudioForge Full-Chain Report

- Generated At: 2026-04-23T09:05:26Z
- Overall: PASS
- Workspace: C:\Users\EDY\wwise
- Export Dir: C:\Users\EDY\wwise\reports\developer_handoff_sample\export
- Unity Validation Dir: C:\Users\EDY\wwise\unity_validation

## Summary

- Total Checks: 4
- Passed: 4
- Failed: 0

## Checks

### pytest - PASS

- exit_code=0
- stdout_tail:
- ============================= test session starts =============================
- platform win32 -- Python 3.14.3, pytest-9.0.3, pluggy-1.6.0
- rootdir: C:\Users\EDY\wwise
- configfile: pyproject.toml
- collected 12 items
- tests\unit\test_developer_handoff_sample.py .                            [  8%]
- tests\unit\test_exporter.py ..                                           [ 25%]
- tests\unit\test_full_chain_check.py ..                                   [ 41%]
- tests\unit\test_preview_bus_mixer.py ..                                  [ 58%]
- tests\unit\test_project_serializer.py .                                  [ 66%]
- tests\unit\test_recovery_service.py .                                    [ 75%]
- tests\unit\test_validator.py ...                                         [100%]
- ============================= 12 passed in 1.21s ==============================

### export_bundle - PASS

- export_dir=C:\Users\EDY\wwise\reports\developer_handoff_sample\export
- all_required_export_files_present
- asset_entries=29

### runtime_contract - PASS

- schema_version=1
- runtime_audio_format=wav
- events=11
- clips=29
- buses=3
- manifest_assets=29

### unity_validation_package - PASS

- unity_validation_dir=C:\Users\EDY\wwise\unity_validation
- runtime_files_checked=8
