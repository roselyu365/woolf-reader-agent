#!/usr/bin/env bash
# 一键建立知识库：创建 venv → 安装依赖 → 灌入 ChromaDB
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── 1. 检查 .env ──────────────────────────────────────────────
if [ ! -f .env ]; then
  cp .env.example .env
  echo "⚠️  已创建 .env，请先填入 ANTHROPIC_API_KEY 再重新运行本脚本。"
  echo "   编辑：open .env"
  exit 1
fi

if grep -q "your_key_here" .env; then
  echo "⚠️  .env 里的 ANTHROPIC_API_KEY 还是占位符，请先填入真实 key。"
  exit 1
fi

# ── 2. 创建 / 激活 venv ───────────────────────────────────────
if [ ! -d ".venv" ]; then
  echo "→ 创建 Python 虚拟环境..."
  python3 -m venv .venv
fi

source .venv/bin/activate

# ── 3. 安装依赖 ───────────────────────────────────────────────
echo "→ 安装依赖（首次较慢，sentence-transformers 会下载模型）..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

# ── 4. 灌入知识库 ─────────────────────────────────────────────
echo "→ 开始构建知识库..."
cd scripts
python build_kb.py

echo ""
echo "✅ 知识库构建完成！ChromaDB 存储在 data/kb/chroma/"
echo "   现在可以启动后端：uvicorn api.main:app --port 8001 --reload"
