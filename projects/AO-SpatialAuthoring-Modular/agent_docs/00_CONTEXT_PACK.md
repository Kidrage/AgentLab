# Context Pack - AO-SpatialAuthoring-Modular

Source workspace: `/Users/saintpeter/Desktop/Coding/AO-SpatialAuthoring-Modular`

Baseline task: `task_0001_baseline-memory`

AgentLab memory role: this project stores high-level local knowledge for the whole Coding workspace. Use it to choose the correct child project before opening or editing files.

## Scan Summary

- Scan mode: `deterministic_metadata_only`
- Top-level projects: 10
- Git repos: 0 (0 dirty)
- Files counted: 95924
- Directories counted: 6669
- Source footprint counted: 5.0 GB

## Top-Level Projects

| Project | Type | Git | Files | Size | Key Signal |
|---|---|---:|---:|---:|---|
| `build_arm64_scnet` | mixed/local project | no | 20726 | 1.2 GB | scnet_package_arm64/README.md, scnet_package_arm64/_pydeps_py311_arm64/torchgen/packaged/autograd/README.md |
| `build_x86_64_scnet` | mixed/local project | no | 20750 | 1.8 GB | scnet_package_x86_64/README.md, scnet_package_x86_64/_pydeps_py311_x86_64/torchgen/packaged/autograd/README.md |
| `cmake` | mixed/local project | no | 1 | 1.6 KB | mixed |
| `docs` | documentation/artifact collection | no | 4 | 55.9 KB | mixed |
| `modules` | documentation/artifact collection | no | 25 | 123.2 KB | README.md, app/README.md |
| `SCNet-main1` | Python project | no | 35610 | 1.6 GB | README.md, _pydeps_py311_arm64/torchgen/packaged/autograd/README.md |
| `scripts` | mixed/local project | no | 6 | 21.4 KB | mixed |
| `spatial-authoring-plugin` | CMake C++ project | no | 19 | 302.0 KB | CMake |
| `spatial-container-sdk` | CMake C++ project | no | 9 | 57.2 KB | CMake |
| `third_party` | mixed/local project | no | 18766 | 452.5 MB | JUCE |

## Operating Rule

Treat this workspace as read-only unless a later task names a specific child project and asks for edits.

## Long-Term Knowledge Base Addendum

- Dedicated memory project exists at `projects/AO-SpatialAuthoring-Modular/`.
- Full-route AgentLab execute task: `task_0002_longterm-knowledgebase-research`.
- Manual rescue backend: `external_ide_manual`, because execute completed but durable `agent_docs` were not updated beyond baseline scanner output.
- Current product focus: JUCE standalone app `Bubbleflow Dynamic Space.app`.
- Canonical build source remains CMake; introduce Xcode first via `cmake -G Xcode`, not by hand-maintaining a separate `.xcodeproj`.
- GUI upgrades must remain behind stable processor/session/service contracts and must not directly alter SCNet execution, BDS export, container writing, or parameter IDs.
- For release builds, validate universal `x86_64;arm64` slices, bundle resources, runtime paths, codesign, and SCNet outputs.

See also: `11_BUILD_AND_RUNTIME_GUIDE.md` and `12_XCODE_GUI_MIGRATION_RESEARCH.md`.
