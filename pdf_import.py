"""Split a PDF question paper into individual questions with options.

Text is extracted with PyMuPDF; every detected question also gets a cropped
image of its own region on the page, so figures, hand-set equations and
anything the text layer mangles stay usable for printing.
"""
import os
import re
import uuid

import pymupdf

from ocr import page_lines as ocr_page_lines
from ocr import page_ocr_backend

QUESTION_START = re.compile(
    r"^\s*(?:Q\s*[.\-\u2013:]?\s*(\d{1,3})\s*[.)\]:]?\s*|(\d{1,3})\s*[.)\]]\s+(?=\S))"
)
# Option labels seen in Indian papers: (A)-(D), (a)-(d), (i)-(iv) and 1)-4).
OPTION_FAMILIES: list[tuple[str, tuple[str, ...]]] = [
    (r"(?:^|\s)[\(\[]?(I{1,3}|IV|i{1,3}|iv)[\).\]]\s*(?=\S)", ("i", "ii", "iii", "iv")),
    (r"(?:^|\s)[\(\[]?([A-D])[\).\]:]\s*(?=\S)", ("a", "b", "c", "d")),
    (r"(?:^|\s)[\(\[]?([a-d])[\).\]:]\s*(?=\S)", ("a", "b", "c", "d")),
    (r"(?:^|\s)[\(\[]?([1-4])[\).\]:]\s*(?=\S)", ("1", "2", "3", "4")),
]
OPTION_PATTERNS = [(re.compile(p), labels) for p, labels in OPTION_FAMILIES]
PAGE_NOISE = re.compile(
    r"^\s*(space for rough work|do not open this booklet|this space for rough work)\s*$",
    re.IGNORECASE,
)
RUNNING_HEAD = re.compile(
    r"^\s*(page\s*\d+|\d+\s*[|/]\s*(page|\d+)|[-\u2013]?\s*\d{1,3}\s*[-\u2013]?)\s*$", re.IGNORECASE
)
REPEATED_HEAD_PAGES = 3
CROP_ZOOM = 4.2  # ~300 DPI canonical source crop for tiny superscripts/subscripts
MIN_TEXT_CHARS = 40
MARGIN_FRACTION = 0.08
COLUMN_GUTTER = 0.03
MIN_COLUMN_LINES = 6
MIN_SCAN_DRAWINGS = 8
OCR_ZOOM = 4.2  # ~300 DPI render; improves tiny scientific symbols
PRIVATE_GLYPHS = re.compile(r"[\ue000-\uf8ff]")
GARBLED_TOKEN_SHARE = 0.3
SYMBOL_FONT_SHARE = 0.02

# Symbol-encoded fonts (very common for maths in Indian papers) extract as
# private-use characters U+F0xx; translate the ones that carry meaning.
SYMBOL_GREEK = {
    "a": "α", "b": "β", "g": "γ", "d": "δ", "e": "ε", "z": "ζ", "h": "η",
    "q": "θ", "i": "ι", "k": "κ", "l": "λ", "m": "μ", "n": "ν", "x": "ξ",
    "o": "ο", "p": "π", "r": "ρ", "s": "σ", "t": "τ", "u": "υ", "f": "φ",
    "c": "χ", "y": "ψ", "w": "ω", "j": "ϑ", "v": "ϖ",
    "A": "Α", "B": "Β", "G": "Γ", "D": "Δ", "E": "Ε", "Z": "Ζ", "H": "Η",
    "Q": "Θ", "I": "Ι", "K": "Κ", "L": "Λ", "M": "Μ", "N": "Ν", "X": "Ξ",
    "O": "Ο", "P": "Π", "R": "Ρ", "S": "Σ", "T": "Τ", "U": "Υ", "F": "Φ",
    "C": "Χ", "Y": "Ψ", "W": "Ω",
}
SYMBOL_HIGH = {
    0xA3: "≤", 0xB3: "≥", 0xB9: "≠", 0xBB: "≈", 0xB1: "±", 0xB4: "×",
    0xB8: "÷", 0xD6: "√", 0xA5: "∞", 0xB6: "∂", 0xF2: "∫", 0xE5: "∑",
    0xD5: "∏", 0xCE: "∈", 0xCF: "∉", 0xC7: "∩", 0xC8: "∪", 0xCC: "⊂",
    0xCD: "⊆", 0xAE: "→", 0xAC: "←", 0xAD: "↑", 0xAF: "↓", 0xAB: "↔",
    0xD8: "¬", 0xD9: "∧", 0xDA: "∨", 0xB0: "°", 0xB7: "·", 0xBC: "…",
    0xA6: "ƒ", 0xA2: "′", 0xC5: "⊕", 0xC4: "⊗", 0x40: "≅", 0x7E: "∼",
    0x22: "∀", 0x24: "∃", 0xDE: "⇒", 0xDB: "⇔", 0xA1: "ϒ",
}


