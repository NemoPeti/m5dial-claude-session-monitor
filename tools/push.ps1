<#
.SYNOPSIS
    M5Stack Dial dev loop: copy and run code with mpremote.

.EXAMPLE
    .\tools\push.ps1 -List            # available serial ports
    .\tools\push.ps1 -Run             # run WITHOUT saving (fast iteration)
    .\tools\push.ps1 -Deploy          # copy to /flash/main.py + reset
    .\tools\push.ps1 -Repl            # interactive REPL (exit: Ctrl-])
    .\tools\push.ps1 -Ls              # list the device filesystem
    .\tools\push.ps1 -Launch session_monitor   # start an app from the launcher
    .\tools\push.ps1 -Apps           # list the apps on the device

.NOTES
    -Launch uses the launcher's own mechanism: it writes the chosen app name into
    the /flash/.launch marker file, then resets. The launcher reads it at boot and
    starts the app, so there is no need to touch the device.

    Important: this only works while the LAUNCHER is running on the Dial. A running
    app sets `kbd_intr(-1)`, so mpremote cannot break in - in that case run
    `session-agent.ps1 -Quit` first (or long-press the button).
#>
[CmdletBinding(DefaultParameterSetName = 'Run')]
param(
    [Parameter(ParameterSetName = 'List')][switch]$List,
    [Parameter(ParameterSetName = 'Run')][switch]$Run,
    [Parameter(ParameterSetName = 'Deploy')][switch]$Deploy,
    [Parameter(ParameterSetName = 'Repl')][switch]$Repl,
    [Parameter(ParameterSetName = 'Ls')][switch]$Ls,
    [Parameter(ParameterSetName = 'Launch', Mandatory = $true)][string]$Launch,
    [Parameter(ParameterSetName = 'Apps')][switch]$Apps,
    [string]$Port = $env:M5DIAL_PORT,
    [string]$Script = "$PSScriptRoot\..\src\main.py"
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command mpremote -ErrorAction SilentlyContinue)) {
    throw "mpremote is not installed. Install it: pip install mpremote"
}

if ($List) { mpremote connect list; return }

if (-not $Port) {
    # Auto-detect a single connected MicroPython device.
    # Without @() a single match would come back as a string, and $found[0] would
    # give the first CHARACTER ('C'), not the first line.
    $found = @((mpremote connect list) -split "`r?`n" | Where-Object { $_ -match '^COM\d+' })
    if ($found.Count -eq 1) {
        $Port = ($found[0] -split '\s+')[0]
        Write-Host "Port auto-detected: $Port" -ForegroundColor DarkGray
    }
    else {
        throw "Specify the port: -Port COM5, or set the M5DIAL_PORT variable. Devices found: $($found.Count)"
    }
}

# --- Port release from the session agent (design 3.2) -----------------------------
#
# If the session agent is running it holds the COM port and nothing here would
# work. The marker file asks it to let go; the agent closes the port within 1 s
# and waits for the file to disappear. If this script crashes and the marker
# stays behind, the agent reconnects by itself after 60 s.

$statusDir = if ($env:CLAUDE_SESSION_STATUS_DIR) {
    $env:CLAUDE_SESSION_STATUS_DIR
} else {
    Join-Path $HOME '.claude\session-status'
}
$releaseFlag = Join-Path $statusDir '.release'
$weSetTheFlag = $false

function Request-PortRelease {
    if (-not (Test-Path $statusDir)) { return }
    # Only ask for a release if an agent is running at all.
    $running = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match 'session_agent' })
    if ($running.Count -eq 0) { return }

    New-Item -ItemType File -Path $releaseFlag -Force | Out-Null
    $script:weSetTheFlag = $true
    Write-Host "session-agent is running - requested port release, waiting..." -ForegroundColor DarkGray
    Start-Sleep -Milliseconds 1500
}

function Complete-PortRelease {
    if ($script:weSetTheFlag -and (Test-Path $releaseFlag)) {
        Remove-Item $releaseFlag -Force -ErrorAction SilentlyContinue
        Write-Host "port handed back to the session agent" -ForegroundColor DarkGray
    }
}

Request-PortRelease
try {
    switch ($PSCmdlet.ParameterSetName) {
        'Repl'   { mpremote connect $Port repl }
        'Ls'     { mpremote connect $Port resume fs ls : }
        'Apps'   { mpremote connect $Port resume fs ls :apps }
        'Launch' {
            # The launcher stores the FILE NAME in the marker (`session_monitor.py`),
            # not the name shown in the list - `_read_apps()` returns names ending
            # in `.py` and `main()` compares against that. This failed live:
            # without `.py` there was no match and the list came up instead.
            # The caller may use either form.
            $app = $Launch
            if ($app -notmatch '\.py$') { $app = "$app.py" }
            $py = "f=open('/flash/.launch','w');f.write('$app');f.close()"
            mpremote connect $Port resume exec $py
            if ($LASTEXITCODE -ne 0) { throw "Writing the marker file failed (exit $LASTEXITCODE)" }
            Write-Host "marker file: $app - reset..." -ForegroundColor Green
            mpremote connect $Port reset
        }
        'Deploy' {
            mpremote connect $Port resume fs cp $Script :main.py
            if ($LASTEXITCODE -ne 0) { throw "Copy failed (exit $LASTEXITCODE)" }
            Write-Host "main.py copied, reset..." -ForegroundColor Green
            mpremote connect $Port reset
        }
        default  { mpremote connect $Port resume run $Script }
    }
}
finally {
    Complete-PortRelease
}
