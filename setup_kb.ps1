# setup_kb.ps1 — Windows PowerShell 一键建立知识库
# 功能与 setup_kb.sh 对等：创建 venv → 安装依赖 → 灌入 ChromaDB
# 要求：Python 3.10+，PowerShell 5.1+ 或 PowerShell Core 7+
#
# 首次运行可能需要先允许脚本执行：
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# ── 1. 检查 .env ──────────────────────────────────────────────
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "⚠️  已创建 .env，请先填入 ZHIPU_API_KEY 再重新运行本脚本。" -ForegroundColor Yellow
    Write-Host "   编辑：notepad .env" -ForegroundColor Yellow
    exit 1
}

$envContent = Get-Content ".env" -Raw
if ($envContent -match "your_zhipu_key_here") {
    Write-Host "⚠️  .env 里的 ZHIPU_API_KEY 还是占位符，请先填入真实 key。" -ForegroundColor Yellow
    exit 1
}

# ── 2. 检查 Python ────────────────────────────────────────────
$pythonCmd = $null
foreach ($cmd in @("python", "python3")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3\.(\d+)") {
            if ([int]$Matches[1] -ge 10) {
                $pythonCmd = $cmd
                break
            }
        }
    } catch {}
}
if (-not $pythonCmd) {
    Write-Host "❌ 未找到 Python 3.10+，请先安装：https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}
Write-Host "→ 使用 Python：$(& $pythonCmd --version)"

# ── 3. 创建 / 激活 venv ───────────────────────────────────────
if (-not (Test-Path ".venv")) {
    Write-Host "→ 创建 Python 虚拟环境..."
    & $pythonCmd -m venv .venv
}

$activateScript = ".\.venv\Scripts\Activate.ps1"
if (-not (Test-Path $activateScript)) {
    Write-Host "❌ 虚拟环境激活脚本不存在：$activateScript" -ForegroundColor Red
    Write-Host "   请删除 .venv 目录后重试。"
    exit 1
}
& $activateScript

# ── 4. 安装依赖 ───────────────────────────────────────────────
Write-Host "→ 安装依赖（首次较慢，sentence-transformers 会下载模型）..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

# ── 5. 灌入知识库 ─────────────────────────────────────────────
Write-Host "→ 开始构建知识库..."
Set-Location scripts
python build_kb.py

Write-Host ""
Write-Host "✅ 知识库构建完成！ChromaDB 存储在 data/kb/chroma/" -ForegroundColor Green
Write-Host "   现在可以启动后端："
Write-Host "   cd $scriptDir"
Write-Host "   uvicorn api.main:app --port 8001 --reload"
