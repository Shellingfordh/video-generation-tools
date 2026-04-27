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

Code structure and module responsibilities:

- main.py
  - GUI entry point (Tkinter desktop app).
  - Handles image/audio selection, style selection, bilingual UI text, status updates, and button interactions.
  - Runs video generation in a background thread and controls UI lock/unlock while generating.
  - Supports exporting diagnostic logs to ~/Downloads/VideoGenerator_logs_*.tgz.

- videogen_cli.py
  - Command-line entry point for batch or scripted usage.
  - Parses CLI arguments (images, audio, seconds per image, style, output path).
  - Uses the same rendering logic as GUI so behavior is consistent.
  - Supports external style names with fallback mapping to built-in effects.

- video_layout.py
  - Shared rendering/layout logic used by both GUI and CLI.
  - Chooses output aspect profile based on input images (3:4 vs 9:16 majority).
  - Preprocesses images into a fixed canvas and builds per-style clips safely.
  - Prevents crashes caused by mixed/unsupported image dimensions.

- build_mac_app.sh
  - Build automation script for macOS packaging.
  - Creates/uses virtualenv, installs dependencies, and runs PyInstaller.
  - Produces distribution artifacts under dist/ (app bundle and packaging inputs).

- VideoGenerator.spec / VideoGeneratorCLI.spec
  - PyInstaller build configuration files.
  - Define included files, hidden imports, app metadata, and output form (.app / CLI).

- requirements.txt
  - Python dependency list for runtime and packaging.
  - Keep this file as the source of truth for reproducible builds.

- dist/ and build/ (generated artifacts)
  - dist/: final build outputs (app bundle, CLI binary, DMG input files).
  - build/: intermediate PyInstaller work files and diagnostics.
  - These are generated files, not core source logic.
