# Xcode / GUI Migration Research - AO-SpatialAuthoring-Modular

Backend: `external_ide_manual` memory rescue after AgentLab execute completed but did not persist durable `agent_docs` content.

## Recommendation

Use Xcode as an IDE/debug/signing workflow through CMake generation first:

```bash
cmake -S . -B build_xcode -G Xcode \
  -DCMAKE_OSX_ARCHITECTURES="x86_64;arm64" \
  -DAO_BUILD_PLUGIN=ON \
  -DAO_ENABLE_BDS=ON \
  -DAO_SCNET_EMBEDDED_ENGINE=ON
```

Do not immediately migrate to a manually maintained native `.xcodeproj`.

## Why CMake-Generated Xcode First

The current CMake system owns JUCE target creation, product identity for `Bubbleflow Dynamic Space`, universal architecture enforcement, BDS/vendored dependency configuration, SCNet embedded/native/legacy options, bundle resource copying, ONNX Runtime dylib copy/install-name/codesign steps, and verification target `ao_verify_macos_compat`.

A hand-maintained native Xcode project would duplicate this logic and likely drift.

## GUI Upgrade Pre-Flight

Before redesigning GUI:

1. Freeze parameter IDs and automation-facing state.
2. Define stable processor/session/service methods for UI actions.
3. Document async operations and ensure long-running work does not run in UI callbacks.
4. Keep SCNet execution and BDS export behind service boundaries.
5. Add UI smoke/regression checklist for app launch, source audio load, stems, export/container path, and parameter persistence.

## Xcode-Specific Risks

| Risk | Why it matters | Mitigation |
|---|---|---|
| Generated Xcode project is verbose | JUCE/CMake targets can be harder to browse than hand-made projects. | Use source groups/CMake organization; keep CMake canonical. |
| Multi-arch settings drift | Xcode UI can hide arch/deployment settings. | Inspect generated build settings and preserve `CMAKE_OSX_ARCHITECTURES`. |
| Resource bundling drift | SCNet ONNX/config and dylibs are copied by CMake post-build commands. | Validate bundle resources after Xcode builds. |
| Signing/notarization complexity | ONNX/Python dylibs require signing and hardened runtime scrutiny. | Keep codesign/notarization scripts explicit. |
| UI refactor impacts runtime | GUI changes can accidentally touch processor/stems/export state. | Keep UI as presentation layer and add boundary checklist before merge. |

## Suggested Migration Sequence

1. Create `build_xcode` with CMake generator and no source changes.
2. Open generated `.xcodeproj`; confirm app target builds.
3. Compare output bundle to Ninja build using `lipo`, `otool`, resource checks, and codesign.
4. Add source grouping improvements if navigation is poor.
5. Start GUI redesign behind existing processor/session APIs.
6. Only consider native `.xcodeproj` if CMake-generated Xcode cannot satisfy workflow needs, and then plan a separate migration with full build/signing parity tests.

## Research Caveat

The AgentLab Researcher report did not perform live browsing in this environment. This note combines local repository evidence with known JUCE/CMake/Apple/ONNX practices. Verify current Apple Developer, JUCE, CMake, and ONNX Runtime docs before production migration.
