$ErrorActionPreference='Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { python -m venv .venv }
    & .venv/Scripts/python.exe -m pip install -r app/requirements/enterprise-win-py313.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python 依赖安装失败。' }
    Push-Location app/web
    try { npm ci --no-audit --no-fund; if ($LASTEXITCODE -ne 0) {throw 'npm ci 失败'}; npm run build; if ($LASTEXITCODE -ne 0) {throw '前端构建失败'} } finally {Pop-Location}
    & .venv/Scripts/python.exe deploy/local_postgres.py
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL 初始化失败。' }
} finally {Pop-Location}
