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


COLORS = {
    "window_bg": "#e7edf6",
    "window_glow": "#f6fbff",
    "card_bg": "#f8fbff",
    "card_edge": "#ffffff",
    "card_shadow": "#c8d5e8",
    "text_primary": "#1b3551",
    "text_secondary": "#69809d",
    "accent": "#dbeafe",
    "accent_active": "#c8ddfb",
    "accent_border": "#97bdf3",
    "button_text": "#123b66",
    "button_secondary_bg": "#fbfdff",
    "button_secondary_active": "#eef4fb",
    "button_secondary_border": "#d5e1f2",
    "input_bg": "#fcfdff",
    "input_border": "#d8e3f2",
    "input_active": "#edf4ff",
}

STYLE_LABELS = {
    "Random": "Random / 随机",
    "None": "None / 无",
    "Fade": "Fade / 淡入淡出",
    "Zoom": "Zoom / 缓慢推近",
    "Mirror": "Mirror / 镜像",
    "BlackWhite": "BlackWhite / 黑白",
    "video": "video / 视频模板",
    "tk1": "tk1 / 模板一",
    "tk2": "tk2 / 模板二",
    "tk3": "tk3 / 模板三",
    "autotk": "autotk / 自动模板",
    "tkdemo": "tkdemo / 演示模板",
}

# minimal startup logging to /tmp for diagnosing missing UI elements in frozen app
try:
    with open('/tmp/vg_startup.log', 'a') as _lg:
        _lg.write(f'START import: {time.strftime("%Y-%m-%d %H:%M:%S")}\n')
except Exception:
    pass


