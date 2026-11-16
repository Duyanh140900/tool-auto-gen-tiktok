"""Layout helper for TikTok review tool: 9:16 canvas with lower-half assets and text."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

from loguru import logger
from PIL import ImageFont
from config import settings


StyleName = Literal["style1", "style2", "style3"]


@dataclass
class OverlayAssets:
    """Asset paths for video overlay. nhay/logo are optional for style3."""
    black_bg: Path
    card_bg: Path          # red-bg.png for style1, green-bg.jpg for style2, bg.png for style3
    logo: Path
    nhay: Optional[Path]   # Only used in style1; None for style2/style3
    style: StyleName = "style1"


def get_public_assets(
    public_dir: Optional[Path] = None,
    style: StyleName = "style1",
    custom_logo: Optional[str | Path] = None,
    custom_card_bg: Optional[str | Path] = None,
    custom_nhay: Optional[str | Path] = None,
    custom_black_bg: Optional[str | Path] = None,
) -> OverlayAssets:
    """Validate and return paths for the required public assets, allowing custom overrides.
    
    Args:
        public_dir: Directory containing default public assets.
        style: "style1" (red-bg + logo_tiembachhoa + nhay), "style2" (green-bg + logo from style2, no nhay),
               or "style3" (bg.png pink template).
        custom_logo: Optional override path for logo image.
        custom_card_bg: Optional override path for card background image.
        custom_nhay: Optional override path for nhay animation overlay icon.
        custom_black_bg: Optional override path for canvas black background.
    """
    if public_dir is None:
        public_dir = settings.PROJECT_ROOT / "public"

    # Determine base assets by style
    if style == "style3":
        default_black_bg = public_dir / "black-bg.webp"
        default_card_bg = public_dir / "style3" / "bg.png"
        default_logo = public_dir / "logo_tiembachhoa.png"  # optional placeholder
        default_nhay = None
    elif style == "style2":
        default_black_bg = public_dir / "black-bg.webp"
        default_card_bg = public_dir / "style2" / "green-bg.jpg"
        default_logo = public_dir / "style2" / "logo.png"
        default_nhay = None
    else:
        default_black_bg = public_dir / "black-bg.webp"
        default_card_bg = public_dir / "red-bg.png"
        default_logo = public_dir / "logo_tiembachhoa.png"
        default_nhay = public_dir / "nhay.png"

    # Check env overrides by specific style
    if style == "style3":
        env_logo = (
            os.environ.get("CUSTOM_STYLE3_LOGO_PATH", getattr(settings, "CUSTOM_STYLE3_LOGO_PATH", "")).strip()
        )
        env_card_bg = (
            os.environ.get("CUSTOM_STYLE3_CARD_BG_PATH", getattr(settings, "CUSTOM_STYLE3_CARD_BG_PATH", "")).strip()
        )
        env_nhay = (
            os.environ.get("CUSTOM_STYLE3_NHAY_PATH", getattr(settings, "CUSTOM_STYLE3_NHAY_PATH", "")).strip()
        )
        env_black_bg = (
            os.environ.get("CUSTOM_STYLE3_BLACK_BG_PATH", getattr(settings, "CUSTOM_STYLE3_BLACK_BG_PATH", "")).strip()
        )
    elif style == "style2":
        env_logo = (
            os.environ.get("CUSTOM_STYLE2_LOGO_PATH", getattr(settings, "CUSTOM_STYLE2_LOGO_PATH", "")).strip()
        )
        env_card_bg = (
            os.environ.get("CUSTOM_STYLE2_CARD_BG_PATH", getattr(settings, "CUSTOM_STYLE2_CARD_BG_PATH", "")).strip()
        )
        env_nhay = (
            os.environ.get("CUSTOM_STYLE2_NHAY_PATH", getattr(settings, "CUSTOM_STYLE2_NHAY_PATH", "")).strip()
        )
        env_black_bg = (
            os.environ.get("CUSTOM_STYLE2_BLACK_BG_PATH", getattr(settings, "CUSTOM_STYLE2_BLACK_BG_PATH", "")).strip()
        )
    else:
        env_logo = (
            os.environ.get("CUSTOM_STYLE1_LOGO_PATH")
            or os.environ.get("CUSTOM_LOGO_PATH")
            or getattr(settings, "CUSTOM_STYLE1_LOGO_PATH", "")
            or getattr(settings, "CUSTOM_LOGO_PATH", "")
        ).strip()
        env_card_bg = (
            os.environ.get("CUSTOM_STYLE1_CARD_BG_PATH")
            or os.environ.get("CUSTOM_CARD_BG_PATH")
            or getattr(settings, "CUSTOM_STYLE1_CARD_BG_PATH", "")
            or getattr(settings, "CUSTOM_CARD_BG_PATH", "")
        ).strip()
        env_nhay = (
            os.environ.get("CUSTOM_STYLE1_NHAY_PATH")
            or os.environ.get("CUSTOM_NHAY_PATH")
            or getattr(settings, "CUSTOM_STYLE1_NHAY_PATH", "")
            or getattr(settings, "CUSTOM_NHAY_PATH", "")
        ).strip()
        env_black_bg = (
            os.environ.get("CUSTOM_STYLE1_BLACK_BG_PATH")
            or os.environ.get("CUSTOM_BLACK_BG_PATH")
            or getattr(settings, "CUSTOM_STYLE1_BLACK_BG_PATH", "")
            or getattr(settings, "CUSTOM_BLACK_BG_PATH", "")
        ).strip()

    final_logo = Path(custom_logo) if custom_logo and str(custom_logo).strip() else (Path(env_logo) if env_logo else default_logo)
    final_card_bg = Path(custom_card_bg) if custom_card_bg and str(custom_card_bg).strip() else (Path(env_card_bg) if env_card_bg else default_card_bg)
    final_black_bg = Path(custom_black_bg) if custom_black_bg and str(custom_black_bg).strip() else (Path(env_black_bg) if env_black_bg else default_black_bg)
    
    if style in ("style2", "style3"):
        final_nhay = Path(custom_nhay) if custom_nhay and str(custom_nhay).strip() else (Path(env_nhay) if env_nhay else None)
    else:
        final_nhay = Path(custom_nhay) if custom_nhay and str(custom_nhay).strip() else (Path(env_nhay) if env_nhay else default_nhay)

    assets = OverlayAssets(
        black_bg=final_black_bg,
        card_bg=final_card_bg,
        logo=final_logo,
        nhay=final_nhay,
        style=style,
    )

    # Check required files
    required_paths = [assets.black_bg, assets.card_bg]
    if style != "style3":
        required_paths.append(assets.logo)
    missing = [str(p) for p in required_paths if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Thiếu các file tài nguyên ảnh: {', '.join(missing)}")

    # Only check nhay for style1
    if style == "style1" and assets.nhay and not assets.nhay.exists():
        raise FileNotFoundError(f"Thiếu các file tài nguyên ảnh nhay: {assets.nhay}")

    return assets


def get_unicode_font_path() -> str:
    """Find a system font that supports Vietnamese Unicode characters."""
    candidates = [
        # TikTok/CapCut Xuong-style font bundled in project assets
        settings.PROJECT_ROOT / "assets" / "font.ttf",
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/tahoma.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    for font_path in candidates:
        if font_path.exists():
            return str(font_path)

    # Fallback search in Windows Fonts dir
    win_fonts = Path("C:/Windows/Fonts")
    if win_fonts.exists():
        for ttf in win_fonts.glob("*.ttf"):
            return str(ttf)

    return "arial"


def format_ffmpeg_font_path(font_path: str) -> str:
    """Format font path for FFmpeg drawtext filter string on Windows/POSIX."""
    if font_path == "arial":
        return "arial"
    # FFmpeg drawtext requires escaping colon and backslashes on Windows
    clean = font_path.replace("\\", "/").replace(":", "\\:")
    return clean


def _wrap_text_by_pixels(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    """Wrap at word boundaries while guaranteeing every line fits max_width."""
    lines: List[str] = []
    current = ""

    for word in text.split():
        candidate = f"{current} {word}".strip()
        if font.getlength(candidate) <= max_width:
            current = candidate
            continue

        if current:
            lines.append(current)
            current = ""

        # A single unusually long token must also remain inside the card.
        chunk = ""
        for char in word:
            candidate = chunk + char
            if chunk and font.getlength(candidate) > max_width:
                lines.append(chunk)
                chunk = char
            else:
                chunk = candidate
        current = chunk

    if current:
        lines.append(current)
    return lines or [text]


def prepare_script_text(
    text: str,
    width: int = 40,
    *,
    font_path: Optional[str] = None,
    max_pixel_width: int = 810,
) -> Tuple[str, int]:
    """Clean and wrap text by real glyph width, preserving a 35 px card padding."""
    clean = " ".join((text or "").strip().upper().split())
    if not clean:
        clean = "THÔNG TIN SẢN PHẨM"

    # Keep ``width`` for API compatibility; actual wrapping uses font metrics.
    del width
    resolved_font_path = font_path or get_unicode_font_path()
    size_limits = ((48, 4), (42, 7), (38, 10), (34, 14), (30, float("inf")))
    wrapped_lines: List[str] = []
    font_size = 48

    try:
        for candidate_size, max_lines in size_limits:
            font = ImageFont.truetype(resolved_font_path, candidate_size)
            lines = _wrap_text_by_pixels(clean, font, max_pixel_width)
            if len(lines) <= max_lines:
                wrapped_lines = lines
                font_size = candidate_size
                break
        else:
            font = ImageFont.truetype(resolved_font_path, 30)
            wrapped_lines = _wrap_text_by_pixels(clean, font, max_pixel_width)
            font_size = 30
    except Exception as exc:
        logger.warning(
            f"Failed to measure text using {resolved_font_path} ({exc}); "
            "falling back to character estimation"
        )
        words = clean.split()
        lines = []
        current: List[str] = []
        cur_len = 0
        for w in words:
            if cur_len + len(w) + (1 if current else 0) <= 24:
                current.append(w)
                cur_len += len(w) + (1 if len(current) > 1 else 0)
            else:
                if current:
                    lines.append(" ".join(current))
                current = [w]
                cur_len = len(w)
        if current:
            lines.append(" ".join(current))
        wrapped_lines = lines
        font_size = 44

    return "\n".join(wrapped_lines), font_size


def prepare_style3_script_text(
    text: str,
    *,
    font_path: Optional[str] = None,
) -> Tuple[List[Tuple[str, int, str]], int, List[str], int]:
    """Parse and wrap text for Style 3.
    
    Returns:
      (headline_segments, headline_size, quote_lines, quote_size)
      where headline_segments is a list of tuples: (left_text, left_pixel_width, right_text)
      so that the left part is rendered in dark black (#141414) and the right part in pink (#BA3846).
    """
    resolved_font_path = font_path or get_unicode_font_path()
    
    raw = (text or "").strip()
    if "\n---\n" in raw:
        parts = raw.split("\n---\n", 1)
        headline_raw = parts[0].strip()
        quote_raw = parts[1].strip()
    elif "\n\n" in raw:
        parts = raw.split("\n\n", 1)
        headline_raw = parts[0].strip()
        quote_raw = parts[1].strip()
    elif "\n" in raw:
        parts = raw.split("\n", 1)
        headline_raw = parts[0].strip()
        quote_raw = parts[1].strip()
    else:
        words = raw.split()
        if len(words) > 10:
            headline_raw = " ".join(words[:6])
            quote_raw = " ".join(words[6:])
        else:
            headline_raw = raw
            quote_raw = ""

    if not headline_raw:
        headline_raw = "THÔNG TIN SẢN PHẨM"

    # Headline typography: uppercase, bold, extra large (size 78, fallback 66), left-aligned
    font_head_size = 78
    font_head = ImageFont.truetype(resolved_font_path, font_head_size)
    # Wrap at max_width=860 (left margin 110 px -> right margin 110 px)
    raw_lines: List[str] = []
    for raw_part in headline_raw.split("\n"):
        raw_lines.extend(_wrap_text_by_pixels(raw_part.upper(), font_head, max_width=860))

    if len(raw_lines) > 2:
        font_head_size = 66
        font_head = ImageFont.truetype(resolved_font_path, font_head_size)
        raw_lines = []
        for raw_part in headline_raw.split("\n"):
            raw_lines.extend(_wrap_text_by_pixels(raw_part.upper(), font_head, max_width=860))

    # Split each line into left half (black) and right half (pink)
    headline_segments: List[Tuple[str, int, str]] = []
    for line in raw_lines:
        words = line.split()
        if len(words) >= 2:
            mid = (len(words) + 1) // 2
            left_part = " ".join(words[:mid]) + " "
            right_part = " ".join(words[mid:])
        else:
            left_part = line
            right_part = ""

        try:
            left_w = int(font_head.getlength(left_part))
        except Exception:
            bbox = font_head.getbbox(left_part)
            left_w = bbox[2] - bbox[0]
        headline_segments.append((left_part, left_w, right_part))

    # Quote typography: primary accent red/pink (#BA3846), size 36 (safe padded max_width=680 inside quote box), centered
    quote_lines: List[str] = []
    font_quote_size = 36
    if quote_raw:
        font_quote = ImageFont.truetype(resolved_font_path, font_quote_size)
        for raw_q in quote_raw.split("\n"):
            quote_lines.extend(_wrap_text_by_pixels(raw_q, font_quote, max_width=680))
        if len(quote_lines) > 4:
            font_quote_size = 30
            font_quote = ImageFont.truetype(resolved_font_path, font_quote_size)
            quote_lines = []
            for raw_q in quote_raw.split("\n"):
                quote_lines.extend(_wrap_text_by_pixels(raw_q, font_quote, max_width=680))

    return headline_segments, font_head_size, quote_lines, font_quote_size


def escape_drawtext_text(text: str) -> str:
    """Escape special characters for FFmpeg drawtext filter text parameter."""
    return (
        text.replace("\\", "\\\\")
        .replace("'", "\u2019")  # Replace single quote with typographic right single quote
        .replace(":", "\\:")
        .replace("%", "\\%")
    )


# ----------------------------------------------------------------------
# Video positioning constants
# ----------------------------------------------------------------------
# Source video is scaled to 108 % → 1166 × 2074 px on a 1080 × 1920 canvas.
DEFAULT_VIDEO_SCALE = 1.08
ZOOMED_VIDEO_W = 1166
ZOOMED_VIDEO_H = 2074
# Centred overlay position (before any vertical shift).
# (1080 - 1166) / 2 = -43; (1920 - 2074) / 2 = -77.
CENTERED_VIDEO_X = -43
CENTERED_VIDEO_Y = -77
DEFAULT_VIDEO_SHIFT_RATIO = 0.3333


def compute_video_geometry(
    video_scale: float = DEFAULT_VIDEO_SCALE,
    video_shift_ratio: float = DEFAULT_VIDEO_SHIFT_RATIO,
) -> Tuple[int, int, int, int]:
    """Compute video width, height, overlay_x, and overlay_y based on scale and shift ratio."""
    scale = max(0.1, float(video_scale))
    zoomed_w = int(round(1080 * scale))
    zoomed_h = int(round(1920 * scale))
    center_x = (1080 - zoomed_w) // 2
    center_y = (1920 - zoomed_h) // 2
    shift_px = round(zoomed_h * float(video_shift_ratio))
    overlay_y = center_y - shift_px
    return zoomed_w, zoomed_h, center_x, overlay_y


def build_complex_filter_graph(
    text: str,
    assets: OverlayAssets,
    *,
    video_input_idx: int = 0,
    black_bg_idx: int = 1,
    card_bg_idx: int = 2,
    logo_idx: int = 3,
    nhay_idx: Optional[int] = None,
    video_shift_ratio: float = DEFAULT_VIDEO_SHIFT_RATIO,
    video_scale: float = DEFAULT_VIDEO_SCALE,
) -> Tuple[str, Dict[str, str]]:
    """
    Build the 1080x1920 CapCut-style overlay layout.

    The layout reproduces the exact geometry for style1, style2, and style3:
      - 9:16 (1080x1920) canvas.
      - Source video scaled and shifted up by video_shift_ratio * zoomed_h.
      - Lower half:
        * style1: black texture + red card + logo + nhay + white text
        * style2: black texture + green card + wide logo + white text
        * style3: pink template (bg.png) + bold headline text + pink framed quote text
      - Output labeled [outv]
    """
    if not (0.0 <= video_shift_ratio <= 1.0):
        raise ValueError(
            f"video_shift_ratio must be between 0.0 and 1.0, got {video_shift_ratio}"
        )
    
    zoomed_w, zoomed_h, overlay_x, video_overlay_y = compute_video_geometry(
        video_scale=video_scale,
        video_shift_ratio=video_shift_ratio,
    )
    video_shift_px = round(zoomed_h * video_shift_ratio)

    font_path_raw = get_unicode_font_path()
    font_path_fmt = format_ffmpeg_font_path(font_path_raw)

    filter_parts: List[str] = []

    # Zoom the source and position it at the centre of a 1080x1920 canvas
    filter_parts.append(
        f"color=c=black:s=1080x1920:r=30[video_canvas];"
        f"[{video_input_idx}:v]scale={zoomed_w}:{zoomed_h}"
        f":force_original_aspect_ratio=increase,"
        f"setsar=1,fps=30[zoomed_v];"
        f"[video_canvas][zoomed_v]overlay=x={overlay_x}:y={video_overlay_y}[base_v];"
    )

    if assets.style == "style3":
        # Style 3 layout:
        # Background card shifted lower (bg_y=800) so that clear video occupies half the screen (Y=0..900)
        # 1. Black texture mask gradient extending down to ribbon tag (TIỆM NHÀ MINH HỈN) ~ Y=1150 (bg_y + 350)
        style3_bg_y = 800
        mask_start = 900
        tag_canvas_y = style3_bg_y + 350  # 1150
        mask_diff = tag_canvas_y - mask_start  # 250
        card_fade = 350

        filter_parts.append(
            f"[{black_bg_idx}:v]crop=312:480:84:0,scale=1080:1920,"
            f"rotate=PI:ow=iw:oh=ih:c=none,format=rgba,"
            f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
            f"a='if(lt(Y,{mask_start}),0,if(gt(Y,{tag_canvas_y}),255,"
            f"pow((Y-{mask_start})/{mask_diff},2)*(3-2*((Y-{mask_start})/{mask_diff}))*255))'[black_mask];"
            f"[base_v][black_mask]overlay=x=0:y=0[stage_black];"
        )

        # 2. Overlay card_bg (bg.png) with smooth top alpha fade down to ribbon tag (card_y=350)
        filter_parts.append(
            f"[{card_bg_idx}:v]scale=1080:1215,format=rgba,"
            f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
            f"a='if(lt(Y,0),0,if(gt(Y,{card_fade}),255,"
            f"pow(Y/{card_fade},2)*(3-2*(Y/{card_fade}))*255))'[card_v];"
            f"[stage_black][card_v]overlay=0:{style3_bg_y}[stage_bg];"
        )

        headline_segments, h_size, quote_lines, q_size = prepare_style3_script_text(
            text,
            font_path=font_path_raw,
        )

        all_text_filters: List[str] = []
        prev_label = "stage_bg"

        # Count total drawtext operations needed to properly label the final output [outv]
        total_draw_ops = 0
        for left_t, _, right_t in headline_segments:
            if left_t:
                total_draw_ops += 1
            if right_t:
                total_draw_ops += 1
        total_draw_ops += len(quote_lines)

        op_counter = 0

        # 2. Draw Headline lines (left-aligned at x=110, y starts below ribbon tag at style3_bg_y + 415)
        # Left half in dark black #141414, right half in pink #BA3846
        # Align via typographic baseline: y={base_y}-ascent so left and right segments
        # stay perfectly locked on the exact same horizontal baseline without diacritic stepping.
        try:
            font_head_obj = ImageFont.truetype(font_path_raw, h_size)
            ascent, _ = font_head_obj.getmetrics()
        except Exception:
            ascent = int(h_size * 0.91)

        h_start_baseline = style3_bg_y + 440 + ascent
        h_line_height = h_size + 18
        logger.debug(
            "Style3 headline geometry: bg_y={}, size={}, ascent={}, first_baseline={}, lines={}",
            style3_bg_y, h_size, ascent, h_start_baseline, len(headline_segments),
        )

        for idx, (left_t, left_w, right_t) in enumerate(headline_segments):
            base_y = h_start_baseline + idx * h_line_height
            if left_t:
                op_counter += 1
                is_last = (op_counter == total_draw_ops)
                out_lbl = "outv" if is_last else f"txt_{op_counter}"
                esc_left = escape_drawtext_text(left_t)
                all_text_filters.append(
                    f"[{prev_label}]drawtext=fontfile='{font_path_fmt}':text='{esc_left}':"
                    f"fontsize={h_size}:fontcolor=0x141414:"
                    f"x=110:y={base_y}-ascent:text_shaping=1[{out_lbl}]"
                )
                prev_label = out_lbl

            if right_t:
                op_counter += 1
                is_last = (op_counter == total_draw_ops)
                out_lbl = "outv" if is_last else f"txt_{op_counter}"
                esc_right = escape_drawtext_text(right_t)
                rx = 110 + left_w
                all_text_filters.append(
                    f"[{prev_label}]drawtext=fontfile='{font_path_fmt}':text='{esc_right}':"
                    f"fontsize={h_size}:fontcolor=0xBA3846:"
                    f"x={rx}:y={base_y}-ascent:text_shaping=1[{out_lbl}]"
                )
                prev_label = out_lbl

        # 3. Draw Quote lines (centered inside quote box with safe padding, accent color #BA3846)
        # Quote box center in card is at ~907 -> canvas quote center = style3_bg_y + 907
        # Use typographic baseline centering so quote block is balanced and never overflows the box bottom.
        try:
            font_q_obj = ImageFont.truetype(font_path_raw, q_size)
            q_ascent, _ = font_q_obj.getmetrics()
        except Exception:
            q_ascent = int(q_size * 0.88)

        q_line_height = q_size + 14
        total_q_block = (len(quote_lines) - 1) * q_line_height + q_ascent if quote_lines else 0
        q_first_baseline = (style3_bg_y + 907) - total_q_block // 2 + q_ascent
        logger.debug(
            "Style3 quote geometry: bg_y={}, center_y={}, size={}, ascent={}, line_height={}, lines={}, total_block={}, first_baseline={}",
            style3_bg_y, style3_bg_y + 907, q_size, q_ascent, q_line_height, len(quote_lines),
            total_q_block, q_first_baseline,
        )
        for idx, line in enumerate(quote_lines):
            op_counter += 1
            is_last = (op_counter == total_draw_ops)
            out_lbl = "outv" if is_last else f"txt_{op_counter}"
            esc = escape_drawtext_text(line)
            base_y = q_first_baseline + idx * q_line_height
            all_text_filters.append(
                f"[{prev_label}]drawtext=fontfile='{font_path_fmt}':text='{esc}':"
                f"fontsize={q_size}:fontcolor=0xBA3846:"
                f"x=(w-text_w)/2:y={base_y}-ascent:text_shaping=1[{out_lbl}]"
            )
            prev_label = out_lbl

        # Fallback if no text lines generated
        if not all_text_filters:
            all_text_filters.append(
                f"[{prev_label}]null[outv]"
            )

        filter_parts.append(";".join(all_text_filters))
        filter_graph = "".join(filter_parts)

        metadata = {
            "font_path": font_path_raw,
            "headline_size": str(h_size),
            "quote_size": str(q_size),
            "headline_sample": " ".join((f"{l}{r}".strip() for l, _, r in headline_segments))[:50],
            "quote_sample": " ".join(quote_lines)[:50],
            "canvas_size": "1080x1920",
            "style": assets.style,
            "video_transform": (
                f"scale={video_scale:.2f},dimensions={zoomed_w}x{zoomed_h},"
                f"overlay={overlay_x}:{video_overlay_y},"
                f"shift_up={video_shift_px}px,ratio={video_shift_ratio},crop=none"
            ),
            "card_bg_transform": f"scale=1080x1215,x=0,y={style3_bg_y}",
            "text_style": (
                f"headline_font=Xuong,size={h_size},colors=#141414|#BA3846,base_y={h_start_baseline};"
                f"quote_font=Xuong,size={q_size},color=#BA3846,base_y={q_first_baseline}"
            ),
        }
        return filter_graph, metadata

    # Styles 1 & 2 layout:
    wrapped_text, font_size = prepare_script_text(
        text,
        font_path=font_path_raw,
        max_pixel_width=810,
    )
    logger.debug(
        "Script text layout: {} lines, font_size={}, max_chars={}",
        len(wrapped_text.splitlines()),
        font_size,
        max((len(line) for line in wrapped_text.splitlines()), default=0),
    )

    wrapped_lines = wrapped_text.splitlines() or [wrapped_text]
    text_filters: List[str] = []
    previous_label = "stage5" if nhay_idx is not None else "stage4"
    text_start_y = 1136
    text_line_height = font_size + 12
    for line_index, line in enumerate(wrapped_lines):
        output_label = "outv" if line_index == len(wrapped_lines) - 1 else f"text_{line_index + 1}"
        escaped_line = escape_drawtext_text(line)
        line_y = text_start_y + line_index * text_line_height
        text_filters.append(
            f"[{previous_label}]drawtext=fontfile='{font_path_fmt}':text='{escaped_line}':"
            f"fontsize={font_size}:fontcolor=white:"
            f"x=135+(810-text_w)/2:y={line_y}:text_shaping=1[{output_label}]"
        )
        previous_label = output_label
    text_filter_graph = ";".join(text_filters)

    # Black texture mask
    filter_parts.append(
        f"[{black_bg_idx}:v]crop=312:480:84:0,scale=1080:1920,"
        f"rotate=PI:ow=iw:oh=ih:c=none,format=rgba,"
        f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
        f"a='if(lt(Y,1000),0,if(gt(Y,1180),255,"
        f"pow((Y-1000)/180,2)*(3-2*((Y-1000)/180))*255))'[black_mask];"
    )

    # Card mask and shadow
    filter_parts.append(
        f"[{card_bg_idx}:v]scale=880:780,format=rgba,"
        f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
        f"a='if(lt(Y,560),255,if(gt(Y,740),0,"
        f"pow((740-Y)/180,2)*(3-2*((740-Y)/180))*255))'[card_mask];"
        f"[card_mask]split=2[card][card_shadow_src];"
        f"[card_shadow_src]colorchannelmixer=rr=0:gg=0:bb=0:aa=0.50,"
        f"boxblur=32:2[card_shadow];"
    )

    # Logo crop & scale
    if assets.style == "style2":
        filter_parts.append(
            f"[{logo_idx}:v]crop=408:171:46:148,scale=263:110[logo_v];"
        )
    else:
        filter_parts.append(
            f"[{logo_idx}:v]crop=185:242:165:119,scale=70:110[logo_v];"
        )

    # Compose overlay layers
    if assets.style == "style2":
        logo_overlay_pos = "409:1019"
    else:
        logo_overlay_pos = "119:1019"
    filter_parts.append(
        f"[base_v][black_mask]overlay=x=0:y=0[stage2];"
        f"[stage2][card_shadow]overlay=100:1020[stage_shadow];"
        f"[stage_shadow][card]overlay=100:1000[stage3];"
        f"[stage3][logo_v]overlay={logo_overlay_pos}[stage4];"
    )

    # Optional nhay layer
    if nhay_idx is not None:
        filter_parts.append(
            f"[{nhay_idx}:v]scale=140:110[nhay_v];"
            f"[stage4][nhay_v]overlay=470:945[stage5];"
        )

    filter_parts.append(text_filter_graph)

    filter_graph = "".join(filter_parts)

    metadata = {
        "font_path": font_path_raw,
        "font_size": str(font_size),
        "text_sample": wrapped_text[:50],
        "canvas_size": "1080x1920",
        "style": assets.style,
        "video_transform": (
            f"scale={video_scale:.2f},dimensions={zoomed_w}x{zoomed_h},"
            f"overlay={overlay_x}:{video_overlay_y},"
            f"shift_up={video_shift_px}px,ratio={video_shift_ratio},crop=none"
        ),
        "black_bg_transform": "canvas-fit,x=0,y=0,rotate=180",
        "black_bg_mask": "split,x=0,y=0,rotate=360,feather=340,smoothstep=true",
        "card_bg_shadow": "offset_y=20,blur=32,opacity=50%",
        "card_bg_transform": "scale=87%,x=20,y=-869,rotate=0",
        "card_bg_mask": "split,x=0,y=-56,rotate=0,feather=180,smoothstep=true",
        "logo_transform": (
            "alpha_crop=185x242+165+119,visible_scale=70x110,"
            "x=119,y=1019,margin=5mm,rotate=0"
        ) if assets.style == "style1" else (
            "alpha_crop=408x171+46+148,visible_scale=263x110,"
            "x=409,y=1019,margin=0,rotate=0"
        ),
        "nhay_transform": "scale=13%,x=470,y=945,offset_up=15px,rotate=0" if nhay_idx is not None else None,
        "text_style": (
            "font=Xuong(fallback=Arial Bold),size=8(dynamic pixel fit),bold=true,"
            "color=white,character=0,line=12,align=per-line-center,scale=100%,"
            "content_x=135,content_width=810,padding=35,wrap_mode=pixel,y=1136,opacity=100%"
        ),
    }

    return filter_graph, metadata
