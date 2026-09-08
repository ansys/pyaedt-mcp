[CmdletBinding()]
param(
    [string]$Version,
    [switch]$SkipRuntimeStaging,
    [switch]$SkipExecutableBuild
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repositoryRoot

if (-not $Version) {
    $projectVersion = (Select-String -Path "pyproject.toml" -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
    $Version = ($projectVersion -replace '\.dev\d*$', '.0')
}

if (-not $SkipRuntimeStaging) {
    uv run --no-sync .\desktop_app\stage_desktop_runtime.py
}

if (-not $SkipExecutableBuild) {
    uv run --no-sync flet pack .\desktop_app\desktop_launcher.py --name PyAEDT_MCP --icon .\desktop_app\assets\pyaedt_mcp_icon.ico --add-data .\desktop_app\.desktop-runtime:runtime --add-data .\desktop_app\assets:assets --yes
}

if (-not (Test-Path ".\dist\PyAEDT_MCP.exe")) {
    throw "The desktop executable was not found at dist\PyAEDT_MCP.exe."
}

$makeNsisPath = (Get-Command makensis.exe -ErrorAction SilentlyContinue).Source
if (-not $makeNsisPath) {
    $defaultMakeNsis = "${env:ProgramFiles(x86)}\NSIS\makensis.exe"
    if (Test-Path $defaultMakeNsis) {
        $makeNsisPath = $defaultMakeNsis
    }
}
if (-not $makeNsisPath) {
    throw "NSIS is required. Install it with: choco install nsis -y"
}

& $makeNsisPath "/DPRODUCT_VERSION=$Version" ".\installer\setup.nsi"
if ($LASTEXITCODE -ne 0) {
    throw "NSIS failed to build the Windows installer."
}

Write-Output "Built dist\PyAEDT-MCP-Installer-windows.exe"
