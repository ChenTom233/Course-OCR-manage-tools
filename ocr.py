"""OCR 后端：优先使用 Windows 内置中文 OCR，未安装时回退到 RapidOCR。"""
from __future__ import annotations

import asyncio
import io
import re
from typing import Callable

from PIL import Image

LogFn = Callable[[str], None]
Item = tuple[float, float, float, float, str]  # x0, y0, x1, y1, text

_ocr_engine = None


def _noop(msg: str) -> None:
    pass


def _windows_engine():
    global _ocr_engine
    if _ocr_engine is None:
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine

        engine = OcrEngine.try_create_from_language(Language("zh-Hans-CN"))
        if engine is None:
            engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise RuntimeError("系统未安装中文 OCR 语言包")
        _ocr_engine = engine
    return _ocr_engine


async def _recognize_async(png: bytes):
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream.get_output_stream_at(0))
    writer.write_bytes(png)
    await writer.store_async()
    await writer.flush_async()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    try:
        return await _windows_engine().recognize_async(bitmap)
    finally:
        bitmap.close()
        stream.close()


def _normalize_ocr_text(text: str) -> str:
    text = text.replace("．", ":")
    # OCR 常把连字符读成汉字“一”，仅在数字之间替换
    text = re.sub(r"(?<=\d)\s*一\s*(?=\d)", "-", text)
    return text.strip()


def _line_items(line) -> list[Item]:
    words = []
    for word in line.words:
        text = (word.text or "").strip()
        if text:
            rect = word.bounding_rect
            words.append(
                (float(rect.x), float(rect.y), float(rect.x + rect.width),
                 float(rect.y + rect.height), text)
            )
    if not words:
        return []
    words.sort(key=lambda item: item[0])

    # 按字间空隙把逐字框合并成语义片段：同一词语内空隙很小，
    # 课程名 / 教师 / 周次之间的空隙明显更大。
    groups: list[list] = []
    for word in words:
        if groups:
            gx0, gy0, gx1, gy1, gtext = groups[-1]
            gap = word[0] - gx1
            height = max(1.0, min(word[3] - word[1], gy1 - gy0))
            if gap <= max(2.0, height * 0.35):
                groups[-1] = [
                    min(gx0, word[0]), min(gy0, word[1]),
                    max(gx1, word[2]), max(gy1, word[3]), gtext + word[4],
                ]
                continue
        groups.append(list(word))

    items: list[Item] = []
    for x0, y0, x1, y1, text in groups:
        text = _normalize_ocr_text(text)
        if text:
            items.append((x0, y0, x1, y1, text))
    return items


def _windows_ocr(image) -> list[Item]:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    result = asyncio.run(_recognize_async(buffer.getvalue()))
    items: list[Item] = []
    for line in result.lines:
        items.extend(_line_items(line))
    return items


def _runs(indices: list[int], max_gap: int = 2) -> list[list[int]]:
    groups: list[list[int]] = []
    for index in indices:
        if groups and index - groups[-1][-1] <= max_gap:
            groups[-1].append(index)
        else:
            groups.append([index])
    return groups


def _line_centers(profile, limit: int) -> list[float]:
    groups = _runs([i for i, value in enumerate(profile) if value < limit])
    # 细线通常只有 1–4 像素宽，宽块是文字而不是表格线
    return [sum(g) / len(g) for g in groups if len(g) <= 5]


def _looks_like_timetable(items: list[Item]) -> bool:
    text = "".join(item[4] for item in items)
    return any(word in text for word in ("节次", "时间", "课程表", "星期", "周"))


def _grid_hints(image, items: list[Item]) -> list[Item]:
    """扫描件表头/节次漏识别时，用表格线补出星期列与节次锚点。"""
    if not _looks_like_timetable(items):
        return []
    gray = image.convert("L")
    mask = gray.point(lambda value: 255 if value < 160 else 0)
    box = mask.getbbox()
    if not box:
        return []
    region = gray.crop(box)
    width, height = region.size
    if width < 300 or height < 200:
        return []

    columns = list(region.resize((width, 1), Image.BOX).getdata())
    rows = list(region.resize((1, height), Image.BOX).getdata())
    vlines = [x + box[0] for x in _line_centers(columns, 170)]
    hlines = [y + box[1] for y in _line_centers(rows, 170)]
    if len(vlines) < 9 or len(hlines) < 4:
        return []

    day_chars = "一二三四五六日"
    hint_y = (hlines[0] + hlines[1]) / 2
    hints: list[Item] = []
    for day, (left, right) in enumerate(
        zip(vlines[-8:-1], vlines[-7:]), start=1
    ):
        cx = (left + right) / 2
        hints.append((cx - 24, hint_y - 14, cx + 24, hint_y + 14, f"周{day_chars[day - 1]}"))

    left_col = (vlines[0] + vlines[1]) / 2
    for period, (top, bottom) in enumerate(
        zip(hlines[1:-1], hlines[2:]), start=1
    ):
        cy = (top + bottom) / 2
        hints.append((left_col - 12, cy - 12, left_col + 12, cy + 12, f"第{period}节"))
    return hints


def _rapidocr(image) -> list[Item]:
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    # RapidOCR 默认按 OpenCV 的 BGR 顺序处理
    array = np.array(image.convert("RGB"))[:, :, ::-1]
    result, _ = engine(array)
    items: list[Item] = []
    for entry in result or []:
        try:
            box, text, score = entry
        except (TypeError, ValueError):
            continue
        if float(score) < 0.4 or not str(text).strip():
            continue
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        items.append((min(xs), min(ys), max(xs), max(ys), str(text).strip()))
    return items


def recognize(image, log: LogFn = _noop) -> list[Item]:
    """识别 PIL 图像，返回 (x0, y0, x1, y1, text) 文字块。"""
    errors: list[str] = []
    try:
        items = _windows_ocr(image)
        if items:
            hints = _grid_hints(image, items)
            if hints:
                log(f"  依据表格线补全 {len(hints)} 个表头/节次锚点")
                items += hints
            log(f"  Windows OCR 识别到 {len(items)} 个文字块")
            return items
        errors.append("Windows OCR 未返回文字")
    except Exception as exc:
        errors.append(f"Windows OCR 不可用（{exc}）")

    try:
        items = _rapidocr(image)
        if items:
            log(f"  已回退到 RapidOCR，识别到 {len(items)} 个文字块")
            return items
        errors.append("RapidOCR 未返回文字")
    except ImportError:
        errors.append("未安装 RapidOCR 回退引擎")
    except Exception as exc:
        errors.append(f"RapidOCR 失败（{exc}）")

    log("  OCR 未识别到文字：" + "；".join(errors))
    return []
