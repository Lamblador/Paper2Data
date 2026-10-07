import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type NodeMouseHandler,
  type OnNodeDrag,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  api,
  type EntityType,
  type GraphEdge,
  type GraphNode,
  type PaperBlock,
  type ProjectSchema,
  type RelationType,
  type StructureProposal,
  type CrossrefResult,
  type ChemSvgResult,
} from "../api/client";

const STATUS_OPTIONS = [
  { value: "manual", label: "ручная" },
  { value: "proposed", label: "предложена" },
  { value: "accepted", label: "принята" },
  { value: "rejected", label: "отклонена" },
];

function toFlowNodes(nodes: GraphNode[]): Node[] {
  return nodes.map((n) => ({
    id: String(n.id),
    position: { x: n.pos_x || 0, y: n.pos_y || 0 },
    data: {
      label: `${n.label || n.entity_type_name || n.entity_type}\n[${n.status}]`,
    },
    deletable: false,
    style: {
      border:
        n.status === "accepted"
          ? "2px solid #0f6e56"
          : n.status === "proposed"
            ? "2px dashed #b7791f"
            : n.status === "rejected"
              ? "2px solid #9b2c2c"
              : "1px solid #c9d2dc",
      borderRadius: 8,
      padding: 8,
      background: "#fffdf8",
      fontSize: 12,
      whiteSpace: "pre-wrap",
      minWidth: 120,
    },
  }));
}

function toFlowEdges(edges: GraphEdge[], selectedId: number | null): Edge[] {
  return edges.map((e) => ({
    id: String(e.id),
    source: String(e.source_node_id),
    target: String(e.target_node_id),
    label: e.relation_type_name || e.relation_type || "",
    animated: e.status === "proposed",
    deletable: true,
    selected: selectedId === e.id,
    interactionWidth: 18,
    style:
      selectedId === e.id
        ? { stroke: "#0f6e56", strokeWidth: 2.5 }
        : e.status === "rejected"
          ? { stroke: "#9b2c2c" }
          : undefined,
  }));
}

function endpointLabel(nodes: GraphNode[], id: number): string {
  const node = nodes.find((n) => n.id === id);
  if (!node) return `#${id}`;
  return node.label || node.entity_type_name || `#${id}`;
}

