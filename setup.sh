#!/bin/bash
 
# ==================== Recipe Extractor API - Setup & Test Script ====================
# This script helps you get the API running in Codespaces
 
set -e  # Exit on any error
 
echo "=========================================="
echo "Recipe Extractor API - Setup Script"
echo "=========================================="
echo ""
 
# Step 1: Check Python
echo "✅ Step 1: Checking Python installation..."
python3 --version
echo ""
 
# Step 2: Install system dependencies for Codespaces
echo "✅ Step 2: Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y chromium-browser xvfb >/dev/null 2>&1
echo "   ✓ System packages installed"
echo ""
 
# Step 3: Install Python dependencies
echo "✅ Step 3: Installing Python dependencies..."
pip install --quiet -r requirements.txt
echo "   ✓ Python packages installed"
echo ""
 
# Step 4: Verify imports
echo "✅ Step 4: Verifying imports..."
python3 -c "import fastapi; print(f'   ✓ FastAPI {fastapi.__version__}')"
python3 -c "import camoufox; print('   ✓ Camoufox loaded')"
python3 -c "import bs4; print('   ✓ BeautifulSoup4 loaded')"
echo ""
 
echo "=========================================="
echo "✅ SETUP COMPLETE!"
echo "=========================================="
echo ""
echo "To start the API, run:"
echo ""
echo "  python main.py"
echo ""
echo "Or with uvicorn directly:"
echo ""
echo "  uvicorn main:app --host 0.0.0.0 --port 8000 --reload --workers 1"
echo ""
echo "Once running, visit:"
echo "  - API: http://localhost:8000"
echo "  - Docs: http://localhost:8000/docs"
echo "  - ReDoc: http://localhost:8000/redoc"
echo ""
echo "To test in another terminal, run:"
echo ""
echo "  python test_api.py"
echo ""