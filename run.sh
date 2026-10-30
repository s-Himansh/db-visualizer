#!/bin/bash

# Database Visualizer - Startup Script

echo "Starting Database Visualizer..."
echo ""

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed"
    echo "Please install Python 3 from https://www.python.org/downloads/"
    exit 1
fi

cd "$(dirname "$0")" || exit 1

# Use a project venv; the system pip (21.x) can't find pyobjc wheels and fails compiling them
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv || exit 1
fi

if ! .venv/bin/python -c "import flask, webview" &> /dev/null; then
    echo "Installing dependencies..."
    .venv/bin/python -m pip install -q --upgrade pip &&
    .venv/bin/python -m pip install -r requirements.txt || { echo "Dependency install failed"; exit 1; }
    echo ""
fi

# Run the application
echo "Launching Database Visualizer..."
.venv/bin/python db.py
