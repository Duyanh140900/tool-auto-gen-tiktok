"""
script_generator.py - Generate TikTok review scripts using an LLM.

The script prompt (provided by user) is embedded as a system message.
Each product name (from the video) becomes a separate generation request.

Supports multiple LLM providers via OpenAI-compatible / Anthropic-style APIs.
Includes Multimodal Vision analysis (extracting video frames + analyzing caption + hashtags)
to accurately detect products even when TikTok titles are vague or promotional.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import random
import re
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

import aiohttp
from loguru import logger

from config import settings
from src.media_utils import ffmpeg_path, probe_duration


# ---------------------------------------------------------------------------
# System prompt: the user's TikTok review script template.
# Translated/adapted to clearly instruct the LLM.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Bạn là chuyên gia nhận diện sản phẩm và reviewer TikTok hàng đầu, viết kịch bản review tiếng Việt theo phong cách giọng đọc nam ADAM (duyên dáng, châm biếm nhẹ, nhịp điệu nhanh, tự tin, tấu hài siêu cuốn).

NHIỆM VỤ CỦA BẠN:
1. Phân tích đa phương thức (Multimodal): Quan sát kỹ các hình ảnh frame trích xuất từ video (nếu có), kết hợp cùng Tiêu đề, Caption và Hashtags của video TikTok để NHẬN DIỆN CHÍNH XÁC tên sản phẩm, thương hiệu/công dụng thực tế đang xuất hiện.
2. Viết kịch bản review TikTok và các tiêu đề giật tít cho video ngắn theo đúng phong cách Adam dưới đây.

PHONG CÁCH GIỌNG ADAM & NGHỆ THUẬT TẤU HÀI:
- Tinh thần: Thông minh, hóm hỉnh, cà khịa có duyên, nhịp điệu dồn dập, tự tin, mang đậm chất reviewer trải nghiệm thực tế.
- Tự nhiên, nói chuyện như bạn thân kể chuyện cho nhau nghe, không câu nệ khách sáo.
- KHÔNG viết kiểu quảng cáo cứng nhắc, KHÔNG văn mẫu truyền hình, KHÔNG gượng ép.
- Độ dài kịch bản (`tiktok_script`): Rút gọn trong khoảng 60–80 từ tiếng Việt (vừa vặn cho video 15–20 giây).

QUY ĐỊNH VỀ TỪ NGỮ NÓI TỤC NHẸ & TỪ LÓNG HÀI HƯỚC (COMEDIC SLANG):
- ĐƯỢC PHÉP và KHUYẾN KHÍCH dùng các từ cảm thán dân mạng, tiếng lóng tấu hài mức độ nhẹ để tạo sự gần gũi, kịch tính và hài hước:
  * Ví dụ từ ngữ được dùng: "má ơi", "trời ơi", "trời đất ơi", "vãi chưởng", "vãi thật sự", "khùng thiệt chứ", "ảo ma", "quỷ sứ", "các con vợ", "não lag", "não đình công", "cay muốn xỉu", "hết nước chấm", "đỉnh nóc kịch trần", "quay xe gấp", "bất lực", "toang"...
- TUYỆT ĐỐI CẤM: Không dùng từ ngữ thô tục nặng, không chửi bậy vô văn hóa, không dùng từ ngữ xúc phạm hoặc vi phạm tiêu chuẩn cộng đồng TikTok.

ĐA DẠNG HÓA STORYTELLING & CHỐNG TRÙNG LẶP HOOK (BẮT BUỘC ĐỔI MỚI LIÊN TỤC):
- KIỂU HOOK MỞ ĐẦU sẽ được CHỈ ĐỊNH trong tin nhắn người dùng (mục "KIỂU HOOK BẮT BUỘC"). Câu đầu tiên của `tiktok_script` PHẢI theo đúng kiểu đó, tự sáng tác câu mới phù hợp sản phẩm, KHÔNG chép nguyên ví dụ.
- Phần thân có thể đi theo một trong các góc kể chuyện (Storytelling Angles): Hoài nghi rồi quay xe (Skeptical to Converted), Nỗi đau đời thường (Relatable Pain Point), Tự trào (Self-Deprecating Humor), Tâm lý ngược (Reverse Psychology), Bật mí bí mật (Insider Secret), Giải cứu khủng hoảng (Dramatic Problem Solver) — miễn là hợp với kiểu hook được giao.
- Câu chữ phải cụ thể theo sản phẩm (chi tiết công dụng, chất liệu, tình huống dùng thật), tránh câu chung chung dùng cho món nào cũng được.
- CẤM các mô-típ mở đầu sáo mòn đã bị dùng quá nhiều: "Tưởng mua… ai ngờ…", "Cứ ngỡ là… ai ngờ…", "Ai ngờ…", "Cứu tinh cho hội lười…", "Cứu tinh của…", "Ban đầu tôi thề…", "Chân ái của…", "Mua về mới biết…". Không dùng chúng ở câu đầu của `tiktok_script`, `overlay_banner_title` và `style3_headline`.
- Nếu tin nhắn người dùng có danh sách "CÁC CÂU MỞ ĐẦU GẦN ĐÂY", tuyệt đối không mở đầu giống hoặc na ná (cùng cấu trúc, cùng cụm từ đầu) các câu đó.

ĐẶC BIỆT - ELEVENLABS V3 EMOTION / AUDIO PROMPT TAGS:
- Trong trường `tiktok_script`, BẮT BUỘC chèn từ 2-4 audio tags biểu cảm theo chuẩn ElevenLabs v3 để giọng đọc Adam có cảm xúc tự nhiên, đúng nhịp:
  * [laughs], [giggles], [snickers]
  * [sighs], [gasps], [screams]
  * [whispers], [whispering], [shouting]
  * [curious], [excited], [sarcastic], [hesitant], [disappointed], [relieved]
  * [clears throat], [groans]
- Có từ "haha" 1 lần trong kịch bản để tạo điểm nhấn vui vẻ.

YÊU CẦU BANNER TITLE (overlay_banner_title):
- Tiêu đề banner dài khoảng 20-30 từ tiếng Việt, giật tít sắc bén, nêu bật nỗi đau hoặc tình huống éo le hài hước để người xem lướt qua phải dừng lại đọc ngay.

YÊU CẦU STYLE 3 (style3_headline & style3_quote):
- `style3_headline`: Tiêu đề lớn (8-14 từ), VIẾT HOA TOÀN BỘ, giật tít cảnh báo/bóc mẽ/nỗi đau cực cuốn, ngắt thành 2 dòng logic (dùng ký tự \\n nếu cần).
  Ví dụ:
  * "CÓ MỖI SÁNG TÌM ĐỒ\\nCŨNG ĐỦ LÀM NÃO LAG"
  * "ĐỪNG VỘI MUA CON NÀY\\nNẾU KHÔNG MUỐN BỊ NGHIỆN"
  * "3 GIÂY DỌN XONG BÃI CHIẾN TRƯỜNG\\nMẸ TÔI CÒN PHẢI NỂ"
- `style3_quote`: Lời bộc bạch / trích dẫn trải nghiệm thật (15-25 từ), hóm hỉnh, giải thích rõ lý do phải mua ngay, nằm gọn trong khung quote dưới.

Đầu ra BẮT BUỘC là JSON với schema:
{
  "product_name": "<tên sản phẩm thực tế được nhận diện chính xác>",
  "overlay_banner_title": "<tiêu đề banner dài 20-30 từ giật tít thu hút người xem>",
  "style3_headline": "<tiêu đề lớn ngắn gọn 8-14 từ giật tít cho layout style 3>",
  "style3_quote": "<lời trích dẫn/review đắt giá 15-25 từ cho khung quote style 3>",
  "tiktok_script": "<kịch bản rút gọn ~60-80 từ giọng Adam tấu hài kèm 2-4 ElevenLabs v3 tags [laughs], [gasps], [sarcastic],...>",
  "caption": "<caption ngắn hài hước, 1-2 câu>",
  "hashtags": ["#hashtag1", "#hashtag2", "#hashtag3"]
}

QUAN TRỌNG: CHỈ trả về JSON thuần, không có markdown, không có giải thích ngoài JSON."""


