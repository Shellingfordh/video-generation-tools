#!/usr/bin/env python3
"""
Simple macOS double-clickable app to build a video from selected images
and an optional local audio file (random or specified). Outputs to ~/Downloads.
"""

import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import os
import time
import random
import subprocess
import tempfile
import shutil
import tarfile
import platform
# Workaround for PyInstaller importlib.metadata PackageNotFoundError for imageio
# Patch importlib.metadata.version to return a sensible fallback for imageio when
# package metadata is not discoverable in the frozen bundle.
import importlib.metadata as _md
_orig_md_version = _md.version

def _md_version_patch(name, *a, **kw):
    try:
        return _orig_md_version(name, *a, **kw)
    except Exception:
        if isinstance(name, str) and name.lower() == 'imageio':
            return '2.37.3'
        raise

_md.version = _md_version_patch

# Ensure temporary files are written to a writable location (avoid app bundle)
import tempfile
import os
try:
    os.environ.setdefault('TMPDIR', '/tmp')
    os.environ.setdefault('TMP', '/tmp')
    os.environ.setdefault('TEMP', '/tmp')
    tempfile.tempdir = '/tmp'
except Exception:
    pass

# Pillow compatibility shim: ensure ANTIALIAS exists for older MoviePy/Pillow expectations
from PIL import Image as _PIL_Image
try:
    _PIL_Image.ANTIALIAS
except Exception:
    try:
        _PIL_Image.ANTIALIAS = _PIL_Image.Resampling.LANCZOS
    except Exception:
        _PIL_Image.ANTIALIAS = getattr(_PIL_Image, 'LANCZOS', 1)

from moviepy.editor import concatenate_videoclips, AudioFileClip
from moviepy.audio.fx.all import audio_loop
from video_layout import choose_output_profile, build_styled_clip

# minimal startup logging to /tmp for diagnosing missing UI elements in frozen app
try:
    with open('/tmp/vg_startup.log', 'a') as _lg:
        _lg.write(f'START import: {time.strftime("%Y-%m-%d %H:%M:%S")}\n')