function formatAttr(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

type Props = {
  documentId: number;
  selectedBlock: PaperBlock | null;
  onMessage?: (msg: string) => void;
  onError?: (msg: string) => void;
  refreshKey?: number;
};

export default function GraphAnnotatePane({
  documentId,
  selectedBlock,
  onMessage,
  onError,
  refreshKey = 0,
}: Props) {
  const [schema, setSchema] = useState<ProjectSchema | null>(null);
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
  const [graphEdges, setGraphEdges] = useState<GraphEdge[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [createTypeId, setCreateTypeId] = useState("");
  const [edgeForm, setEdgeForm] = useState({
    relation_type: "",
    source_node_id: "",
    target_node_id: "",
  });
  const [rfNodes, setRfNodes, onRfNodesChange] = useNodesState<Node>([]);
  const [rfEdges, setRfEdges, onRfEdgesChange] = useEdgesState<Edge>([]);
  const [chemBusy, setChemBusy] = useState(false);
  const [structureSvg, setStructureSvg] = useState<string | null>(null);
  const [chemNote, setChemNote] = useState<string | null>(null);
  const [structureProposals, setStructureProposals] = useState<StructureProposal[]>([]);
  const [crossrefPreview, setCrossrefPreview] = useState<CrossrefResult | null>(null);

  const selectedNode = useMemo(
    () => graphNodes.find((n) => n.id === selectedNodeId) ?? null,
    [graphNodes, selectedNodeId],
  );

  const selectedEdge = useMemo(
    () => graphEdges.find((e) => e.id === selectedEdgeId) ?? null,
    [graphEdges, selectedEdgeId],
  );

  const selectedEntityType: EntityType | null = useMemo(() => {
    if (!schema || !selectedNode?.entity_type) return null;
    return schema.entity_types.find((e) => e.id === selectedNode.entity_type) ?? null;
  }, [schema, selectedNode]);

  const incidentEdges = useMemo(() => {
    if (!selectedNode) return [];
    return graphEdges.filter(
      (e) =>
        e.source_node_id === selectedNode.id || e.target_node_id === selectedNode.id,
    );
  }, [graphEdges, selectedNode]);

  const loadGraph = useCallback(async () => {
    const g = await api.getDocumentGraph(documentId);
    setGraphNodes(g.nodes);
    setGraphEdges(g.edges);
    setRfNodes(toFlowNodes(g.nodes));
  }, [documentId, setRfNodes]);

  useEffect(() => {
    void (async () => {
      try {
        const res = await api.currentSchema();
        setSchema(res.schema);
        if (res.schema?.entity_types?.[0]) {
          setCreateTypeId(res.schema.entity_types[0].id);
        }
      } catch (err) {
        onError?.(err instanceof Error ? err.message : String(err));
      }
    })();
  }, [onError]);

  useEffect(() => {
    void loadGraph().catch((err) =>
      onError?.(err instanceof Error ? err.message : String(err)),
    );
  }, [documentId, loadGraph, onError, refreshKey]);

  useEffect(() => {
    setRfEdges(toFlowEdges(graphEdges, selectedEdgeId));
  }, [graphEdges, selectedEdgeId, setRfEdges]);

  const onConnect = useCallback(
    (connection: Connection) => {
      if (!schema) return;
      const source = graphNodes.find((n) => String(n.id) === connection.source);
      const target = graphNodes.find((n) => String(n.id) === connection.target);
      if (!source || !target) return;
      const candidates = schema.relation_types.filter(
        (r: RelationType) =>
          r.from === source.entity_type && r.to === target.entity_type,
      );
      const rel =
        candidates.find((r) => r.id === edgeForm.relation_type) || candidates[0];
      if (!rel) {
        onError?.(
          `Нет типа связи ${source.entity_type} → ${target.entity_type}`,
        );
        return;
      }
      void (async () => {
        setBusy(true);
        try {
          await api.createEdge(documentId, {
            relation_type: rel.id,
            source_node_id: source.id,
            target_node_id: target.id,
            status: "manual",
          });
          await loadGraph();
          onMessage?.(`Связь «${rel.name}» создана`);
        } catch (err) {
          onError?.(err instanceof Error ? err.message : String(err));
        } finally {
          setBusy(false);
        }
      })();
    },
    [schema, graphNodes, edgeForm.relation_type, documentId, loadGraph, onError, onMessage],
  );

  const deleteEdgeById = useCallback(
    async (edgeId: number) => {
      const edge = graphEdges.find((e) => e.id === edgeId);
      const name = edge?.relation_type_name || edge?.relation_type || "связь";
      if (!window.confirm(`Удалить связь «${name}» #${edgeId}?`)) return;
      setBusy(true);
      try {
        await api.deleteEdge(edgeId);
        setSelectedEdgeId((cur) => (cur === edgeId ? null : cur));
        await loadGraph();
        onMessage?.("Связь удалена");
      } catch (err) {
        onError?.(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [graphEdges, loadGraph, onError, onMessage],
  );

  const onEdgesDelete = useCallback(
    (deleted: Edge[]) => {
      void (async () => {
        setBusy(true);
        try {
          for (const edge of deleted) {
            await api.deleteEdge(Number(edge.id));
          }
          setSelectedEdgeId((cur) =>
            deleted.some((edge) => Number(edge.id) === cur) ? null : cur,
          );
          await loadGraph();
          onMessage?.(
            deleted.length === 1
              ? "Связь удалена"
              : `Удалено связей: ${deleted.length}`,
          );
        } catch (err) {
          onError?.(err instanceof Error ? err.message : String(err));
          await loadGraph().catch(() => undefined);
        } finally {
          setBusy(false);
        }
      })();
    },
    [loadGraph, onError, onMessage],
  );

  const onNodeClick: NodeMouseHandler = (_evt, node) => {
    setSelectedNodeId(Number(node.id));
    setSelectedEdgeId(null);
  };

  const onNodeDragStop: OnNodeDrag = (_evt, node) => {
    void api
      .updateNode(Number(node.id), {
        pos_x: node.position.x,
        pos_y: node.position.y,
      })
      .catch(() => undefined);
  };

  const createFromBlock = async () => {
    if (!selectedBlock || !schema || !createTypeId) return;
    const et = schema.entity_types.find((e) => e.id === createTypeId);
    if (!et) return;
    setBusy(true);
    try {
      const attrs: Record<string, unknown> = {};
      const quote = selectedBlock.text.slice(0, 240);
      if (et.label_attribute) attrs[et.label_attribute] = quote.slice(0, 80);
      await api.createNode(documentId, {
        entity_type: createTypeId,
        attributes: attrs,
        status: "manual",
        pos_x: 80 + (graphNodes.length % 5) * 180,
        pos_y: 60 + Math.floor(graphNodes.length / 5) * 100,
        evidence: {
          quote,
          block_id: selectedBlock.id,
          page: selectedBlock.page,
          bbox: selectedBlock.bbox,
          created_by: "human",
        },
      });
      await loadGraph();
      onMessage?.(`Создана сущность «${et.name}»`);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onSaveNodeCard = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!selectedNode) return;
    const form = new FormData(e.currentTarget);
    const schemaAttrs = selectedEntityType?.attributes ?? [];
    const knownIds = new Set(schemaAttrs.map((attr) => attr.id));
    const attrs: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(selectedNode.attributes || {})) {
      if (!knownIds.has(key)) attrs[key] = value;
    }
    for (const attr of schemaAttrs) {
      const raw = form.get(`attr_${attr.id}`);
      if (raw === null) continue;
      if (raw === "") {
        delete attrs[attr.id];
        continue;
      }
      attrs[attr.id] =
        attr.type === "bool"
          ? raw === "true"
          : attr.type === "number"
            ? Number(raw)
            : String(raw);
    }
    for (const key of Object.keys(selectedNode.attributes || {})) {
      if (knownIds.has(key)) continue;
      const raw = form.get(`extra_${key}`);
      if (raw === null) continue;
      const text = String(raw);
      if (!text.trim()) {
        delete attrs[key];
        continue;
      }
      const trimmed = text.trim();
      if (
        (trimmed.startsWith("{") && trimmed.endsWith("}")) ||
        (trimmed.startsWith("[") && trimmed.endsWith("]"))
      ) {
        try {
          attrs[key] = JSON.parse(trimmed);
          continue;
        } catch {
          // оставляем строкой
        }
      }
      attrs[key] = text;
    }
    const label = String(form.get("label") ?? "").trim();
    setBusy(true);
    try {
      await api.updateNode(selectedNode.id, {
        attributes: attrs,
        status: String(form.get("status") || selectedNode.status),
        ...(label ? { label } : {}),
      });
      await loadGraph();
      onMessage?.("Карточка сохранена");
    } catch (err) {
      onError?.(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    setStructureSvg(null);
    setChemNote(null);
    setStructureProposals([]);
    setCrossrefPreview(null);
  }, [selectedNodeId]);

  const attrValue = (keys: string[]) => {
    if (!selectedNode) return "";
    const attrs = selectedNode.attributes || {};
    for (const k of keys) {
      const v = attrs[k];
      if (v != null && String(v).trim()) return String(v);
    }
    return "";
  };

  const onValidateDraw = async () => {
    if (!selectedNode) return;
    const smiles = attrValue(["smiles", "SMILES"]);
    const inchi = attrValue(["inchi", "InChI", "inchi_key"]);
    if (!smiles && !inchi) {
      onError?.("Нет SMILES/InChI в атрибутах узла");
      return;
    }
    setChemBusy(true);
    setChemNote(null);
    try {
      const { result } = await api.chemValidate({
        smiles: smiles || undefined,
        inchi: inchi || undefined,
      });
      const svgRes = (result.svg as ChemSvgResult | undefined) ||
        (smiles ? (await api.chemSvg({ smiles })).result : null);
      if (svgRes?.svg) setStructureSvg(svgRes.svg);
      const check = result.smiles_check || result;
      const parts: string[] = [];
      if (check.valid) parts.push("Структура валидна");
      else parts.push(check.error || "Структура невалидна");
      if (check.backend === "stub" || check.stub) {
        parts.push(check.note || "режим stub без RDKit");
      }
      if (check.canonical_smiles) parts.push(`канон.: ${check.canonical_smiles}`);
      setChemNote(parts.join(" · "));
      onMessage?.(parts[0]);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : String(err));
    } finally {
      setChemBusy(false);
    }
  };

  const onFindStructure = async () => {
    if (!selectedNode) return;
    const name =
      attrValue(["name", "iupac", "abbreviation", "title"]) ||
      selectedNode.label ||
      "";
    if (!name.trim()) {
      onError?.("Укажите название / IUPAC / аббревиатуру в атрибутах");
      return;
    }
    setChemBusy(true);
    setStructureProposals([]);
    try {
      const { result } = await api.chemNameToStructure({ name: name.trim() });
      setStructureProposals(result.proposals || []);
      if (!result.ok) {
        onError?.(
          (result.errors || []).join("; ") || "Структура не найдена",
        );
      } else {
        onMessage?.(
          `Найдено предложений: ${result.proposals.length}. Подтвердите запись.`,
        );
      }
      setChemNote(result.note || null);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : String(err));
    } finally {
      setChemBusy(false);
    }
  };

  const onConfirmStructure = async (p: StructureProposal) => {
    if (!selectedNode || !p.smiles) return;
    setChemBusy(true);
    try {
      await api.chemApplyStructure({
        node_id: selectedNode.id,
        smiles: p.smiles,
        inchi: p.inchi,
        iupac: p.iupac,
      });
      await loadGraph();
      setStructureProposals([]);
      const svg = await api.chemSvg({ smiles: p.smiles });
      if (svg.result.svg) setStructureSvg(svg.result.svg);
      onMessage?.(`SMILES записан (${p.source || "lookup"})`);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : String(err));
    } finally {
      setChemBusy(false);
    }
  };

  const onCrossref = async () => {
    if (!selectedNode) return;
    const doi = attrValue(["doi", "DOI"]) || "";
    if (!doi.trim()) {
      onError?.("В атрибутах нет DOI");
      return;
    }
    setChemBusy(true);
    setCrossrefPreview(null);
    try {
      const { result } = await api.chemCrossref(doi.trim());
      setCrossrefPreview(result);
      if (!result.ok) {
        onError?.(result.error || "Crossref: ошибка");
      } else {
        onMessage?.(result.title || "Метаданные Crossref получены");
      }
    } catch (err) {
      onError?.(err instanceof Error ? err.message : String(err));
    } finally {
      setChemBusy(false);
    }
  };

  const onConfirmCrossref = async () => {
    if (!selectedNode || !crossrefPreview?.ok) return;
    setChemBusy(true);
    try {
      await api.chemApplyCrossref({
        node_id: selectedNode.id,
        doi: crossrefPreview.doi,
        title: crossrefPreview.title || undefined,
      });
      await loadGraph();
      setCrossrefPreview(null);
      onMessage?.("Метаданные Crossref записаны в узел");
    } catch (err) {
      onError?.(err instanceof Error ? err.message : String(err));
    } finally {
      setChemBusy(false);
    }
  };

  return (
    <div className="stack graph-annotate-pane">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="row">
          <button
            type="button"
            className="btn secondary"
            disabled={busy}
            onClick={() =>
              void (async () => {
                setBusy(true);
                try {
                  await api.saveGold(documentId, { only_accepted: true });
                  onMessage?.("Эталон сохранён");
                } catch (err) {
                  onError?.(err instanceof Error ? err.message : String(err));
                } finally {
                  setBusy(false);
                }
              })()
            }
          >
            Сохранить эталон
          </button>
          <button
            type="button"
            className="btn secondary"
            disabled={busy}
            onClick={() =>
              void (async () => {
                setBusy(true);
                try {
                  const res = await api.exportGraph(documentId);
                  onMessage?.(`Экспорт: ${String(res.export.json_path || "")}`);
                } catch (err) {
                  onError?.(err instanceof Error ? err.message : String(err));
                } finally {
                  setBusy(false);
                }
              })()
            }
          >
            Экспорт
          </button>
        </div>
      </div>

      {selectedBlock ? (
        <div className="row">
          <label>
            Тип из блока
            <select
              value={createTypeId}
              onChange={(e) => setCreateTypeId(e.target.value)}
            >
              {(schema?.entity_types || []).map((et) => (
                <option key={et.id} value={et.id}>
                  {et.name}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="btn"
            disabled={busy || !schema}
            onClick={() => void createFromBlock()}
          >
            Создать сущность из блока
          </button>
        </div>
      ) : (
        <p className="muted">Выберите блок в PDF/структуре для создания сущности.</p>
      )}

      <div className="flow-wrap compact">
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          onNodesChange={onRfNodesChange}
          onEdgesChange={onRfEdgesChange}
          onConnect={onConnect}
          onNodeClick={onNodeClick}
          onEdgeClick={(_evt, edge) => setSelectedEdgeId(Number(edge.id))}
          onEdgesDelete={onEdgesDelete}
          onNodeDragStop={onNodeDragStop}
          deleteKeyCode={["Backspace", "Delete"]}
          fitView
        >
          <Background />
          <Controls />
          <MiniMap />
        </ReactFlow>
      </div>

      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          void (async () => {
            setBusy(true);
            try {
              await api.createEdge(documentId, {
                relation_type: edgeForm.relation_type,
                source_node_id: Number(edgeForm.source_node_id),
                target_node_id: Number(edgeForm.target_node_id),
                status: "manual",
              });
              await loadGraph();
              onMessage?.("Связь создана");
            } catch (err) {
              onError?.(err instanceof Error ? err.message : String(err));
            } finally {
              setBusy(false);
            }
          })();
        }}
      >
        <h3>Связи</h3>
        {graphEdges.length === 0 ? (
          <p className="muted">Связей пока нет.</p>
        ) : (
          <ul className="list compact">
            {graphEdges.map((edge) => (
              <li key={edge.id}>
                <button
                  type="button"
                  className={`edge-pick${selectedEdgeId === edge.id ? " selected" : ""}`}
                  onClick={() => setSelectedEdgeId(edge.id)}
                >
                  #{edge.id} {endpointLabel(graphNodes, edge.source_node_id)} →{" "}
                  {edge.relation_type_name || edge.relation_type} →{" "}
                  {endpointLabel(graphNodes, edge.target_node_id)}
                  <span className="muted"> · {edge.status}</span>
                </button>
                <button
                  type="button"
                  className="btn danger"
                  disabled={busy}
                  onClick={() => void deleteEdgeById(edge.id)}
                >
                  Удалить
                </button>
              </li>
            ))}
          </ul>
        )}
        {selectedEdge ? (
          <p className="muted">
            Выбрана связь #{selectedEdge.id}. Delete удаляет её с холста.
          </p>
        ) : (
          <p className="muted">
            Кликните связь на холсте или выберите её в списке. Узлы, включая
            принятые, правятся в карточке ниже.
          </p>
        )}
        <h3>Новая связь</h3>
        <div className="grid-2">
          <label>
            Тип
            <select
              required
              value={edgeForm.relation_type}
              onChange={(e) =>
                setEdgeForm({ ...edgeForm, relation_type: e.target.value })
              }
            >
              <option value="">—</option>
              {(schema?.relation_types || []).map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            От
            <select
              required
              value={edgeForm.source_node_id}
              onChange={(e) =>
                setEdgeForm({ ...edgeForm, source_node_id: e.target.value })
              }
            >
              <option value="">—</option>
              {graphNodes.map((n) => (
                <option key={n.id} value={n.id}>
                  #{n.id} {n.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            К
            <select
              required
              value={edgeForm.target_node_id}
              onChange={(e) =>
                setEdgeForm({ ...edgeForm, target_node_id: e.target.value })
              }
            >
              <option value="">—</option>
              {graphNodes.map((n) => (
                <option key={n.id} value={n.id}>
                  #{n.id} {n.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <button className="btn secondary" type="submit" disabled={busy}>
          Создать связь
        </button>
      </form>

      <div>
        <h3>Карточка</h3>
        {!selectedNode ? (
          <p className="muted">
            Выберите узел на графе — принятые сущности тоже можно править.
          </p>
        ) : (
          <form className="stack" onSubmit={onSaveNodeCard} key={selectedNode.id}>
            <div>
              <strong>
                {selectedEntityType?.name ||
                  selectedNode.entity_type_name ||
                  selectedNode.entity_type}
              </strong>{" "}
              <span className="badge">#{selectedNode.id}</span>{" "}
              <span className="muted">{selectedNode.status}</span>
            </div>
            <label>
              Метка
              <input name="label" defaultValue={selectedNode.label || ""} />
            </label>
            <label>
              Статус
              <select name="status" defaultValue={selectedNode.status}>
                {STATUS_OPTIONS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
            {(selectedEntityType?.attributes ?? []).map((attr) => (
              <label key={attr.id}>
                {attr.name}
                <input
                  name={`attr_${attr.id}`}
                  defaultValue={formatAttr(selectedNode.attributes[attr.id])}
                />
              </label>
            ))}
            {Object.keys(selectedNode.attributes || {})
              .filter(
                (key) =>
                  !(selectedEntityType?.attributes ?? []).some((attr) => attr.id === key),
              )
              .map((key) => (
                <label key={key}>
                  {key}
                  <input
                    name={`extra_${key}`}
                    defaultValue={formatAttr(selectedNode.attributes[key])}
                  />
                </label>
              ))}
            <button className="btn" type="submit" disabled={busy}>
              Сохранить
            </button>
            <div className="stack">
              <strong>Связи этой сущности</strong>
              {incidentEdges.length === 0 ? (
                <p className="muted">Нет связей.</p>
              ) : (
                <ul className="list compact">
                  {incidentEdges.map((edge) => (
                    <li key={edge.id}>
                      <span>
                        {endpointLabel(graphNodes, edge.source_node_id)} →{" "}
                        {edge.relation_type_name || edge.relation_type} →{" "}
                        {endpointLabel(graphNodes, edge.target_node_id)}
                        <span className="muted"> · {edge.status}</span>
                      </span>
                      <button
                        type="button"
                        className="btn danger"
                        disabled={busy}
                        onClick={() => void deleteEdgeById(edge.id)}
                      >
                        Удалить
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="chem-actions stack">
              <div className="row" style={{ flexWrap: "wrap", gap: "0.4rem" }}>
                <button
                  type="button"
                  className="btn secondary"
                  disabled={chemBusy || busy}
                  onClick={() => void onValidateDraw()}
                >
                  Проверить / нарисовать
                </button>
                <button
                  type="button"
                  className="btn secondary"
                  disabled={chemBusy || busy}
                  onClick={() => void onFindStructure()}
                >
                  Найти структуру
                </button>
                <button
                  type="button"
                  className="btn secondary"
                  disabled={chemBusy || busy}
                  onClick={() => void onCrossref()}
                >
                  Crossref по DOI
                </button>
              </div>
              {chemNote ? <p className="muted">{chemNote}</p> : null}
              {structureSvg ? (
                <div
                  className="chem-svg"
                  dangerouslySetInnerHTML={{ __html: structureSvg }}
                />
              ) : null}
              {structureProposals.length > 0 ? (
                <div className="stack">
                  <strong>Предложения структуры (подтвердите):</strong>
                  <ul className="list compact">
                    {structureProposals.map((p, i) => (
                      <li key={`${p.source}-${i}`}>
                        <div>
                          <code>{p.smiles}</code>
                          <div className="muted">
                            {p.source}
                            {p.iupac ? ` · ${p.iupac}` : ""}
                          </div>
                        </div>
                        <button
                          type="button"
                          className="btn"
                          disabled={chemBusy}
                          onClick={() => void onConfirmStructure(p)}
                        >
                          Применить
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {crossrefPreview ? (
                <div className="stack">
                  {crossrefPreview.ok ? (
                    <>
                      <strong>Crossref</strong>
                      <div>{crossrefPreview.title}</div>
                      <div className="muted">
                        {[crossrefPreview.authors, crossrefPreview.year, crossrefPreview.container_title]
                          .filter(Boolean)
                          .join(" · ")}
                      </div>
                      <button
                        type="button"
                        className="btn"
                        disabled={chemBusy}
                        onClick={() => void onConfirmCrossref()}
                      >
                        Записать в узел
                      </button>
                    </>
                  ) : (
                    <p className="error">{crossrefPreview.error}</p>
                  )}
                </div>
              ) : null}
            </div>
            {selectedNode.evidences?.length > 0 ? (
              <ul className="list compact">
                {selectedNode.evidences.map((ev) => (
                  <li key={ev.id}>
                    <span className={ev.verified ? "success" : "muted"}>
                      {ev.verified ? "✓ " : "?"} «{ev.quote}»
                    </span>
                  </li>
                ))}
              </ul>
            ) : null}
          </form>
        )}
      </div>
    </div>
  );
}
