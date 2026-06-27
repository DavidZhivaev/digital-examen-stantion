#!/bin/bash
set -e
mkdir -p build && cd build
cmake -DBUILD_PYTHON_MODULE=ON ..
cmake --build . --config Release
cp scanner_hal*.so ../../