except Exception:
    pass

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        try:
            with open('/tmp/vg_startup.log', 'a') as _lg:
                _lg.write(f'INIT start: {time.strftime("%Y-%m-%d %H:%M:%S")}\n')
        except Exception:
            pass
        self.title("Video Generator - v20260422")
        self.geometry("720x520")
        self.images = []
        self.audio_path = None
        self.audio_folder = None

        tk.Button(self, text="Select Images", command=self.select_images).pack(pady=6)
        self.images_label = tk.Label(self, text="No images selected")
        self.images_label.pack()

        # Audio selection
        self.audio_choice = tk.StringVar(value="random")
        frame = tk.Frame(self)
        frame.pack(pady=8)
        tk.Radiobutton(frame, text="Random audio from folder", variable=self.audio_choice, value="random").grid(row=0, column=0, sticky="w")
        tk.Button(frame, text="Choose Audio Folder", command=self.select_audio_folder).grid(row=0, column=1, padx=6)
        tk.Radiobutton(frame, text="Specific audio file", variable=self.audio_choice, value="specific").grid(row=1, column=0, sticky="w")
        tk.Button(frame, text="Choose Audio File", command=self.select_audio_file).grid(row=1, column=1, padx=6)
        self.audio_label = tk.Label(self, text="No audio selected")
        self.audio_label.pack()

        # Music folder default label (for user's info)
        mf_row = tk.Frame(self)
        mf_row.pack(pady=4)
        tk.Label(mf_row, text="Music folder:").pack(side="left")
        self.music_folder = os.path.expanduser('~/Downloads/musics')
        self.music_folder_label = tk.Label(mf_row, text=self.music_folder)
        self.music_folder_label.pack(side="left", padx=6)
        tk.Button(mf_row, text="Change", command=self.select_audio_folder).pack(side="left")

        # Music picker (dropdown of files in music folder)
        music_picker_row = tk.Frame(self)
        music_picker_row.pack(pady=4)
        tk.Label(music_picker_row, text="Pick music:").pack(side="left")
        self.selected_music = tk.StringVar(value="Random")
        self.music_menu = tk.OptionMenu(music_picker_row, self.selected_music, "Random")
        self.music_menu.pack(side="left", padx=6)
        tk.Button(music_picker_row, text="Refresh", command=self.refresh_music_list).pack(side="left")
        # initialize list
        self.refresh_music_list()

        # Image duration per image
        row = tk.Frame(self)
        row.pack(pady=6)
        tk.Label(row, text="Seconds per image:").pack(side="left")
        self.duration_var = tk.StringVar(value="2.0")
        tk.Entry(row, textvariable=self.duration_var, width=6).pack(side="left")

        # Style selection
        style_row = tk.Frame(self)
        style_row.pack(pady=6)
        tk.Label(style_row, text="Style:").pack(side="left")
        # built-in effects + external scripts from repo
        self.external_styles = ["video","tk1","tk2","tk3","autotk","tkdemo"]
        choices = ["None", "Fade", "Zoom", "Mirror", "BlackWhite"] + self.external_styles
        self.effect_var = tk.StringVar(value="None")
        tk.OptionMenu(style_row, self.effect_var, *choices).pack(side="left")

        # Menu with Generate and Export Logs for accessibility
        try:
            with open('/tmp/vg_startup.log', 'a') as _lg:
                _lg.write(f'MENU start: {time.strftime("%Y-%m-%d %H:%M:%S")}\n')
        except Exception:
            pass
        menubar = tk.Menu(self)
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label='Generate Video', command=self.start_generate)
        filemenu.add_command(label='Export Logs', command=self.export_logs)
        filemenu.add_separator()
        filemenu.add_command(label='Quit', command=self.quit)
        menubar.add_cascade(label='File', menu=filemenu)
        self.config(menu=menubar)

        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=12)
        tk.Button(btn_frame, text="Generate Video", command=self.start_generate, width=20).pack(side='left', padx=8)
        tk.Button(btn_frame, text="Export Logs", command=self.export_logs, width=16).pack(side='left')
        try:
            with open('/tmp/vg_startup.log', 'a') as _lg:
                _lg.write(f'BUTTONS packed: {time.strftime("%Y-%m-%d %H:%M:%S")}\n')
        except Exception:
            pass
        self.status = tk.Label(self, text="Ready")
        self.status.pack()

    def select_images(self):
        paths = filedialog.askopenfilenames(title="Select images", filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif")])
        if paths:
            self.images = list(paths)
            self.images_label.config(text=f"{len(self.images)} images selected")

    def select_audio_file(self):
        path = filedialog.askopenfilename(title="Select audio", filetypes=[("Audio", "*.mp3 *.wav *.m4a *.aac")])
        if path:
            self.audio_path = path
            self.audio_label.config(text=os.path.basename(path))

    def select_audio_folder(self):
        path = filedialog.askdirectory(title="Select audio folder")
        if path:
            self.audio_folder = path
            self.music_folder = path
            self.audio_label.config(text=f"Folder: {path}")
            self.music_folder_label.config(text=self.music_folder)
            self.refresh_music_list()

    def refresh_music_list(self):
        # populate the music dropdown from self.music_folder
        try:
            folder = getattr(self, 'music_folder', os.path.expanduser('~/Downloads/musics'))
            files = [f for f in os.listdir(folder) if f.lower().endswith(('.mp3', '.wav', '.m4a', '.aac'))]
            files = sorted(files)
        except Exception:
            files = []

        try:
            menu = self.music_menu['menu']
            menu.delete(0, 'end')
            menu.add_command(label='Random', command=lambda: self.selected_music.set('Random'))
            for fn in files:
                menu.add_command(label=fn, command=lambda v=fn: self.selected_music.set(v))
            # keep current selection if still valid
            current = self.selected_music.get()
            if current not in (['Random'] + files):
                self.selected_music.set('Random')
        except Exception:
            # if widget not ready, ignore
            pass

    def start_generate(self):
        if not self.images:
            messagebox.showerror("Error", "Please select at least one image.")
            return
        try:
            duration = float(self.duration_var.get())
            if duration <= 0:
                raise ValueError()
        except Exception:
            messagebox.showerror("Error", "Invalid duration")
            return
        # choose audio depending on choice and selected music
        audio_choice = self.audio_choice.get()
        audio_path = None
        chosen = self.selected_music.get() if hasattr(self, 'selected_music') else 'Random'
        # priority: if user selected specific file via file dialog, use that
        if audio_choice == "specific" and self.audio_path:
            audio_path = self.audio_path
        elif chosen and chosen != 'Random':
            # selected from dropdown
            candidate = os.path.join(self.music_folder, chosen)
            if os.path.isfile(candidate):
                audio_path = candidate
            else:
                # maybe user selected absolute path
                if os.path.isfile(chosen):
                    audio_path = chosen
        else:
            # random: prefer chosen audio_folder then default music_folder
            folder = self.audio_folder or self.music_folder
            if not folder:
                messagebox.showerror("Error", "Please choose an audio folder for random selection.")
                return
            auds = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith((".mp3", ".wav", ".m4a", ".aac"))]
            if not auds:
                messagebox.showerror("Error", f"No audio files found in folder: {folder}")
                return
            audio_path = random.choice(auds)

        out_dir = os.path.expanduser("~/Downloads")
        ts = time.strftime("%Y%m%d-%H%M%S")
        out_path = os.path.join(out_dir, f"video_{ts}.mp4")

        # Run generation in thread
        t = threading.Thread(target=self.generate_video, args=(self.images, duration, audio_path, out_path, self.effect_var.get()), daemon=True)
        t.start()
        self.status.config(text="Generating...")

    def generate_video(self, images, duration, audio_path, out_path, effect):
        try:
            # If effect is one of external styles and repo exists, try to run external script
            if effect in self.external_styles:
                external_enabled = os.environ.get('VG_ENABLE_EXTERNAL_STYLES') == '1'
                repo_path = os.path.expanduser('~/video-generation-tools')
                script_candidates = [os.path.join(repo_path, 'scripts', f'{effect}.py'), os.path.join(repo_path, f'{effect}.py')]
                script = next((s for s in script_candidates if os.path.isfile(s)), None) if external_enabled else None
                if script:
                    # prepare temp images dir
                    tmp = tempfile.mkdtemp(prefix='vg-images-')
                    try:
                        for idx, p in enumerate(images):
                            ext = os.path.splitext(p)[1]
                            dst = os.path.join(tmp, f'{idx:04d}{ext}')
                            shutil.copy(p, dst)
                        # Probe script help and adapt arg names across different external scripts.
                        help_proc = subprocess.run(
                            ['python3', script, '--help'],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                        )
                        help_text = (help_proc.stdout or '').lower()
                        if '--img_dir' in help_text:
                            img_flag = '--img_dir'
                        elif '--img-dir' in help_text:
                            img_flag = '--img-dir'
                        else:
                            img_flag = '--input'

                        if '--music_dir' in help_text:
                            audio_flag = '--music_dir'
                        elif '--music-dir' in help_text:
                            audio_flag = '--music-dir'
                        else:
                            audio_flag = '--audio'

                        if '--output_file' in help_text:
                            out_flag = '--output_file'
                        elif '--output-file' in help_text:
                            out_flag = '--output-file'
                        else:
                            out_flag = '--output'

                        cmd = ['python3', script, img_flag, tmp, audio_flag, audio_path or '', out_flag, out_path]
                        with open('/tmp/vg_run.log', 'a') as lg:
                            lg.write(f'External script cmd: {" ".join(cmd)}\n')

                        try:
                            proc = subprocess.run(
                                cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                text=True,
                                timeout=30,
                            )
                            with open('/tmp/vg_run.log', 'a') as lg:
                                lg.write(proc.stdout or '')
                            if proc.returncode == 0 and os.path.isfile(out_path):
                                self.status.config(text=f"Saved: {out_path}")
                                messagebox.showinfo("Done", f"Video saved to:\n{out_path}")
                                return
                            with open('/tmp/vg_run.log', 'a') as lg:
                                lg.write(f'External script failed or no output, fallback style for {effect}\n')
                        except subprocess.TimeoutExpired:
                            with open('/tmp/vg_run.log', 'a') as lg:
                                lg.write(f'External script timed out after 30s, fallback style for {effect}\n')
                    finally:
                        shutil.rmtree(tmp, ignore_errors=True)

                else:
                    with open('/tmp/vg_run.log', 'a') as lg:
                        lg.write(f'External styles disabled, fallback style for {effect}\n')

                # fallback: map external style to a built-in approximation
                mapping = {
                    'video': 'Zoom',
                    'tk1': 'Fade',
                    'tk2': 'Zoom',
                    'tk3': 'Mirror',
                    'autotk': 'Fade',
                    'tkdemo': 'Fade'
                }
                effect = mapping.get(effect, 'None')

            clips = []
            fade_dur = min(0.6, max(0.05, duration * 0.2))
            profile_name, target_size, profile_counts = choose_output_profile(images)
            with open('/tmp/vg_run.log', 'a') as lg:
                lg.write(f'Output profile: {profile_name} {target_size} counts={profile_counts}\\n')
            for p in images:
                clip = build_styled_clip(p, duration, effect, target_size, fade_dur)
                clips.append(clip)
            video = concatenate_videoclips(clips, method="compose")
            if audio_path:
                # Validate audio before attaching. If random selection, try others on failure.
                def try_audio(path):
                    try:
                        a = AudioFileClip(path)
                        a.close()
                        return True
                    except Exception as _e:
                        import traceback
                        with open('/tmp/vg_run.log', 'a') as lg:
                            lg.write(f'Audio validation failed for {path}: {_e}\n')
                            traceback.print_exc(file=lg)
                        return False

                # If this was random selection, attempt to fall back to other files in folder
                if self.audio_choice.get() == 'random':
                    folder = self.audio_folder or self.music_folder
                    candidates = []
                    try:
                        candidates = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(('.mp3', '.wav', '.m4a', '.aac'))]
                        random.shuffle(candidates)
                    except Exception:
                        candidates = [audio_path]
                    valid = None
                    for c in candidates:
                        if try_audio(c):
                            valid = c
                            break
                    if valid:
                        audio_path = valid
                    else:
                        with open('/tmp/vg_run.log', 'a') as lg:
                            lg.write(f'No valid audio in folder {folder}, proceeding without audio\n')
                        audio_path = None
                else:
                    if not try_audio(audio_path):
                        raise RuntimeError(f'Audio file invalid or corrupted: {audio_path}')

            if audio_path:
                audio = AudioFileClip(audio_path)
                if audio.duration < video.duration:
                    audio = audio_loop(audio, duration=video.duration)
                else:
                    audio = audio.subclip(0, min(audio.duration, video.duration))
                video = video.set_audio(audio)

            # write file (removed unsupported progress_bar arg)
            # Ensure ffmpeg temporary files are written to a writable directory (e.g., /tmp)
            old_cwd = None
            try:
                old_cwd = os.getcwd()
            except Exception:
                old_cwd = None
            try:
                os.chdir(tempfile.gettempdir())
            except Exception:
                pass
            try:
                video.write_videofile(out_path, fps=24, codec="libx264", audio_codec="aac", threads=4, verbose=False)
                self.status.config(text=f"Saved: {out_path}")
                messagebox.showinfo("Done", f"Video saved to:\n{out_path}")
            finally:
                try:
                    if old_cwd:
                        os.chdir(old_cwd)
                except Exception:
                    pass
        except Exception as e:
            import traceback
            with open('/tmp/vg_run.log', 'a') as lg:
                lg.write(f'Failed to generate video: {e}\n')
                traceback.print_exc(file=lg)
            messagebox.showerror("Error", f"Failed to generate video:\n{e}\n(Details written to /tmp/vg_run.log)")
            self.status.config(text="Error")

