import type { PaperBlock } from "../api/client";

const LETTER = /[\p{L}\p{N}]/u;

export function compactText(value: string): string {
  let out = "";
  for (const ch of value || "") {
    if (LETTER.test(ch)) out += ch.toLowerCase();
  }
  return out;
}

/** Фрагменты цитаты: многоточие в ответе модели — пропуск куска, а не часть текста. */
export function quoteFragments(quote: string): string[] {
  const pieces = (quote || "")
    .split(/\.{3,}|…/g)
    .map((part) => compactText(part))
    .filter((part) => part.length >= 4);
  if (pieces.length > 0) return pieces;
  const whole = compactText(quote || "");
  return whole.length >= 4 ? [whole] : [];
}

export function findFragmentSpan(
  haystack: string,
  fragments: string[],
  maxGap = 360,
): { start: number; end: number } | null {
  if (!haystack || fragments.length === 0) return null;
  const first = fragments[0];
  if (!first) return null;
  if (fragments.length === 1) {
    const idx = haystack.indexOf(first);
    if (idx < 0) return null;
    return { start: idx, end: idx + first.length };
  }
  let origin = 0;
  while (origin < haystack.length) {
    const start = haystack.indexOf(first, origin);
    if (start < 0) return null;
    let cursor = start + first.length;
    let matched = true;
    for (let i = 1; i < fragments.length; i += 1) {
      const part = fragments[i];
      if (!part) continue;
      const idx = haystack.indexOf(part, cursor);
      if (idx < 0 || idx - cursor > maxGap) {
        matched = false;
        break;
      }
      cursor = idx + part.length;
    }
    if (matched) return { start, end: cursor };
    origin = start + 1;
  }
  return null;
}

export type CompactBlock = {
  block: PaperBlock;
  compact: string;
};

export function compactBlocks(blocks: Iterable<PaperBlock>): CompactBlock[] {
  return [...blocks]
    .map((block) => ({ block, compact: compactText(block.text || "") }))
    .sort((a, b) => a.block.order_index - b.block.order_index);
}

export type QuoteLocation = {
  block: PaperBlock | null;
  page: number | null;
};

/** Блок и страница, где цитата реально встречается, а не номер страницы в колонтитуле. */
export function locateQuote(quote: string, blocks: CompactBlock[]): QuoteLocation {
  const fragments = quoteFragments(quote);
  if (fragments.length === 0) return { block: null, page: null };

  for (const item of blocks) {
    if (item.compact.length < 8) continue;
    if (findFragmentSpan(item.compact, fragments)) {
      return { block: item.block, page: item.block.page };
    }
  }

  const byPage = new Map<number, CompactBlock[]>();
  for (const item of blocks) {
    if (item.block.page == null) continue;
    const list = byPage.get(item.block.page) ?? [];
    list.push(item);
    byPage.set(item.block.page, list);
  }
  for (const page of [...byPage.keys()].sort((a, b) => a - b)) {
    const list = byPage.get(page) ?? [];
    const haystack = list.map((item) => item.compact).join("");
    if (!findFragmentSpan(haystack, fragments)) continue;
    const head = fragments[0];
    const host = head ? list.find((item) => item.compact.includes(head)) : undefined;
    return { block: host?.block ?? list[0]?.block ?? null, page };
  }
  return { block: null, page: null };
}