def _from_symbol_font(ch: str) -> str:
    """Best-effort Unicode for one U+F0xx Symbol-font character."""
    code = ord(ch) & 0xFF
    if code in SYMBOL_HIGH:
        return SYMBOL_HIGH[code]
    if 0x20 <= code <= 0x7E:
        plain = chr(code)
        return SYMBOL_GREEK.get(plain, plain)
    return " "


def _clean(text: str) -> str:
    """Drop boilerplate lines and undo the PDF's hard line wrapping."""
    text = PRIVATE_GLYPHS.sub(lambda m: _from_symbol_font(m.group()), text)
    kept = [ln.strip() for ln in text.splitlines() if ln.strip() and not PAGE_NOISE.match(ln)]
    out = ""
    for line in kept:
        if not out:
            out = line
        elif out.endswith("-") and line[0].isalpha() and out[-2:-1].isalpha():
            out = out[:-1] + line
        else:
            out += " " + line
    return re.sub(r"\s{2,}", " ", out).strip()


def _label_run(chunk: str, pattern: re.Pattern, labels: tuple[str, ...]) -> list[re.Match]:
    """Matches of one label family, in order, starting at the first label."""
    ordered: list[re.Match] = []
    for m in pattern.finditer(chunk):
        if len(ordered) < len(labels) and m.group(1).lower() == labels[len(ordered)]:
            ordered.append(m)
            if len(ordered) == len(labels):
                break
    return ordered


def _best_run(chunk: str) -> list[re.Match]:
    """Longest sequential option run across the supported label families."""
    best: list[re.Match] = []
    for pattern, labels in OPTION_PATTERNS:
        run = _label_run(chunk, pattern, labels)
        if len(run) > len(best) or (len(run) == 4 and labels == ("1", "2", "3", "4")):
            best = run
    return best


def _has_full_option_set(chunk: str) -> bool:
    """True once a complete four-option set has been seen: the question ended."""
    return len(_best_run(chunk)) == 4


def _split_options(chunk: str) -> tuple[str, list[str]]:
    """Return (statement, options) for one question chunk."""
    parenthesized = re.compile(r"(?:^|\s)\(([1-4])\)\s*(?=\S)")
    ordered = _label_run(chunk, parenthesized, ("1", "2", "3", "4"))
    if len(ordered) != 4:
        ordered = _best_run(chunk)
    if len(ordered) < 2:
        return _clean(chunk), []
    statement = chunk[: ordered[0].start()]
    options = []
    for idx, m in enumerate(ordered):
        end = ordered[idx + 1].start() if idx + 1 < len(ordered) else len(chunk)
        options.append(_clean(chunk[m.end():end]))
    return _clean(statement), options


def _reading_order(lines: list[tuple], page: pymupdf.Page) -> list[tuple]:
    """Reading order for one- and two-column pages.

    Sorting by height alone interleaves the two columns of a typical Indian
    paper, which scrambles both the wording and the question boundaries. Lines
    that cross the page's centre split the page into bands; inside a band the
    left column is read before the right one.
    """
    mid = (page.rect.x0 + page.rect.x1) / 2
    gutter = page.rect.width * COLUMN_GUTTER
    lines = sorted(lines, key=lambda item: (round(item[1][1], 1), item[1][0]))
    left = [ln for ln in lines if ln[1][2] <= mid + gutter]
    right = [ln for ln in lines if ln[1][0] >= mid - gutter]
    if min(len(left), len(right)) < MIN_COLUMN_LINES:
        return lines

    ordered: list[tuple] = []
    band: list[tuple] = []

    def flush_band() -> None:
        # Preserve the actual row order instead of emitting every left-column item
        # before every right-column item. OCR often interleaves questions by row,
        # and the old behavior could reorder whole question blocks.
        ordered.extend(sorted(band, key=lambda item: (round(item[1][1], 1), item[1][0])))
        band.clear()

    for line in lines:
        x0, x1 = line[1][0], line[1][2]
        if x0 < mid - gutter and x1 > mid + gutter:  # spans both columns
            flush_band()
            ordered.append(line)
        else:
            band.append(line)
    flush_band()
    return ordered


