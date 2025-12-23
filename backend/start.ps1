# Activate virtual environment and start backend
if (Test-Path ".\\venv\\Scripts\\python.exe") {
    .\\venv\\Scripts\\python.exe -m uvicorn main:app --reload
} else {
    python -m uvicorn main:app --reload
}
