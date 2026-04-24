from PIL import Image
from moviepy.editor import CompositeVideoClip, ImageClip
from moviepy.video.fx.all import blackwhite, fadein, fadeout, mirror_x


PORTRAIT_PROFILES = {
    "3:4": (1080, 1440),
    "9:16": (1080, 1920),
}


def _image_ratio(path):
    with Image.open(path) as img:
        width, height = img.size
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid image size for {path}")
    return width / height


def choose_output_profile(image_paths):
    counts = {"3:4": 0, "9:16": 0}
    ratios = []
    for path in image_paths:
        ratio = _image_ratio(path)
        ratios.append(ratio)
        profile = min(PORTRAIT_PROFILES, key=lambda name: abs(ratio - (PORTRAIT_PROFILES[name][0] / PORTRAIT_PROFILES[name][1])))
        counts[profile] += 1

    if counts["3:4"] > counts["9:16"]:
        selected = "3:4"
    elif counts["9:16"] > counts["3:4"]:
        selected = "9:16"
    else:
        avg_ratio = sum(ratios) / len(ratios)
        selected = min(PORTRAIT_PROFILES, key=lambda name: abs(avg_ratio - (PORTRAIT_PROFILES[name][0] / PORTRAIT_PROFILES[name][1])))
    return selected, PORTRAIT_PROFILES[selected], counts


def _fit_clip_to_canvas(clip, target_size):
    target_w, target_h = target_size
    scale = min(target_w / clip.w, target_h / clip.h)
    fitted = clip.resize(scale)
    return CompositeVideoClip([fitted.set_position("center")], size=target_size).set_duration(clip.duration)


def build_styled_clip(path, duration, effect, target_size, fade_duration):
    base_clip = ImageClip(path).set_duration(duration)
    if effect == "Zoom":
        fitted = _fit_clip_to_canvas(base_clip, target_size)
        zoomed = fitted.resize(lambda t: 1 + 0.04 * t)
        return CompositeVideoClip([zoomed.set_position("center")], size=target_size).set_duration(duration)

    clip = _fit_clip_to_canvas(base_clip, target_size)
    if effect == "Fade":
        clip = clip.fx(fadein, fade_duration).fx(fadeout, fade_duration)
    elif effect == "Mirror":
        clip = clip.fx(mirror_x)
    elif effect == "BlackWhite":
        clip = clip.fx(blackwhite)
    return clip
