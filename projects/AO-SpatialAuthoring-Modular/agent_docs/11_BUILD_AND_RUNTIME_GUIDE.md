# Build and AI Runtime Guide - AO-SpatialAuthoring-Modular

Backend: `external_ide_manual` memory rescue after AgentLab execute completed but did not persist durable `agent_docs` content.

## Canonical Build Commands

Universal distribution build:

```bash
scripts/build_universal_scnet.sh --clean
```

This script packages Python runtimes and SCNet dependencies for both `x86_64` and `arm64`, stages a SCNet package, configures CMake/Ninja with `CMAKE_OSX_ARCHITECTURES="x86_64;arm64"`, enables BDS, builds, runs `ctest`, runs `ao_verify_macos_compat`, checks app/model artifacts, clears quarantine, and ad-hoc signs the app.

Expected output:

```text
build_universal_scnet/spatial-authoring-plugin/AOSpatialAuthoringPlugin_artefacts/Release/Standalone/Bubbleflow Dynamic Space.app
```

Per-architecture builds:

```bash
scripts/build_scnet_app.sh --arch=arm64 --clean
scripts/build_scnet_app.sh --arch=x86_64 --clean
```

Per-arch builds use `CMAKE_OSX_ARCHITECTURES=<arch>` and `AO_ENFORCE_UNIVERSAL_MACOS=OFF`.

## Top-Level CMake Contract

Root `CMakeLists.txt` requires CMake `3.22`, C++17, and defaults Apple builds to `x86_64;arm64` through `AO_MACOS_ARCHS_DEFAULT`.

- `AO_ENFORCE_UNIVERSAL_MACOS=ON` fails configure if either `x86_64` or `arm64` is absent.
- `spatial-container-sdk` is added before the JUCE app/plugin.
- `AO_ENABLE_BDS=ON` enables vendored BDS, Opus, and Boost integration.
- `AO_BUILD_PLUGIN=ON` adds vendored JUCE, `modules/stems`, and `spatial-authoring-plugin`.
- Key SCNet options: `AO_SCNET_EMBEDDED_ENGINE`, `AO_SCNET_USE_NATIVE`, `AO_SCNET_MODEL_ROOT`.

## Runtime / Distribution Contract

For embedded ONNX Runtime release bundles, verify these paths:

- `Contents/MacOS/Bubbleflow Dynamic Space`
- `Contents/Resources/scnet_outstft_core_t432.onnx`
- `Contents/Resources/scnet_config.yaml`
- `Contents/Frameworks/libonnxruntime.1.20.1.dylib`
- `Contents/Frameworks/libonnxruntime.dylib`

Release validation commands: `lipo -info`, `otool -L`, and `codesign --verify --deep --strict --verbose=2`.

`otool -L` must not contain Homebrew, Anaconda, `/Users/...`, or source-tree runtime dependencies for a distributable build.

## SCNet Runtime Paths

Legacy Python path: `StemSeparationService` locates `AO_STEM_MODEL_ROOT`, bundled/sibling `SCNet-main1`, or package roots near the app. It chooses `_python_py311_arm64/bin/python3.11` or `_python_py311_x86_64/bin/python3.11` and invokes `inference_onnx_outstft.py`.

Embedded ONNX Runtime path: `ScnetEngine` performs resample -> 11-second chunks -> STFT -> ONNX Runtime inference -> iSTFT -> WAV stems.

Native fallback path: `ScnetNativeEngine` loads raw weights and graph descriptors, implements operators manually, and avoids ONNX Runtime. It requires golden-output tests against Python/ONNX reference outputs.

## Required Validation Gates

- CMake configure succeeds for chosen release options.
- `ctest` passes.
- `ao_verify_macos_compat` passes.
- App and runtime dylibs have `x86_64 arm64` slices.
- Bundle contains required SCNet resources.
- Runtime paths are bundle-relative.
- `codesign --verify --deep --strict` passes.
- SCNet smoke test produces or reuses `vocals.wav`, `drums.wav`, `bass.wav`, `other.wav`.
