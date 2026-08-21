"""Build the branded inline preview banner from the canonical BoudyOS avatar."""

from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
AVATAR = ROOT / "resources" / "extras" / "boudyos_avatar.jpg"
OUTPUT = ROOT / "resources" / "extras" / "inline.jpg"
SIZE = (1280, 720)


def font_path(pattern: str) -> str:
    return subprocess.check_output(
        ["fc-match", "-f", "%{file}", pattern], text=True
    ).strip()


def font(pattern: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(font_path(pattern), size)


def radial_glow(size: tuple[int, int], center: tuple[int, int], color, radius: int):
    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    pixels = glow.load()
    assert pixels is not None
    cx, cy = center
    for y in range(max(0, cy - radius), min(size[1], cy + radius)):
        for x in range(max(0, cx - radius), min(size[0], cx + radius)):
            distance = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if distance >= radius:
                continue
            alpha = int(110 * (1 - distance / radius) ** 2)
            pixels[x, y] = (*color, alpha)
    return glow.filter(ImageFilter.GaussianBlur(18))


def build() -> None:
    width, height = SIZE
    image = Image.new("RGB", SIZE)
    pixels = image.load()
    top = (5, 11, 29)
    bottom = (13, 29, 70)
    for y in range(height):
        ratio = y / (height - 1)
        row = tuple(int(top[i] * (1 - ratio) + bottom[i] * ratio) for i in range(3))
        for x in range(width):
            pixels[x, y] = row

    image = Image.alpha_composite(image.convert("RGBA"), radial_glow(SIZE, (1040, 320), (0, 210, 255), 420))
    image = Image.alpha_composite(image, radial_glow(SIZE, (120, 650), (33, 82, 255), 300))

    atmosphere = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(atmosphere)
    for x in range(40, width, 80):
        draw.line((x, 0, x, height), fill=(130, 190, 255, 8), width=1)
    for y in range(40, height, 80):
        draw.line((0, y, width, y), fill=(130, 190, 255, 8), width=1)
    image = Image.alpha_composite(image, atmosphere)

    artwork = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(artwork)
    cyan = (40, 216, 245, 230)
    blue = (38, 112, 255, 180)
    draw.rounded_rectangle((744, 112, 1168, 608), radius=32, outline=(75, 205, 255, 72), width=2)
    draw.line((744, 144, 1168, 144), fill=(75, 205, 255, 42), width=1)
    draw.ellipse((1032, 124, 1040, 132), fill=cyan)
    draw.ellipse((1052, 124, 1060, 132), fill=blue)
    draw.ellipse((1072, 124, 1080, 132), fill=(255, 255, 255, 72))
    image = Image.alpha_composite(image, artwork)

    avatar = Image.open(AVATAR).convert("RGB").resize((390, 390), Image.Resampling.LANCZOS)
    avatar_layer = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    avatar_layer.paste(avatar, (761, 178))
    image = Image.alpha_composite(image, avatar_layer)

    content = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(content)
    label = font("Noto Sans:style=Regular", 19)
    title = font("Noto Sans:style=Bold", 66)
    body = font("Noto Sans:style=Regular", 25)
    meta = font("Noto Sans:style=Regular", 18)
    draw.text((88, 118), "BOUDYOS / TELEGRAM WORKSPACE", font=label, fill=(89, 222, 247, 255))
    draw.text((88, 186), "Your personal", font=title, fill=(245, 249, 255, 255))
    draw.text((88, 266), "Telegram workspace", font=title, fill=(245, 249, 255, 255))
    draw.rounded_rectangle((92, 382, 230, 388), radius=3, fill=(35, 205, 246, 255))
    draw.text((88, 425), "One focused place for everyday commands.", font=body, fill=(195, 212, 240, 240))
    draw.text((88, 487), "HELP  /  PLUGINS  /  VOICE CHAT  /  TOOLS", font=meta, fill=(124, 156, 205, 220))
    image = Image.alpha_composite(image, content)

    image.convert("RGB").save(OUTPUT, "JPEG", quality=92, optimize=True, progressive=True)
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size} bytes)")


if __name__ == "__main__":
    build()
