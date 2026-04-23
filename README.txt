Usage:
1) To run during development: python3 main.py
2) To build a double-clickable macOS app (on a Mac):
   ./build_mac_app.sh
   The built app will be in dist/ (VideoGenerator.app or a bundled executable).

Notes for distribution to operations team:
- Test the built .app on a clean Mac (Apple Silicon vs Intel matters; build on same arch).
- Code signing and notarization may be required for Gatekeeper on modern macOS.
- The app writes output to ~/Downloads by default.

Operation steps for users:
- Double-click the app.
- Click "Select Images" and pick images (multiple allowed).
- Choose audio: either random from a folder (click "Choose Audio Folder") or pick a specific file ("Choose Audio File").
- Adjust seconds per image if needed.
- Click "Generate Video". Result is saved to ~/Downloads.

CLI usage (for engineers/operators who want to build locally):
- Run directly (requires Python and deps):
  python3 videogen_cli.py --images img1.jpg img2.jpg --audio-folder ~/Music --random --effect Fade
- Build a single-file CLI with PyInstaller (on mac):
  ./build_mac_app.sh  # installs deps
  ./venv/bin/pyinstaller --onefile --name VideoGeneratorCLI videogen_cli.py
  The produced binary will be in dist/

To build the .app GUI bundle as a double-clickable Mac app (internal distribution, self-signing optional):
- On a Mac, run: ./build_mac_app.sh
- The script will create a venv, install deps, optionally create an icon from ~/Downloads, and run PyInstaller.
- Test the resulting dist/VideoGenerator.app on a clean/local machine.
