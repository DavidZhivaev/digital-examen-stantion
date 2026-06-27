@echo off

setlocal enabledelayedexpansion

echo ========================================
echo Scanner Module - Windows Build Script
echo ========================================
echo.

set "DTWAIN_ROOT=C:\Libraries\dtwain"
set "OPENCV_DIR="
set "INSTALL_PREFIX=C:\Program Files\ScannerModule"
set "BUILD_TYPE=Release"
set "VS_GENERATOR=Visual Studio 16 2019"
set "ARCHITECTURE=x64"

where cmake >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] CMake not found! Please install CMake and add it to PATH.
    echo Download from: https://cmake.org/download/
    pause
    exit /b 1
)

echo [INFO] CMake found:
cmake --version | findstr /C:"cmake version"
echo.

echo [INFO] Creating build directory...
if not exist "build" (
    mkdir build
) else (
    echo [WARNING] Build directory already exists
)
cd build

echo.
echo [INFO] Configuring CMake...
echo [INFO] Build type: %BUILD_TYPE%
echo [INFO] Generator: %VS_GENERATOR%
echo [INFO] Architecture: %ARCHITECTURE%
echo [INFO] DTWAIN root: %DTWAIN_ROOT%
echo.

set "CMAKE_ARGS=-G \"%VS_GENERATOR%\" -A %ARCHITECTURE%"
set "CMAKE_ARGS=%CMAKE_ARGS% -DCMAKE_BUILD_TYPE=%BUILD_TYPE%"
set "CMAKE_ARGS=%CMAKE_ARGS% -DCMAKE_INSTALL_PREFIX=\"%INSTALL_PREFIX%\""
set "CMAKE_ARGS=%CMAKE_ARGS% -DDTWAIN_ROOT=\"%DTWAIN_ROOT%\""

if not "%OPENCV_DIR%"=="" (
    set "CMAKE_ARGS=%CMAKE_ARGS% -DOpenCV_DIR=\"%OPENCV_DIR%\""
)

echo [INFO] Running: cmake .. %CMAKE_ARGS%
cmake .. %CMAKE_ARGS%

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] CMake configuration failed!
    echo Please check the error messages above and verify:
    echo   1. All dependencies are installed (OpenCV, Python, pybind11)
    echo   2. DTWAIN path is correct: %DTWAIN_ROOT%
    echo   3. Visual Studio is installed
    cd ..
    pause
    exit /b 1
)

echo.
echo [SUCCESS] CMake configuration completed!
echo.

echo [INFO] Building project...
echo [INFO] This may take several minutes...
echo.

cmake --build . --config %BUILD_TYPE% --parallel

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Build failed!
    echo Please check the error messages above.
    cd ..
    pause
    exit /b 1
)

echo.
echo [SUCCESS] Build completed successfully!
echo.
echo Executable location: build\bin\%BUILD_TYPE%\scanner_module.exe
echo.

set /p INSTALL_CHOICE="Do you want to install to %INSTALL_PREFIX%? (y/n): "
if /i "%INSTALL_CHOICE%"=="y" (
    echo.
    echo [INFO] Installing...
    echo [WARNING] This requires administrator privileges.

    cmake --install . --config %BUILD_TYPE%

    if %ERRORLEVEL% neq 0 (
        echo.
        echo [ERROR] Installation failed!
        echo Please run this script as Administrator or install manually:
        echo   cmake --install . --config %BUILD_TYPE%
    ) else (
        echo.
        echo [SUCCESS] Installation completed!
        echo Installed to: %INSTALL_PREFIX%
    )
)

echo.
set /p PACKAGE_CHOICE="Do you want to create installer package? (y/n): "
if /i "%PACKAGE_CHOICE%"=="y" (
    echo.
    echo [INFO] Creating installer package...

    where makensis >nul 2>nul
    if %ERRORLEVEL% neq 0 (
        echo [WARNING] NSIS not found. Creating ZIP package instead.
        echo Download NSIS from: https://nsis.sourceforge.io/
        cpack -G ZIP
    ) else (
        echo [INFO] NSIS found, creating both NSIS and ZIP packages...
        cpack -G NSIS
        cpack -G ZIP
    )

    if %ERRORLEVEL% neq 0 (
        echo.
        echo [ERROR] Package creation failed!
    ) else (
        echo.
        echo [SUCCESS] Package(s) created in build directory!
        dir /b *.exe *.zip 2>nul
    )
)

cd ..

echo.
echo ========================================
echo Build process completed!
echo ========================================
echo.
echo Next steps:
echo   1. Run the application: build\bin\%BUILD_TYPE%\scanner_module.exe
if /i "%INSTALL_CHOICE%"=="y" (
    echo   2. Or run installed version: "%INSTALL_PREFIX%\bin\scanner_module.exe"
)
if /i "%PACKAGE_CHOICE%"=="y" (
    echo   3. Distribute the installer package to other computers
)
echo.

pause