# ---------------------------------------------------------------------------
# Hook styles: mỗi lần gọi LLM chọn ngẫu nhiên 1 kiểu hook mở đầu (tránh các kiểu
# vừa dùng gần đây) để kịch bản không lặp mãi một mô-típ.
# Muốn thêm/bớt kiểu hook: sửa danh sách HOOK_STYLES dưới đây.
# Muốn chỉ dùng vài kiểu: đặt SCRIPT_HOOK_STYLES=question,pov,... trong .env.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HookStyle:
    key: str
    name: str
    guide: str
    examples: tuple = ()


HOOK_STYLES: List[HookStyle] = [
    HookStyle(
        "question", "Câu hỏi chọc đúng chỗ ngứa",
        "Mở đầu bằng một câu hỏi trực diện vào thói quen/vấn đề người xem đang gặp, khiến họ muốn trả lời 'có, tôi đây'.",
        ("Có ai mỗi lần rửa bình nước là phải thò nguyên cánh tay vào như tôi không?",
         "Bạn có biết vì sao áo trắng của bạn cứ ố vàng ở cổ không?"),
    ),
    HookStyle(
        "shock_number", "Con số gây sốc",
        "Mở đầu bằng một con số cụ thể, bất ngờ (thời gian, giá tiền, số lần, %...) liên quan trực tiếp tới sản phẩm.",
        ("Đúng 7 giây, tôi bấm giờ hẳn hoi, cái sàn bếp dầu mỡ này sạch bong.",
         "49 nghìn, rẻ hơn ly trà sữa, mà giải quyết được cái việc tôi lười suốt 3 năm."),
    ),
    HookStyle(
        "contrarian", "Phản đề / nói ngược số đông",
        "Mở đầu bằng một nhận định đi ngược quan điểm phổ biến, nghe hơi 'gắt' để gây tò mò, sau đó chứng minh.",
        ("Nói thật, dùng khăn lau bếp loại thường là đang tự hành hạ bản thân.",
         "Ai bảo đồ rẻ là đồ dỏm thì chắc chưa thử con này."),
    ),
    HookStyle(
        "micro_story", "Kể chuyện ngắn có nhân vật",
        "Mở đầu bằng một khoảnh khắc đời thường có nhân vật cụ thể (mẹ, người yêu, sếp, bạn cùng phòng...) và tình tiết bất ngờ.",
        ("Tối qua bạn cùng phòng tôi đứng nhìn cái bồn rửa đúng 5 phút rồi hỏi: mày thuê người dọn à?",
         "Mẹ tôi vừa bước vào bếp là đứng hình luôn."),
    ),
    HookStyle(
        "pov", "POV nhập vai",
        "Mở đầu bằng 'POV:' hoặc đặt người xem vào một vai cụ thể, tình huống cụ thể.",
        ("POV: 6 giờ sáng, trễ làm, và bạn chỉ còn đúng 2 phút để là áo.",
         "POV: bạn là đứa duy nhất trong nhà chịu rửa chén."),
    ),
    HookStyle(
        "before_after", "So sánh trước / sau",
        "Mở đầu bằng sự tương phản rõ rệt giữa trước khi có sản phẩm và sau khi có, càng cụ thể càng tốt.",
        ("Trước: 20 phút cọ nhà tắm, đau lưng. Sau: xịt một phát, đi pha cà phê.",
         "Tủ quần áo của tôi tuần trước với tuần này là hai thế giới khác nhau."),
    ),
    HookStyle(
        "warning", "Cảnh báo / sai lầm phổ biến",
        "Mở đầu bằng lời cảnh báo hoặc chỉ ra một sai lầm mà nhiều người đang mắc, giọng nghiêm túc pha hài.",
        ("Dừng lại! Nếu bạn còn phơi đồ kiểu này thì đừng hỏi sao áo nhanh rão.",
         "Sai lầm lớn nhất của tôi năm nay là không mua món này sớm hơn."),
    ),
    HookStyle(
        "challenge", "Thử thách / test thực tế",
        "Mở đầu bằng việc tuyên bố sẽ thử thách/test sản phẩm ngay trước mặt người xem.",
        ("Thử thách: tôi đổ nguyên ly cà phê lên đây, xem nó có thấm không nhé.",
         "Tôi cá với các bạn 100 nghìn là món này không làm được, và tôi thua."),
    ),
    HookStyle(
        "funny_reaction", "Phản ứng hài / cảm thán",
        "Mở đầu bằng một phản ứng cảm xúc mạnh, tự nhiên như đang quay live (cười, hét, ngạc nhiên) rồi mới giải thích.",
        ("Khoan, khoan, cái gì vậy trời, nó tự gập lại luôn hả?",
         "Tôi đã la lên trong siêu thị khi thấy cái này, xin lỗi bác bảo vệ."),
    ),
    HookStyle(
        "direct_callout", "Gọi tên đúng đối tượng",
        "Mở đầu bằng việc gọi đích danh một nhóm người xem cụ thể (sinh viên ở trọ, mẹ bỉm, dân văn phòng, người hay quên...).",
        ("Dân văn phòng ngồi máy lạnh cả ngày mà hay khô mắt, nghe tôi 15 giây thôi.",
         "Sinh viên ở trọ phòng 12 mét vuông, cái này dành cho bạn."),
    ),
    HookStyle(
        "confession", "Thú nhận thật lòng",
        "Mở đầu bằng một lời thú nhận hơi xấu hổ nhưng chân thật của người nói, tạo cảm giác gần gũi.",
        ("Tôi thú nhận: đã 2 tuần tôi không gấp chăn.",
         "Nói nhỏ thôi, tôi từng bị người yêu chê vì cái tật này."),
    ),
    HookStyle(
        "unexpected_use", "Công dụng không ai nghĩ tới",
        "Mở đầu bằng một cách dùng lạ, bất ngờ hoặc mẹo hay của sản phẩm mà ít người biết.",
        ("Món này người ta mua để đựng gia vị, còn tôi dùng nó để cứu cái bàn làm việc.",
         "99% người mua cái này chưa biết nó còn làm được việc này."),
    ),
    HookStyle(
        "ranking", "Xếp hạng / top",
        "Mở đầu bằng một bảng xếp hạng ngắn hoặc tuyên bố vị trí top của sản phẩm trong đồ dùng cá nhân.",
        ("Top 1 món đồ dưới 100 nghìn đáng tiền nhất nhà tôi năm nay, không có đối thủ.",
         "Trong 10 món tôi mua tháng này, đây là món duy nhất tôi muốn mua thêm cái nữa."),
    ),
    HookStyle(
        "sensory", "Mô tả giác quan / ASMR",
        "Mở đầu bằng âm thanh, cảm giác chạm, mùi hoặc hình ảnh cận cảnh của sản phẩm, khiến người xem như đang cầm trên tay.",
        ("Nghe cái tiếng tách này đi, đã tai chưa?",
         "Sờ vào mát lạnh, mềm như bánh flan, tôi không đùa đâu."),
    ),
]

