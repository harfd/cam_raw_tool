$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { python -m venv .venv }
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependencies failed' }
& '.\.venv\Scripts\python.exe' scripts/download-model.py
if ($LASTEXITCODE -ne 0) { throw 'Local model preparation failed' }
npm.cmd ci
if ($LASTEXITCODE -ne 0) { throw 'Frontend dependencies failed' }