def export_files_list(src_files, dst_dir):
    for p in src_files:
        try:
            if os.path.exists(p):
                shutil.copy(p, dst_dir)
        except Exception:
            pass

def export_warn_files(build_dir, dst_dir):
    # copy any warn-*.txt produced by PyInstaller
    try:
        for root, dirs, files in os.walk(build_dir):
            for f in files:
                if f.startswith('warn-') and f.endswith('.txt'):
                    shutil.copy(os.path.join(root, f), dst_dir)
    except Exception:
        pass

class AppWithLogs(App):
    def export_logs(self):
        try:
            ts = time.strftime('%Y%m%d-%H%M%S')
            tmp = tempfile.mkdtemp(prefix='vg-logs-')
            diag = os.path.join(tmp, 'diagnostics.txt')
            with open(diag, 'w') as fh:
                fh.write(f'Timestamp: {ts}\n')
                fh.write(f'Platform: {platform.platform()}\n')
                fh.write(f'Python: {platform.python_version()}\n')
                fh.write(f'Music folder: {self.music_folder}\n')
                fh.write(f'Images selected: {len(self.images)}\n')
                fh.write(f'Current style/effect: {self.effect_var.get()}\n')
                fh.write(f'Audio selection mode: {self.audio_choice.get()}\n')

            candidates = ['/tmp/vg_demo.log', '/tmp/vg_demo_src.log', '/tmp/vg_run.log', '/tmp/vg.log']
            export_files_list(candidates, tmp)

            # include build warn files
            build_dir = os.path.join(os.path.dirname(__file__), 'build')
            export_warn_files(build_dir, tmp)

            # include the app logs in project (if any)
            project_logs = os.path.join(os.path.dirname(__file__), 'dist')
            export_warn_files(project_logs, tmp)

            # create archive
            out = os.path.expanduser(f'~/Downloads/VideoGenerator_logs_{ts}.tgz')
            with tarfile.open(out, 'w:gz') as tar:
                tar.add(tmp, arcname=os.path.basename(tmp))

            shutil.rmtree(tmp, ignore_errors=True)
            messagebox.showinfo('Export Logs', f'Logs exported to:\n{out}')
        except Exception as e:
            messagebox.showerror('Error', f'Failed to export logs:\n{e}')

if __name__ == '__main__':
    app = AppWithLogs()
    app.mainloop()