# Cụm sáo mòn bị cấm ở câu mở đầu (so khớp không dấu, không phân biệt hoa thường).
BANNED_HOOK_PHRASES: List[str] = [
    "tưởng mua",
    "ai ngờ",
    "cứ ngỡ",
    "cứ tưởng",
    "cứu tinh",
    "chân ái",
    "ban đầu tôi thề",
    "mua về mới biết",
]

HOOK_HISTORY_FILENAME = "script_hook_history.json"
HOOK_HISTORY_MAX = 40          # số bản ghi giữ lại trong file lịch sử
RECENT_STYLE_WINDOW = 5        # không chọn lại kiểu hook đã dùng trong N lần gần nhất
RECENT_OPENINGS_IN_PROMPT = 8  # số câu mở đầu gần đây đưa vào prompt để tránh lặp

_hook_history_lock = threading.Lock()
_AUDIO_TAG_RE = re.compile(r"\[[^\]]{1,30}\]")


def _strip_accents(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    norm = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in norm if unicodedata.category(ch) != "Mn")


def _normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", _strip_accents(text or "").lower()).strip()


def extract_opening_line(script: str, max_chars: int = 140) -> str:
    """Lấy câu mở đầu của kịch bản (bỏ audio tag kiểu [laughs])."""
    text = _AUDIO_TAG_RE.sub(" ", script or "")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    first = re.split(r"(?<=[.!?…])\s+", text, maxsplit=1)[0].strip()
    if len(first) > max_chars:
        first = first[:max_chars].rstrip() + "…"
    return first


