import { findFragmentSpan, quoteFragments } from "./quoteLocate";

const LETTER = /[\p{L}\p{N}]/u;

export type TextRun = {
  str: string;
  transform: number[];
  width: number;
  height: number;
  hasEOL: boolean;
};

export type GlyphSlice = {
  transform: number[];
  width: number;
  strLength: number;
  charStart: number;
  charEnd: number;
};

export function textRunsFromItems(items: Array<Record<string, unknown>>): TextRun[] {
  const runs: TextRun[] = [];
  for (const item of items) {
    if (typeof item.str !== "string") continue;
    const transform = Array.isArray(item.transform) ? item.transform.map(Number) : [];
    if (transform.length < 6 || transform.some((value) => Number.isNaN(value))) continue;
    runs.push({
      str: item.str,
      transform,
      width: Number(item.width) || 0,
      height: Number(item.height) || 0,
      hasEOL: Boolean(item.hasEOL),
    });
  }
  return runs;
}

/** Куски глифов PDF, которые покрывают цитату на одной странице. */
export function matchQuoteToGlyphs(items: TextRun[], quote: string): GlyphSlice[] | null {
  const fragments = quoteFragments(quote);
  if (fragments.length === 0) return null;

  let raw = "";
  const spans: { start: number; end: number; item: TextRun }[] = [];
  for (const item of items) {
    if (item.str) {
      const start = raw.length;
      raw += item.str;
      spans.push({ start, end: raw.length, item });
    }
    if (item.hasEOL) raw += "\n";
  }

  const compactToRaw: number[] = [];
  let compact = "";
  for (let i = 0; i < raw.length; i += 1) {
    const ch = raw[i];
    if (ch && LETTER.test(ch)) {
      compact += ch.toLowerCase();
      compactToRaw.push(i);
    }
  }

  const found = findFragmentSpan(compact, fragments);
  if (!found || found.end <= found.start) return null;
  const rawStart = compactToRaw[found.start];
  const rawEnd = compactToRaw[found.end - 1];
  if (rawStart == null || rawEnd == null) return null;

  const slices: GlyphSlice[] = [];
  for (const span of spans) {
    const overlapStart = Math.max(span.start, rawStart);
    const overlapEnd = Math.min(span.end, rawEnd + 1);
    if (overlapEnd <= overlapStart) continue;
    slices.push({
      transform: span.item.transform,
      width: span.item.width,
      strLength: Math.max(1, span.item.str.length),
      charStart: overlapStart - span.start,
      charEnd: overlapEnd - span.start,
    });
  }
  return slices.length > 0 ? slices : null;
}
