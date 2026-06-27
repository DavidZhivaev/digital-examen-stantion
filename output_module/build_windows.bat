@echo off
setlocal enabledelayedexpansion

set BUILD_DIR=build
set CONFIG=Release

if not exist %BUILD_DIR% mkdir %BUILD_DIR%
cd %BUILD_DIR%

where g++ >nul 2>&1
if %errorlevel%==0 (
    echo Using MinGW...
    cmake -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=%CONFIG% ..
    if errorlevel 1 goto :cmake_failed
    cmake --build . -j%NUMBER_OF_PROCESSORS%
) else (
    where cl >nul 2>&1
    if %errorlevel%==0 (
        echo Using MSVC...
        cmake -G "NMake Makefiles" -DCMAKE_BUILD_TYPE=%CONFIG% ..
        if errorlevel 1 goto :cmake_failed
        cmake --build .
    ) else (
        echo No compiler found. Install MinGW-w64 or Visual Studio Build Tools.
        exit /b 1
    )
)

if errorlevel 1 (
    echo Build failed
    exit /b 1
)

for /r %%f in (output_generator_cpp*.pyd) do (
    copy "%%f" ..\..\ >nul
    echo Copied %%~nxf to project root
)

echo Build completed successfully
exit /b 0

:cmake_failed
echo CMake configuration failed
exit /b 1
