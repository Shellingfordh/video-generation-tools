#!/usr/bin/env python3
"""Command-line video generator.
Usage examples:
  ./videogen_cli.py --images img1.jpg img2.jpg --audio-folder ~/Music --random --effect Fade
  ./videogen_cli.py --images-dir ./pics --audio-file bg.mp3 --seconds 1.5 --output ~/Downloads/out.mp4
"""
import argparse
import os
import random
import time
import tempfile
import shutil
import subprocess
# Pillow compatibility shim: newer Pillow moved ANTIALIAS to Resampling; ensure older attribute exists
from PIL import Image as _PIL_Image
try:
    # Pillow 9.1+: Resampling enum
    _PIL_Image.ANTIALIAS
except Exception:
    try:
        _PIL_Image.ANTIALIAS = _PIL_Image.Resampling.LANCZOS
    except Exception:
        # last resort: try LANCZOS or set to a numeric fallback
        _PIL_Image.ANTIALIAS = getattr(_PIL_Image, 'LANCZOS', 1)

from moviepy.editor import concatenate_videoclips, AudioFileClip
from moviepy.audio.fx.all import audio_loop
from video_layout import choose_output_profile, build_styled_clip


def find_images_in_dir(d):
    exts = ('.png', '.jpg', '.jpeg', '.bmp', '.gif')
    return [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.lower().endswith(exts)]


def pick_random_audio(folder):
    exts = ('.mp3', '.wav', '.m4a', '.aac')
    files = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(exts)]
    if not files:
        raise SystemExit('No audio files found in folder: ' + folder)
    return random.choice(files)


def build_video(images, seconds, audio_path, out_path, effect):
    clips = []
    fade_dur = min(0.6, max(0.05, seconds * 0.2))
    profile_name, target_size, profile_counts = choose_output_profile(images)
    print(f'Output profile: {profile_name} {target_size} counts={profile_counts}')
    for p in images:
        clip = build_styled_clip(p, seconds, effect, target_size, fade_dur)
        clips.append(clip)
    video = concatenate_videoclips(clips, method='compose')
    if audio_path:
        audio = AudioFileClip(audio_path)
        if audio.duration < video.duration:
            audio = audio_loop(audio, duration=video.duration)
        else:
            audio = audio.subclip(0, min(audio.duration, video.duration))
        video = video.set_audio(audio)
    video.write_videofile(out_path, fps=24, codec='libx264', audio_codec='aac', threads=4)


