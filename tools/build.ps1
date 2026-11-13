# SPDX-License-Identifier: GPL-3.0-or-later
#
# Configures and builds a CMake preset from any PowerShell, loading the Visual Studio
# developer environment first when it isn't loaded yet.
#
#   tools\build.ps1                          # the "release" preset
#   tools\build.ps1 -Preset local            # a preset from your CMakeUserPresets.json
#   tools\build.ps1 -Preset local -Target deploy
#   tools\build.ps1 -Fresh                   # configure from scratch (a new CMake cache)
#   tools\build.ps1 -Preset local -Test      # then run the unit tests

param(
    [string]$Preset = "release",
    [string]$Target = "",
    [switch]$Fresh,
    [switch]$Test
)

$ErrorActionPreference = "Stop"

if (-not $env:VSCMD_VER) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path $vswhere)) { throw "Visual Studio Installer not found; install the VS 2022 Build Tools." }
    $vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if (-not $vs) { throw "No Visual Studio installation with the C++ x64 build tools was found." }
    $env:PATH = (Split-Path $vswhere) + ";" + $env:PATH  # the developer shell scripts call vswhere too
    & (Join-Path $vs "Common7\Tools\Launch-VsDevShell.ps1") -Arch amd64 -HostArch amd64 -SkipAutomaticLocation | Out-Null
}

Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    $configureArgs = @("--preset", $Preset)
    if ($Fresh) { $configureArgs += "--fresh" }
    cmake @configureArgs
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    $buildArgs = @("--build", "--preset", $Preset)
    if ($Target) { $buildArgs += @("--target", $Target) }
    cmake @buildArgs
    if ($LASTEXITCODE -or -not $Test) { exit $LASTEXITCODE }
    ctest --preset $Preset
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
