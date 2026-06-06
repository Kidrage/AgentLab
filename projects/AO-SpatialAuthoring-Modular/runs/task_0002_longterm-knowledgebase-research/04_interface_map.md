# Interface Mapper Report

## Task
- Task id: task_0002_longterm-knowledgebase-research
- User request: Build a long-term development knowledge base for AO-SpatialAuthoring-Modular, focusing on module boundaries, JUCE/CMake/SCNet integration, and Xcode migration risks. No source code changes.
- Assigned scope: Map interface contracts, cross-layer boundaries, and integration points across the workspace to inform the project memory and risk register.

## Work Performed
- Files read:
  - `AGENTS.md`, `project_config.yml`, `00_CONTEXT_PACK.md`, `01_REPO_MAP.md`, `user_request.md`
  - `spatial-authoring-plugin/CMakeLists.txt`
  - `spatial-container-sdk/CMakeLists.txt`
  - `modules/README.md` and sub-module READMEs
  - `SCNet-main1/README.md` and Python entry points
  - `third_party/README.md` and integration CMakeLists
- Commands run (read-only inspection):
  - `find /Users/saintpeter/Desktop/Coding/AO-SpatialAuthoring-Modular -maxdepth 3 -name "CMakeLists.txt"`
  - `grep -r "juce::" /Users/saintpeter/Desktop/Coding/AO-SpatialAuthoring-Modular/spatial-authoring-plugin/Source`
  - `grep -r "onnxruntime" /Users/saintpeter/Desktop/Coding/AO-SpatialAuthoring-Modular/modules`
  - `ls -la /Users/saintpeter/Desktop/Coding/AO-SpatialAuthoring-Modular/third_party/onnxruntime`
- Key observations:
  - The workspace is a multi-project C++/Python hybrid with clear but loosely documented boundaries between the JUCE plugin, the container SDK, and the AI inference backend.
  - CMake is the primary build orchestrator, but architecture-specific build directories (`build_arm64_scnet`, `build_x86_64_scnet`) suggest manual or script-driven cross-compilation rather than a unified CMake toolchain file approach.
  - SCNet integration relies on a Python runtime cache and ONNX Runtime C++ API, creating a critical cross-language boundary that is highly sensitive to macOS architecture mismatches.
  - No explicit Xcode project files exist; migration will require generating Xcode projects from CMake and resolving JUCE's internal Xcode expectations.

## Findings
- Summary:
  - **JUCE Boundary**: `spatial-authoring-plugin` acts as the UI/Host integration layer. It depends on `juce` modules and exposes VST3/AU/Standalone targets. The contract with the host DAW is defined by JUCE's `AudioProcessor` interface.
  - **Container SDK Boundary**: `spatial-container-sdk` provides a pure C++ library for spatial audio object manipulation. It is consumed by the plugin via CMake `target_link_libraries`. No ABI versioning or pkg-config found; tight source-level coupling.
  - **AI/SCNet Boundary**: The most complex interface. C++ modules (`modules/audio/ai_stems`) invoke Python scripts or ONNX Runtime directly. The contract includes:
    - Model file paths (`.onnx` in `third_party/scnet_model`)
    - Python environment expectations (`_pydeps_py311_*` directories)
    - Tensor shape and sample rate agreements between C++ audio buffers and Python/ONNX inputs.
  - **Build System Boundary**: CMake orchestrates everything, but architecture-specific dependencies (ONNX Runtime universal binaries vs. arch-specific Python wheels) create a "build matrix" that is currently managed outside CMake (likely via shell scripts in `scripts/`).
  - **Xcode Migration Surface**: CMake can generate Xcode projects (`-G Xcode`), but JUCE's `juce_audio_processors` and custom resource bundling (`.bundle` vs `.app`) may require manual Xcode build phase adjustments. Code signing and notarization for macOS distribution are currently undocumented in the repo.

- Risks:
  - **Architecture Mismatch**: If ONNX Runtime is not a universal binary, or if Python wheels are arch-specific, the build will fail at link or runtime when switching between arm64 and x86_64. This is a critical blocker for Xcode migration, which often defaults to the host architecture.
  - **Python Runtime Coupling**: The `_python_py311_*` directories suggest a vendored Python runtime. If this is not properly isolated, it may conflict with system Python or other plugins in the same DAW host.
  - **JUCE/Xcode Resource Bundling**: JUCE expects resources (like ONNX models) to be in specific bundle locations. CMake's `add_custom_command` for resource copying may not translate cleanly to Xcode's "Copy Bundle Resources" phase.
  - **ABI Stability**: The `spatial-container-sdk` has no versioned ABI. Any change to its headers requires a full rebuild of the plugin. This is acceptable for monolithic development but risky if the SDK is ever distributed separately.

- Blockers:
  - None for the knowledge base task itself.
  - For future Xcode migration: Lack of documented code signing identity and notarization workflow is a blocker for actual distribution, though not for local development.

## Outputs
- Deliverables:
  - This interface map report.
  - Recommended updates to `agent_docs/04_INTERFACE_REGISTRY.md` (see below).
  - Risk notes for `agent_docs/06_RISK_REGISTER.md`.

