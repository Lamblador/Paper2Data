"""Извлечение рисунков из PDF: встроенные изображения + области по подписям.

DocLayout/YOLO не используются (тяжёлые зависимости, слабая практичность на Windows).
Вместо детекции: xref-изображения PyMuPDF и рендер области над caption-блоком.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from paper2data.ingest.captions import classify_caption


@dataclass
class ExtractedFigure:
    page: int
    caption: str
    image_path: str  # relative to cache/
    bbox: list[float] | None
    source_kind: str  # embedded | caption_region
    order_index: int
    meta: dict[str, Any] = field(default_factory=dict)


def _safe_rel(path: Path, cache_dir: Path) -> str:
    return path.resolve().relative_to(cache_dir.resolve()).as_posix()


def _nearest_caption(page_captions: list[dict[str, Any]], bbox: list[float]) -> str:
    """Подпись ниже изображения на той же странице (минимальный зазор по Y)."""
    x0, y0, x1, y1 = bbox
    best = ""
    best_gap = 1e18
    for cap in page_captions:
        cb = cap.get("bbox") or [0, 0, 0, 0]
        cy0 = float(cb[1])
        if cy0 < y1 - 2:
            continue
        # горизонтальное пересечение
        cx0, cx1 = float(cb[0]), float(cb[2])
        if cx1 < x0 or cx0 > x1:
            continue
        gap = cy0 - y1
        if 0 <= gap < best_gap:
            best_gap = gap
            best = str(cap.get("text") or "")
    return best


def extract_figures_from_pdf(
    pdf_path: Path,
    cache_dir: Path,
    document_id: int,
    *,
    caption_blocks: list[dict[str, Any]] | None = None,
) -> list[ExtractedFigure]:
    """
    Извлечь рисунки в cache/figures/{document_id}/.

    caption_blocks: опционально [{page, text, bbox}] из БД (kind=caption).
    """
    import pymupdf as fitz

    out_dir = cache_dir / "figures" / str(document_id)
    if out_dir.exists():
        for old in out_dir.glob("*"):
            if old.is_file():
                old.unlink()
    else:
        out_dir.mkdir(parents=True, exist_ok=True)

    captions_by_page: dict[int, list[dict[str, Any]]] = {}
    for cap in caption_blocks or []:
        page = int(cap.get("page") or 0)
        if page <= 0:
            continue
        captions_by_page.setdefault(page, []).append(cap)

    results: list[ExtractedFigure] = []
    order = 0
    used_caption_keys: set[str] = set()

    doc = fitz.open(pdf_path)
    try:
        for page_index in range(len(doc)):
            page = doc[page_index]
            page_no = page_index + 1
            page_caps = captions_by_page.get(page_no, [])

            # --- встроенные изображения ---
            for img_idx, img in enumerate(page.get_images(full=True)):
                xref = int(img[0])
                try:
                    pix = fitz.Pixmap(doc, xref)
                    if pix.n > 4:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    elif pix.alpha:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                except Exception:  # noqa: BLE001
                    continue
                if pix.width < 40 or pix.height < 40:
                    continue

                # bbox из image rects
                bbox: list[float] | None = None
                try:
                    rects = page.get_image_rects(xref)
                    if rects:
                        r = rects[0]
                        bbox = [float(r.x0), float(r.y0), float(r.x1), float(r.y1)]
                except Exception:  # noqa: BLE001
                    bbox = None

                fname = f"emb_p{page_no}_{img_idx}.png"
                dest = out_dir / fname
                try:
                    pix.save(dest.as_posix())
                except Exception:  # noqa: BLE001
                    continue

                caption = ""
                if bbox:
                    caption = _nearest_caption(page_caps, bbox)
                    if caption:
                        used_caption_keys.add(f"{page_no}:{caption[:80]}")

                results.append(
                    ExtractedFigure(
                        page=page_no,
                        caption=caption,
                        image_path=_safe_rel(dest, cache_dir),
                        bbox=bbox,
                        source_kind="embedded",
                        order_index=order,
                        meta={"xref": xref, "width": pix.width, "height": pix.height},
                    )
                )
                order += 1

            # --- области по подписям без сопоставленного изображения ---
            for c_idx, cap in enumerate(page_caps):
                text = str(cap.get("text") or "").strip()
                key = f"{page_no}:{text[:80]}"
                if key in used_caption_keys:
                    continue
                cb = cap.get("bbox")
                if not cb or len(cb) < 4:
                    continue
                x0, y0, x1, y1 = [float(v) for v in cb[:4]]
                # область над подписью: от ~15% высоты страницы до верха caption
                page_h = float(page.rect.height)
                page_w = float(page.rect.width)
                top = max(0.0, y0 - min(page_h * 0.45, 320.0))
                # чуть шире caption по горизонтали
                pad = 8.0
                left = max(0.0, x0 - pad)
                right = min(page_w, x1 + pad)
                bottom = max(top + 20.0, y0 - 2.0)
                if bottom - top < 24 or right - left < 24:
                    continue

                clip = fitz.Rect(left, top, right, bottom)
                try:
                    pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), clip=clip, alpha=False)
                except Exception:  # noqa: BLE001
                    continue
                fname = f"cap_p{page_no}_{c_idx}.png"
                dest = out_dir / fname
                pix.save(dest.as_posix())

                matched = classify_caption(text)
                results.append(
                    ExtractedFigure(
                        page=page_no,
                        caption=text,
                        image_path=_safe_rel(dest, cache_dir),
                        bbox=[left, top, right, bottom],
                        source_kind="caption_region",
                        order_index=order,
                        meta={
                            "caption_kind": matched.kind if matched else None,
                            "caption_label": matched.label if matched else None,
                        },
                    )
                )
                order += 1
                used_caption_keys.add(key)
    finally:
        doc.close()

    return results


def dumps_bbox(bbox: list[float] | None) -> str | None:
    if not bbox:
        return None
    return json.dumps([float(x) for x in bbox], ensure_ascii=False)
