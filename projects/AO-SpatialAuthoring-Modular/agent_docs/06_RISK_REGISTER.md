# Risk Register

| Risk | Severity | Evidence | Mitigation |
|---|---|---|---|
| Broad workspace scope | Medium | 10 top-level projects under one folder | Start future edits from a named child project. |
| Generated/build artifacts can distort memory | Medium | Build-like directories were ignored during scan | Keep source maps separate from build output. |
| Large generated trees | Low | `build_arm64_scnet`, `build_x86_64_scnet`, `SCNet-main1` | Inspect only when debugging build/package output. |
| Secret handling | High | `.env` and common local caches are ignored by scanner | Never copy credential files into AgentLab memory. |

## Long-Term Risk Addendum

Backend: `external_ide_manual` memory rescue.

| Risk | Severity | Evidence | Mitigation / Gate |
|---|---|---|---|
| AgentLab execute did not persist durable memory | Medium | `task_0002` completed, but `agent_docs` stayed baseline and Coder report lacked command evidence. | Record rescue as `external_ide_manual`; improve AgentLab Archivist persistence later. |
| Universal macOS build drift | High | CMake and scripts manage `x86_64;arm64`; per-arch scripts intentionally disable universal enforcement. | Validate `lipo -info` for app binary and bundled dylibs before release. |
| Deployment target inconsistency | Medium | Top-level default is `11.0`; handoff says release contract `12.0`; per-arch script uses `12.0`; universal script uses `11.0`. | Decide canonical deployment target before Xcode migration. |
| Legacy Python SCNet distribution complexity | High | Package scripts stage `_python_py311_*` and `_pydeps_py311_*`; service can launch `ChildProcess`. | Prefer embedded ONNX/native path for release or validate arch-specific imports/signing. |
| ONNX Runtime signing/install-name failure | High | Plugin CMake copies `libonnxruntime` to `Contents/Frameworks`, changes install name, and signs. | Gate with `otool -L`, `codesign --verify --deep --strict`, and universal dylib slice checks. |
| Native SCNet engine correctness | High | Native engine implements operators manually and loads extracted weights. | Require golden-output tests vs Python/ONNX reference before release. |
| UI redesign breaks runtime contracts | High | Handoff says UI must not own SCNet, BDS export, container writing, or parameter IDs. | Freeze parameter IDs and service APIs before GUI work. |
| Full native Xcode migration creates dual source of truth | High | CMake owns targets, resources, arch, BDS, SCNet options. | Start with `cmake -G Xcode`; avoid hand-maintained `.xcodeproj` until parity is proven. |
| Local path leakage into distributable | High | Handoff forbids Homebrew, Anaconda, `/Users/...` runtime references. | Gate with `otool -L`, install-name checks, codesign, and clean-machine launch smoke test. |
