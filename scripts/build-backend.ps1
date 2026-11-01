$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
& '.\.venv\Scripts\python.exe' scripts/download-model.py
if ($LASTEXITCODE -ne 0) { throw 'Local model preparation failed' }
& '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --onedir --name raw-studio-server --collect-all rawpy --collect-all keyring --collect-all onnxruntime --add-data 'backend/assets;backend/assets' --hidden-import backend.main --hidden-import keyring.backends.Windows backend/server.py
if ($LASTEXITCODE -ne 0) { throw 'Backend packaging failed' }