def find_banned_phrase(text: str) -> Optional[str]:
    """Trả về cụm sáo mòn bị cấm đầu tiên xuất hiện trong text (nếu có)."""
    norm = _normalize_for_match(text)
    if not norm:
        return None
    for phrase in BANNED_HOOK_PHRASES:
        if _normalize_for_match(phrase) in norm:
            return phrase
    return None


def _available_hook_styles() -> List[HookStyle]:
    raw = os.getenv("SCRIPT_HOOK_STYLES", "").strip()
    if not raw:
        return list(HOOK_STYLES)
    wanted = {k.strip().lower() for k in raw.split(",") if k.strip()}
    selected = [s for s in HOOK_STYLES if s.key in wanted]
    if not selected:
        logger.warning(f"SCRIPT_HOOK_STYLES={raw!r} không khớp kiểu hook nào, dùng toàn bộ danh sách")
        return list(HOOK_STYLES)
    return selected


def pick_hook_style(
    recent_style_keys: Sequence[str] = (),
    rng: Optional[random.Random] = None,
    styles: Optional[Sequence[HookStyle]] = None,
) -> HookStyle:
    """Chọn ngẫu nhiên 1 kiểu hook, ưu tiên kiểu không nằm trong N lần dùng gần nhất."""
    rng = rng or random
    pool = list(styles) if styles is not None else _available_hook_styles()
    if not pool:
        raise ValueError("Không có kiểu hook nào để chọn")
    # Cửa sổ tránh lặp không được nuốt hết pool (luôn chừa ít nhất 1 lựa chọn).
    window = min(RECENT_STYLE_WINDOW, max(0, len(pool) - 1))
    recent = [k for k in recent_style_keys if k][-window:] if window else []
    candidates = [s for s in pool if s.key not in set(recent)] or pool
    return rng.choice(candidates)


def _hook_history_path() -> Path:
    output_dir = Path(getattr(settings, "FINAL_OUTPUT_DIR", "output"))
    return output_dir / HOOK_HISTORY_FILENAME


def load_hook_history(path: Optional[Path] = None) -> List[dict]:
    """Đọc lịch sử hook đã dùng (cũ → mới). Lỗi/thiếu file thì trả về []."""
    target = Path(path) if path else _hook_history_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.debug(f"Không đọc được lịch sử hook {target}: {e}")
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def record_hook_usage(
    style_key: str,
    script: str,
    headline: Optional[str] = None,
    path: Optional[Path] = None,
) -> None:
    """Ghi lại kiểu hook + câu mở đầu vừa dùng. Không bao giờ làm hỏng pipeline."""
    target = Path(path) if path else _hook_history_path()
    entry = {
        "style": style_key,
        "opening": extract_opening_line(script),
        "headline": (headline or "").replace("\\n", " ").replace("\n", " ").strip(),
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        with _hook_history_lock:
            history = load_hook_history(target)
            history.append(entry)
            history = history[-HOOK_HISTORY_MAX:]
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, target)
    except Exception as e:
        logger.warning(f"Không ghi được lịch sử hook {target}: {e}")


