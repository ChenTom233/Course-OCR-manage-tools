"""PDF 课表解析：文本层表格 → 坐标还原 → 文本行兜底 → OCR。"""
from __future__ import annotations

from .ocr import recognize
from .parsing import (
    Item,
    LogFn,
    _dedupe_courses,
    _noop,
    _period_from_row_cell,
    courses_from_items,
    courses_from_text,
    detect_day_header,
    detect_period_col,
    normalize_text,
    parse_grid,
    parse_table,
)


def _cell_text(value) -> str:
    return "" if value is None else str(value).strip()


def _extract_tables(page, strategy: str, log: LogFn):
    try:
        if strategy == "lines":
            return page.extract_tables() or []
        return page.extract_tables(
            {
                "vertical_strategy": "text",
                "horizontal_strategy": "text",
                "intersection_tolerance": 4,
            }
        ) or []
    except Exception as exc:  # pdfplumber 对复杂 PDF 可能抛异常
        log(f"  表格提取失败（{strategy}）：{exc}")
        return []


def _words_to_items(page) -> list[Item]:
    items: list[Item] = []
    try:
        words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
    except Exception:
        return items
    for word in words:
        text = _cell_text(word.get("text"))
        if not text:
            continue
        items.append(
            (
                float(word.get("x0", 0)),
                float(word.get("top", 0)),
                float(word.get("x1", 0)),
                float(word.get("bottom", 0)),
                text,
            )
        )
    return items


def _ocr_page(path: str, page_index: int, log: LogFn) -> list:
    try:
        import pypdfium2 as pdfium
    except ImportError:
        log("  缺少 OCR 依赖：pip install pypdfium2 Pillow")
        return []

    try:
        doc = pdfium.PdfDocument(path)
        try:
            page = doc[page_index]
            image = page.render(scale=3.0).to_pil()
        finally:
            doc.close()
    except Exception as exc:
        log(f"  OCR 失败：{exc}")
        return []

    items = recognize(image, log)
    if not items:
        return []
    return courses_from_items(items, log)


def _has_text(matrix: list[list[str]]) -> bool:
    return any(normalize_text(cell) for row in matrix for cell in row)


def _pad_rows(matrix: list[list[str]]) -> list[list[str]]:
    width = max((len(row) for row in matrix), default=0)
    return [list(row) + [""] * (width - len(row)) for row in matrix]


def _is_continuation_row(
    matrix: list[list[str]], day_cols: dict[int, int], period_col
) -> bool:
    """跨页被拆开的单元格：下一页顶部没有节次，但在星期列里有文字。"""
    if not matrix:
        return False
    row = matrix[0]
    if period_col is not None and period_col < len(row):
        if _period_from_row_cell(row[period_col]):
            return False
    return any(ci < len(row) and normalize_text(row[ci]) for ci in day_cols)


def _merge_continuation(
    prev_matrix: list[list[str]], row: list[str], day_cols: dict[int, int]
) -> None:
    """把续页顶部的文字拼回上一页同列最后一个非空单元格。"""
    for ci in day_cols:
        text = normalize_text(row[ci]) if ci < len(row) else ""
        if not text:
            continue
        for ri in range(len(prev_matrix) - 1, -1, -1):
            prow = prev_matrix[ri]
            if ci < len(prow) and normalize_text(prow[ci]):
                prow[ci] = prow[ci].rstrip() + "\n" + text
                break


def parse_pdf(path: str, log: LogFn = _noop) -> list:
    import pdfplumber

    all_courses = []
    with pdfplumber.open(path) as pdf:
        pages = list(pdf.pages)
        log(f"PDF 共 {len(pages)} 页")

        matrices: list[tuple[int, list[list[str]]]] = []
        for page_no, page in enumerate(pages, 1):
            log(f"第 {page_no} 页")
            tables = _extract_tables(page, "lines", log)
            if not tables:
                tables = _extract_tables(page, "text", log)
            for table in tables:
                matrix = _pad_rows([[_cell_text(c) for c in row] for row in table])
                if _has_text(matrix):
                    matrices.append((page_no, matrix))

        # 表头、节次列通常只在第一页出现，后续页沿用
        day_cols = None
        period_col = None
        for _page_no, matrix in matrices:
            hr, cols, _best = detect_day_header(matrix)
            if hr >= 0:
                day_cols = cols
                period_col = detect_period_col(matrix, hr, cols)
                break

        page_counts: dict[int, int] = {}
        if day_cols is not None:
            for idx in range(1, len(matrices)):
                page_no, matrix = matrices[idx]
                prev_page_no, prev_matrix = matrices[idx - 1]
                if page_no == prev_page_no:
                    continue
                while matrix:
                    hr, _cols, _best = detect_day_header(matrix)
                    if hr == 0 or not _is_continuation_row(
                        matrix, day_cols, period_col
                    ):
                        break
                    _merge_continuation(prev_matrix, matrix[0], day_cols)
                    matrix = matrix[1:]
                matrices[idx] = (page_no, matrix)

            for page_no, matrix in matrices:
                if not matrix:
                    continue
                hr, _cols, _best = detect_day_header(matrix)
                found = parse_grid(
                    matrix,
                    log=log,
                    day_cols=day_cols,
                    header_row=(hr if hr >= 0 else None),
                    period_col=period_col,
                )
                all_courses.extend(found)
                page_counts[page_no] = page_counts.get(page_no, 0) + len(found)
        else:
            for page_no, matrix in matrices:
                found = parse_table(matrix, log)
                all_courses.extend(found)
                page_counts[page_no] = page_counts.get(page_no, 0) + len(found)

        # 表格没解析出课程的页面，再尝试坐标还原 / 文本行 / OCR
        for page_no, page in enumerate(pages, 1):
            if page_counts.get(page_no):
                continue
            courses: list = []
            items = _words_to_items(page)
            if items:
                courses = courses_from_items(items, log)

            text = ""
            if not courses:
                try:
                    text = page.extract_text() or ""
                except Exception:
                    text = ""
                if text.strip():
                    courses = courses_from_text(text, log)
                    if courses:
                        log(f"  按文本行解析，识别到 {len(courses)} 条课程")

            if not courses and len(text.strip()) < 10:
                log("  未检测到文本层，尝试 OCR")
                courses = _ocr_page(path, page_no - 1, log)

            if courses:
                log(f"  本页识别到 {len(courses)} 条课程")
            all_courses.extend(courses)

    before = len(all_courses)
    all_courses = _dedupe_courses(all_courses)
    if before != len(all_courses):
        log(f"去除重复记录 {before - len(all_courses)} 条")
    return all_courses
