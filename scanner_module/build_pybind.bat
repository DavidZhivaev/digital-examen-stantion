@echo off
mkdir build 2>nul
cd build
cmake -DBUILD_PYTHON_MODULE=ON ..
cmake --build . --config Release
copy Release\scanner_hal*.pyd ..\..\
