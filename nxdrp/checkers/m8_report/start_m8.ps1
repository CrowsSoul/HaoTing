param([switch]$CheckOnly, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../..')).Path
Set-Location -LiteralPath $projectRoot
$platformFiles = @('nxdrp/catalog.py', 'nxdrp/pipeline.py', 'nxdrp/contracts/__init__.py')
foreach ($platformFile in $platformFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $platformFile))) {
        Write-Host '当前目录缺少完整平台代码。这是模块合并包，不能单独运行。' -ForegroundColor Yellow
        Write-Host '请将包里的 nxdrp 和 tests 按原目录名合并到 HaoTing 仓库根目录，保留仓库原有文件。'
        Write-Host '需要独立演示时，请解压完整交付包，进入 harting_drp 后启动。'
        exit 1
    }
}
$runtimeCandidates = @(
    (Join-Path $projectRoot '.venv/Scripts/python.exe'),
    (Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe')
)
$m8Python = $runtimeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $m8Python) {
    $pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCmd) { $m8Python = $pythonCmd.Source }
}
if (-not $m8Python) { throw '请先安装 Python 3.12 或以上版本。' }
& $m8Python -c "import sys; assert sys.version_info >= (3,12), 'Python 需要 3.12 或以上'; import PIL, docx, reportlab, numpy"
if ($LASTEXITCODE -ne 0) {
    Write-Host '请在项目目录安装依赖后重新启动：' -ForegroundColor Yellow
    Write-Host ('"' + $m8Python + '" -m pip install -r nxdrp/checkers/m8_report/requirements.txt')
    exit 1
}
if ($CheckOnly) {
    Write-Host ('启动检查通过。项目目录：' + $projectRoot)
    Write-Host ('Python：' + $m8Python)
    exit 0
}
$m8ServiceRunning = $false
try {
    $existing = Invoke-RestMethod -Uri 'http://127.0.0.1:8768/api/info' -TimeoutSec 2
    $m8ServiceRunning = $existing.catalog_count -eq 44 -and $existing.version -eq '1.1.0'
} catch { }
if ($m8ServiceRunning) {
    Write-Host '插件已经在运行，打开 http://127.0.0.1:8768 即可使用。'
    if (-not $NoBrowser) {
        try { Start-Process 'http://127.0.0.1:8768' } catch { Write-Host '浏览器未能自动打开，请手动访问上面的网址。' }
    }
    exit 0
}
Write-Host 'M8 报告与知识库正在启动。保留此窗口；关闭窗口即停止服务。'
Write-Host '浏览器地址：http://127.0.0.1:8768'
if ($NoBrowser) {
    & $m8Python -m nxdrp.checkers.m8_report serve --no-browser
} else {
    & $m8Python -m nxdrp.checkers.m8_report serve
}
exit $LASTEXITCODE