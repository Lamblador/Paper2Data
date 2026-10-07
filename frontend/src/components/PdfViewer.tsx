import { useEffect, useMemo, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import type { PaperBlock } from "../api/client";
import { matchQuoteToGlyphs, textRunsFromItems, type GlyphSlice, type TextRun } from "../lib/pdfQuote";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

const MIN_ZOOM = 1;
const MAX_ZOOM = 4;

type PdfDoc = {
  numPages: number;
  getPage: (pageNumber: number) => Promise<{
    getViewport: (opts: { scale: number }) => {
      width: number;
      height: number;
      transform: number[];
      scale: number;
    };
    getTextContent: () => Promise<{ items: Array<Record<string, unknown>> }>;
  }>;
};

type QuoteHit = {
  page: number;
  slices: GlyphSlice[];
  key: string;
};

type Rect = {
  left: number;
  top: number;
  width: number;
  height: number;
};

type Props = {
  fileUrl: string;
  highlightBlock: PaperBlock | null;
  highlightQuote?: string | null;
  focusKey?: string | null;
  onPageChange?: (page: number) => void;
};

function clampZoom(value: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round(value * 100) / 100));
}

function slicesToCss(
  slices: GlyphSlice[],
  viewport: { transform: number[]; scale: number },
): Rect[] {
  return slices.map((slice) => {
    const tx = pdfjs.Util.transform(viewport.transform, slice.transform);
    const fontHeight = Math.hypot(tx[2] ?? 0, tx[3] ?? 0) || 10;
    const fullWidth = Math.max(0, slice.width * viewport.scale);
    const startFrac = slice.charStart / slice.strLength;
    const endFrac = Math.max(startFrac, slice.charEnd / slice.strLength);
    const width = Math.max(2, fullWidth * (endFrac - startFrac));
    return {
      left: (tx[4] ?? 0) + fullWidth * startFrac,
      top: (tx[5] ?? 0) - fontHeight * 0.92,
      width,
      height: fontHeight * 1.25,
    };
  });
}

