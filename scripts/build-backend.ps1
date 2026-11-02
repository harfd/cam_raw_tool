$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
& '.\.venv\Scripts\python.exe' -X utf8 scripts/prepare-film.py
if ($LASTEXITCODE -ne 0) { throw 'Film engine preparation failed' }
& '.\.venv\Scripts\python.exe' scripts/download-model.py
if ($LASTEXITCODE -ne 0) { throw 'Local model preparation failed' }
& '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --onedir --name raw-studio-server --collect-all rawpy --collect-all keyring --collect-all onnxruntime --add-data 'backend/assets;backend/assets' --add-data 'backend/film_worker.py;backend' --hidden-import backend.main --hidden-import keyring.backends.Windows backend/server.py
if ($LASTEXITCODE -ne 0) { throw 'Backend packaging failed' }
& '.\.venv\Scripts\python.exe' -c "import shutil; shutil.copytree('.tools/film-runtime', 'dist/raw-studio-server/film-runtime', dirs_exist_ok=True)"
if ($LASTEXITCODE -ne 0) { throw 'Film runtime copy failed' }