def main():
    p = argparse.ArgumentParser(description='Video generator CLI (images + optional audio -> mp4)')
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--images', nargs='+', help='List of image files in order')
    group.add_argument('--images-dir', help='Directory containing images (sorted)')
    p.add_argument('--audio-file', help='Specific audio file')
    p.add_argument('--audio-folder', help='Folder to pick random audio from (default ~/Downloads/musics)')
    p.add_argument('--random', action='store_true', help='Pick random audio from audio-folder')
    p.add_argument('--seconds', type=float, default=2.0, help='Seconds per image (default 2.0)')
    p.add_argument('--style', dest='effect', choices=['None', 'Fade', 'Zoom', 'Mirror', 'BlackWhite','video','tk1','tk2','tk3','autotk','tkdemo'], default='None', help='Visual style or external script')
    p.add_argument('--output', help='Output path (default ~/Downloads/video_TIMESTAMP.mp4)')
    args = p.parse_args()

    if args.images:
        images = args.images
    else:
        if not os.path.isdir(args.images_dir):
            raise SystemExit('images-dir not found: ' + args.images_dir)
        images = find_images_in_dir(args.images_dir)

    if not images:
        raise SystemExit('No images found/selected')

    audio_path = None
    if args.audio_file:
        if not os.path.isfile(args.audio_file):
            raise SystemExit('audio-file not found: ' + args.audio_file)
        audio_path = args.audio_file
    elif args.random:
        folder = args.audio_folder or os.path.expanduser('~/Downloads/musics')
        audio_path = pick_random_audio(folder)
    elif args.audio_folder:
        # if folder provided but not --random, pick first file
        files = [os.path.join(args.audio_folder, f) for f in os.listdir(args.audio_folder) if f.lower().endswith(('.mp3', '.wav', '.m4a', '.aac'))]
        if files:
            audio_path = files[0]

    out = args.output or os.path.expanduser('~/Downloads/video_') + time.strftime('%Y%m%d-%H%M%S') + '.mp4'
    out = os.path.expanduser(out)

    print('Building video...')
    print(f'Images: {len(images)}  Audio: {audio_path or "(none)"}  Style: {args.effect}  Seconds/image: {args.seconds}  Out: {out}')
    # If effect is external style and repo present, try running external script
    external_styles = ['video','tk1','tk2','tk3','autotk','tkdemo']
    external_enabled = os.environ.get('VG_ENABLE_EXTERNAL_STYLES') == '1'
    if args.effect in external_styles:
        repo = os.path.expanduser('~/video-generation-tools')
        script_candidates = [os.path.join(repo, 'scripts', f'{args.effect}.py'), os.path.join(repo, f'{args.effect}.py')]
        script = next((s for s in script_candidates if os.path.isfile(s)), None) if external_enabled else None
        if script:
            # use images dir if provided or create temp dir
            if args.images_dir:
                input_dir = args.images_dir
            else:
                tmp = tempfile.mkdtemp(prefix='vg-images-')
                for idx, p in enumerate(images):
                    ext = os.path.splitext(p)[1]
                    dst = os.path.join(tmp, f'{idx:04d}{ext}')
                    shutil.copy(p, dst)
                input_dir = tmp
            try:
                # Probe the external script's help to choose appropriate flags
                help_proc = subprocess.run(['python3', script, '--help'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                help_text = (help_proc.stdout or '').lower()
                # pick input flag
                if '--img_dir' in help_text:
                    img_flag = '--img_dir'
                elif '--img-dir' in help_text:
                    img_flag = '--img-dir'
                elif '--input' in help_text:
                    img_flag = '--input'
                else:
                    img_flag = '--input'
                # pick audio/music flag
                if '--music_dir' in help_text:
                    audio_flag = '--music_dir'
                elif '--music-dir' in help_text:
                    audio_flag = '--music-dir'
                elif '--audio' in help_text:
                    audio_flag = '--audio'
                else:
                    audio_flag = '--audio'
                # pick output flag
                if '--output_file' in help_text:
                    out_flag = '--output_file'
                elif '--output-file' in help_text:
                    out_flag = '--output-file'
                elif '--output' in help_text:
                    out_flag = '--output'
                else:
                    out_flag = '--output'
                cmd = ['python3', script, img_flag, input_dir, audio_flag, audio_path or '', out_flag, out]
                print('Running external script:', ' '.join(cmd))
                try:
                    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
                    print(proc.stdout)
                    if proc.returncode != 0:
                        print('External script exited with non-zero code, falling back to built-in mapping')
                        raise RuntimeError('External script failed')
                    # external script claimed success; check output exists
                    if not os.path.isfile(out):
                        print('External script did not produce output, falling back')
                        raise RuntimeError('No output produced')
                    print('Saved to', out)
                    return
                except subprocess.TimeoutExpired:
                    print('External script timed out after 30s, falling back to built-in mapping')
                except Exception as e:
                    print(f'External script error: {e}; falling back to built-in mapping')
                # fallback mapping: continue to internal processing
                mapping = {'video':'Zoom','tk1':'Fade','tk2':'Zoom','tk3':'Mirror','autotk':'Fade','tkdemo':'Fade'}
                args_effect = mapping.get(args.effect, 'None')
                print(f'Fallback effect for {args.effect}: {args_effect}')
                effect = args_effect
                # continue to build_video below using effect variable
            finally:
                if not args.images_dir:
                    shutil.rmtree(tmp, ignore_errors=True)
        else:
            if not external_enabled:
                print('External styles disabled; using built-in fallback mapping')
            mapping = {'video':'Zoom','tk1':'Fade','tk2':'Zoom','tk3':'Mirror','autotk':'Fade','tkdemo':'Fade'}
            args.effect = mapping.get(args.effect,'None')

    build_video(images, args.seconds, audio_path, out, args.effect)
    print('Saved to', out)


if __name__ == '__main__':
    main()