class RoundedButton(tk.Canvas):
    def __init__(self, parent, text, command, width=220, height=46, radius=20, primary=False):
        bg = COLORS["accent"] if primary else COLORS["button_secondary_bg"]
        active_bg = COLORS["accent_active"] if primary else COLORS["button_secondary_active"]
        border = COLORS["accent_border"] if primary else COLORS["button_secondary_border"]
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=parent.cget("bg"),
            highlightthickness=0,
            bd=0,
            relief="flat",
            cursor="hand2",
        )
        self.command = command
        self.base_bg = bg
        self.active_bg = active_bg
        self.border = border
        self.radius = radius
        self.text = text
        self.width_px = width
        self.height_px = height
        self._draw(bg)
        for tag in ("button", "label"):
            self.tag_bind(tag, "<Button-1>", self._on_click)
            self.tag_bind(tag, "<Enter>", self._on_enter)
            self.tag_bind(tag, "<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _rounded_rect(self, x1, y1, x2, y2, radius, fill, outline):
        self.create_arc(x1, y1, x1 + radius * 2, y1 + radius * 2, start=90, extent=90, fill=fill, outline=outline, tags="button")
        self.create_arc(x2 - radius * 2, y1, x2, y1 + radius * 2, start=0, extent=90, fill=fill, outline=outline, tags="button")
        self.create_arc(x1, y2 - radius * 2, x1 + radius * 2, y2, start=180, extent=90, fill=fill, outline=outline, tags="button")
        self.create_arc(x2 - radius * 2, y2 - radius * 2, x2, y2, start=270, extent=90, fill=fill, outline=outline, tags="button")
        self.create_rectangle(x1 + radius, y1, x2 - radius, y2, fill=fill, outline=outline, tags="button")
        self.create_rectangle(x1, y1 + radius, x2, y2 - radius, fill=fill, outline=outline, tags="button")

    def _draw(self, fill_color):
        self.delete("all")
        inset = 2
        self._rounded_rect(inset, inset, self.width_px - inset, self.height_px - inset, self.radius, fill_color, self.border)
        self.create_line(18, 10, self.width_px - 18, 10, fill="#ffffff", width=1, tags="button")
        self.create_text(
            self.width_px / 2,
            self.height_px / 2,
            text=self.text,
            fill=COLORS["button_text"],
            font=("SF Pro Text", 11, "bold"),
            tags="label",
        )

    def _on_enter(self, _event):
        self._draw(self.active_bg)

    def _on_leave(self, _event):
        self._draw(self.base_bg)

    def _on_click(self, _event):
        if callable(self.command):
            self.command()

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        try:
            with open('/tmp/vg_startup.log', 'a') as _lg:
                _lg.write(f'INIT start: {time.strftime("%Y-%m-%d %H:%M:%S")}\n')
        except Exception:
            pass
        self.title("Video Generator / 视频生成器 - v20260424")
        self.geometry("920x700")
        self.minsize(880, 660)
        self.configure(bg=COLORS["window_bg"])
        self.images = []
        self.audio_path = None
        self.audio_folder = None
        self.music_folder = os.path.expanduser('~/Downloads/musics')
        self.external_styles = ["video","tk1","tk2","tk3","autotk","tkdemo"]
        self.audio_choice = tk.StringVar(value="random")
        self.duration_var = tk.StringVar(value="2.0")
        self.selected_music = tk.StringVar(value="Random / 随机")
        self.effect_display_var = tk.StringVar(value=STYLE_LABELS["Random"])
        self.is_generating = False

        self._build_background()
        self._build_ui()
        self.refresh_music_list()

        # Menu with Generate and Export Logs for accessibility
        try:
            with open('/tmp/vg_startup.log', 'a') as _lg:
                _lg.write(f'MENU start: {time.strftime("%Y-%m-%d %H:%M:%S")}\n')
        except Exception:
            pass
        menubar = tk.Menu(self)
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label='Generate Video / 生成视频', command=self.start_generate)
        filemenu.add_command(label='Export Logs / 导出日志', command=self.export_logs)
        filemenu.add_separator()
        filemenu.add_command(label='Quit / 退出', command=self.quit)
        menubar.add_cascade(label='File / 文件', menu=filemenu)
        self.config(menu=menubar)
        try:
            with open('/tmp/vg_startup.log', 'a') as _lg:
                _lg.write(f'BUTTONS packed: {time.strftime("%Y-%m-%d %H:%M:%S")}\n')
        except Exception:
            pass
        self._set_status("Ready / 就绪")

    def _set_busy_state(self, busy):
        self.is_generating = busy

        def walk_and_set_state(widget, state):
            for child in widget.winfo_children():
                try:
                    if child.winfo_class() in {"Button", "Radiobutton", "Entry", "Menubutton"}:
                        child.configure(state=state)
                except Exception:
                    pass
                walk_and_set_state(child, state)

        if busy:
            walk_and_set_state(self.content, "disabled")
            self.busy_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.busy_overlay.lift()
            self.update_idletasks()
            self._set_status("Generating... / 正在生成，请稍候...")
        else:
            self.busy_overlay.place_forget()
            walk_and_set_state(self.content, "normal")
            self._set_status("Ready / 就绪")

    def _build_background(self):
        self.bg_canvas = tk.Canvas(self, bg=COLORS["window_bg"], highlightthickness=0, bd=0)
        self.bg_canvas.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.bg_canvas.create_oval(-120, -80, 320, 280, fill="#f4f9ff", outline="")
        self.bg_canvas.create_oval(560, 40, 980, 420, fill="#dbe8fb", outline="")
        self.bg_canvas.create_oval(120, 460, 540, 880, fill="#edf3ff", outline="")
        self.bg_canvas.create_rectangle(18, 18, 902, 682, outline="#ffffff", width=1)
        self.bg_canvas.create_rectangle(20, 20, 900, 680, outline="#edf4ff", width=1)
        self.bg_canvas.create_line(28, 30, 892, 30, fill="#ffffff")

    def _make_card(self, parent):
        outer = tk.Frame(parent, bg=COLORS["card_shadow"], bd=0, highlightthickness=0)
        inner = tk.Frame(
            outer,
            bg=COLORS["card_bg"],
            bd=0,
            highlightbackground=COLORS["card_edge"],
            highlightcolor=COLORS["card_edge"],
            highlightthickness=1,
        )
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        return outer, inner

    def _make_button(self, parent, text, command, width=220, height=46, primary=False):
        # Prefer native Button for click reliability on macOS packaged app.
        bg = COLORS["accent"] if primary else COLORS["button_secondary_bg"]
        active_bg = COLORS["accent_active"] if primary else COLORS["button_secondary_active"]
        border = COLORS["accent_border"] if primary else COLORS["button_secondary_border"]
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=COLORS["button_text"],
            activebackground=active_bg,
            activeforeground=COLORS["button_text"],
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=border,
            highlightcolor=border,
            padx=14,
            pady=max(8, int(height / 6)),
            width=max(10, int(width / 12)),
            cursor="hand2",
            font=("SF Pro Text", 11, "bold"),
        )

    def _make_label(self, parent, text, secondary=False, **kwargs):
        color = COLORS["text_secondary"] if secondary else COLORS["text_primary"]
        return tk.Label(parent, text=text, bg=COLORS["card_bg"], fg=color, **kwargs)

    def _make_radio(self, parent, text, variable, value):
        return tk.Radiobutton(
            parent,
            text=text,
            variable=variable,
            value=value,
            bg=COLORS["card_bg"],
            fg=COLORS["text_primary"],
            activebackground=COLORS["card_bg"],
            activeforeground=COLORS["text_primary"],
            selectcolor="#f4f8ff",
            highlightthickness=0,
            anchor="w",
            font=("SF Pro Text", 11),
        )

    def _build_ui(self):
        self.content = tk.Frame(self, bg=COLORS["window_bg"])
        self.content.pack(fill="both", expand=True, padx=18, pady=18)

        header_card, header = self._make_card(self.content)
        header.pack(fill="x", padx=18, pady=(18, 12))
        self._make_label(header, "Video Generator / 视频生成器", font=("SF Pro Display", 24, "bold")).pack(anchor="w", padx=22, pady=(18, 4))
        self._make_label(
            header,
            "Build portrait videos from local images and music / 用本地图片与音乐生成竖版视频",
            secondary=True,
            font=("SF Pro Text", 12),
        ).pack(anchor="w", padx=22, pady=(0, 18))
        self._make_label(
            header,
            "风格未选自动随机 / If style is not selected, a random style will be used",
            secondary=True,
            font=("SF Pro Text", 10),
        ).pack(anchor="w", padx=22, pady=(0, 14))

        media_card, media = self._make_card(self.content)
        media_card.pack(fill="x", padx=18, pady=12)
        self._make_label(media, "Images / 图片", font=("SF Pro Text", 15, "bold")).pack(anchor="w", padx=20, pady=(16, 6))
        action_row = tk.Frame(media, bg=COLORS["card_bg"])
        action_row.pack(fill="x", padx=20, pady=(0, 8))
        self._make_button(action_row, "Select Images / 选择图片", self.select_images, width=230, height=48, primary=True).pack(side="left")
        self.images_label = self._make_label(
            action_row,
            "No images selected / 未选择图片",
            secondary=True,
            font=("SF Pro Text", 11),
            wraplength=450,
            justify="left",
        )
        self.images_label.pack(side="left", padx=14)

        audio_card, audio = self._make_card(self.content)
        audio_card.pack(fill="x", padx=18, pady=12)
        self._make_label(audio, "Audio / 音频", font=("SF Pro Text", 15, "bold")).pack(anchor="w", padx=20, pady=(16, 6))

        audio_mode = tk.Frame(audio, bg=COLORS["card_bg"])
        audio_mode.pack(fill="x", padx=20, pady=(0, 8))
        self._make_radio(audio_mode, "Random audio from folder / 从文件夹随机选音乐", self.audio_choice, "random").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=4)
        self._make_button(audio_mode, "Choose Folder / 选择文件夹", self.select_audio_folder, width=220, height=44).grid(row=0, column=1, sticky="w", pady=4)
        self._make_radio(audio_mode, "Specific audio file / 指定音频文件", self.audio_choice, "specific").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=4)
        self._make_button(audio_mode, "Choose File / 选择文件", self.select_audio_file, width=220, height=44).grid(row=1, column=1, sticky="w", pady=4)

        self.audio_label = self._make_label(
            audio,
            "No audio selected / 未选择音频",
            secondary=True,
            font=("SF Pro Text", 11),
            wraplength=760,
            justify="left",
        )
        self.audio_label.pack(anchor="w", padx=20, pady=(2, 10))

        folder_row = tk.Frame(audio, bg=COLORS["card_bg"])
        folder_row.pack(fill="x", padx=20, pady=(0, 8))
        self._make_label(folder_row, "Music folder / 音乐目录", font=("SF Pro Text", 11, "bold")).pack(side="left")
        self.music_folder_label = self._make_label(folder_row, self.music_folder, secondary=True, font=("SF Pro Text", 10), wraplength=470, justify="left")
        self.music_folder_label.pack(side="left", padx=12)
        self._make_button(folder_row, "Change / 更改", self.select_audio_folder, width=148, height=40).pack(side="right")

        picker_row = tk.Frame(audio, bg=COLORS["card_bg"])
        picker_row.pack(fill="x", padx=20, pady=(0, 16))
        self._make_label(picker_row, "Track / 曲目", font=("SF Pro Text", 11, "bold")).pack(side="left")
        self.music_menu = tk.OptionMenu(picker_row, self.selected_music, "Random / 随机")
        self.music_menu.config(
            width=28,
            bg=COLORS["input_bg"],
            fg=COLORS["text_primary"],
            activebackground=COLORS["input_active"],
            activeforeground=COLORS["text_primary"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLORS["input_border"],
            font=("SF Pro Text", 11),
            )
        self.music_menu["menu"].config(bg=COLORS["input_bg"], fg=COLORS["text_primary"], activebackground=COLORS["input_active"], activeforeground=COLORS["text_primary"], font=("SF Pro Text", 11))
        self.music_menu.pack(side="left", padx=12)
        self._make_button(picker_row, "Refresh / 刷新", self.refresh_music_list, width=148, height=40).pack(side="left")

        settings_card, settings = self._make_card(self.content)
        settings_card.pack(fill="x", padx=18, pady=12)
        self._make_label(settings, "Output / 输出设置", font=("SF Pro Text", 15, "bold")).pack(anchor="w", padx=20, pady=(16, 6))
        settings_row = tk.Frame(settings, bg=COLORS["card_bg"])
        settings_row.pack(fill="x", padx=20, pady=(0, 16))

        self._make_label(settings_row, "Seconds per image / 每张图片秒数", font=("SF Pro Text", 11, "bold")).grid(row=0, column=0, sticky="w")
        tk.Entry(
            settings_row,
            textvariable=self.duration_var,
            width=8,
            bg=COLORS["input_bg"],
            fg=COLORS["text_primary"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLORS["input_border"],
            font=("SF Pro Text", 11),
            insertbackground=COLORS["text_primary"],
        ).grid(row=0, column=1, sticky="w", padx=(10, 24))

        self._make_label(settings_row, "Style / 风格", font=("SF Pro Text", 11, "bold")).grid(row=0, column=2, sticky="w")
        choices = [STYLE_LABELS[key] for key in ["Random", "None", "Fade", "Zoom", "Mirror", "BlackWhite"] + self.external_styles]
        self.effect_menu = tk.OptionMenu(settings_row, self.effect_display_var, *choices)
        self.effect_menu.config(
            width=24,
            bg=COLORS["input_bg"],
            fg=COLORS["text_primary"],
            activebackground=COLORS["input_active"],
            activeforeground=COLORS["text_primary"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLORS["input_border"],
            font=("SF Pro Text", 11),
        )
        self.effect_menu["menu"].config(bg=COLORS["input_bg"], fg=COLORS["text_primary"], activebackground=COLORS["input_active"], activeforeground=COLORS["text_primary"], font=("SF Pro Text", 11))
        self.effect_menu.grid(row=0, column=3, sticky="w", padx=(10, 0))

        footer_card, footer = self._make_card(self.content)
        footer_card.pack(fill="x", padx=18, pady=(12, 18))
        btn_frame = tk.Frame(footer, bg=COLORS["card_bg"])
        btn_frame.pack(fill="x", padx=20, pady=(16, 10))
        self._make_button(btn_frame, "Generate Video / 生成视频", self.start_generate, width=250, height=54, primary=True).pack(side='left')
        self._make_button(btn_frame, "Export Logs / 导出日志", self.export_logs, width=230, height=54).pack(side='left', padx=12)
        self.status = self._make_label(footer, "Ready / 就绪", secondary=True, font=("SF Pro Text", 11), wraplength=760, justify="left")
        self.status.pack(anchor="w", padx=20, pady=(0, 16))

        # Gray overlay while generating to prevent repeated clicks.
        self.busy_overlay = tk.Frame(self.content, bg="#d3dbe7", bd=0, highlightthickness=0)
        tk.Label(
            self.busy_overlay,
            text="Generating video, please wait... / 正在生成视频，请稍候...",
            bg="#d3dbe7",
            fg=COLORS["text_primary"],
            font=("SF Pro Text", 12, "bold"),
        ).pack(expand=True)

    def _set_status(self, text):
        if hasattr(self, "status"):
            self.status.config(text=text)

    def select_images(self):
        paths = filedialog.askopenfilenames(title="Select Images / 选择图片", filetypes=[("Images / 图片", "*.png *.jpg *.jpeg *.bmp *.gif")])
        if paths:
            self.images = list(paths)
            self.images_label.config(text=f"{len(self.images)} images selected / 已选择 {len(self.images)} 张图片")

    def select_audio_file(self):
        path = filedialog.askopenfilename(title="Select Audio / 选择音频", filetypes=[("Audio / 音频", "*.mp3 *.wav *.m4a *.aac")])
        if path:
            self.audio_path = path
            self.audio_label.config(text=f"Selected file / 已选文件: {os.path.basename(path)}")

    def select_audio_folder(self):
        path = filedialog.askdirectory(title="Select Audio Folder / 选择音频文件夹")
        if path:
            self.audio_folder = path
            self.music_folder = path
            self.audio_label.config(text=f"Audio folder / 音频目录: {path}")
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
            menu.add_command(label='Random / 随机', command=lambda: self.selected_music.set('Random / 随机'))
            for fn in files:
                menu.add_command(label=fn, command=lambda v=fn: self.selected_music.set(v))
            # keep current selection if still valid
            current = self.selected_music.get()
            if current not in (['Random / 随机'] + files):
                self.selected_music.set('Random / 随机')
        except Exception:
            # if widget not ready, ignore
            pass

    def start_generate(self):
        if self.is_generating:
            messagebox.showinfo("Busy / 忙碌中", "Video is already generating.\n正在生成中，请勿重复点击。")
            return
        if not self.images:
            messagebox.showerror("Error / 错误", "Please select at least one image.\n请至少选择一张图片。")
            return
        try:
            duration = float(self.duration_var.get())
            if duration <= 0:
                raise ValueError()
        except Exception:
            messagebox.showerror("Error / 错误", "Invalid duration.\n秒数无效。")
            return
        # choose audio depending on choice and selected music
        audio_choice = self.audio_choice.get()
        audio_path = None
        chosen = self.selected_music.get() if hasattr(self, 'selected_music') else 'Random / 随机'
        # priority: if user selected specific file via file dialog, use that
        if audio_choice == "specific" and self.audio_path:
            audio_path = self.audio_path
        elif chosen and chosen != 'Random / 随机':
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
                messagebox.showerror("Error / 错误", "Please choose an audio folder for random selection.\n请先选择随机音频文件夹。")
                return
            auds = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith((".mp3", ".wav", ".m4a", ".aac"))]
            if not auds:
                messagebox.showerror("Error / 错误", f"No audio files found in folder:\n{folder}\n\n该目录下没有可用音频文件。")
                return
            audio_path = random.choice(auds)

        out_dir = os.path.expanduser("~/Downloads")
        ts = time.strftime("%Y%m%d-%H%M%S")
        out_path = os.path.join(out_dir, f"video_{ts}.mp4")
        selected_effect = next((key for key, label in STYLE_LABELS.items() if label == self.effect_display_var.get()), "Random")
        if selected_effect == "Random":
            selected_effect = random.choice(["None", "Fade", "Zoom", "Mirror", "BlackWhite"] + self.external_styles)

        # Run generation in thread
        self._set_busy_state(True)
        t = threading.Thread(target=self.generate_video, args=(self.images, duration, audio_path, out_path, selected_effect), daemon=True)
        t.start()

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
                                self.after(0, lambda: self._set_status(f"Saved / 已保存: {out_path}"))
                                self.after(0, lambda: messagebox.showinfo("Done / 完成", f"Video saved to:\n{out_path}\n\n视频已保存到以上路径。"))
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
                self.after(0, lambda: self._set_status(f"Saved / 已保存: {out_path}"))
                self.after(0, lambda: messagebox.showinfo("Done / 完成", f"Video saved to:\n{out_path}\n\n视频已保存到以上路径。"))
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
            self.after(0, lambda: messagebox.showerror("Error / 错误", f"Failed to generate video:\n{e}\n\nDetails written to /tmp/vg_run.log\n详细日志已写入 /tmp/vg_run.log"))
            self.after(0, lambda: self._set_status("Error / 出错"))
        finally:
            self.after(0, lambda: self._set_busy_state(False))

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
                fh.write(f'Current style/effect: {self.effect_display_var.get()}\n')
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
            messagebox.showinfo('Export Logs / 导出日志', f'Logs exported to:\n{out}\n\n日志压缩包已导出到以上路径。')
        except Exception as e:
            messagebox.showerror('Error / 错误', f'Failed to export logs:\n{e}\n\n导出日志失败。')

if __name__ == '__main__':
    app = AppWithLogs()
    app.mainloop()
