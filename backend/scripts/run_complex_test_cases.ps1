param(
    [string]$ApiUrl = "http://localhost:8000/api/v1/chat/",
    [string]$CasesPath = "..\\complex_test_cases.json",
    [int]$TimeoutSec = 30
)

$casesFullPath = Resolve-Path $CasesPath
$casesData = Get-Content $casesFullPath -Raw | ConvertFrom-Json
$cases = $casesData.cases
$results = @()

foreach ($case in $cases) {
    $body = @{
        user_id = "test_runner"
        message = $case.input.message
        conversation_id = $null
        locale = "en-US"
    }
    $json = $body | ConvertTo-Json -Depth 6
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    try {
        $resp = Invoke-RestMethod -Uri $ApiUrl -Method Post -ContentType "application/json" -TimeoutSec $TimeoutSec -Body $bytes
        $preview = ($resp.reply_text -replace "\s+", " ").Trim()
        if ($preview.Length -gt 120) {
            $preview = $preview.Substring(0, 120)
        }
        $results += [pscustomobject]@{
            id = $case.id
            status = "ok"
            intent = $resp.intent
            route = $resp.debug.route
            reply_preview = $preview
        }
    } catch {
        $msg = $_.Exception.Message
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            $msg = "$msg (HTTP $([int]$_.Exception.Response.StatusCode))"
        }
        $results += [pscustomobject]@{
            id = $case.id
            status = "error"
            error = $msg
        }
    }
}

$results | ConvertTo-Json -Depth 4
