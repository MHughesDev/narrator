#!/usr/bin/env sh
# Narrator is Windows-first (WinRT / UI Automation). This script only documents that.
set -e
cd "$(dirname "$0")"
echo "Narrator targets Windows 10/11. On Linux or macOS, clone the repo on a Windows machine"
echo "and run setup.bat, or use a Windows VM."
echo ""
echo "Optional: inspect hardware detection logic (for documentation):"
echo "  python3 scripts/hw_detect.py"
exit 1
