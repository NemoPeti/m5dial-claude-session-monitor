<#
.SYNOPSIS
    Agent of the Claude session notifier: watches the sessions and sends them to the Dial.

.DESCRIPTION
    Launcher of the PC-side part described in the design
    (docs/superpowers/specs/2026-09-09-dial-session-monitor-design.md). The real
    work lives in the Python core (tools/session_agent/); this script only starts
    it, or writes the mute/volume setting - which also works while an agent runs.

.EXAMPLE
    .\tools\session-agent.ps1                  # auto-detect the port, with logging
    .\tools\session-agent.ps1 -Port COM4
    .\tools\session-agent.ps1 -Quiet           # quiet

.EXAMPLE
    .\tools\session-agent.ps1 -Mute            # sound off
    .\tools\session-agent.ps1 -Unmute
    .\tools\session-agent.ps1 -Volume 2        # 0=mute 1=low 2=medium 3=loud
#>
[CmdletBinding(DefaultParameterSetName = 'Run')]
param(
    [Parameter(ParameterSetName = 'Run')][string]$Port = $env:M5DIAL_PORT,
    [Parameter(ParameterSetName = 'Run')][switch]$Quiet,
    [Parameter(ParameterSetName = 'Mute')][switch]$Mute,
    [Parameter(ParameterSetName = 'Unmute')][switch]$Unmute,
    [Parameter(ParameterSetName = 'Volume')][ValidateRange(0, 3)][int]$Volume = -1,
    [Parameter(ParameterSetName = 'Quit')][switch]$Quit,
    [Parameter(ParameterSetName = 'Quit')][string]$QuitPort = $env:M5DIAL_PORT
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$statusDir = if ($env:CLAUDE_SESSION_STATUS_DIR) {
    $env:CLAUDE_SESSION_STATUS_DIR
} else {
    Join-Path $HOME '.claude\session-status'
}
$configPath = Join-Path $statusDir 'config.json'

function Set-AgentConfig {
    param([hashtable]$Changes)

    if (-not (Test-Path $statusDir)) { New-Item -ItemType Directory -Force $statusDir | Out-Null }

    $cfg = @{ mute = $false; volume = 2 }
    if (Test-Path $configPath) {
        try {
            $existing = Get-Content $configPath -Raw | ConvertFrom-Json
            if ($null -ne $existing.mute) { $cfg.mute = [bool]$existing.mute }
            if ($null -ne $existing.volume) { $cfg.volume = [int]$existing.volume }
        } catch {
            # Corrupt config: overwrite it with the defaults. A broken file
            # must not silently mute the system (design 4.6).
        }
    }
    foreach ($key in $Changes.Keys) { $cfg[$key] = $Changes[$key] }

    # Same atomicity as on the Python side: temp file + rename.
    $tmp = "$configPath.tmp"
    ($cfg | ConvertTo-Json -Compress) | Set-Content -Path $tmp -Encoding utf8 -NoNewline
    Move-Item -Path $tmp -Destination $configPath -Force
    Write-Host "config: $($cfg | ConvertTo-Json -Compress)"
}

function Send-Quit {
    <#
        The monitor app running on the Dial calls `micropython.kbd_intr(-1)` (needed,
        otherwise a 0x03 byte would kill the program), and mpremote cannot break in
        because of it: "could not enter raw repl". By hand, a long press of the
        launcher button is the way out - this is the same thing, remotely: one
        protocol line on which the app hands control back.
    #>
    param([string]$Port)

    if (-not $Port) {
        $found = @(Get-CimInstance Win32_PnPEntity |
            Where-Object { $_.Name -match '\(COM(\d+)\)' -and $_.DeviceID -match 'VID_303A&PID_81DD' } |
            ForEach-Object { [regex]::Match($_.Name, '\(COM(\d+)\)').Groups[1].Value })
        if ($found.Count -eq 0) { Write-Error "Cannot find an M5Dial."; exit 1 }
        $Port = "COM$($found[0])"
    }

    $sp = New-Object System.IO.Ports.SerialPort $Port, 115200, 'None', 8, 'One'
    # DTR must NOT be omitted: on the native USB-CDC line data does not reach the
    # device without it. pyserial raises it by default - that is why the agent
    # works - but .NET SerialPort does not, and the first version was silently
    # ineffective because of it.
    $sp.DtrEnable = $true
    $sp.RtsEnable = $true
    try {
        $sp.Open()
        $sp.Write("{`"t`":`"quit`"}`n")
        Start-Sleep -Milliseconds 600
    } finally {
        if ($sp.IsOpen) { $sp.Close() }
    }
    Write-Host "quit sent to $Port - the Dial returns to the launcher"
}

switch ($PSCmdlet.ParameterSetName) {
    'Mute' { Set-AgentConfig @{ mute = $true }; return }
    'Unmute' { Set-AgentConfig @{ mute = $false }; return }
    'Volume' { Set-AgentConfig @{ volume = $Volume; mute = $false }; return }
    'Quit' { Send-Quit -Port $QuitPort; return }
}

if (-not $Port) {
    # Same detection as in push.ps1: the UIFlow2 PID is 303a:81dd.
    $found = @(Get-CimInstance Win32_PnPEntity |
        Where-Object { $_.Name -match '\(COM(\d+)\)' -and $_.DeviceID -match 'VID_303A&PID_81DD' } |
        ForEach-Object { [regex]::Match($_.Name, '\(COM(\d+)\)').Groups[1].Value })
    if ($found.Count -eq 0) {
        Write-Error "Cannot find an M5Dial (303a:81dd). Specify it by hand: -Port COMx"
        exit 1
    }
    $Port = "COM$($found[0])"
    Write-Host "device: $Port"
}

$python = 'python'
$code = @"
import sys
sys.path.insert(0, r'$root\tools')
from session_agent.agent import Agent
log = (lambda *a: None) if $(if ($Quiet) { 'True' } else { 'False' }) else print
Agent('$Port', log=log).run()
"@

Write-Host "agent starting on $Port - Ctrl-C to stop"
& $python -c $code