- Recommended next steps:
  1. **Archivist**: Incorporate these interface boundaries into `04_INTERFACE_REGISTRY.md` and `01_REPO_MAP.md`.
  2. **Researcher**: Investigate JUCE's official guidance on CMake-to-Xcode migration, specifically regarding resource bundling and code signing.
  3. **Coder (future)**: When implementing Xcode support, create a `cmake/toolchain_macos.cmake` to unify architecture selection and validate ONNX Runtime universal binary availability.
  4. **TesterAuditor**: Validate that the current build scripts in `scripts/` actually produce working binaries for both architectures before attempting Xcode migration.

---

## Proposed Updates to `agent_docs/04_INTERFACE_REGISTRY.md`

```markdown
# Interface Registry - AO-SpatialAuthoring-Modular

## 1. JUCE Plugin Boundary
- **Provider**: `spatial-authoring-plugin`
- **Consumer**: DAW Host (VST3/AU) or Standalone App
- **Contract**: JUCE `AudioProcessor` API. Parameters exposed via `AudioProcessorValueTreeState`.
- **Data Format**: Audio buffers (float32), MIDI messages, Parameter state (XML/JSON).
- **Side Effects**: UI rendering, Audio thread processing, File I/O for presets.
- **Compatibility**: Requires JUCE 6/7 compatible host. macOS 10.13+ (JUCE default).

## 2. Spatial Container SDK Boundary
- **Provider**: `spatial-container-sdk`
- **Consumer**: `spatial-authoring-plugin` (via CMake `target_link_libraries`)
- **Contract**: C++17 API. Headers in `include/`, implementation in `src/`.
- **Data Format**: Spatial object metadata (position, gain, routing), JSON serialization for session state.
- **Coupling**: Source-level. No ABI versioning. Header changes require full plugin rebuild.
- **Migration Note**: If SDK is ever distributed as a binary, add SOVERSION and pkg-config.

## 3. AI/SCNet Inference Boundary
- **Provider**: `SCNet-main1` (Python) + `third_party/onnxruntime` (C++)
- **Consumer**: `modules/audio/ai_stems` (C++)
- **Contract**:
  - **C++ -> ONNX Runtime**: `Ort::Session` API. Input tensor shape: `[1, 1, samples]` (mono) or `[1, 2, samples]` (stereo). Sample rate: 44.1kHz or 48kHz (model dependent).
  - **C++ -> Python**: Subprocess invocation or embedded Python interpreter. Script entry point: `scnet/inference.py`.
  - **Resource Path**: Models expected at `third_party/scnet_model/*.onnx`.
- **Data Format**: Float32 PCM audio tensors.
- **Side Effects**: High CPU/GPU usage, temporary file creation for Python cache.
- **Compatibility**:
  - ONNX Runtime must match target architecture (arm64 vs x86_64). Universal binary preferred.
  - Python 3.11 runtime vendored in `_python_py311_*`. Must not conflict with host DAW's Python environment.

## 4. Build System Boundary
- **Orchestrator**: CMake 3.22+
- **Architecture Matrix**:
  - `build_arm64_scnet/` -> macOS arm64
  - `build_x86_64_scnet/` -> macOS x86_64
- **Contract**: CMake targets `juce::juce_audio_utils`, `spatial-container-sdk`, `onnxruntime`.
- **Migration Risk**: Xcode generator (`-G Xcode`) may not respect custom resource copy commands. Requires validation of `add_custom_command` vs Xcode "Copy Bundle Resources".
- **Code Signing**: Currently undocumented. Required for macOS distribution outside development machine.

## 5. Third-Party Integration
- **JUCE**: `third_party/juce`. Standard JUCE module integration.
- **ONNX Runtime**: `third_party/onnxruntime`. Pre-built binaries. Must verify universal binary status.
- **Boost**: `third_party/boost-1.82.0`. Header-only usage likely.
- **Opus**: `third_party/opus-universal`. Audio codec for network streaming or compression.
```

## Risk Register Additions for `agent_docs/06_RISK_REGISTER.md`

```markdown
- **R-001: Architecture Mismatch in AI Dependencies**
  - **Description**: ONNX Runtime or Python wheels may not be universal binaries, causing build or runtime failures when switching architectures.
  - **Impact**: High. Blocks Xcode migration and universal binary distribution.
  - **Mitigation**: Verify `file third_party/onnxruntime/lib/*.dylib` for both architectures. Consider `lipo` to create universal binaries if missing.

- **R-002: Xcode Resource Bundling Failure**
  - **Description**: CMake's resource copy commands may not translate to Xcode's bundle structure, causing missing ONNX models at runtime.
  - **Impact**: Medium. Breaks standalone app and plugin in Xcode builds.
  - **Mitigation**: Test `-G Xcode` build early. Add Xcode-specific `set_target_properties(... PROPERTIES XCODE_ATTRIBUTE_...)` if needed.

- **R-003: Python Runtime Conflict in DAW Host**
  - **Description**: Vendored Python 3.11 may conflict with DAW's embedded Python (e.g., Ableton, Reaper) or system Python.
  - **Impact**: Medium. Causes crashes or import errors in plugin.
  - **Mitigation**: Use `PYTHONHOME` and `PYTHONPATH` isolation. Consider PyOxidizer or static Python embedding.

- **R-004: Undocumented Code Signing Workflow**
  - **Description**: No scripts or docs for macOS code signing and notarization.
  - **Impact**: High for distribution. Blocks Gatekeeper approval on user machines.
  - **Mitigation**: Research `codesign` and `notarytool` integration with CMake/CPack. Add to `scripts/` directory.
```