def _mark_margins(lines: list[tuple], page: pymupdf.Page) -> list[tuple]:
    margin = page.rect.height * MARGIN_FRACTION
    top, bottom = page.rect.y0 + margin, page.rect.y1 - margin
    return [(text, bbox, bbox[1] < top or bbox[3] > bottom) for text, bbox in lines]


def _text_layer_lines(page: pymupdf.Page) -> list[tuple]:
    lines = []
    for block in page.get_text("dict", sort=True)["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line["spans"])
            if text.strip():
                lines.append((text, tuple(line["bbox"])))
    return lines


def _layout_formula_lines(page: pymupdf.Page, upload_dir: str, heads: set[str]) -> list[tuple] | None:
    """Keep Type3 equations as inline crops, ordered alongside editable prose.

    These fonts often store every mathematical glyph in a separate PDF object.
    Flattening them destroys fractions, powers and even the sentence order.
    Prose baselines anchor rows; each contiguous mathematical region stays visual.
    """
    spans = []
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                chars = span["chars"]
                runs = []
                for char in chars:
                    if not runs or char["bbox"][0] - runs[-1][-1]["bbox"][2] > 2.5:
                        runs.append([])
                    runs[-1].append(char)
                for run in runs:
                    text = "".join(c["c"] for c in run)
                    if not text.strip():
                        continue
                    box = (min(c["bbox"][0] for c in run), min(c["bbox"][1] for c in run),
                           max(c["bbox"][2] for c in run), max(c["bbox"][3] for c in run))
                    if (box[3] < page.rect.height * .08 or box[1] > page.rect.height * .92) and (text.strip() in heads or RUNNING_HEAD.match(text)):
                        continue
                    spans.append({**span, "text": text, "bbox": box})
    math = [s for s in spans if s["font"].startswith("Type3")]
    if not math:
        return None
    prose = [s for s in spans if not s["font"].startswith("Type3")]
    rows = []
    for span in sorted(prose, key=lambda s: s["origin"][1]):
        baseline = span["origin"][1]
        row = next((r for r in rows if abs(r[0] - baseline) < 2), None)
        if row is None:
            row = [baseline, []]
            rows.append(row)
        row[1].append(span)
    for span in math:
        # The bottom of a normal math glyph sits close to the prose baseline.
        center = (span["bbox"][1] + span["bbox"][3]) / 2
        row = min(rows, key=lambda r: abs((r[0] - 4) - center)) if rows else None
        if row is None or abs(row[0] - 4 - center) > 12:
            row = [center + 4, []]
            rows.append(row)
        row[1].append(span)
    result = []
    for baseline, row_spans in sorted(rows):
        pieces, group = [], []
        def emit():
            if not group:
                return
            rect = pymupdf.Rect(group[0]["bbox"])
            for span in group[1:]:
                rect |= pymupdf.Rect(span["bbox"])
            rect = (rect + (-0.4, -0.6, 0.4, 0.6)) & page.rect
            name = f"{uuid.uuid4().hex}.png"
            page.get_pixmap(matrix=pymupdf.Matrix(3, 3), clip=rect).save(os.path.join(upload_dir, name))
            # Height is relative to the source prose font, so formulas scale with text.
            height = round(rect.height / 11, 3)
            pieces.append(f"![formula:{height}](/uploads/{name})")
            group.clear()
        for span in sorted(row_spans, key=lambda s: s["bbox"][0]):
            if span["font"].startswith("Type3"):
                if group and span["bbox"][0] - max(s["bbox"][2] for s in group) > 7:
                    emit()
                group.append(span)
            else:
                emit()
                pieces.append(span["text"])
        emit()
        bbox = (min(s["bbox"][0] for s in row_spans), min(s["bbox"][1] for s in row_spans),
                max(s["bbox"][2] for s in row_spans), max(s["bbox"][3] for s in row_spans))
        result.append((" ".join(pieces), bbox))
    return _mark_margins(result, page)


def _ocr_lines(page: pymupdf.Page) -> list[tuple]:
    """Lines read off the rendered page by the page-OCR backend, in page coordinates."""
    pix = page.get_pixmap(matrix=pymupdf.Matrix(OCR_ZOOM, OCR_ZOOM))
    return [(t, b) for t, b in ocr_page_lines(pix.tobytes("png"), OCR_ZOOM) if t.strip()]


def _text_layer_is_poor(lines: list[tuple]) -> bool:
    """True when a page's own text layer cannot be trusted for wording.

    Scanned pages carry no text at all, and symbol-encoded fonts — the other
    way a paper's meaning changes on extraction — leave private-use glyphs.
    """
    text = " ".join(t for t, _ in lines)
    if len(text) < MIN_TEXT_CHARS:
        return True
    return len(PRIVATE_GLYPHS.findall(text)) / len(text) > SYMBOL_FONT_SHARE


def _page_lines(page: pymupdf.Page, mode: str = "auto") -> tuple[list[tuple], str]:
    """((text, bbox, in_margin) in reading order, source of the wording).

    ``mode`` is ``text`` (the PDF's own text layer), ``ocr`` (read the rendered
    page as pixels) or ``auto``, which reads the page layer and falls back to
    OCR for pages whose text layer is unusable.
    """
    source = mode if mode == "ocr" else "text"
    if mode == "ocr":
        lines = _ocr_lines(page)
    else:
        lines = _text_layer_lines(page)
        if mode == "auto" and _text_layer_is_poor(lines) and page_ocr_backend() != "none":
            try:
                read = _ocr_lines(page)
            except Exception:
                read = []
            if read:
                lines, source = read, "ocr"
    return _reading_order(_mark_margins(lines, page), page), source


def _running_heads(pages: list[list[tuple]]) -> set[str]:
    """Header/footer texts that repeat in the margins of several pages."""
    counts: dict[str, int] = {}
    for lines in pages:
        for text in {
            t.strip() for t, _, in_margin in lines
            if in_margin and not QUESTION_START.match(t)
        }:
            counts[text] = counts.get(text, 0) + 1
    return {t for t, n in counts.items() if n >= REPEATED_HEAD_PAGES}


def _looks_garbled(text: str) -> bool:
    """Maths laid out as loose glyphs extracts as a stream of one-char tokens."""
    tokens = text.split()
    if len(tokens) < 12:
        return False
    singles = sum(1 for t in tokens if len(t) == 1 and t.lower() not in {"a", "i"})
    return singles / len(tokens) > GARBLED_TOKEN_SHARE


def _crop(page: pymupdf.Page, boxes: list[tuple], upload_dir: str) -> tuple[str, list[float]]:
    """High-resolution crop plus normalized source bbox for provenance/reconciliation."""
    if not boxes:
        return "", []
    x0 = min(b[0] for b in boxes) - 6
    y0 = min(b[1] for b in boxes) - 6
    x1 = max(b[2] for b in boxes) + 6
    y1 = max(b[3] for b in boxes) + 6
    rect = pymupdf.Rect(x0, y0, x1, y1) & page.rect
    if rect.is_empty:
        return "", []
    pix = page.get_pixmap(matrix=pymupdf.Matrix(CROP_ZOOM, CROP_ZOOM), clip=rect, alpha=False)
    name = f"{uuid.uuid4().hex}.png"
    pix.save(os.path.join(upload_dir, name))
    pr = page.rect
    bbox = [
        round((rect.x0 - pr.x0) / pr.width, 6),
        round((rect.y0 - pr.y0) / pr.height, 6),
        round((rect.x1 - pr.x0) / pr.width, 6),
        round((rect.y1 - pr.y0) / pr.height, 6),
    ]
    return f"/uploads/{name}", bbox


def parse_pdf(pdf_bytes: bytes, upload_dir: str, mode: str = "auto") -> dict:
    """Return {"questions": [...], "warnings": [...]} for an uploaded paper.

    ``mode`` picks where the wording comes from: ``auto`` uses each page's text
    layer and re-reads unusable pages with OCR, ``ocr`` forces OCR everywhere and
    ``text`` trusts the PDF only.
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    questions: list[dict] = []
    warnings: list[str] = []
    current: dict | None = None

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        statement, options = _split_options("\n".join(current["lines"]))
        if statement or options:
            source_segments = []
            for segment_page in sorted(current.get("segments", {})):
                segment = current["segments"][segment_page]
                image, bbox = _crop(segment["page_ref"], segment["boxes"], upload_dir)
                if image:
                    source_segments.append({"page": segment_page, "bbox": bbox, "image": image})
            first = source_segments[0] if source_segments else {"image": "", "bbox": []}
            questions.append({
                "number": current["number"],
                "page": current["page"],
                "statement": statement,
                "options": options,
                "image": first["image"],
                "source_bbox": first["bbox"],
                "source_segments": source_segments,
                "garbled": _looks_garbled(statement),
            })
        current = None

    # Stop at the explicit answer section; solution numbering is not question numbering.
    question_pages = []
    for page in doc:
        if re.search(r"(?im)^\s*ANSWERS?\s+(?:AND|&)\s+SOLUTIONS?\s*$", page.get_text()):
            break
        question_pages.append(page)
    heads = _running_heads([_mark_margins(_text_layer_lines(p), p) for p in doc])
    formula_pages = []
    read_pages = []
    for page in question_pages:
        layout = _layout_formula_lines(page, upload_dir, heads) if mode != "ocr" else None
        if layout is not None:
            formula_pages.append(page.number + 1)
            read_pages.append((layout, "layout"))
        else:
            read_pages.append(_page_lines(page, mode))
    pages = [lines for lines, _ in read_pages]
    ocr_pages = [i for i, (_, src) in enumerate(read_pages, start=1) if src == "ocr"]

    for page_index, (page, raw_lines) in enumerate(zip(doc, pages), start=1):
        lines = [
            (text, bbox) for text, bbox, in_margin in raw_lines
            if not (in_margin and (text.strip() in heads or RUNNING_HEAD.match(text)))
        ]
        if sum(len(t) for t, _ in lines) < MIN_TEXT_CHARS:
            flush()
            if not page.get_images(full=True) and len(page.get_drawings()) < MIN_SCAN_DRAWINGS:
                continue  # genuinely blank / end-of-paper page
            pix = page.get_pixmap(matrix=pymupdf.Matrix(CROP_ZOOM, CROP_ZOOM))
            name = f"{uuid.uuid4().hex}.png"
            pix.save(os.path.join(upload_dir, name))
            warnings.append(f"Page {page_index} has no text layer (scanned) — imported as a page image.")
            questions.append({
                "number": None, "page": page_index, "statement": "",
                "options": [], "image": f"/uploads/{name}", "source_bbox": [0, 0, 1, 1],
                "source_segments": [{"page": page_index, "bbox": [0, 0, 1, 1], "image": f"/uploads/{name}"}],
                "garbled": True,
            })
            continue
        for text, bbox in lines:
            match = QUESTION_START.match(text)
            if match:
                flush()
                number = match.group(1) or match.group(2)
                current = {
                    "number": int(number), "page": page_index,
                    "lines": [text[match.end():]],
                    "segments": {page_index: {"page_ref": page, "boxes": [bbox]}},
                }
            elif current is not None:
                current["lines"].append(text)
                segment = current["segments"].setdefault(page_index, {"page_ref": page, "boxes": []})
                segment["boxes"].append(bbox)
        if current is not None and _has_full_option_set("\n".join(current["lines"])):
            flush()
    flush()

    if not questions:
        if all(not lines for lines in pages):
            warnings.append(
                "This PDF carries no readable content — its page streams are damaged or "
                "empty. Re-download or re-save the original file and try again."
            )
        else:
            warnings.append("No questions detected — the paper may use an unsupported numbering style.")
    without_options = sum(1 for q in questions if not q["options"])
    if questions and without_options:
        warnings.append(f"{without_options} of {len(questions)} questions had no options detected.")
    garbled = sum(1 for q in questions if q["garbled"])
    if questions and garbled > len(questions) / 3:
        warnings.append(
            f"{garbled} of {len(questions)} questions have maths the text layer cannot "
            "represent — import them as images to keep the equations readable."
        )
    return {
        "questions": questions,
        "warnings": warnings,
        "ocr_pages": ocr_pages,
        "pages": len(doc),
        "formula_pages": formula_pages,
        "mostly_garbled": bool(questions) and garbled > len(questions) / 3,
    }