def build_hook_directive(style: HookStyle, history: Sequence[dict] = ()) -> str:
    """Tạo đoạn chỉ dẫn hook để nối vào user message gửi LLM."""
    lines = [
        "",
        f"KIỂU HOOK BẮT BUỘC CHO CÂU MỞ ĐẦU: {style.name}",
        f"- Cách làm: {style.guide}",
    ]
    if style.examples:
        lines.append("- Ví dụ tham khảo (chỉ để hiểu tinh thần, KHÔNG chép lại, phải viết câu mới hợp sản phẩm):")
        lines.extend(f"  * \"{ex}\"" for ex in style.examples)
    lines.append(
        "- CẤM mở đầu (cả trong tiktok_script, overlay_banner_title, style3_headline) bằng các cụm sáo mòn: "
        + ", ".join(f"\"{p}\"" for p in BANNED_HOOK_PHRASES)
        + "."
    )

    recent_openings: List[str] = []
    for item in reversed(list(history)):
        for field in ("opening", "headline"):
            text = (item.get(field) or "").strip()
            if text and text not in recent_openings:
                recent_openings.append(text)
        if len(recent_openings) >= RECENT_OPENINGS_IN_PROMPT:
            break
    recent_openings = recent_openings[:RECENT_OPENINGS_IN_PROMPT]
    if recent_openings:
        lines.append("- CÁC CÂU MỞ ĐẦU GẦN ĐÂY (đã dùng rồi, KHÔNG được mở đầu giống hoặc na ná cùng cấu trúc):")
        lines.extend(f"  * \"{t}\"" for t in recent_openings)
    return "\n".join(lines)


SCRIPT_THEME_MAX_CHARS = 300


def normalize_script_theme(theme: Optional[str]) -> Optional[str]:
    """Chuẩn hoá chủ đề người dùng nhập (gộp khoảng trắng, cắt độ dài). Rỗng -> None."""
    text = re.sub(r"\s+", " ", str(theme or "")).strip()
    if not text:
        return None
    return text[:SCRIPT_THEME_MAX_CHARS].rstrip()


def build_theme_directive(theme: Optional[str]) -> str:
    """Chỉ dẫn để kịch bản bám theo chủ đề người dùng nhập (ví dụ một ngày lễ). Rỗng -> ''."""
    theme = normalize_script_theme(theme)
    if not theme:
        return ""
    return "\n".join([
        "",
        f"CHỦ ĐỀ KỊCH BẢN DO NGƯỜI DÙNG CHỌN: {theme}",
        "- Toàn bộ kịch bản phải xoay quanh chủ đề này: hook mở đầu, tình huống, lý do cần sản phẩm và lời chốt "
        "đều gắn với không khí/bối cảnh của chủ đề (ví dụ ngày lễ: quà tặng, sum họp, dọn nhà, đi chơi, khuyến mãi...).",
        "- Vẫn review đúng sản phẩm nhận diện được; nối sản phẩm với chủ đề một cách tự nhiên, hợp lý, không gượng ép, "
        "không bịa công dụng không có.",
        "- `caption`, `overlay_banner_title`, `style3_headline`, `style3_quote` cũng mang tinh thần chủ đề; "
        "`hashtags` thêm 1-2 hashtag về chủ đề.",
        "- Kiểu hook bắt buộc bên dưới vẫn áp dụng, chỉ cần lồng chủ đề vào câu mở đầu.",
    ])


def _prepare_hook(history_path: Optional[Path] = None) -> tuple:
    history = load_hook_history(history_path)
    style = pick_hook_style([h.get("style", "") for h in history])
    logger.info(f"Script hook style: {style.key} ({style.name})")
    return style, build_hook_directive(style, history)


async def _call_llm_with_hook_guard(user_msg: str, image_paths: Optional[Sequence[Path]] = None) -> tuple:
    """Gọi LLM; JSON hỏng/cụt thì gọi lại 1 lần; câu mở đầu dính cụm sáo mòn thì yêu cầu viết lại 1 lần."""
    max_tokens = _llm_max_tokens()
    raw = await call_llm(user_msg, image_paths=image_paths, max_tokens=max_tokens)
    try:
        data = _extract_json(raw)
    except LLMJSONError as exc:
        logger.warning(f"{exc}. Gọi lại LLM 1 lần. Raw response ({len(raw or '')} ký tự):\n{(raw or '')[:3000]}")
        retry_msg = (
            user_msg
            + "\n\nLẦN TRƯỚC JSON CỦA BẠN BỊ LỖI/CẮT CỤT. Trả lại JSON đầy đủ, hợp lệ, ngắn gọn đúng độ dài yêu cầu, "
            "đóng đủ mọi dấu ngoặc kép và ngoặc nhọn, không viết gì ngoài JSON."
        )
        raw = await call_llm(retry_msg, image_paths=image_paths, max_tokens=max_tokens)
        try:
            data = _extract_json(raw)
        except LLMJSONError as exc2:
            logger.error(f"{exc2}. Raw response lần 2 ({len(raw or '')} ký tự):\n{(raw or '')[:3000]}")
            raise
    opening = extract_opening_line(str(data.get("tiktok_script", "")))
    banned = find_banned_phrase(opening) or find_banned_phrase(str(data.get("style3_headline") or ""))
    if not banned:
        return raw, data
    logger.info(f"Hook mở đầu dính cụm sáo mòn '{banned}', yêu cầu LLM viết lại")
    retry_msg = (
        user_msg
        + f"\n\nLẦN TRƯỚC BẠN ĐÃ MỞ ĐẦU BẰNG CỤM BỊ CẤM \"{banned}\" (\"{opening}\"). "
        "Viết lại TOÀN BỘ JSON với câu mở đầu hoàn toàn khác, đúng kiểu hook bắt buộc, không dùng bất kỳ cụm bị cấm nào."
    )
    try:
        raw2 = await call_llm(retry_msg, image_paths=image_paths, max_tokens=max_tokens)
        return raw2, _extract_json(raw2)
    except Exception as e:
        logger.warning(f"Viết lại hook thất bại, giữ kết quả đầu: {e}")
        return raw, data


