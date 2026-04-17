#!/usr/bin/env bash
# ============================================================
# Finance Digest Bot — Setup Script
# Run once to set up the Python environment
# ============================================================
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo "=== Finance Digest Bot Setup ==="
echo ""

# 1. Check Python
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.11+."
    exit 1
fi
PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Python $PYTHON_VERSION detected"
if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"; then
    echo "  ✓ Python version OK"
else
    echo "  ✗ Python 3.11+ required"
    exit 1
fi

# 2. Create virtual environment
echo ""
echo "Creating virtual environment..."
python3 -m venv .venv
echo "  ✓ .venv created"

# 3. Install dependencies
echo ""
echo "Installing dependencies..."
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q
echo "  ✓ Dependencies installed"

# 4. Create .env from example
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "  ✓ .env created from .env.example"
    echo "  ⚠️  EDIT .env before starting the bot!"
else
    echo ""
    echo "  .env already exists — skipping"
fi

# 5. Create logs directory
mkdir -p logs
echo "  ✓ logs/ directory created"

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env with your API keys and Discord token"
echo "  2. Ensure Ollama is running: sudo systemctl status ollama"
echo "  3. Test the bot: .venv/bin/python run.py"
echo ""
echo "To install as a systemd service:"
echo "  sudo cp systemd/finance-digest.service /etc/systemd/system/"
echo "  sudo systemctl enable finance-digest"
echo "  sudo systemctl start finance-digest"
echo "  sudo journalctl -u finance-digest -f"
