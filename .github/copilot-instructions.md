# AudioForge Project Guidelines

## Scope
These instructions apply to all work in this repository.

## Build And Test
- Prefer the workspace virtual environment when running Python commands.
- For Qt-related tests, run with `QT_QPA_PLATFORM=offscreen`.
- After the first substantive code edit, immediately run the narrowest executable validation that can falsify the change.
- Prefer focused pytest commands for the touched slice before broader suites.
- Do not treat `git diff` as validation when a runnable test or type/error check exists.

## Test Rules
- Any bug fix must include or update a regression test unless the behavior can only be verified through real UI/manual interaction and the repository has no suitable automated test surface.
- Any change to branching logic, state transitions, exception handling, data conversion, or serialization must add or update focused tests.
- Any refactor with meaningful regression risk must be followed by behavior-scoped validation, even if the intent is "no behavior change".
- Prefer the smallest nearby test that asserts the behavior directly; do not default to broad end-to-end coverage when a narrow test can protect the change.

## Documentation Rules
- Update documentation whenever a change affects architecture boundaries, workflow responsibilities, command entry points, validation flow, release flow, or user/developer operating expectations.
- Update documentation whenever existing docs would become misleading after the change.
- If a change affects harness coverage, harness entry points, or harness expectations, also update:
  - `docs/internal/architecture/audioforge_Harness环境与迭代基线.md`
  - `docs/internal/architecture/audioforge_Harness准入规则与场景矩阵.md`

## Harness Rules
- Do not add every change to harness.
- Add or update harness only when all of the following are true:
  - the change spans at least two modules or layers
  - failure would break a real user-critical flow
  - targeted pytest coverage can still miss the full chain failure
- Typical harness-worthy areas include serialization, export, recovery, experiment workspace flows, variant activation, delta preview, and delta export.
- Keep UI detail assertions out of harness; those belong in targeted pytest or dedicated GUI coverage.
- If a harness scenario is added or changed, also update:
  - `audioforge/harness/scenarios.py`
  - `tests/unit/test_harness_environment.py`
  - the harness docs listed above

## Editing Rules
- Fix root causes instead of hiding failures with broad exception handling or surface-level guards.
- For large fragile files such as `audioforge/app/controllers/main_controller.py`, edit one method-sized slice at a time and validate immediately after each risky patch.
- Do not expand scope to unrelated defects unless they block the requested task.
- If you create temporary artifacts to probe or reproduce behavior, clean them up before finishing.
- If runtime behavior depends on a restarted app process, explicitly tell the user.

## Project Conventions
- Treat code changes, tests, and documentation as one delivery unit when behavior, workflow, or validation expectations change.
- Prefer existing repository test surfaces and helpers over introducing parallel validation mechanisms.
- For harness usage and scope, follow:
  - `docs/internal/architecture/audioforge_Harness环境与迭代基线.md`
  - `docs/internal/architecture/audioforge_Harness准入规则与场景矩阵.md`