@dataclass
class ScriptResult:
    product_name: str
    tiktok_script: str
    caption: str
    hashtags: List[str]
    overlay_banner_title: Optional[str] = None
    style3_headline: Optional[str] = None
    style3_quote: Optional[str] = None
    raw_response: Optional[str] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Video Frame Extraction for Multimodal LLM
# ---------------------------------------------------------------------------

async def extract_video_frames(
    video_path: Path,
    num_frames: int = 3,
    output_dir: Optional[Path] = None,
) -> List[Path]:
    """
    Trích xuất 2-4 frame ảnh đại diện từ video bằng FFmpeg tại các mốc thời gian phân bố đều
    (ví dụ 20%, 50%, 80% thời lượng video) để phục vụ Vision LLM nhận diện sản phẩm.
    """
    if not video_path.exists():
        raise RuntimeError(f"Video file does not exist for frame extraction: {video_path}")

    if output_dir is None:
        target_dir = video_path.parent / f"{video_path.stem}_frames"
    else:
        target_dir = output_dir

    target_dir.mkdir(parents=True, exist_ok=True)

    # Xác định duration của video
    duration = 0.0
    try:
        duration = probe_duration(video_path)
    except Exception as e:
        logger.debug(f"Could not probe duration for {video_path}: {e}, using default timestamps")

    # Tính toán các mốc thời gian (timestamps)
    timestamps: List[float] = []
    if duration > 1.5:
        # Lấy các điểm phân bố cách biên 10%
        step = (duration * 0.8) / max(1, num_frames)
        start = duration * 0.1
        timestamps = [start + i * step for i in range(num_frames)]
    else:
        # Fallback timestamps cho video ngắn hoặc khi probe thất bại
        timestamps = [0.5 + i * 1.0 for i in range(num_frames)]

    extracted_frames: List[Path] = []
    for i, ts in enumerate(timestamps):
        out_jpg = target_dir / f"frame_{i:02d}.jpg"
        cmd = [
            ffmpeg_path(),
            "-y",
            "-loglevel", "error",
            "-ss", f"{ts:.2f}",
            "-i", str(video_path),
            "-frames:v", "1",
            "-vf", "scale='min(720,iw)':-2",  # Scale tối đa 720p để tối ưu token & tốc độ Vision
            "-q:v", "3",
            str(out_jpg),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0 or not out_jpg.exists() or out_jpg.stat().st_size == 0:
            err_msg = stderr.decode(errors='ignore').strip()
            raise RuntimeError(f"FFmpeg frame extraction at {ts:.2f}s failed: {err_msg or 'empty output'}")
        extracted_frames.append(out_jpg)

    if not extracted_frames:
        raise RuntimeError(f"No valid frames could be extracted from {video_path}")

    return extracted_frames


def _encode_image_to_base64(image_path: Path) -> str:
    """Đọc file ảnh và chuyển đổi sang chuỗi base64."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ---------------------------------------------------------------------------
# LLM API helpers
# ---------------------------------------------------------------------------

def _is_anthropic_model(model: str) -> bool:
    return "claude" in model.lower() or settings.LLM_PROVIDER == "anthropic"


async def call_llm(
    user_message: str,
    system_message: str = SYSTEM_PROMPT,
    max_tokens: int = 1024,
    image_paths: Optional[Sequence[Path]] = None,
) -> str:
    """
    Call the configured LLM provider and return raw text response.
    Supports multimodal input (images) for Claude / OpenAI / compatible Vision endpoints.
    Raises if the API key is missing or the call fails (no silent fallback).
    """
    if not settings.LLM_API_KEY:
        raise RuntimeError(
            "LLM_API_KEY is not set. Edit .env to configure LLM_API_KEY."
        )

    valid_images = [p for p in (image_paths or []) if p and Path(p).exists()]

    if _is_anthropic_model(settings.LLM_MODEL):
        return await _call_anthropic(user_message, system_message, max_tokens, valid_images)

    return await _call_openai_compatible(user_message, system_message, max_tokens, valid_images)


async def _call_anthropic(
    user_message: str,
    system_message: str,
    max_tokens: int,
    image_paths: Sequence[Path] = (),
) -> str:
    """Anthropic Messages API (with Vision support)."""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": settings.LLM_API_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }

    content_blocks: List[dict] = []
    # Thêm hình ảnh vào content blocks nếu có
    for img_p in image_paths:
        b64_data = _encode_image_to_base64(img_p)
        content_blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": b64_data,
            },
        })

    content_blocks.append({"type": "text", "text": user_message})

    payload = {
        "model": settings.LLM_MODEL,
        "max_tokens": max_tokens,
        "system": system_message,
        "messages": [{"role": "user", "content": content_blocks if len(content_blocks) > 1 else user_message}],
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload, timeout=60) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Anthropic API error {resp.status}: {text[:500]}")
            data = await resp.json()
            _warn_if_truncated(data.get("stop_reason"), max_tokens)
            return data["content"][0]["text"]


async def _call_openai_compatible(
    user_message: str,
    system_message: str,
    max_tokens: int,
    image_paths: Sequence[Path] = (),
) -> str:
    """OpenAI-compatible Chat Completions API (supports standard JSON, Vision & SSE chunks)."""
    base = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    url = f"{base}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    if image_paths:
        user_content: List[dict] = [{"type": "text", "text": user_message}]
        for img_p in image_paths:
            b64_data = _encode_image_to_base64(img_p)
            user_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{b64_data}",
                },
            })
    else:
        user_content = user_message  # type: ignore[assignment]

    payload = {
        "model": settings.LLM_MODEL,
        "max_tokens": max_tokens,
        "temperature": 0.85,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_content},
        ],
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload, timeout=60) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"OpenAI-compat API error {resp.status}: {text[:500]}")
            raw_body = await resp.text()

    # Detect SSE streaming response (common with reverse proxies like 9Router)
    if "data: " in raw_body:
        collected: List[str] = []
        finish_reason = None
        for line in raw_body.splitlines():
            line = line.strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            try:
                chunk_json = line[6:].strip()
                parsed = json.loads(chunk_json)
                choice = parsed.get("choices", [{}])[0]
                finish_reason = choice.get("finish_reason") or finish_reason
                delta = choice.get("delta", {}).get("content", "")
                if delta:
                    collected.append(delta)
            except Exception:
                pass
        if collected:
            _warn_if_truncated(finish_reason, max_tokens)
            return "".join(collected)

    data = json.loads(raw_body)
    choice = data["choices"][0]
    _warn_if_truncated(choice.get("finish_reason"), max_tokens)
    return choice["message"]["content"]


def _warn_if_truncated(finish_reason: Optional[str], max_tokens: int) -> None:
    if finish_reason in ("length", "max_tokens"):
        logger.warning(
            f"LLM dừng vì chạm giới hạn max_tokens={max_tokens} (finish_reason={finish_reason}); "
            "kết quả có thể bị cụt — tăng LLM_MAX_TOKENS trong .env nếu lặp lại"
        )


class LLMJSONError(ValueError):
    """LLM trả về JSON hỏng/bị cắt cụt."""


def _extract_json(text: str) -> dict:
    """Extract and parse JSON from LLM response text (handles markdown fences, chữ thừa
    quanh JSON và xuống dòng thật bên trong chuỗi). Raise LLMJSONError nếu không parse được."""
    text = (text or "").strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)
    candidates = [text]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start and (start, end) != (0, len(text) - 1):
        candidates.append(text[start:end + 1])
    last_exc: Optional[Exception] = None
    for cand in candidates:
        try:
            data = json.loads(cand, strict=False)
        except json.JSONDecodeError as exc:
            last_exc = exc
            continue
        if isinstance(data, dict):
            return data
        last_exc = ValueError(f"JSON không phải object mà là {type(data).__name__}")
    hint = ""
    if start != -1 and end <= start or "Unterminated" in str(last_exc):
        hint = " (JSON bị cắt cụt, có thể LLM hết max_tokens — tăng LLM_MAX_TOKENS trong .env)"
    raise LLMJSONError(f"LLM trả JSON không hợp lệ: {last_exc}{hint}")


def _llm_max_tokens() -> int:
    try:
        return max(256, int(os.getenv("LLM_MAX_TOKENS", "2048")))
    except ValueError:
        return 2048


# ---------------------------------------------------------------------------
# High-level script generation functions
# ---------------------------------------------------------------------------

async def generate_script_from_tiktok_meta(
    title: str,
    description: str = "",
    caption: str = "",
    hashtags: Optional[List[str]] = None,
    product_hint: Optional[str] = None,
    video_path: Optional[Path] = None,
    num_frames: int = 3,
    theme: Optional[str] = None,
) -> ScriptResult:
    """
    Tự động nhận diện sản phẩm và tạo kịch bản review TikTok kết hợp:
    1. Thông tin văn bản: Tiêu đề video, Caption, Description, Hashtags.
    2. Thông tin hình ảnh: 2-4 frame ảnh đại diện trích xuất từ video gốc bằng FFmpeg.
    Nếu gặp lỗi, bắn lỗi ra ngay (không fallback).
    """
    tags_str = ", ".join(hashtags) if hashtags else ""
    user_msg_parts = [
        "THÔNG TIN VIDEO TIKTOK ĐỂ PHÂN TÍCH NHẬN DIỆN SẢN PHẨM:",
        f"- Tiêu đề (Title): {title or '(Không có)'}",
    ]
    if caption:
        user_msg_parts.append(f"- Caption: {caption}")
    if description and description != caption:
        user_msg_parts.append(f"- Mô tả (Description): {description}")
    if tags_str:
        user_msg_parts.append(f"- Hashtags: {tags_str}")
    if product_hint:
        user_msg_parts.append(f"- Gợi ý tên sản phẩm: {product_hint}")

    user_msg_parts.append(
        "\nYÊU CẦU:\n"
        "1. Phân tích các frame ảnh từ video đính kèm (nếu có) cùng Tiêu đề, Caption và Hashtags để nhận diện chính xác tên sản phẩm thực tế, công dụng nổi bật và chi tiết trải nghiệm.\n"
        "2. Tạo kịch bản review TikTok theo phong cách giọng nam Adam duyên dáng, tấu hài; câu mở đầu PHẢI theo đúng KIỂU HOOK BẮT BUỘC bên dưới, viết mới hoàn toàn, không trùng lặp các câu mở đầu gần đây.\n"
        "3. Sử dụng từ ngữ cảm thán, tiếng lóng tấu hài nhẹ nhàng (má ơi, trời ơi, vãi chưởng, khùng thiệt, não lag...) một cách tiết chế, đổi từ liên tục, không dùng từ thô tục nặng.\n"
        "4. Xuất dữ liệu banner/style 3 theo đúng schema JSON đã hướng dẫn."
    )
    theme_directive = build_theme_directive(theme)
    if theme_directive:
        logger.info(f"Script theme: {normalize_script_theme(theme)}")
        user_msg_parts.append(theme_directive)
    hook_style, hook_directive = _prepare_hook()
    user_msg_parts.append(hook_directive)
    user_msg = "\n".join(user_msg_parts)

    frames: List[Path] = []
    if video_path:
        frames = await extract_video_frames(Path(video_path), num_frames=num_frames)
        logger.info(f"Extracted {len(frames)} video frames for multimodal product recognition: {video_path}")

    raw, data = await _call_llm_with_hook_guard(user_msg, image_paths=frames)
    prod_name = data.get("product_name") or product_hint or title or "Sản phẩm"
    record_hook_usage(hook_style.key, str(data.get("tiktok_script", "")), data.get("style3_headline"))
    return ScriptResult(
        product_name=prod_name,
        tiktok_script=data.get("tiktok_script", ""),
        caption=data.get("caption", ""),
        hashtags=data.get("hashtags", hashtags or []),
        overlay_banner_title=data.get("overlay_banner_title"),
        style3_headline=data.get("style3_headline"),
        style3_quote=data.get("style3_quote"),
        raw_response=raw,
    )


async def generate_script(
    product_name: str,
    extra_context: Optional[str] = None,
    image_paths: Optional[Sequence[Path]] = None,
    theme: Optional[str] = None,
) -> ScriptResult:
    """
    Generate a single script for one product name (with optional context/images/theme).
    """
    user_msg = f"Sản phẩm: {product_name}"
    if extra_context:
        user_msg += f"\nGhi chú: {extra_context}"
    user_msg += build_theme_directive(theme)
    hook_style, hook_directive = _prepare_hook()
    user_msg += "\n" + hook_directive

    raw, data = await _call_llm_with_hook_guard(user_msg, image_paths=image_paths)
    record_hook_usage(hook_style.key, str(data.get("tiktok_script", "")), data.get("style3_headline"))
    return ScriptResult(
        product_name=data.get("product_name", product_name),
        tiktok_script=data["tiktok_script"],
        caption=data["caption"],
        hashtags=data.get("hashtags", []),
        overlay_banner_title=data.get("overlay_banner_title"),
        style3_headline=data.get("style3_headline"),
        style3_quote=data.get("style3_quote"),
        raw_response=raw,
    )


def from_custom_text(product_name: str, custom_text: str) -> ScriptResult:
    """
    Build a ScriptResult from user-supplied text (no LLM call).
    """
    text = custom_text.strip()
    if not text:
        raise ValueError("custom_text cannot be empty")
    safe_name = product_name.replace(" ", "")
    return ScriptResult(
        product_name=product_name,
        tiktok_script=text,
        caption=f"Múc liền em này về đi mấy cưng 😆",
        hashtags=["#review", "#tiktokvietnam", f"#{safe_name}"],
        overlay_banner_title=product_name.upper(),
        style3_headline=product_name.upper(),
        style3_quote=text[:100],
        raw_response="[manual override]",
    )


def split_into_sentences(text: str, max_sentences: int = 3) -> list[str]:
    """
    Split text into at most max_sentences clean sentences.
    Preserves Vietnamese punctuation and ElevenLabs audio tags.
    """
    raw_sentences = re.split(r"(?<=[.!?…])\s+", text.strip())
    sentences = [s.strip() for s in raw_sentences if s.strip()]

    if not sentences:
        return [text]

    if len(sentences) <= max_sentences:
        return sentences

    # Group into max_sentences chunks
    chunk_size = len(sentences) // max_sentences
    remainder = len(sentences) % max_sentences
    result = []
    idx = 0
    for i in range(max_sentences):
        size = chunk_size + (1 if i < remainder else 0)
        chunk = " ".join(sentences[idx : idx + size])
        result.append(chunk)
        idx += size

    return result


async def generate_batch(
    product_names: List[str],
    concurrency: int = 3,
) -> List[ScriptResult]:
    """Generate scripts for multiple products concurrently."""
    semaphore = asyncio.Semaphore(concurrency)

    async def _worker(name: str) -> ScriptResult:
        async with semaphore:
            return await generate_script(name)

    tasks = [_worker(name) for name in product_names]
    return await asyncio.gather(*tasks)
