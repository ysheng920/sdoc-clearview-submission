<#
    Stop the API and start it again, so edited code is actually the code running.

    Python loads a module once per process. Editing a file under app/ changes
    nothing for a server that is already up, and the symptom is not an error --
    the old code keeps answering, correctly, with the old behaviour. That has
    cost real debugging time twice.

    `--reload` would be the obvious answer and it does not work here: uvicorn
    logs "WatchFiles detected changes ... Reloading" and then never replaces the
    worker, on 0.53 / Python 3.11 / Windows, whichever way it is launched.

    Stopping is the part that has to be right. A uvicorn worker on Windows is
    spawned through multiprocessing, so its command line says spawn_main and not
    uvicorn: a filter matching only "uvicorn" kills the reloader and leaves the
    worker holding the port. The next start then binds nothing, and every
    request goes to the orphan -- which is how a server can serve code that no
    longer exists anywhere on disk.

    Usage:  .\restart.ps1            start on 8000
            .\restart.ps1 -Port 8100 somewhere else
            .\restart.ps1 -Stop      stop and leave it stopped
#>
param(
    [int]$Port = 8000,
    [switch]$Stop
)

$ErrorActionPreference = 'Stop'
$backend = Split-Path -Parent $MyInvocation.MyCommand.Path

function Stop-Api {
    # Both halves: the reloader, and the worker it spawned under another name.
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match 'uvicorn|spawn_main' }
    foreach ($p in $procs) {
        Write-Host "  stopping $($p.ProcessId)"
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }

    # Anything still listening owns the port regardless of how it was started.
    try {
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
            ForEach-Object {
                Write-Host "  stopping $($_.OwningProcess) (holds port $Port)"
                Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
            }
    } catch {
        # No listener: nothing to stop.
    }

    # Wait for the port, not for the process: a dead process can leave the
    # socket in TIME_WAIT and the next bind fails without saying why.
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 250
        $busy = $null
        try { $busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop } catch {}
        if (-not $busy) { return $true }
    }
    Write-Warning "port $Port is still held after 5s"
    return $false
}

Write-Host "Stopping API..."
Stop-Api | Out-Null
if ($Stop) { Write-Host "Stopped."; exit 0 }

Write-Host "Starting API on $Port..."
$log = Join-Path $env:TEMP "clearview-api.log"
Start-Process -FilePath 'python' `
    -ArgumentList @('-m', 'uvicorn', 'app.main:app',
                    '--host', '127.0.0.1', '--port', "$Port",
                    '--log-level', 'warning') `
    -WorkingDirectory $backend `
    -RedirectStandardOutput $log -RedirectStandardError "$log.err" `
    -WindowStyle Hidden | Out-Null

foreach ($i in 1..30) {
    Start-Sleep -Milliseconds 400
    try {
        $r = Invoke-RestMethod "http://127.0.0.1:$Port/api/config" -TimeoutSec 2
        Write-Host "Ready: $($r.backend) $($r.model)"
        Write-Host "Log:   $log"
        exit 0
    } catch { }
}

Write-Warning "did not answer within 12s -- see $log.err"
exit 1
