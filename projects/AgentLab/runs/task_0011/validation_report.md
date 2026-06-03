# Validation Report

## Commands Run

- `/Users/saintpeter/Desktop/Coding/AO-SpatialAuthoring-Modular/scripts/build_universal_scnet.sh --clean`
- `/Users/saintpeter/Desktop/Coding/AO-SpatialAuthoring-Modular/scripts/build_universal_scnet.sh`
- `otool -L` on the built standalone app binary
- `find` for bundled SCNet required files
- `du -sh` on the app bundle and bundled `SCNet-main1`

## Passed

- CMake configuration reports `SCNet embedded engine: DISABLED`.
- CTest passed: `2/2` tests passed.
- macOS compatibility verification passed.
- `lipo` verification shows the standalone app binary contains `x86_64 arm64`.
- `codesign --verify --deep --strict` passed after ad hoc signing.
- `otool -L` shows no `onnxruntime` linkage in the app binary.
- Required bundled model files are present:
  - `Contents/Resources/SCNet-main1/scnet/inference_onnx_outstft.py`
  - `Contents/Resources/SCNet-main1/scnet/scnet_outstft_core_t432.onnx`
  - `Contents/Resources/SCNet-main1/conf/config.yaml`

## Sizes

- App bundle: `164M`
- Bundled `SCNet-main1`: `150M`

## Residual Risk

The build emitted linker warnings that the vendored `third_party/opus-universal/lib/libopus.a` objects were built for macOS 12.7 while the app links with deployment target 12.0. The app still built and validation passed, but this should be revisited if strict macOS 12.0 compatibility is required.

## Apple Silicon Launch Follow-Up Validation

- Rebuilt with `CMAKE_OSX_DEPLOYMENT_TARGET=11.0`.
- Verified arm64 load command: `LC_BUILD_VERSION minos 11.0`.
- Verified Info.plist: `LSMinimumSystemVersion=11.0`.
- Verified `xattr -lr` on the app bundle returns no extended attributes.
- Verified `codesign --verify --deep --strict --verbose=4` passes.

Residual risk remains that `third_party/opus-universal/lib/libopus.a` contains objects built for macOS 12.0/12.7 while linking the app as 11.0. The app builds and validates, but truly strict macOS 11.x support requires rebuilding the vendored Opus universal library with deployment target 11.0.
