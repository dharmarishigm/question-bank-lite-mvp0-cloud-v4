"""Google Cloud Document AI Enterprise OCR + Math OCR integration.

The local MVP is intentionally synchronous and lightweight. PDFs are internally split
into <=15-page chunks because Enterprise Document OCR online processing has a per-request
page limit. Results are merged back with original page numbers.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class MathFormula:
    page: int
    latex: str
    confidence: float
    bbox: list[float]


@dataclass
class OcrPage:
    page: int
    text: str
    quality_score: float | None
    formulas: list[MathFormula]


def _project() -> str:
    value = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or ""
    return value.strip() if value and value.strip() not in {"your-project-id"} else ""


def _location() -> str:
    return os.getenv("DOCUMENTAI_LOCATION", "us")


def _processor_id() -> str:
    value = os.getenv("DOCUMENTAI_PROCESSOR_ID", "").strip()
    return value if value and value not in {"your-processor-id"} else ""


def status() -> dict:
    processor = _processor_id()
    return {
        "available": bool(_project() and processor),
        "provider": "gcp-document-ai",
        "project": _project(),
        "location": _location(),
        "processor_id": processor,
        "math_ocr": True,
        "sync_chunk_pages": min(15, max(1, int(os.getenv("DOCUMENTAI_CHUNK_PAGES", "15")))),
    }


def _anchor_text(document_text: str, anchor: Any) -> str:
    pieces: list[str] = []
    for segment in getattr(anchor, "text_segments", []) or []:
        start = int(getattr(segment, "start_index", 0) or 0)
        end = int(getattr(segment, "end_index", 0) or 0)
        if end > start:
            pieces.append(document_text[start:end])
    return "".join(pieces).strip()


def _normalized_bbox(layout: Any) -> list[float]:
    poly = getattr(layout, "bounding_poly", None)
    vertices = list(getattr(poly, "normalized_vertices", []) or []) if poly else []
    if not vertices:
        return []
    xs = [float(getattr(v, "x", 0.0) or 0.0) for v in vertices]
    ys = [float(getattr(v, "y", 0.0) or 0.0) for v in vertices]
    return [min(xs), min(ys), max(xs), max(ys)]


def _parse_response(doc: Any, page_offset: int = 0) -> tuple[list[OcrPage], list[MathFormula]]:
    pages: list[OcrPage] = []
    all_formulas: list[MathFormula] = []
    for page in doc.pages:
        local_page = int(page.page_number or (len(pages) + 1))
        page_number = local_page + page_offset
        page_text_parts = []
        for line in page.lines:
            text = _anchor_text(doc.text, line.layout.text_anchor)
            if text:
                page_text_parts.append(text)

        formulas: list[MathFormula] = []
        for element in page.visual_elements:
            element_type = str(getattr(element, "type_", "") or getattr(element, "type", ""))
            if element_type != "math_formula":
                continue
            latex = _anchor_text(doc.text, element.layout.text_anchor)
            if not latex:
                continue
            item = MathFormula(
                page=page_number,
                latex=latex,
                confidence=float(getattr(element.layout, "confidence", 0.0) or 0.0),
                bbox=_normalized_bbox(element.layout),
            )
            formulas.append(item)
            all_formulas.append(item)

        quality = None
        scores = getattr(page, "image_quality_scores", None)
        if scores is not None:
            q = getattr(scores, "quality_score", None)
            quality = float(q) if q is not None else None
        pages.append(OcrPage(page_number, "\n".join(page_text_parts), quality, formulas))
    return pages, all_formulas


def _process_once(client: Any, documentai: Any, name: str, content: bytes, mime_type: str) -> Any:
    options = documentai.ProcessOptions(
        ocr_config=documentai.OcrConfig(
            enable_native_pdf_parsing=True,
            enable_image_quality_scores=True,
            enable_symbol=True,
            premium_features=documentai.OcrConfig.PremiumFeatures(
                compute_style_info=True,
                enable_math_ocr=True,
                enable_selection_mark_detection=True,
            ),
        )
    )
    request = documentai.ProcessRequest(
        name=name,
        raw_document=documentai.RawDocument(content=content, mime_type=mime_type),
        process_options=options,
    )
    return client.process_document(request=request).document


def _pdf_chunks(content: bytes, pages_per_chunk: int):
    import pymupdf
    with pymupdf.open(stream=content, filetype="pdf") as source:
        total = len(source)
        for start in range(0, total, pages_per_chunk):
            end = min(total, start + pages_per_chunk)
            chunk = pymupdf.open()
            chunk.insert_pdf(source, from_page=start, to_page=end - 1)
            try:
                yield chunk.tobytes(garbage=4, deflate=True), start
            finally:
                chunk.close()


def process_document(content: bytes, mime_type: str) -> dict:
    """Run Enterprise Document OCR with Math OCR and return compact evidence.

    Uses Application Default Credentials. Imports are lazy so local-only mode works
    without Google libraries/configuration.
    """
    if not status()["available"]:
        raise RuntimeError("Document AI is not configured")

    from google.api_core.client_options import ClientOptions
    from google.cloud import documentai

    location = _location()
    endpoint = f"{location}-documentai.googleapis.com"
    client = documentai.DocumentProcessorServiceClient(
        client_options=ClientOptions(api_endpoint=endpoint)
    )
    name = client.processor_path(_project(), location, _processor_id())

    pages: list[OcrPage] = []
    formulas: list[MathFormula] = []
    if mime_type == "application/pdf":
        chunk_size = status()["sync_chunk_pages"]
        for chunk_bytes, page_offset in _pdf_chunks(content, chunk_size):
            doc = _process_once(client, documentai, name, chunk_bytes, mime_type)
            chunk_pages, chunk_formulas = _parse_response(doc, page_offset)
            pages.extend(chunk_pages)
            formulas.extend(chunk_formulas)
    else:
        doc = _process_once(client, documentai, name, content, mime_type)
        pages, formulas = _parse_response(doc, 0)

    return {
        "provider": "gcp-document-ai",
        "pages": [
            {
                "page": p.page,
                "text": p.text,
                "quality_score": p.quality_score,
                "formulas": [asdict(f) for f in p.formulas],
            }
            for p in pages
        ],
        "formulas": [asdict(f) for f in formulas],
    }
