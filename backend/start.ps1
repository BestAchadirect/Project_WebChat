# Activate virtual environment and start backend
$sslArgs = @()
if ($env:SSL_CERTFILE -and $env:SSL_KEYFILE) {
    $sslArgs = @("--ssl-certfile", $env:SSL_CERTFILE, "--ssl-keyfile", $env:SSL_KEYFILE)
}

if (Test-Path ".\\venv\\Scripts\\python.exe") {
    .\\venv\\Scripts\\python.exe -m uvicorn main:app --reload @sslArgs
} else {
    python -m uvicorn main:app --reload @sslArgs
}