export default function PdfViewer({
  fileUrl,
  highlightBlock,
  highlightQuote,
  focusKey,
  onPageChange,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const textCache = useRef<Map<number, TextRun[]>>(new Map());
  const epoch = useRef(0);
  const navEpoch = useRef(0);
  const focusNav = useRef<{ key: string; nav: number } | null>(null);
  const scrolledFor = useRef<string | null>(null);
  const blockRef = useRef(highlightBlock);
  blockRef.current = highlightBlock;

  const [numPages, setNumPages] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<{ w: number; h: number } | null>(null);
  const [pdf, setPdf] = useState<PdfDoc | null>(null);
  const [zoom, setZoom] = useState(1);
  const [fitWidth, setFitWidth] = useState(720);
  const [quoteHit, setQuoteHit] = useState<QuoteHit | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchDone, setSearchDone] = useState(false);
  const [quoteRects, setQuoteRects] = useState<Rect[]>([]);

  const renderWidth = Math.max(280, Math.round(Math.min(3600, (fitWidth - 16) * zoom)));
  const pixelRatio = renderWidth > 1800 ? 1 : Math.min(2, window.devicePixelRatio || 1);

  useEffect(() => {
    textCache.current.clear();
    scrolledFor.current = null;
    setPdf(null);
    setNumPages(0);
    setPage(1);
    setQuoteHit(null);
    setQuoteRects([]);
    setPageSize(null);
  }, [fileUrl]);

  useEffect(() => {
    const el = panelRef.current;
    if (!el) return;
    const update = () => setFitWidth(Math.max(320, el.clientWidth));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey) return;
      event.preventDefault();
      setZoom((current) => clampZoom(current * (event.deltaY < 0 ? 1.1 : 1 / 1.1)));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  useEffect(() => {
    const my = ++epoch.current;
    let cancelled = false;
    const quote = highlightQuote?.trim() || "";
    const focus = focusKey ?? "";
    if (focusNav.current?.key !== focus) {
      focusNav.current = { key: focus, nav: navEpoch.current };
    }
    const allowJump = () => navEpoch.current === focusNav.current?.nav;
    const block = blockRef.current;

    if (!pdf || !quote) {
      setQuoteHit(null);
      setSearching(false);
      setSearchDone(!quote);
      setQuoteRects([]);
      if (allowJump() && block?.page) setPage(block.page);
      return () => {
        cancelled = true;
      };
    }

    setSearching(true);
    setSearchDone(false);
    setQuoteHit(null);
    setQuoteRects([]);
    void (async () => {
      for (let number = 1; number <= pdf.numPages; number += 1) {
        if (cancelled || epoch.current !== my) return;
        let runs = textCache.current.get(number);
        if (!runs) {
          const proxy = await pdf.getPage(number);
          if (cancelled || epoch.current !== my) return;
          const content = await proxy.getTextContent();
          runs = textRunsFromItems(content.items);
          textCache.current.set(number, runs);
        }
        const slices = matchQuoteToGlyphs(runs, quote);
        if (!slices) continue;
        if (cancelled || epoch.current !== my) return;
        setQuoteHit({ page: number, slices, key: focus });
        if (allowJump()) setPage(number);
        setSearching(false);
        setSearchDone(true);
        return;
      }
      if (cancelled || epoch.current !== my) return;
      setQuoteHit(null);
      setSearching(false);
      setSearchDone(true);
      if (allowJump() && block?.page) setPage(block.page);
    })();

    return () => {
      cancelled = true;
    };
  }, [pdf, highlightQuote, focusKey]);

  useEffect(() => {
    if (!pdf || !quoteHit || quoteHit.page !== page) {
      setQuoteRects([]);
      return;
    }
    let cancelled = false;
    void pdf.getPage(quoteHit.page).then((proxy) => {
      const base = proxy.getViewport({ scale: 1 });
      const viewport = proxy.getViewport({ scale: renderWidth / base.width });
      if (!cancelled) setQuoteRects(slicesToCss(quoteHit.slices, viewport));
    });
    return () => {
      cancelled = true;
    };
  }, [pdf, quoteHit, page, renderWidth]);

  const bboxOverlay = useMemo(() => {
    const quote = highlightQuote?.trim();
    if (quote && !(searchDone && !quoteHit)) return null;
    if (!highlightBlock?.bbox || !pageSize) return null;
    if (highlightBlock.page !== page) return null;
    const [x0, y0, x1, y1] = highlightBlock.bbox;
    const srcW = highlightBlock.page_width || pageSize.w;
    const scale = renderWidth / srcW;
    return {
      left: x0 * scale,
      top: y0 * scale,
      width: Math.max(2, (x1 - x0) * scale),
      height: Math.max(2, (y1 - y0) * scale),
    };
  }, [highlightBlock, highlightQuote, page, pageSize, quoteHit, renderWidth, searchDone]);

  const marks = quoteRects.length > 0 ? quoteRects : bboxOverlay ? [bboxOverlay] : [];

  useEffect(() => {
    const key = focusKey ?? "";
    if (!key || scrolledFor.current === key) return;
    if (highlightQuote?.trim()) {
      if (searching || !searchDone) return;
      if (quoteHit && (quoteHit.key !== key || page !== quoteHit.page || quoteRects.length === 0)) {
        return;
      }
    }
    const rect = quoteRects[0] ?? bboxOverlay;
    const wrap = wrapRef.current;
    const stage = stageRef.current;
    if (!rect || !wrap || !stage) return;
    scrolledFor.current = key;
    const wrapBox = wrap.getBoundingClientRect();
    const stageBox = stage.getBoundingClientRect();
    const top = stageBox.top - wrapBox.top + wrap.scrollTop + rect.top;
    const left = stageBox.left - wrapBox.left + wrap.scrollLeft + rect.left;
    wrap.scrollTo({
      top: Math.max(0, top - wrap.clientHeight * 0.28),
      left: Math.max(0, left - 28),
    });
  }, [bboxOverlay, focusKey, highlightQuote, page, quoteHit, quoteRects, searchDone, searching]);

  const go = (next: number) => {
    navEpoch.current += 1;
    const target = Math.min(Math.max(1, next), numPages || 1);
    setPage(target);
    onPageChange?.(target);
  };

  return (
    <div className="pdf-viewer" ref={panelRef}>
      <div className="row pdf-toolbar">
        <button
          type="button"
          className="btn secondary"
          disabled={page <= 1}
          onClick={() => go(page - 1)}
        >
          ←
        </button>
        <span className="muted">
          Стр. {page}
          {numPages ? ` / ${numPages}` : ""}
          {searching ? " · ищу цитату…" : ""}
        </span>
        <button
          type="button"
          className="btn secondary"
          disabled={numPages > 0 && page >= numPages}
          onClick={() => go(page + 1)}
        >
          →
        </button>
        <div className="pdf-zoom">
          <button
            type="button"
            className="btn secondary"
            disabled={zoom <= MIN_ZOOM}
            title="Уменьшить"
            onClick={() => setZoom((current) => clampZoom(current - 0.25))}
          >
            −
          </button>
          <input
            type="range"
            min={100}
            max={400}
            step={10}
            value={Math.round(zoom * 100)}
            aria-label="Масштаб страницы"
            title="Масштаб. Ctrl+колесо мыши на странице"
            onChange={(event) => setZoom(clampZoom(Number(event.target.value) / 100))}
          />
          <button
            type="button"
            className="btn secondary"
            disabled={zoom >= MAX_ZOOM}
            title="Увеличить"
            onClick={() => setZoom((current) => clampZoom(current + 0.25))}
          >
            +
          </button>
          <span className="muted pdf-zoom-label">{Math.round(zoom * 100)}%</span>
        </div>
      </div>
      {highlightQuote && searchDone && !quoteHit ? (
        <p className="muted pdf-search-note">Точная подсветка цитаты в PDF не найдена.</p>
      ) : null}
      <div className="pdf-page-wrap" ref={wrapRef}>
        <Document
          file={fileUrl}
          loading={<p className="muted">Загрузка PDF…</p>}
          error={<p className="error">Не удалось открыть PDF</p>}
          onLoadSuccess={(info) => {
            setPdf(info as unknown as PdfDoc);
            setNumPages(info.numPages);
          }}
        >
          <div className="pdf-page-stage" ref={stageRef}>
            <Page
              pageNumber={page}
              width={renderWidth}
              devicePixelRatio={pixelRatio}
              onLoadSuccess={(info) => {
                setPageSize({
                  w: info.originalWidth,
                  h: info.originalHeight,
                });
              }}
              renderTextLayer
              renderAnnotationLayer
            />
            {marks.map((mark, index) => (
              <div
                key={`${page}-${index}-${mark.left.toFixed(1)}`}
                className="pdf-highlight"
                style={{
                  left: mark.left,
                  top: mark.top,
                  width: mark.width,
                  height: mark.height,
                }}
              />
            ))}
          </div>
        </Document>
      </div>
    </div>
  );
}
