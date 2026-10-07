import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type EdgeMouseHandler,
  type Node,
  type NodeMouseHandler,
  type NodeProps,
  type OnBeforeDelete,
  type OnNodeDrag,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type {
  AttributeDef,
  EntityType,
  ProjectSchema,
  RelationType,
} from "../api/client";
import {
  clearPositions,
  loadPositions,
  mergeLayout,
  parallelEdgeOffsets,
  savePositions,
  type PositionsMap,
} from "../lib/schemaLayout";

export type SchemaRelDraft = {
  from: string;
  to: string;
};

type EntityNodeData = {
  entity: EntityType;
  selected: boolean;
};

type EntityFlowNode = Node<EntityNodeData, "entitySchema">;

function attrCount(rel: RelationType): number {
  const attrs = rel.attributes;
  if (!attrs) return 0;
  if (Array.isArray(attrs)) return attrs.length;
  return Object.keys(attrs).length;
}

function EntitySchemaNode({ data }: NodeProps<EntityFlowNode>) {
  const { entity, selected } = data;
  return (
    <div className={`schema-entity-node${selected ? " selected" : ""}`}>
      <Handle type="target" position={Position.Left} className="schema-handle" />
      <div className="schema-entity-header">
        <div className="schema-entity-name">{entity.name}</div>
        <div className="schema-entity-id path">{entity.id}</div>
      </div>
      <ul className="schema-attr-list">
        {entity.attributes.length === 0 ? (
          <li className="muted">нет атрибутов</li>
        ) : (
          entity.attributes.map((a: AttributeDef) => (
            <li
              key={a.id}
              className={
                entity.label_attribute === a.id
                  ? "schema-attr label-attr"
                  : "schema-attr"
              }
            >
              <span className="schema-attr-name">{a.name}</span>
              <span className="badge">{a.type}</span>
              {a.required ? <span className="badge warn">обяз.</span> : null}
              {entity.label_attribute === a.id ? (
                <span className="badge">label</span>
              ) : null}
            </li>
          ))
        )}
      </ul>
      <Handle type="source" position={Position.Right} className="schema-handle" />
    </div>
  );
}

const nodeTypes = { entitySchema: memo(EntitySchemaNode) };

function toFlowNodes(
  entities: EntityType[],
  positions: PositionsMap,
  selectedTypeId: string | null,
): EntityFlowNode[] {
  return entities.map((entity) => ({
    id: entity.id,
    type: "entitySchema" as const,
    position: positions[entity.id] ?? { x: 0, y: 0 },
    data: {
      entity,
      selected: selectedTypeId === entity.id,
    },
    deletable: false,
    selected: selectedTypeId === entity.id,
  }));
}

function toFlowEdges(
  relations: RelationType[],
  entityIds: Set<string>,
  selectedRelationId: string | null,
): Edge[] {
  const offsets = parallelEdgeOffsets(relations, entityIds);
  return relations
    .filter((r) => entityIds.has(r.from) && entityIds.has(r.to))
    .map((r) => {
      const isLoop = r.from === r.to;
      const offset = offsets.get(r.id) ?? 0;
      const nAttrs = attrCount(r);
      const labelParts = [`${r.name} (${r.cardinality})`];
      if (nAttrs > 0) labelParts.push(`+${nAttrs}`);
      return {
        id: r.id,
        source: r.from,
        target: r.to,
        label: labelParts.join(" "),
        type: isLoop ? "default" : "smoothstep",
        animated: false,
        deletable: true,
        selected: selectedRelationId === r.id,
        interactionWidth: 20,
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 16,
          height: 16,
        },
        style: {
          stroke: selectedRelationId === r.id ? "#0f6e56" : "#64748b",
          strokeWidth: selectedRelationId === r.id ? 2.5 : 1.5,
        },
        labelStyle: {
          fontSize: 11,
          fill: "#334155",
        },
        labelBgStyle: {
          fill: "#fffdf8",
          fillOpacity: 0.9,
        },
        labelBgPadding: [4, 6] as [number, number],
        labelBgBorderRadius: 4,
        pathOptions: isLoop ? undefined : { offset: offset * 18 },
        data: { relation: r, offset },
      };
    });
}

type Props = {
  schema: ProjectSchema;
  projectPath: string;
  selectedTypeId: string | null;
  selectedRelationId: string | null;
  onSelectEntity: (entity: EntityType) => void;
  onSelectRelation: (relation: RelationType) => void;
  onConnectDraft: (draft: SchemaRelDraft) => void;
  onDeleteRelation: (relationId: string) => void;
  busy?: boolean;
  /** Боковая панель просмотра/редактирования выбранного типа. */
  inspector?: ReactNode;
};

