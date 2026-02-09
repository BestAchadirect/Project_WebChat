[CmdletBinding()]
param(
    [switch]$Ngrok,
    [int]$BackendPort = 8000,
    [int]$FrontendAdminPort = 5173
)

$ErrorActionPreference = "Stop"

function Get-PwshExe {
    if (Get-Command pwsh -ErrorAction SilentlyContinue) { return "pwsh" }
    return "powershell"
}

function Import-DotEnv {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path $Path)) { return }
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }

        $eq = $trimmed.IndexOf("=")
        if ($eq -lt 1) { continue }

        $key = $trimmed.Substring(0, $eq).Trim()
        $value = $trimmed.Substring($eq + 1).Trim()

        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        if ($key) { Set-Item -Path "Env:$key" -Value $value }
    }
}

function Get-NgrokPublicUrl {
    param(
        [Parameter(Mandatory = $true)][string]$TunnelName,
        [int]$TimeoutSeconds = 20
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 2
            foreach ($t in $resp.tunnels) {
                if ($t.name -eq $TunnelName -and $t.public_url) { return $t.public_url }
            }
        } catch {
            # ngrok not ready yet
        }
        Start-Sleep -Milliseconds 400
    }

    throw "Timed out waiting for ngrok tunnel '$TunnelName' to become available."
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Import-DotEnv (Join-Path $repoRoot ".env")

$pwsh = Get-PwshExe

$backendCmd = @"
`$host.UI.RawUI.WindowTitle = 'WebChat Backend';
Set-Location '$repoRoot\\backend';
`$sslArgs = ''
if ('$($env:SSL_CERTFILE)' -and '$($env:SSL_KEYFILE)') {
  `$sslArgs = '--ssl-certfile "$($env:SSL_CERTFILE)" --ssl-keyfile "$($env:SSL_KEYFILE)"'
}
if (Test-Path '.\\venv\\Scripts\\python.exe') {
  .\\venv\\Scripts\\python.exe -m uvicorn main:app --reload --host 0.0.0.0 --port $BackendPort `$sslArgs
} else {
  python -m uvicorn main:app --reload --host 0.0.0.0 --port $BackendPort `$sslArgs
}
"@

$frontendCmdTemplate = @"
`$host.UI.RawUI.WindowTitle = 'WebChat Frontend Admin';
Set-Location '$repoRoot\\frontend-admin';
npm run dev
"@

if ($Ngrok) {
    $ngrokCmd = @"
`$host.UI.RawUI.WindowTitle = 'ngrok';
Set-Location '$repoRoot';
& '$repoRoot\\infra\\ngrok\\start-ngrok.ps1'
"@
    Start-Process -FilePath $pwsh -ArgumentList @("-NoExit", "-Command", $ngrokCmd) | Out-Null

    # Get the public URL for the frontend (single tunnel).
    $frontendPublic = Get-NgrokPublicUrl -TunnelName "frontend-admin"

    $hmrHost = ([uri]$frontendPublic).Host

    $frontendCmd = @"
`$env:VITE_API_BASE_URL = '/api/v1';
`$env:VITE_DEV_BACKEND_URL = 'http://127.0.0.1:$BackendPort';
`$env:VITE_DEV_HMR_HOST = '$hmrHost';
`$env:VITE_DEV_ALLOW_ALL_HOSTS = '1';
$frontendCmdTemplate
"@

    Write-Host "ngrok frontend: $frontendPublic"
    Write-Host "VITE_API_BASE_URL=/api/v1 (proxied via Vite)"

    Start-Process -FilePath $pwsh -ArgumentList @("-NoExit", "-Command", $backendCmd) | Out-Null
    Start-Process -FilePath $pwsh -ArgumentList @("-NoExit", "-Command", $frontendCmd) | Out-Null
    exit 0
}

Start-Process -FilePath $pwsh -ArgumentList @("-NoExit", "-Command", $backendCmd) | Out-Null
Start-Process -FilePath $pwsh -ArgumentList @("-NoExit", "-Command", $frontendCmdTemplate) | Out-Null

Write-Host "Started backend (port $BackendPort) + frontend-admin (port $FrontendAdminPort)."
Write-Host "Add -Ngrok to also start tunnels + set VITE_API_BASE_URL."
