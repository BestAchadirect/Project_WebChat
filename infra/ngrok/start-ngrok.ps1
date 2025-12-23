[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "ngrok.yml")
)

$ErrorActionPreference = "Stop"

function Import-DotEnv {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path $Path)) {
        return
    }

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

        if ($key) {
            Set-Item -Path "Env:$key" -Value $value
        }
    }
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\\..")
Import-DotEnv (Join-Path $repoRoot ".env")

if (-not (Test-Path $ConfigPath)) {
    Write-Error "ngrok config not found at: $ConfigPath"
    exit 1
}

$ngrokExe =
    if ($env:NGROK_EXE -and (Test-Path $env:NGROK_EXE)) { $env:NGROK_EXE }
    elseif (Test-Path (Join-Path $PSScriptRoot "ngrok.exe")) { (Join-Path $PSScriptRoot "ngrok.exe") }
    else { "ngrok" }

if (-not $env:NGROK_AUTHTOKEN) {
    Write-Error "Missing NGROK_AUTHTOKEN. Set it in the repo root `.env` (do NOT commit it)."
    exit 1
}

# Generate a local config (gitignored) so we can include the authtoken without committing it.
$localConfigPath = Join-Path $PSScriptRoot "ngrok.local.yml"
$localConfig = @"
version: "2"
authtoken: "$($env:NGROK_AUTHTOKEN)"
"@

Set-Content -LiteralPath $localConfigPath -Value $localConfig -Encoding utf8

Write-Host "Starting ngrok with config: $ConfigPath"
Write-Host "Tip: run `infra/ngrok/check-ngrok.ps1` in another shell to see public URLs."

& $ngrokExe start --all --config $localConfigPath --config $ConfigPath
