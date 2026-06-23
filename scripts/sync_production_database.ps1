#Requires -Version 5.1
<#
.SYNOPSIS
  Pull production SQLite database from VPS (24/7 canonical source) to localhost.

.DESCRIPTION
  VPS runs the live engine. Local data/signals.db is NOT synced via git.
  Run this before local audits so localhost matches VPS statistics.

.EXAMPLE
  .\scripts\sync_production_database.ps1
  .\scripts\sync_production_database.ps1 -VpsHost 203.0.113.10 -VpsUser root
#>
param(
    [string]$VpsHost = $env:VPS_HOST,
    [string]$VpsUser = $env:VPS_USER,
    [string]$RemoteDbPath = $env:VPS_DATABASE_PATH,
    [string]$LocalDbPath = $env:DATABASE_PATH
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

if (-not $VpsHost) { $VpsHost = "vmi3381775" }
if (-not $VpsUser) { $VpsUser = "root" }
if (-not $RemoteDbPath) { $RemoteDbPath = "/root/delta-signal-engine/data/signals.db" }
if (-not $LocalDbPath) { $LocalDbPath = Join-Path $Root "data\signals.db" }
else {
    if (-not [System.IO.Path]::IsPathRooted($LocalDbPath)) {
        $LocalDbPath = Join-Path $Root ($LocalDbPath -replace '/', '\')
    }
}

$DataDir = Split-Path -Parent $LocalDbPath
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupPath = "$LocalDbPath.local-backup-$Timestamp"

if (Test-Path $LocalDbPath) {
    Copy-Item $LocalDbPath $BackupPath -Force
    Write-Host "Backed up local DB -> $BackupPath"
}

$Remote = "${VpsUser}@${VpsHost}:$RemoteDbPath"
$TempPath = "$LocalDbPath.download"

Write-Host "Pulling production DB from $Remote ..."
& scp $Remote $TempPath
if ($LASTEXITCODE -ne 0) {
    Write-Error "scp failed. Ensure SSH access: ssh ${VpsUser}@${VpsHost}"
}

Move-Item -Force $TempPath $LocalDbPath

$MetaPath = Join-Path $DataDir "production_sync.json"
$Meta = @{
    synced_at = (Get-Date).ToUniversalTime().ToString("o")
    source = "vps"
    vps_host = $VpsHost
    vps_user = $VpsUser
    remote_path = $RemoteDbPath
    local_path = $LocalDbPath
    backup_path = $BackupPath
} | ConvertTo-Json -Depth 4
Set-Content -Path $MetaPath -Value $Meta -Encoding UTF8

Write-Host "OK - local database replaced with VPS copy."
Write-Host "Local path: $LocalDbPath"
Write-Host "Metadata:   $MetaPath"
Write-Host ""
Write-Host "Next: restart uvicorn, then open http://localhost:8000/debug/system"
Write-Host "Verify signal_count and trade_count match VPS."
