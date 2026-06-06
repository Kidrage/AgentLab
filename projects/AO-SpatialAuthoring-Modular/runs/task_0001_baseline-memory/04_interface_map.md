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
