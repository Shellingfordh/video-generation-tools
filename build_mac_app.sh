#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
# Create a virtualenv, install deps and build .app with PyInstaller
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
# Build mac app (this must be run on macOS host matching target arch)
pyinstaller --noconfirm --windowed --name "VideoGenerator" \
  --collect-all imageio --collect-all imageio_ffmpeg --collect-all moviepy \
  --copy-metadata imageio --copy-metadata imageio_ffmpeg --copy-metadata moviepy \
  main.py

echo "Build finished. Check dist/ for VideoGenerator.app or executable."