export default function SchemaGraphPane({
  schema,
  projectPath,
  selectedTypeId,
  selectedRelationId,
  onSelectEntity,
  onSelectRelation,
  onConnectDraft,
  onDeleteRelation,
  busy = false,
  inspector,
}: Props) {
  const [positions, setPositions] = useState<PositionsMap>(() =>
    mergeLayout(
      schema.entity_types,
      schema.relation_types,
      loadPositions(projectPath),
    ),
  );
  const [rfNodes, setRfNodes, onRfNodesChange] = useNodesState<EntityFlowNode>([]);
  const [rfEdges, setRfEdges, onRfEdgesChange] = useEdgesState<Edge>([]);

  const entityIds = useMemo(
    () => new Set(schema.entity_types.map((e) => e.id)),
    [schema.entity_types],
  );

  // Rebuild layout when schema entity set changes; keep saved coords
  useEffect(() => {
    const merged = mergeLayout(
      schema.entity_types,
      schema.relation_types,
      loadPositions(projectPath),
    );
    setPositions(merged);
  }, [schema.entity_types, schema.relation_types, projectPath]);

  useEffect(() => {
    setRfNodes(toFlowNodes(schema.entity_types, positions, selectedTypeId));
    setRfEdges(toFlowEdges(schema.relation_types, entityIds, selectedRelationId));
  }, [
    schema.entity_types,
    schema.relation_types,
    positions,
    selectedTypeId,
    selectedRelationId,
    entityIds,
    setRfNodes,
    setRfEdges,
  ]);

  const persistPositions = useCallback(
    (next: PositionsMap) => {
      setPositions(next);
      savePositions(projectPath, next);
    },
    [projectPath],
  );

  const onRelayout = useCallback(() => {
    clearPositions(projectPath);
    const auto = mergeLayout(schema.entity_types, schema.relation_types, {});
    persistPositions(auto);
  }, [projectPath, schema.entity_types, schema.relation_types, persistPositions]);

  const onNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      const entity = schema.entity_types.find((e) => e.id === node.id);
      if (entity) onSelectEntity(entity);
    },
    [schema.entity_types, onSelectEntity],
  );

  const onEdgeClick: EdgeMouseHandler = useCallback(
    (event: ReactMouseEvent, edge: Edge) => {
      event.stopPropagation();
      const rel = schema.relation_types.find((r) => r.id === edge.id);
      if (rel) onSelectRelation(rel);
    },
    [schema.relation_types, onSelectRelation],
  );

  const onNodeDragStop: OnNodeDrag = useCallback(
    (_event, node) => {
      const next = {
        ...positions,
        [node.id]: { x: node.position.x, y: node.position.y },
      };
      persistPositions(next);
    },
    [positions, persistPositions],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return;
      onConnectDraft({ from: connection.source, to: connection.target });
    },
    [onConnectDraft],
  );

  const onBeforeDelete = useCallback<OnBeforeDelete<EntityFlowNode, Edge>>(
    async ({ nodes: delNodes, edges: delEdges }) => {
      if (delNodes.length > 0) {
        return false;
      }
      if (delEdges.length === 0) return false;
      const names = delEdges
        .map((e) => {
          const rel = schema.relation_types.find((r) => r.id === e.id);
          return rel?.name || e.id;
        })
        .join(", ");
      if (!confirm(`Удалить тип связи «${names}»?`)) {
        return false;
      }
      for (const edge of delEdges) {
        onDeleteRelation(edge.id);
      }
      // Parent reloads schema; keep RF edges until schema update
      return false;
    },
    [schema.relation_types, onDeleteRelation],
  );

  const canvas =
    schema.entity_types.length === 0 ? (
      <div className="flow-wrap schema schema-empty">
        <p className="muted">Добавьте типы сущностей — они появятся на холсте.</p>
      </div>
    ) : (
      <div className="flow-wrap schema">
        <ReactFlow<EntityFlowNode, Edge>
          nodes={rfNodes}
          edges={rfEdges}
          nodeTypes={nodeTypes}
          onNodesChange={onRfNodesChange}
          onEdgesChange={onRfEdgesChange}
          onNodeClick={onNodeClick}
          onEdgeClick={onEdgeClick}
          onNodeDragStop={onNodeDragStop}
          onConnect={onConnect}
          onBeforeDelete={onBeforeDelete}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          deleteKeyCode={["Backspace", "Delete"]}
          nodesDraggable
          nodesConnectable
          elementsSelectable
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={16} size={1} />
          <Controls />
          <MiniMap pannable zoomable />
        </ReactFlow>
      </div>
    );

  return (
    <section className="panel">
      <div className="row schema-graph-toolbar">
        <h2>Диаграмма схемы</h2>
        <div className="row" style={{ gap: "0.5rem" }}>
          <button
            type="button"
            className="btn secondary"
            disabled={busy || schema.entity_types.length === 0}
            onClick={onRelayout}
          >
            Упорядочить
          </button>
        </div>
      </div>
      <p className="muted schema-graph-hint">
        Клик по узлу или ребру открывает детали справа. Протяжка между узлами
        задаёт from/to новой связи. Delete удаляет выбранную связь.
      </p>
      <div className={inspector ? "schema-workspace" : undefined}>
        {canvas}
        {inspector ? (
          <aside className="schema-inspector">{inspector}</aside>
        ) : null}
      </div>
    </section>
  );
}
