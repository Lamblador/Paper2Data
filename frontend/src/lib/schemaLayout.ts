import type { EntityType, RelationType } from "../api/client";

export type Position = { x: number; y: number };

export type PositionsMap = Record<string, Position>;

const STORAGE_PREFIX = "paper2data.schemaLayout.";

const NODE_WIDTH = 240;
const NODE_HEIGHT = 160;
const COL_GAP = 80;
const ROW_GAP = 48;
const ORIGIN_X = 40;
const ORIGIN_Y = 40;

export function layoutStorageKey(projectPath: string): string {
  return `${STORAGE_PREFIX}${projectPath}`;
}

export function loadPositions(projectPath: string): PositionsMap {
  try {
    const raw = localStorage.getItem(layoutStorageKey(projectPath));
    if (!raw) return {};
    const parsed = JSON.parse(raw) as PositionsMap;
    if (!parsed || typeof parsed !== "object") return {};
    return parsed;
  } catch {
    return {};
  }
}

export function savePositions(projectPath: string, positions: PositionsMap): void {
  try {
    localStorage.setItem(layoutStorageKey(projectPath), JSON.stringify(positions));
  } catch {
    // ignore quota / private mode
  }
}

export function clearPositions(projectPath: string): void {
  try {
    localStorage.removeItem(layoutStorageKey(projectPath));
  } catch {
    // ignore
  }
}

/**
 * Layered left-to-right layout based on relation direction.
 * Sources (no incoming) start at layer 0; sinks end further right.
 */
export function computeLayeredLayout(
  entities: EntityType[],
  relations: RelationType[],
): PositionsMap {
  const ids = entities.map((e) => e.id);
  const idSet = new Set(ids);
  if (ids.length === 0) return {};

  const outgoing = new Map<string, string[]>();
  const incoming = new Map<string, string[]>();
  for (const id of ids) {
    outgoing.set(id, []);
    incoming.set(id, []);
  }

  for (const rel of relations) {
    if (!idSet.has(rel.from) || !idSet.has(rel.to)) continue;
    if (rel.from === rel.to) continue;
    outgoing.get(rel.from)!.push(rel.to);
    incoming.get(rel.to)!.push(rel.from);
  }

  // Kahn-style longest-path layering
  const layer = new Map<string, number>();
  const indeg = new Map<string, number>();
  for (const id of ids) {
    indeg.set(id, incoming.get(id)!.length);
  }

  const queue: string[] = [];
  for (const id of ids) {
    if (indeg.get(id) === 0) {
      layer.set(id, 0);
      queue.push(id);
    }
  }

  // Stable order within queue by order_index then id
  const orderRank = new Map(
    entities.map((e, i) => [e.id, e.order_index ?? i] as const),
  );
  const byOrder = (a: string, b: string) =>
    (orderRank.get(a) ?? 0) - (orderRank.get(b) ?? 0) || a.localeCompare(b);

  queue.sort(byOrder);

  const visited = new Set<string>();
  while (queue.length) {
    const u = queue.shift()!;
    if (visited.has(u)) continue;
    visited.add(u);
    const lu = layer.get(u) ?? 0;
    for (const v of outgoing.get(u)!) {
      const next = lu + 1;
      if (!layer.has(v) || (layer.get(v) ?? 0) < next) {
        layer.set(v, next);
      }
      indeg.set(v, (indeg.get(v) ?? 1) - 1);
      if ((indeg.get(v) ?? 0) <= 0) {
        queue.push(v);
        queue.sort(byOrder);
      }
    }
  }

  // Cycles / unreachable: place remaining after max layer
  let maxLayer = 0;
  for (const l of layer.values()) maxLayer = Math.max(maxLayer, l);
  for (const id of ids) {
    if (!layer.has(id)) {
      maxLayer += 1;
      layer.set(id, maxLayer);
    }
  }

  const byLayer = new Map<number, string[]>();
  for (const id of ids) {
    const l = layer.get(id) ?? 0;
    const list = byLayer.get(l) ?? [];
    list.push(id);
    byLayer.set(l, list);
  }

  for (const list of byLayer.values()) {
    list.sort(byOrder);
  }

  const positions: PositionsMap = {};
  const sortedLayers = [...byLayer.keys()].sort((a, b) => a - b);
  for (const l of sortedLayers) {
    const list = byLayer.get(l)!;
    list.forEach((id, row) => {
      positions[id] = {
        x: ORIGIN_X + l * (NODE_WIDTH + COL_GAP),
        y: ORIGIN_Y + row * (NODE_HEIGHT + ROW_GAP),
      };
    });
  }

  return positions;
}

export function mergeLayout(
  entities: EntityType[],
  relations: RelationType[],
  saved: PositionsMap,
): PositionsMap {
  const auto = computeLayeredLayout(entities, relations);
  const result: PositionsMap = {};
  for (const e of entities) {
    result[e.id] = saved[e.id] ?? auto[e.id] ?? { x: ORIGIN_X, y: ORIGIN_Y };
  }
  return result;
}

/** Offset index for parallel edges between the same pair (including reverse). */
export function parallelEdgeOffsets(
  relations: RelationType[],
  entityIds: Set<string>,
): Map<string, number> {
  const groups = new Map<string, string[]>();
  for (const rel of relations) {
    if (!entityIds.has(rel.from) || !entityIds.has(rel.to)) continue;
    const a = rel.from < rel.to ? rel.from : rel.to;
    const b = rel.from < rel.to ? rel.to : rel.from;
    const key = `${a}::${b}`;
    const list = groups.get(key) ?? [];
    list.push(rel.id);
    groups.set(key, list);
  }

  const offsets = new Map<string, number>();
  for (const list of groups.values()) {
    list.forEach((id, i) => {
      // Center around 0: …, -2, -1, 0, 1, 2
      const mid = (list.length - 1) / 2;
      offsets.set(id, i - mid);
    });
  }
  return offsets;
}

export const SCHEMA_NODE_SIZE = {
  width: NODE_WIDTH,
  estimatedHeight: NODE_HEIGHT,
};
