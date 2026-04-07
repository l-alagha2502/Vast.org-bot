"""
Image generation utilities for rank cards and welcome banners.
Uses Pillow.
"""

from __future__ import annotations

import io
from typing import Optional
from urllib.request import urlopen

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_FONT_SIZE = 28
_SMALL_FONT_SIZE = 18
_BIG_FONT_SIZE = 40


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype("assets/font.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _fetch_avatar(url: str, size: int = 128) -> Image.Image:
    try:
        with urlopen(url, timeout=5) as resp:
            data = resp.read()
        img = Image.open(io.BytesIO(data)).convert("RGBA").resize((size, size))
        # Circular mask
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        img.putalpha(mask)
        return img
    except Exception:
        img = Image.new("RGBA", (size, size), (128, 128, 128, 255))
        return img


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Rank Card
# ---------------------------------------------------------------------------


def generate_rank_card(
    *,
    username: str,
    discriminator: str,
    avatar_url: str,
    level: int,
    current_xp: int,
    required_xp: int,
    rank: int,
    bar_color: str = "#5865F2",
    text_color: str = "#FFFFFF",
    background_url: Optional[str] = None,
) -> io.BytesIO:
    """
    Generate a rank card image and return it as a BytesIO PNG buffer.
    """
    width, height = 800, 220
    bg_color = (35, 39, 42, 255)

    if background_url:
        try:
            with urlopen(background_url, timeout=5) as resp:
                bg = Image.open(io.BytesIO(resp.read())).convert("RGBA")
                bg = bg.resize((width, height))
                card = bg
        except Exception:
            card = Image.new("RGBA", (width, height), bg_color)
    else:
        card = Image.new("RGBA", (width, height), bg_color)

    draw = ImageDraw.Draw(card)

    # Avatar
    avatar = _fetch_avatar(avatar_url, size=160)
    card.paste(avatar, (30, 30), avatar)

    txt_rgb = _hex_to_rgb(text_color)

    # Username
    font_big = _load_font(_BIG_FONT_SIZE)
    font_med = _load_font(_DEFAULT_FONT_SIZE)
    font_sm = _load_font(_SMALL_FONT_SIZE)

    draw.text((210, 30), f"{username}#{discriminator}", font=font_big, fill=txt_rgb)
    draw.text((210, 80), f"RANK #{rank}", font=font_med, fill=(185, 187, 190))
    draw.text((210, 110), f"LEVEL {level}", font=font_med, fill=txt_rgb)

    # Progress bar background
    bar_x, bar_y, bar_w, bar_h = 210, 155, 550, 30
    draw.rounded_rectangle(
        [bar_x, bar_y, bar_x + bar_w, bar_y + bar_h],
        radius=15,
        fill=(79, 84, 92),
    )

    # Progress bar fill
    progress = min(current_xp / max(required_xp, 1), 1.0)
    filled_w = max(int(bar_w * progress), 30)
    bar_rgb = _hex_to_rgb(bar_color)
    draw.rounded_rectangle(
        [bar_x, bar_y, bar_x + filled_w, bar_y + bar_h],
        radius=15,
        fill=(*bar_rgb, 255),
    )

    # XP text
    draw.text(
        (bar_x + bar_w // 2, bar_y + bar_h // 2 - 9),
        f"{current_xp:,} / {required_xp:,} XP",
        font=font_sm,
        fill=(255, 255, 255),
        anchor="mm",
    )

    buf = io.BytesIO()
    card.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Welcome / Goodbye Card
# ---------------------------------------------------------------------------


def generate_welcome_card(
    *,
    username: str,
    avatar_url: str,
    member_count: int,
    guild_name: str,
    background_url: Optional[str] = None,
    embed_color: str = "#5865F2",
    goodbye: bool = False,
) -> io.BytesIO:
    """
    Generate a welcome (or goodbye) banner and return a PNG BytesIO.
    """
    width, height = 800, 300
    bg_color = (35, 39, 42, 255)

    if background_url:
        try:
            with urlopen(background_url, timeout=5) as resp:
                card = Image.open(io.BytesIO(resp.read())).convert("RGBA").resize(
                    (width, height)
                )
        except Exception:
            card = Image.new("RGBA", (width, height), bg_color)
    else:
        card = Image.new("RGBA", (width, height), bg_color)

    # Overlay strip for readability
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 120))
    card = Image.alpha_composite(card, overlay)
    draw = ImageDraw.Draw(card)

    accent = _hex_to_rgb(embed_color)

    # Avatar
    avatar = _fetch_avatar(avatar_url, size=180)
    card.paste(avatar, (310, 30), avatar)

    font_big = _load_font(_BIG_FONT_SIZE)
    font_med = _load_font(_DEFAULT_FONT_SIZE)
    font_sm = _load_font(_SMALL_FONT_SIZE)

    action = "GOODBYE" if goodbye else "WELCOME"
    draw.text((400, 225), action, font=font_big, fill=accent, anchor="mm")
    draw.text((400, 260), username, font=font_med, fill=(255, 255, 255), anchor="mm")
    if not goodbye:
        draw.text(
            (400, 285),
            f"Member #{member_count:,} of {guild_name}",
            font=font_sm,
            fill=(185, 187, 190),
            anchor="mm",
        )

    buf = io.BytesIO()
    card.save(buf, format="PNG")
    buf.seek(0)
    return buf
