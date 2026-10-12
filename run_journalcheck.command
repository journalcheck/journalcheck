#!/bin/bash
# JournalCheck for macOS: double-click to set up Python, download the lists and open the app.
cd "$(dirname "$0")" || exit 1
PY=$(command -v python3)
if [ -z "$PY" ]; then echo "python3 not found. Install Python 3.10+ from python.org and try again."; read -r; exit 1; fi
if [ ! -x .venv/bin/python ]; then
  echo "Creating the Python environment (.venv) ..."
  "$PY" -m venv .venv || { echo "Could not create .venv"; read -r; exit 1; }
fi
source .venv/bin/activate
echo "Installing packages (the first run takes a few minutes) ..."
python -m pip install -q --upgrade pip > /dev/null 2>&1
python -m pip install -q -r requirements.txt || { echo "Package installation failed"; read -r; exit 1; }
if [ ! -f data/lists/hijacked.csv ]; then
  echo "Downloading the public lists (first run only) ..."
  python scripts/build_lists.py
fi
echo "Starting JournalCheck at http://localhost:8501 (close this window to stop)"
python -m streamlit run app.py
