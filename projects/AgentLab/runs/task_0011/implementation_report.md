# Implementation Report

## Result

Completed the SCNet rollback path for `/Users/saintpeter/Desktop/Coding/AO-SpatialAuthoring-Modular`.

The rebuilt standalone app now uses the legacy external SCNet Python package flow instead of the embedded ONNX Runtime/native engine path. The distributable app bundle includes `SCNet-main1` under `Contents/Resources`, so the model root can be discovered automatically without requiring the user to set `AO_STEM_MODEL_ROOT`.

Built app:

`/Users/saintpeter/Desktop/Coding/AO-SpatialAuthoring-Modular/build_universal_scnet/spatial-authoring-plugin/AOSpatialAuthoringPlugin_artefacts/Release/Standalone/Bubbleflow Dynamic Space.app`

## Source Changes

- `spatial-authoring-plugin/Source/Stems/StemSeparationService.cpp`
  - Added app-bundled resource lookup for `SCNet-main1`.
  - Kept environment override support for `AO_STEM_MODEL_ROOT`.
  - Scoped embedded-engine logging code behind `AO_SCNET_EMBEDDED_ENGINE`.

- `spatial-authoring-plugin/CMakeLists.txt`
  - Added non-embedded standalone app post-build copy of `SCNet-main1` into app resources.
  - Preserved the existing embedded engine option, but the release build script now disables it.

- `scripts/build_universal_scnet.sh`
  - Switched the build configuration to `-DAO_SCNET_EMBEDDED_ENGINE=OFF`.
  - Uses `SCNet-main1` as `AO_SCNET_MODEL_ROOT`.
  - Verifies bundled SCNet Python script, ONNX model file, and YAML config.
  - Codesigns the completed app bundle ad hoc so macOS verification passes.

## Notes

The model package is bundled. The Python runtime and Python dependencies remain part of the legacy external SCNet execution path unless a separate packaged Python environment is added later.

## Apple Silicon Launch Fix Follow-Up

After Apple Silicon testing reported that the app could not open, the build was updated again:

- macOS deployment target changed from `12.0` to `11.0`.
- `LSMinimumSystemVersion=11.0` added to the app Info.plist.
- The bundled app now clears extended attributes with `xattr -cr` after copying `SCNet-main1` and before signing.
- This specifically removes inherited `com.apple.quarantine` metadata from the SCNet package files before distribution signing.
