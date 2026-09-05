"""Math OCR: turn a question crop into editable LaTeX.

Two interchangeable backends, picked by ``QB_OCR`` (default ``auto``):

``mathpix``  Mathpix Convert API — best quality on printed IIT papers.
             Needs ``MATHPIX_APP_ID`` and ``MATHPIX_APP_KEY``.
``pix2tex``  Local LaTeX-OCR model (``pip install pix2tex``) — no account,
             no network, but slower and formula-only.

A request may name a sub-region of the crop (fractions of width/height); the
formula-only backends need one, since a whole question with prose around the
maths is outside what they were trained on.

Separately, :func:`page_lines` reads a whole rendered page as pixels — the
wording-and-order path, not the LaTeX one: it re-derives the words and their
positions from the image, so papers whose text layer stores glyphs in the wrong
order come out readable. It runs on Google Cloud Vision when
``GCP_VISION_API_KEY`` is set, otherwise on a local Tesseract install.
"""
import base64
import io
import json
import os
import urllib.request

MATHPIX_URL = "https://api.mathpix.com/v3/text"
MATHPIX_TIMEOUT = 60
MIN_OCR_HEIGHT = 160  # crops come off the page too small for the models to read
MAX_UPSCALE = 4


class OcrUnavailable(RuntimeError):
    """No OCR backend is configured."""


def _mathpix_credentials() -> tuple[str, str] | None:
    app_id = os.environ.get("MATHPIX_APP_ID", "").strip()
    app_key = os.environ.get("MATHPIX_APP_KEY", "").strip()
    return (app_id, app_key) if app_id and app_key else None


def _pix2tex_available() -> bool:
    try:
        import pix2tex.cli  # noqa: F401
    except Exception:
        return False
    return True


def _documentai_available() -> bool:
    try:
        from gcp_documentai import status as documentai_status
        return bool(documentai_status().get("available"))
    except Exception:
        return False


def _backend() -> str:
    choice = os.environ.get("QB_OCR", "auto").strip().lower()
    if choice in {"documentai", "mathpix", "pix2tex"}:
        return choice
    # GCP-native Math OCR is the preferred backend for this MVP.
    if _documentai_available():
        return "documentai"
    if _mathpix_credentials():
        return "mathpix"
    return "pix2tex" if _pix2tex_available() else "none"


def ocr_status() -> dict:
    backend = _backend()
    return {
        "backend": backend,
        "available": backend != "none",
        "hint": {
            "documentai": "Google Cloud Document AI Math OCR",
            "mathpix": "Mathpix Convert API",
            "pix2tex": "local pix2tex model",
            "none": "configure DOCUMENTAI_PROCESSOR_ID, Mathpix, or install pix2tex",
        }[backend],
    }


