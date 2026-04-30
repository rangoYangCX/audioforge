# AudioForge Full-Chain Report

- Generated At: 2026-04-30T04:11:33Z
- Overall: PASS
- Workspace: C:\Users\EDY\wwise
- Export Dir: C:\Users\EDY\wwise\reports\internal_release_smoke\export
- Unity Package Dir: C:\Users\EDY\wwise\unity_package
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
- collected 62 items
- tests\unit\test_developer_handoff_sample.py .                            [  1%]
- tests\unit\test_exporter.py ....                                         [  8%]
- tests\unit\test_full_chain_check.py ..                                   [ 11%]
- tests\unit\test_main_controller_full_flow.py ......                      [ 20%]
- tests\unit\test_main_controller_layout.py .............................. [ 69%]
- .....                                                                    [ 77%]
- tests\unit\test_preview_bus_mixer.py ..                                  [ 80%]
- tests\unit\test_project_serializer.py .                                  [ 82%]
- tests\unit\test_recovery_service.py .                                    [ 83%]
- tests\unit\test_validator.py ..........                                  [100%]
- ============================= 62 passed in 11.75s =============================

### export_bundle - PASS

- export_dir=C:\Users\EDY\wwise\reports\internal_release_smoke\export
- all_required_export_files_present
- asset_entries=12

### runtime_contract - PASS

- schema_version=1
- runtime_audio_format=wav
- events=12
- clips=12
- buses=3
- manifest_assets=12

### unity_integration_package - PASS

- unity_package_dir=C:\Users\EDY\wwise\unity_package
- unity_validation_dir=C:\Users\EDY\wwise\unity_validation
- runtime_files_checked=13
