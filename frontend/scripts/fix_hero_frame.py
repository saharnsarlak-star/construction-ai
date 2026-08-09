"""Extend left edge of hero so the hard-hat figure sits inset; upscale for clarity."""

from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

src = Path(
    r"C:\Users\Aryan Digitai\.cursor\projects\c-Users-Aryan-Digitai-Desktop-standard"
    r"\assets\c__Users_Aryan_Digitai_AppData_Roaming_Cursor_User_workspaceStorage_"
    r"empty-window_images_cropped_no_panels_v2-58d76fe8-e0f4-47f3-90e4-d5af643c8839.png"
)
dst = Path(__file__).resolve().parents[1] / "public" / "home-hero-bim.png"

im = Image.open(src).convert("RGB")
im = im.resize((im.width * 2, im.height * 2), Image.Resampling.LANCZOS)

pad = int(round(im.width * 0.2))
canvas = Image.new("RGB", (im.width + pad, im.height))

strip_w = max(48, im.width // 18)
left = im.crop((0, 0, strip_w, im.height)).resize((pad, im.height), Image.Resampling.LANCZOS)
left = left.filter(ImageFilter.GaussianBlur(18))
left = ImageEnhance.Brightness(left).enhance(0.72)
canvas.paste(left, (0, 0))
canvas.paste(im, (pad, 0))

canvas = ImageEnhance.Sharpness(canvas).enhance(1.12)
canvas = ImageEnhance.Contrast(canvas).enhance(1.06)
canvas = ImageEnhance.Color(canvas).enhance(1.08)

canvas.save(dst, format="PNG", optimize=True)
print(f"saved {canvas.size[0]}x{canvas.size[1]} -> {dst} ({dst.stat().st_size} bytes)")
