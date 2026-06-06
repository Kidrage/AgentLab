# Interface Registry

Detected from metadata only. Confirm against source before making API or plugin-format decisions.

| Project | Interface/Boundary Signal | Notes |
|---|---|---|
| `build_arm64_scnet` | local folder boundary | scnet_package_arm64/README.md; scnet_package_arm64/_pydeps_py311_arm64/torchgen/packaged/autograd/README.md; scnet_package_arm64/_python_py311_arm64/lib/python3.11/config-3.11-darwin/Makefile; scnet_package_arm64/requirements.txt |
| `build_x86_64_scnet` | local folder boundary | scnet_package_x86_64/README.md; scnet_package_x86_64/_pydeps_py311_x86_64/torchgen/packaged/autograd/README.md; scnet_package_x86_64/_python_py311_x86_64/lib/python3.11/config-3.11-darwin/Makefile; scnet_package_x86_64/requirements.txt |
| `cmake` | local folder boundary | No key files detected |
| `docs` | document artifact boundary | No key files detected |
| `modules` | document artifact boundary | README.md; app/README.md; audio/README.md; domain/README.md |
| `SCNet-main1` | local folder boundary | README.md; _pydeps_py311_arm64/torchgen/packaged/autograd/README.md; _pydeps_py311_x86_64/torchgen/packaged/autograd/README.md; _python_py311_arm64/lib/python3.11/config-3.11-darwin/Makefile |
| `scripts` | local folder boundary | No key files detected |
| `spatial-authoring-plugin` | CMake build interface | CMakeLists.txt; Source/Stems/README.md |
| `spatial-container-sdk` | CMake build interface | CMakeLists.txt |
| `third_party` | JUCE plugin/application boundary | README.md; bds-codec/CMakeLists.txt; bds-codec/README.md; bds-codec/tests/CMakeLists.txt |

## Long-Term Interface Addendum

Backend: `external_ide_manual` memory rescue.

- UI boundary: `PluginEditor.*` and future `modules/ui/` render controls and forward user intent only.
- Processor boundary: `PluginProcessor.*` owns JUCE lifecycle, parameters, automation state, and service coordination.
- Stems boundary: `Source/Stems/StemSeparationService.*` exposes `runScnetSeparation(sourceFile, jobRoot)` and supports legacy Python plus embedded modes.
- Embedded SCNet manifest: `modules/stems/ScnetManifest.h` defines `scnet_outstft_core_t432.onnx`, `scnet_config.yaml`, 44.1kHz, FFT 4096, hop 2048, T=432, and 4 sources.
- ONNX Runtime engine: `modules/stems/ScnetEngine.*` handles resample -> chunks -> STFT -> ONNX -> iSTFT -> stems.
- Native fallback: `modules/stems/ScnetNativeEngine.*` loads extracted weights and must be validated against Python/ONNX reference outputs.
- Build boundary: root/plugin/stems CMake files own universal arch, BDS, JUCE, SCNet options, bundle resources, and runtime dylib handling.
- Xcode migration must preserve CMake as canonical source of target membership, resources, signing, and universal architecture settings.
