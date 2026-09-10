"""Lightweight multimodal question representation helpers.

The MVP deliberately keeps durable source evidence as images while converting what is
safe/useful into structured digital blocks. Visual crops are never regenerated.
"""
from __future__ import annotations

import io
import re
import uuid
from pathlib import Path
from typing import Iterable

from PIL import Image
import pymupdf

MATH_RE = re.compile(r"(\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$[^$\n]*?\$)")
VISUAL_TYPES = {"table", "graph", "diagram", "shape", "image", "chemical_structure"}


def normalize_bbox(bbox: Iterable[float] | None) -> list[float]:
    if not bbox:
        return []
    try:
        vals = [float(x) for x in bbox]
    except (TypeError, ValueError):
        return []
    if len(vals) != 4:
        return []
    x0, y0, x1, y1 = vals
    x0, x1 = sorted((max(0.0, min(1.0, x0)), max(0.0, min(1.0, x1))))
    y0, y1 = sorted((max(0.0, min(1.0, y0)), max(0.0, min(1.0, y1))))
    if x1 - x0 < 0.005 or y1 - y0 < 0.005:
        return []
    return [round(x0, 6), round(y0, 6), round(x1, 6), round(y1, 6)]


def split_rich_text(text: str, *, role: str = "statement") -> list[dict]:
    """Split mixed Markdown/LaTeX into ordered text/math/chemistry blocks.

    This is intentionally conservative: it does not rewrite LaTeX. It simply exposes
    equation/chemistry spans as structured blocks while preserving the original string.
    """
    source = text or ""
    blocks: list[dict] = []
    pos = 0
    seq = 1
    for match in MATH_RE.finditer(source):
        if match.start() > pos:
            chunk = source[pos:match.start()]
            if chunk:
                blocks.append({"sequence": seq, "type": "text", "role": role, "content": chunk})
                seq += 1
        expr = match.group(0)
        kind = "chemistry" if "\\ce{" in expr or "\\pu{" in expr else "math"
        blocks.append({"sequence": seq, "type": kind, "role": role, "content": expr})
        seq += 1
        pos = match.end()
    if pos < len(source):
        blocks.append({"sequence": seq, "type": "text", "role": role, "content": source[pos:]})
    if not blocks and source:
        blocks.append({"sequence": 1, "type": "text", "role": role, "content": source})
    return blocks


def _render_page(source_bytes: bytes, mime_type: str, page: int, scale: float = 4.2) -> Image.Image:
    if mime_type == "application/pdf":
        with pymupdf.open(stream=source_bytes, filetype="pdf") as doc:
            if not (1 <= int(page) <= len(doc)):
                raise ValueError(f"page {page} is outside document")
            pix = doc[int(page) - 1].get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    return Image.open(io.BytesIO(source_bytes)).convert("RGB")


def crop_source_region(
    source_bytes: bytes,
    mime_type: str,
    page: int,
    bbox: Iterable[float] | None,
    upload_dir: str,
    *,
    prefix: str = "asset",
    fallback_full_page: bool = True,
) -> str:
    """Crop a normalized page region and return a local /uploads URL.

    If a region is absent and fallback_full_page=True, the complete page/image is kept.
    This means extraction uncertainty never discards visual source evidence.
    """
    image = _render_page(source_bytes, mime_type, page)
    box = normalize_bbox(bbox)
    if box:
        width, height = image.size
        px = (
            max(0, int(box[0] * width)),
            max(0, int(box[1] * height)),
            min(width, int(box[2] * width)),
            min(height, int(box[3] * height)),
        )
        if px[2] > px[0] and px[3] > px[1]:
            image = image.crop(px)
    elif not fallback_full_page:
        return ""
    name = f"{prefix}-{uuid.uuid4().hex}.png"
    path = Path(upload_dir) / name
    image.save(path, format="PNG", optimize=True)
    return f"/uploads/{name}"


def build_content_blocks(statement: str, visuals: list[dict] | None) -> list[dict]:
    """Create the durable digital representation used by SQLite and the UI."""
    blocks = split_rich_text(statement, role="statement")
    seq = len(blocks) + 1
    for visual in visuals or []:
        kind = str(visual.get("type") or visual.get("kind") or "image")
        if kind not in VISUAL_TYPES:
            kind = "image"
        block = {
            "sequence": seq,
            "type": kind,
            "role": "statement",
            "asset": visual.get("asset", ""),
            "page": visual.get("page", 0),
            "bbox": normalize_bbox(visual.get("bbox")),
            "description": visual.get("description", ""),
            "source_truth": True,
        }
        table = visual.get("table") or {}
        if table:
            block["table"] = {
                "headers": table.get("headers") or [],
                "rows": table.get("rows") or [],
            }
        graph = visual.get("graph") or {}
        if graph:
            block["graph"] = graph
        blocks.append(block)
        seq += 1
    return blocks


def statement_with_question_figures(statement: str, assets: list) -> str:
    """Keep bank question figures visible in paper previews and exam snapshots."""
    for asset in assets or []:
        url=asset.get('asset','')
        if asset.get('type')!='answer_figures' and re.fullmatch(r'/uploads/[A-Za-z0-9_./-]+',url) and url not in statement:
            statement+='\n\n![Question figure]('+url+')'
    return statement
