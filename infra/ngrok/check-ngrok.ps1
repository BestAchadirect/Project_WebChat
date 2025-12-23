param(
    [string]$Name,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$apiUrl = "http://127.0.0.1:4040/api/tunnels"

try {
    $resp = Invoke-RestMethod -Method Get -Uri $apiUrl -TimeoutSec 2
} catch {
    Write-Error "ngrok doesn't look like it's running (expected local API at $apiUrl)."
    exit 1
}

$map = [ordered]@{}
foreach ($tunnel in ($resp.tunnels | Where-Object { $_ -and $_.name -and $_.public_url })) {
    $map[$tunnel.name] = $tunnel.public_url
}

if ($Name) {
    if (-not $map.Contains($Name)) {
        $known = ($map.Keys | Sort-Object) -join ", "
        Write-Error "No tunnel named '$Name' found. Known tunnels: $known"
        exit 1
    }

    if ($Json) {
        [ordered]@{ name = $Name; public_url = $map[$Name] } | ConvertTo-Json
    } else {
        $map[$Name]
    }
    exit 0
}

if ($Json) {
    $map | ConvertTo-Json
} else {
    $map.GetEnumerator() | Sort-Object Name | ForEach-Object { "{0} = {1}" -f $_.Name, $_.Value }
}

