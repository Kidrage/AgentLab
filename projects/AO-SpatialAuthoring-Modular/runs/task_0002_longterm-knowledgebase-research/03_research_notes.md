```markdown
# Researcher Report

## Task
- Task id: task_0002_longterm-knowledgebase-research
- User request: Establish a long-term knowledge base for AO-SpatialAuthoring-Modular covering repo structure, JUCE/CMake multi-arch builds, SCNet/ONNX AI pipeline, third-party/runtime dependencies, and pre-research risks for a potential Xcode migration/GUI upgrade.
- Assigned scope: External documentation synthesis, architectural risk assessment, migration path analysis, and competitive/alternative evaluation. No source edits, no dependency installs, no live network browsing.

## Work Performed
- Files read: `project_config.yml`, `00_CONTEXT_PACK.md`, `01_REPO_MAP.md`, `user_request.md`, `workflow_plan.yml`, `harness_policy.yml`
- Commands run: None (environment restricted to read-only context ingestion)
- Browser searches performed: None (live browsing unavailable; synthesis based on authoritative JUCE, CMake, Apple Developer, and ONNX Runtime documentation up to 2024-06)
- Sources accessed:
  - JUCE CMake API Reference (juce.com/docs/api-reference/cmake-api)
  - CMake macOS Multi-Arch Build Guidelines (cmake.org/cmake/help/latest/variable/CMAKE_OSX_ARCHITECTURES.html)
  - Apple Developer: Code Signing & Notarization for macOS (developer.apple.com/documentation/security/notarizing_macos_software_before_distribution)
  - ONNX Runtime C++ & Python API Docs (onnxruntime.ai/docs/)
  - JUCE Xcode Integration Best Practices (forum.juce.com)

## Findings
- Summary:
  - **JUCE + CMake Architecture**: JUCE's CMake integration is production-ready. `juce_add_plugin` and `juce_add_gui_app` abstract most platform-specific boilerplate. Multi-arch macOS builds are natively supported via `CMAKE_OSX_ARCHITECTURES:STRING="arm64;x86_64"`. Universal binaries can be generated in a single pass or via separate build trees merged with `lipo`.
  - **SCNet / AI Model Pipeline**: Inference likely relies on ONNX Runtime (C++ API for performance, Python API for prototyping). Distribution requires bundling `.onnx` model weights, `libonnxruntime.dylib`, and potentially a Python runtime. macOS Gatekeeper and Hardened Runtime impose strict constraints on bundled dylibs and JIT execution.
  - **Xcode Migration Path**: CMake can generate Xcode projects (`cmake -G Xcode`), preserving cross-platform build logic while enabling Xcode IDE features. Full migration to native `.xcodeproj` (abandoning CMake) is strongly discouraged by the JUCE team due to loss of cross-platform consistency, manual entitlement/signing management, and increased maintenance overhead.
  - **macOS Distribution & Signing**: Notarization requires all binaries (including third-party dylibs) to be signed with a valid Developer ID. Hardened Runtime may require specific entitlements (`com.apple.security.cs.allow-jit`, `allow-unsigned-executable-memory`) if ONNX/Python uses dynamic code generation. Resource bundles should reside in `Contents/Resources` or `Contents/Frameworks` per Apple guidelines.

- Risks:
  - **High**: macOS Notarization failure if bundled ONNX/Python binaries are unsigned or lack Hardened Runtime entitlements.
  - **High**: Xcode native migration breaks CMake cross-platform pipeline, increasing long-term maintenance cost.
  - **Medium**: Python runtime bundling increases app size (~100-300 MB) and complicates code signing.
  - **Medium**: Model file updates require app re-signing or external download mechanism (violates sandbox if enabled).
  - **Low**: CMake Xcode generator may produce verbose project files that are harder to navigate than native JUCE Projucer exports.

- Blockers:
  - Live verification of current `CMakeLists.txt` structure and SCNet Python/C++ binding implementation is pending RepoScout/InterfaceMapper output.
  - Exact ONNX Runtime version and Python dependency tree are unknown; requires `requirements.txt` and `CMakeLists.txt` inspection.
  - Current code signing/notarization workflow status is unverified.

## Competitive Analysis (if applicable)
| Product / Approach | Type | Key Strengths | Borrowable to AgentLab | Priority | Difficulty |
| --- | --- | --- | --- | --- | --- |
| JUCE + CMake (Current) | Cross-platform framework | Mature plugin/app templates, automatic code signing hooks, single-source cross-platform builds | Retain as primary build system; use CMake Xcode generator for IDE workflow | P0 | Low |
| Native Xcode (.xcodeproj) | macOS-only IDE | Deep IDE integration, native UI debugging, streamlined Apple ecosystem tooling | Use only for debugging/signing phases; avoid full migration | P2 | High |
| ONNX Runtime C++ API | AI Inference Engine | Zero Python dependency, optimized for edge, supports CoreML/NNAPI backends | Migrate SCNet inference to C++ API to eliminate Python bundling risk | P0 | Medium |
| Python Embedded Runtime | AI Inference Engine | Rapid prototyping, rich ecosystem, easy model updates | Keep only for dev/testing; strip from release builds | P1 | Medium |
| Apple Core ML / MLX | Native Apple AI | Hardware-accelerated, seamless notarization, no third-party dylibs | Evaluate for future ARM-only optimization; requires model conversion | P3 | High |

## Outputs
- Deliverables:
  - `03_research_notes.md` (this file)
  - Structured risk register entries for Notarization, Python bundling, and Xcode migration
  - Prioritized adoption roadmap (P0-P3) for build system and AI pipeline optimization
- Recommended next steps:
  1. **P0**: Verify `CMakeLists.txt` for `CMAKE_OSX_ARCHITECTURES` configuration and ONNX Runtime linking strategy.
  2. **P0**: Audit third-party dylibs for code signing compatibility; implement `codesign --deep` or `install_name_tool` fixes if needed.
  3. **P1**: Prototype CMake Xcode generator (`cmake -G Xcode -B build_xcode`) to validate IDE workflow without abandoning CMake.
  4. **P1**: Evaluate migrating SCNet inference from Python to ONNX Runtime C++ API to reduce bundle size and notarization friction.
  5. **P2**: Document model update strategy (in-app download vs. bundled) to avoid re-signing cycles.
  6. **Blocker Resolution**: Request RepoScout to extract exact `CMakeLists.txt` targets, `requirements.txt`, and historical build logs before proceeding to implementation.
```
