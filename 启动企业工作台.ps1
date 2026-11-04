param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$enterpriseRoot = $PSScriptRoot
$enterprisePython = Join-Path $enterpriseRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $enterprisePython)) { throw '请先运行 安装与构建.ps1。' }
Push-Location $enterpriseRoot
try {
    & $enterprisePython deploy/local_postgres.py
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL 未就绪。' }
    $enterpriseOrigin = 'http://127.0.0.1:8774'
    $enterpriseReady = $false
    try { $enterpriseHealth = Invoke-RestMethod "$enterpriseOrigin/api/health" -TimeoutSec 2; $enterpriseReady = $enterpriseHealth.runtime -eq 'LangGraph' -and $enterpriseHealth.database -eq 'PostgreSQL' } catch {}
    if (-not $enterpriseReady) {
        $priorPythonPath = $env:PYTHONPATH
        try {
            $env:PYTHONPATH = (Join-Path $enterpriseRoot 'app\src') + ';' + (Join-Path $enterpriseRoot 'app')
            $env:PYTHONUTF8 = '1'
            Start-Process -FilePath $enterprisePython -ArgumentList @('-m','factory_enterprise.launch','--no-browser') -WorkingDirectory $enterpriseRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $enterpriseRoot '.local\server.log') -RedirectStandardError (Join-Path $enterpriseRoot '.local\server-error.log') | Out-Null
        } finally { $env:PYTHONPATH = $priorPythonPath }
        for ($enterpriseAttempt = 0; $enterpriseAttempt -lt 60; $enterpriseAttempt++) {
            Start-Sleep -Milliseconds 250
            try { $enterpriseHealth = Invoke-RestMethod "$enterpriseOrigin/api/health" -TimeoutSec 1; if ($enterpriseHealth.runtime -eq 'LangGraph') { $enterpriseReady=$true;break } } catch {}
        }
    }
    if (-not $enterpriseReady) { throw '企业服务启动失败，请查看 .local/server-error.log。' }
    if (-not $NoBrowser) {
        $enterpriseSetup = Invoke-RestMethod "$enterpriseOrigin/api/setup"
        if ($enterpriseSetup.required) {
            $enterpriseLink = Get-Content -LiteralPath (Join-Path $enterpriseRoot 'workspace\.local\first-login-url.txt') -Raw
            Start-Process $enterpriseLink.Trim()
        } else { Start-Process $enterpriseOrigin }
    }
    Write-Output "企业工作台：$enterpriseOrigin"
} finally { Pop-Location }
