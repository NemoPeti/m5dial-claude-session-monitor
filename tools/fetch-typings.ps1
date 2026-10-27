<#
.SYNOPSIS
    Downloads the UIFlow2 MicroPython libraries into the typings/ folder so the
    editor (Pylance/pyright) can resolve the `M5`, `hardware`, `m5ui` and
    `unit` imports.

.DESCRIPTION
    The typings/ folder is not version controlled (see .gitignore) - this script
    generates it from a shallow clone. It only serves editor completion and is
    never copied to the device.

.EXAMPLE
    .\tools\fetch-typings.ps1
#>
[CmdletBinding()]
param(
    [string]$Ref = 'master'
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path $PSScriptRoot -Parent
$typings = Join-Path $repoRoot 'typings'
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("uiflow-typings-" + [guid]::NewGuid().ToString('N').Substring(0, 8))

Write-Host "Cloning ($Ref)..." -ForegroundColor Cyan
git clone --depth 1 --branch $Ref https://github.com/m5stack/uiflow-micropython.git $tmp 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Clone failed (exit $LASTEXITCODE)" }

try {
    if (Test-Path $typings) { Remove-Item $typings -Recurse -Force }
    New-Item -ItemType Directory -Path $typings | Out-Null

    Copy-Item (Join-Path $tmp 'm5stack\libs\*') $typings -Recurse -Force
    Copy-Item (Join-Path $tmp 'm5stack\modules\widgets') $typings -Recurse -Force -ErrorAction SilentlyContinue

    $count = (Get-ChildItem $typings -Recurse -Filter *.py -File).Count
    Write-Host "Done: $count .py files in the typings/ folder." -ForegroundColor Green

    if (-not (Get-Command pip -ErrorAction SilentlyContinue)) { return }
    if (-not (pip show m5stack-stubs 2>$null)) {
        Write-Host "Tip: for the M5 module .pyi stub: pip install m5stack-stubs" -ForegroundColor DarkGray
    }
}
finally {
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