def _prepare(path: str, box: list[float] | None) -> bytes:
    """PNG bytes of the requested region, upscaled to a size the models read."""
    from PIL import Image

    image = Image.open(path).convert("RGB")
    if box:
        x0, y0, x1, y1 = box
        width, height = image.size
        region = (
            max(0, int(x0 * width)), max(0, int(y0 * height)),
            min(width, int(x1 * width)), min(height, int(y1 * height)),
        )
        if region[2] - region[0] > 4 and region[3] - region[1] > 4:
            image = image.crop(region)
    scale = min(MAX_UPSCALE, max(1, MIN_OCR_HEIGHT // max(1, image.height)))
    if scale > 1:
        image = image.resize((image.width * scale, image.height * scale), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _mathpix(png: bytes) -> str:
    credentials = _mathpix_credentials()
    if credentials is None:
        raise OcrUnavailable("Mathpix credentials are not set")
    app_id, app_key = credentials
    encoded = base64.b64encode(png).decode()
    payload = {
        "src": f"data:image/png;base64,{encoded}",
        "formats": ["text"],
        "math_inline_delimiters": ["$", "$"],
        "math_display_delimiters": ["$$", "$$"],
        "rm_spaces": True,
    }
    request = urllib.request.Request(
        MATHPIX_URL,
        data=json.dumps(payload).encode(),
        headers={"app_id": app_id, "app_key": app_key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=MATHPIX_TIMEOUT) as response:
        result = json.loads(response.read())
    if result.get("error"):
        raise RuntimeError(result["error"])
    return (result.get("text") or "").strip()


_pix2tex_model = None


def _pix2tex(png: bytes) -> str:
    global _pix2tex_model
    if not _pix2tex_available():
        raise OcrUnavailable("pix2tex is not installed")
    from PIL import Image
    from pix2tex.cli import LatexOCR

    if _pix2tex_model is None:
        _pix2tex_model = LatexOCR()
    latex = _pix2tex_model(Image.open(io.BytesIO(png)))
    return f"${latex}$" if latex else ""


VISION_URL = "https://vision.googleapis.com/v1/images:annotate"
VISION_TIMEOUT = 90


def vision_key() -> str:
    return os.environ.get("GCP_VISION_API_KEY", "").strip()


def _tesseract_available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
    except Exception:
        return False
    return True


def page_ocr_backend() -> str:
    if vision_key():
        return "vision"
    return "tesseract" if _tesseract_available() else "none"


def vision_status() -> dict:
    backend = page_ocr_backend()
    return {
        "available": backend != "none",
        "backend": backend,
        "hint": {
            "vision": "Google Cloud Vision",
            "tesseract": "local Tesseract",
            "none": "set GCP_VISION_API_KEY or install tesseract-ocr",
        }[backend],
    }


def _vision_annotate(png: bytes) -> dict:
    key = vision_key()
    if not key:
        raise OcrUnavailable("GCP_VISION_API_KEY is not set")
    payload = {
        "requests": [{
            "image": {"content": base64.b64encode(png).decode()},
            "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
            "imageContext": {"languageHints": ["en"]},
        }]
    }
    request = urllib.request.Request(
        f"{VISION_URL}?key={key}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=VISION_TIMEOUT) as response:
        result = json.loads(response.read())
    first = (result.get("responses") or [{}])[0]
    if first.get("error"):
        raise RuntimeError(first["error"].get("message", "Vision error"))
    return first


def _word_text(word: dict) -> tuple[str, bool]:
    """The word's characters, and whether a line ends after it."""
    text = "".join(symbol.get("text", "") for symbol in word.get("symbols", []))
    symbols = word.get("symbols") or [{}]
    break_type = (symbols[-1].get("property", {}).get("detectedBreak", {})).get("type", "")
    return text, break_type in {"LINE_BREAK", "EOL_SURE_SPACE"}


def _bbox(vertices: list[dict]) -> tuple[float, float, float, float]:
    xs = [v.get("x", 0) for v in vertices] or [0]
    ys = [v.get("y", 0) for v in vertices] or [0]
    return (min(xs), min(ys), max(xs), max(ys))


def vision_page_lines(png: bytes, scale: float = 1.0) -> list[tuple[str, tuple[float, float, float, float]]]:
    """Lines of one rendered page as (text, bbox), bboxes divided by ``scale``."""
    annotation = _vision_annotate(png).get("fullTextAnnotation", {})
    lines: list[tuple[str, tuple[float, float, float, float]]] = []
    for page in annotation.get("pages", []):
        for block in page.get("blocks", []):
            for paragraph in block.get("paragraphs", []):
                words, boxes = [], []
                for word in paragraph.get("words", []):
                    text, ends_line = _word_text(word)
                    words.append(text)
                    boxes.append(_bbox(word.get("boundingBox", {}).get("vertices", [])))
                    if ends_line:
                        lines.extend(_split_at_gutters(list(zip(words, boxes)), scale))
                        words, boxes = [], []
                if words:
                    lines.extend(_split_at_gutters(list(zip(words, boxes)), scale))
    return lines


def _merge(boxes: list[tuple], scale: float) -> tuple[float, float, float, float]:
    return (
        min(b[0] for b in boxes) / scale, min(b[1] for b in boxes) / scale,
        max(b[2] for b in boxes) / scale, max(b[3] for b in boxes) / scale,
    )


TESSERACT_CONFIG = "--oem 1 --psm 6"
GUTTER_GAP = 4.0  # a gap this many character-widths wide is a column boundary, not a space


def _split_at_gutters(words: list[tuple[str, tuple]], scale: float) -> list[tuple[str, tuple]]:
    """One OCR line cut wherever it jumps across a column gutter.

    Page OCR reads straight across a two-column paper, gluing the left
    question's text to the right question's; the wide blank between the columns
    is the only signal, so split on it and let the caller order the pieces.
    """
    words = sorted(words, key=lambda w: w[1][0])
    heights = sorted(box[3] - box[1] for _, box in words)
    limit = GUTTER_GAP * max(1.0, heights[len(heights) // 2])
    pieces, run = [], [words[0]]
    for word in words[1:]:
        if word[1][0] - run[-1][1][2] > limit:
            pieces.append(run)
            run = []
        run.append(word)
    pieces.append(run)
    return [(" ".join(w for w, _ in p), _merge([b for _, b in p], scale)) for p in pieces]


def tesseract_page_lines(png: bytes, scale: float = 1.0) -> list[tuple[str, tuple[float, float, float, float]]]:
    """Lines of one rendered page as (text, bbox), read by local Tesseract."""
    import pytesseract
    from PIL import Image

    data = pytesseract.image_to_data(
        Image.open(io.BytesIO(png)),
        config=TESSERACT_CONFIG,
        output_type=pytesseract.Output.DICT,
    )
    grouped: dict[tuple, list[tuple[str, tuple]]] = {}
    for i, text in enumerate(data["text"]):
        if not text.strip():
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        left, top = data["left"][i], data["top"][i]
        box = (left, top, left + data["width"][i], top + data["height"][i])
        grouped.setdefault(key, []).append((text, box))
    lines: list[tuple[str, tuple]] = []
    for words in grouped.values():
        lines.extend(_split_at_gutters(words, scale))
    return lines


def page_lines(png: bytes, scale: float = 1.0) -> list[tuple[str, tuple[float, float, float, float]]]:
    """Lines of one rendered page, through whichever page-OCR backend is available."""
    backend = page_ocr_backend()
    if backend == "vision":
        try:
            return vision_page_lines(png, scale)
        except Exception:
            if not _tesseract_available():
                raise
            backend = "tesseract"  # e.g. billing disabled on the Google project
    if backend == "tesseract":
        return tesseract_page_lines(png, scale)
    raise OcrUnavailable("No page OCR backend — set GCP_VISION_API_KEY or install tesseract-ocr")


def ocr_to_latex(path: str, box: list[float] | None = None) -> str:
    backend = _backend()
    if backend == "documentai":
        from gcp_documentai import process_document
        png = _prepare(path, box)
        evidence = process_document(png, "image/png")
        formulas = sorted(evidence.get("formulas", []), key=lambda x: x.get("confidence", 0), reverse=True)
        if not formulas:
            raise OcrUnavailable("Document AI did not detect a math formula in the selected region")
        latex = formulas[0].get("latex", "").strip()
        return latex if latex.startswith("$") else f"${latex}$"
    if backend in {"mathpix", "pix2tex"}:
        png = _prepare(path, box)
        return _mathpix(png) if backend == "mathpix" else _pix2tex(png)
    raise OcrUnavailable(
        "No math OCR backend configured — configure Document AI Math OCR, Mathpix, or pix2tex."
    )
