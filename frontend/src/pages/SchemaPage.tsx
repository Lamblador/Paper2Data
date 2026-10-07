import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  api,
  type AttributeDef,
  type EntityType,
  type ProjectSchema,
  type RelationType,
  type SchemaTemplateInfo,
} from "../api/client";
import SchemaGraphPane from "../components/SchemaGraphPane";
import { useProject } from "../store/project";

const ATTR_TYPES = [
  "text",
  "number",
  "number_with_unit",
  "range",
  "enum",
  "smiles",
  "inchi",
  "doi",
  "bool",
];

export default function SchemaPage() {
  const { project, refresh } = useProject();
  const [templates, setTemplates] = useState<SchemaTemplateInfo[]>([]);
  const [schema, setSchema] = useState<ProjectSchema | null>(null);
  const [selectedTypeId, setSelectedTypeId] = useState<string | null>(null);
  const [selectedRelationId, setSelectedRelationId] = useState<string | null>(
    null,
  );
  const [inspectorTab, setInspectorTab] = useState<"entity" | "relation">(
    "entity",
  );
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [entityForm, setEntityForm] = useState({
    id: "",
    name: "",
    description: "",
    label_attribute: "",
  });
  const [attrForm, setAttrForm] = useState({
    id: "",
    name: "",
    type: "text",
    required: false,
    unit: "",
    enum_values: "",
    llm_hint: "",
  });
  const [relForm, setRelForm] = useState({
    id: "",
    name: "",
    from: "",
    to: "",
    cardinality: "1:N",
    description: "",
    llm_hint: "",
  });

  const selectedEntity: EntityType | null = useMemo(() => {
    if (!schema || !selectedTypeId) return null;
    return schema.entity_types.find((e) => e.id === selectedTypeId) ?? null;
  }, [schema, selectedTypeId]);

  const fillEntityForm = (entity: EntityType) => {
    setSelectedTypeId(entity.id);
    setSelectedRelationId(null);
    setInspectorTab("entity");
    setEntityForm({
      id: entity.id,
      name: entity.name,
      description: entity.description || "",
      label_attribute: entity.label_attribute || "",
    });
  };

  const fillRelationForm = (rel: RelationType) => {
    setSelectedRelationId(rel.id);
    setInspectorTab("relation");
    setRelForm({
      id: rel.id,
      name: rel.name,
      from: rel.from,
      to: rel.to,
      cardinality: rel.cardinality || "1:N",
      description: rel.description || "",
      llm_hint: rel.llm_hint || "",
    });
  };

  const fillAttrForm = (a: AttributeDef) => {
    setAttrForm({
      id: a.id,
      name: a.name,
      type: a.type || "text",
      required: !!a.required,
      unit: a.unit || "",
      enum_values: (a.enum_values || []).join(", "),
      llm_hint: a.llm_hint || "",
    });
  };

  const startNewEntity = () => {
    setSelectedTypeId(null);
    setSelectedRelationId(null);
    setInspectorTab("entity");
    setEntityForm({ id: "", name: "", description: "", label_attribute: "" });
    setAttrForm({
      id: "",
      name: "",
      type: "text",
      required: false,
      unit: "",
      enum_values: "",
      llm_hint: "",
    });
  };

  const startNewRelation = () => {
    setSelectedRelationId(null);
    setInspectorTab("relation");
    setRelForm({
      id: "",
      name: "",
      from: selectedTypeId || "",
      to: "",
      cardinality: "1:N",
      description: "",
      llm_hint: "",
    });
  };

  const onDeleteRelationFromGraph = async (relationId: string) => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.deleteRelationType(relationId);
      setSchema(res.schema);
      if (selectedRelationId === relationId) {
        setSelectedRelationId(null);
        setRelForm({
          id: "",
          name: "",
          from: "",
          to: "",
          cardinality: "1:N",
          description: "",
          llm_hint: "",
        });
      }
      setMessage("Тип связи удалён.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const load = async () => {
    const [tpl, cur] = await Promise.all([
      api.listSchemaTemplates(),
      api.currentSchema(),
    ]);
    setTemplates(tpl.templates);
    setSchema(cur.schema);
    if (cur.schema?.entity_types?.length) {
      const current =
        (selectedTypeId &&
          cur.schema.entity_types.find((e) => e.id === selectedTypeId)) ||
        cur.schema.entity_types[0];
      fillEntityForm(current);
    }
  };

  useEffect(() => {
    if (!project) {
      setSchema(null);
      return;
    }
    void load().catch((err) =>
      setError(err instanceof Error ? err.message : String(err)),
    );
  }, [project]);

  if (!project) {
    return (
      <section className="panel">
        <h1>Схема</h1>
        <p className="muted">Откройте проект, чтобы редактировать онтологию.</p>
      </section>
    );
  }

  const onApply = async (templateId: string) => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const res = await api.applySchemaTemplate(templateId);
      setSchema(res.schema);
      setSelectedTypeId(res.schema.entity_types[0]?.id ?? null);
      setMessage(`Применён шаблон «${res.schema.name}» (v${res.schema.version}).`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onSaveEntity = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.upsertEntityType({
        id: entityForm.id.trim(),
        name: entityForm.name.trim() || entityForm.id.trim(),
        description: entityForm.description,
        label_attribute: entityForm.label_attribute || null,
      });
      setSchema(res.schema);
      const savedId = entityForm.id.trim();
      const saved = res.schema.entity_types.find((e) => e.id === savedId);
      if (saved) fillEntityForm(saved);
      else setSelectedTypeId(savedId);
      setMessage("Тип сущности сохранён.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onSaveAttr = async (e: FormEvent) => {
    e.preventDefault();
    if (!selectedTypeId) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.upsertAttribute(selectedTypeId, {
        id: attrForm.id.trim(),
        name: attrForm.name.trim() || attrForm.id.trim(),
        type: attrForm.type,
        required: attrForm.required,
        unit: attrForm.unit || null,
        enum_values: attrForm.enum_values
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        llm_hint: attrForm.llm_hint,
      });
      setSchema(res.schema);
      setAttrForm({
        id: "",
        name: "",
        type: "text",
        required: false,
        unit: "",
        enum_values: "",
        llm_hint: "",
      });
      setMessage("Атрибут сохранён.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onSaveRelation = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.upsertRelationType({
        id: relForm.id.trim(),
        name: relForm.name.trim() || relForm.id.trim(),
        from: relForm.from,
        to: relForm.to,
        cardinality: relForm.cardinality,
        description: relForm.description,
        llm_hint: relForm.llm_hint,
      });
      setSchema(res.schema);
      const savedId = relForm.id.trim();
      const saved = res.schema.relation_types.find((r) => r.id === savedId);
      if (saved) fillRelationForm(saved);
      setMessage("Тип связи сохранён.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <section className="panel">
        <h1>Редактор схемы</h1>
        <p className="muted">
          Онтология проекта задаёт типы сущностей, атрибуты и связи. Из неё
          строятся формы разметки и (позже) промпты LLM.
        </p>
        {schema ? (
          <p>
            Активная схема: <strong>{schema.name}</strong>{" "}
            <span className="badge">v{schema.version}</span>{" "}
            {schema.template_id && (
              <span className="badge">{schema.template_id}</span>
            )}
          </p>
        ) : (
          <p className="muted">Схема ещё не применена — выберите шаблон ниже.</p>
        )}
        {error && <p className="error">{error}</p>}
        {message && <p className="success">{message}</p>}
      </section>

      {schema && (
        <SchemaGraphPane
          schema={schema}
          projectPath={project.path}
          selectedTypeId={selectedTypeId}
          selectedRelationId={selectedRelationId}
          busy={busy}
          onSelectEntity={fillEntityForm}
          onSelectRelation={fillRelationForm}
          onConnectDraft={({ from, to }) => {
            setSelectedRelationId(null);
            setInspectorTab("relation");
            setRelForm((prev) => ({
              ...prev,
              id: "",
              name: "",
              from,
              to,
              cardinality: prev.cardinality || "1:N",
            }));
            setMessage(
              `Связь: ${from} → ${to}. Заполните ID и название справа.`,
            );
          }}
          onDeleteRelation={(relationId) => {
            void onDeleteRelationFromGraph(relationId);
          }}
          inspector={
            <div className="schema-inspector-body">
              <div className="schema-inspector-tabs">
                <button
                  type="button"
                  className={
                    inspectorTab === "entity" ? "btn" : "btn secondary"
                  }
                  onClick={() => setInspectorTab("entity")}
                >
                  Сущность
                </button>
                <button
                  type="button"
                  className={
                    inspectorTab === "relation" ? "btn" : "btn secondary"
                  }
                  onClick={() => setInspectorTab("relation")}
                >
                  Связь
                </button>
              </div>

              {inspectorTab === "entity" ? (
                <>
                  <div className="schema-inspector-picker">
                    <label>
                      Тип
                      <select
                        value={selectedTypeId ?? ""}
                        onChange={(e) => {
                          const id = e.target.value;
                          if (!id) {
                            startNewEntity();
                            return;
                          }
                          const et = schema.entity_types.find(
                            (x) => x.id === id,
                          );
                          if (et) fillEntityForm(et);
                        }}
                      >
                        <option value="">— новый тип —</option>
                        {schema.entity_types.map((et) => (
                          <option key={et.id} value={et.id}>
                            {et.name} ({et.id})
                          </option>
                        ))}
                      </select>
                    </label>
                    <button
                      type="button"
                      className="btn secondary"
                      onClick={startNewEntity}
                    >
                      +
                    </button>
                    {selectedEntity ? (
                      <button
                        type="button"
                        className="btn danger"
                        disabled={busy}
                        onClick={() =>
                          void (async () => {
                            if (
                              !confirm(
                                `Удалить тип «${selectedEntity.name}»?`,
                              )
                            )
                              return;
                            setBusy(true);
                            try {
                              const res = await api.deleteEntityType(
                                selectedEntity.id,
                              );
                              setSchema(res.schema);
                              const next = res.schema.entity_types[0];
                              if (next) fillEntityForm(next);
                              else startNewEntity();
                            } catch (err) {
                              setError(
                                err instanceof Error
                                  ? err.message
                                  : String(err),
                              );
                            } finally {
                              setBusy(false);
                            }
                          })()
                        }
                      >
                        Удалить
                      </button>
                    ) : null}
                  </div>

                  <form className="stack" onSubmit={onSaveEntity}>
                    <h3>
                      {selectedEntity
                        ? "Редактировать тип"
                        : "Новый тип сущности"}
                    </h3>
                    <div className="grid-2">
                      <label>
                        ID
                        <input
                          required
                          value={entityForm.id}
                          onChange={(e) =>
                            setEntityForm({
                              ...entityForm,
                              id: e.target.value,
                            })
                          }
                          placeholder="Compound"
                        />
                      </label>
                      <label>
                        Название
                        <input
                          value={entityForm.name}
                          onChange={(e) =>
                            setEntityForm({
                              ...entityForm,
                              name: e.target.value,
                            })
                          }
                          placeholder="Соединение"
                        />
                      </label>
                    </div>
                    <label>
                      Описание
                      <textarea
                        rows={2}
                        value={entityForm.description}
                        onChange={(e) =>
                          setEntityForm({
                            ...entityForm,
                            description: e.target.value,
                          })
                        }
                      />
                    </label>
                    <label>
                      Атрибут для подписи
                      <input
                        value={entityForm.label_attribute}
                        onChange={(e) =>
                          setEntityForm({
                            ...entityForm,
                            label_attribute: e.target.value,
                          })
                        }
                        placeholder="code"
                      />
                    </label>
                    <button className="btn" type="submit" disabled={busy}>
                      Сохранить тип
                    </button>
                  </form>

                  {selectedEntity ? (
                    <>
                      <h3>
                        Атрибуты{" "}
                        <span className="badge">
                          {selectedEntity.attributes.length}
                        </span>
                      </h3>
                      <ul className="list compact schema-inspector-attrs">
                        {selectedEntity.attributes.map((a: AttributeDef) => (
                          <li key={a.id}>
                            <button
                              type="button"
                              className={
                                attrForm.id === a.id
                                  ? "edge-pick selected"
                                  : "edge-pick"
                              }
                              onClick={() => fillAttrForm(a)}
                            >
                              <strong>{a.name}</strong>{" "}
                              <span className="badge">{a.type}</span>
                              {a.required ? (
                                <span className="badge warn">обяз.</span>
                              ) : null}
                              {selectedEntity.label_attribute === a.id ? (
                                <span className="badge">label</span>
                              ) : null}
                              <div className="muted path">{a.id}</div>
                            </button>
                            <button
                              className="btn danger"
                              disabled={busy}
                              onClick={() =>
                                void (async () => {
                                  setBusy(true);
                                  try {
                                    const res = await api.deleteAttribute(
                                      selectedEntity.id,
                                      a.id,
                                    );
                                    setSchema(res.schema);
                                    if (attrForm.id === a.id) {
                                      setAttrForm({
                                        id: "",
                                        name: "",
                                        type: "text",
                                        required: false,
                                        unit: "",
                                        enum_values: "",
                                        llm_hint: "",
                                      });
                                    }
                                  } catch (err) {
                                    setError(
                                      err instanceof Error
                                        ? err.message
                                        : String(err),
                                    );
                                  } finally {
                                    setBusy(false);
                                  }
                                })()
                              }
                            >
                              ×
                            </button>
                          </li>
                        ))}
                      </ul>
                      <form className="stack" onSubmit={onSaveAttr}>
                        <h3>
                          {attrForm.id
                            ? "Редактировать атрибут"
                            : "Новый атрибут"}
                        </h3>
                        <div className="grid-2">
                          <label>
                            ID
                            <input
                              required
                              value={attrForm.id}
                              onChange={(e) =>
                                setAttrForm({
                                  ...attrForm,
                                  id: e.target.value,
                                })
                              }
                            />
                          </label>
                          <label>
                            Название
                            <input
                              value={attrForm.name}
                              onChange={(e) =>
                                setAttrForm({
                                  ...attrForm,
                                  name: e.target.value,
                                })
                              }
                            />
                          </label>
                          <label>
                            Тип
                            <select
                              value={attrForm.type}
                              onChange={(e) =>
                                setAttrForm({
                                  ...attrForm,
                                  type: e.target.value,
                                })
                              }
                            >
                              {ATTR_TYPES.map((t) => (
                                <option key={t} value={t}>
                                  {t}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label>
                            Единица
                            <input
                              value={attrForm.unit}
                              onChange={(e) =>
                                setAttrForm({
                                  ...attrForm,
                                  unit: e.target.value,
                                })
                              }
                            />
                          </label>
                        </div>
                        <label>
                          Значения enum (через запятую)
                          <input
                            value={attrForm.enum_values}
                            onChange={(e) =>
                              setAttrForm({
                                ...attrForm,
                                enum_values: e.target.value,
                              })
                            }
                          />
                        </label>
                        <label>
                          Подсказка для LLM
                          <textarea
                            rows={2}
                            value={attrForm.llm_hint}
                            onChange={(e) =>
                              setAttrForm({
                                ...attrForm,
                                llm_hint: e.target.value,
                              })
                            }
                          />
                        </label>
                        <label
                          className="row"
                          style={{ justifyContent: "flex-start" }}
                        >
                          <input
                            type="checkbox"
                            checked={attrForm.required}
                            onChange={(e) =>
                              setAttrForm({
                                ...attrForm,
                                required: e.target.checked,
                              })
                            }
                          />
                          Обязательный
                        </label>
                        <div className="row" style={{ gap: "0.5rem" }}>
                          <button className="btn" type="submit" disabled={busy}>
                            Сохранить атрибут
                          </button>
                          {attrForm.id ? (
                            <button
                              type="button"
                              className="btn secondary"
                              onClick={() =>
                                setAttrForm({
                                  id: "",
                                  name: "",
                                  type: "text",
                                  required: false,
                                  unit: "",
                                  enum_values: "",
                                  llm_hint: "",
                                })
                              }
                            >
                              Сброс
                            </button>
                          ) : null}
                        </div>
                      </form>
                    </>
                  ) : (
                    <p className="muted">
                      Сохраните тип, чтобы добавлять атрибуты.
                    </p>
                  )}
                </>
              ) : (
                <>
                  <div className="schema-inspector-picker">
                    <label>
                      Связь
                      <select
                        value={selectedRelationId ?? ""}
                        onChange={(e) => {
                          const id = e.target.value;
                          if (!id) {
                            startNewRelation();
                            return;
                          }
                          const rel = schema.relation_types.find(
                            (x) => x.id === id,
                          );
                          if (rel) fillRelationForm(rel);
                        }}
                      >
                        <option value="">— новая связь —</option>
                        {schema.relation_types.map((r) => (
                          <option key={r.id} value={r.id}>
                            {r.name} ({r.from}→{r.to})
                          </option>
                        ))}
                      </select>
                    </label>
                    <button
                      type="button"
                      className="btn secondary"
                      onClick={startNewRelation}
                    >
                      +
                    </button>
                    {selectedRelationId ? (
                      <button
                        type="button"
                        className="btn danger"
                        disabled={busy}
                        onClick={() =>
                          void (async () => {
                            if (
                              !confirm(
                                `Удалить тип связи «${relForm.name || selectedRelationId}»?`,
                              )
                            )
                              return;
                            await onDeleteRelationFromGraph(selectedRelationId);
                          })()
                        }
                      >
                        Удалить
                      </button>
                    ) : null}
                  </div>

                  <form className="stack" onSubmit={onSaveRelation}>
                    <h3>
                      {selectedRelationId
                        ? "Редактировать связь"
                        : "Новая связь"}
                    </h3>
                    <div className="grid-2">
                      <label>
                        ID
                        <input
                          required
                          value={relForm.id}
                          onChange={(e) =>
                            setRelForm({ ...relForm, id: e.target.value })
                          }
                        />
                      </label>
                      <label>
                        Название
                        <input
                          value={relForm.name}
                          onChange={(e) =>
                            setRelForm({ ...relForm, name: e.target.value })
                          }
                        />
                      </label>
                      <label>
                        От (from)
                        <select
                          required
                          value={relForm.from}
                          onChange={(e) =>
                            setRelForm({ ...relForm, from: e.target.value })
                          }
                        >
                          <option value="">—</option>
                          {schema.entity_types.map((et) => (
                            <option key={et.id} value={et.id}>
                              {et.name}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        К (to)
                        <select
                          required
                          value={relForm.to}
                          onChange={(e) =>
                            setRelForm({ ...relForm, to: e.target.value })
                          }
                        >
                          <option value="">—</option>
                          {schema.entity_types.map((et) => (
                            <option key={et.id} value={et.id}>
                              {et.name}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        Кардинальность
                        <input
                          value={relForm.cardinality}
                          onChange={(e) =>
                            setRelForm({
                              ...relForm,
                              cardinality: e.target.value,
                            })
                          }
                        />
                      </label>
                    </div>
                    <label>
                      Описание
                      <textarea
                        rows={2}
                        value={relForm.description}
                        onChange={(e) =>
                          setRelForm({
                            ...relForm,
                            description: e.target.value,
                          })
                        }
                      />
                    </label>
                    <label>
                      Подсказка для LLM
                      <textarea
                        rows={2}
                        value={relForm.llm_hint}
                        onChange={(e) =>
                          setRelForm({
                            ...relForm,
                            llm_hint: e.target.value,
                          })
                        }
                      />
                    </label>
                    <button className="btn" type="submit" disabled={busy}>
                      Сохранить связь
                    </button>
                  </form>
                </>
              )}
            </div>
          }
        />
      )}

      <section className="panel">
        {schema ? (
          <details className="schema-templates-fold">
            <summary>
              <strong>Шаблоны</strong>{" "}
              <span className="muted">
                применить другой шаблон ({templates.length})
              </span>
            </summary>
            <ul className="list">
              {templates.map((t) => (
                <li key={t.id}>
                  <div>
                    <div>
                      <strong>{t.name}</strong>{" "}
                      <span className="badge">{t.id}</span>
                    </div>
                    <div className="muted">{t.description || "—"}</div>
                    {t.imports?.length > 0 && (
                      <div className="muted">
                        импорты: {t.imports.join(", ")}
                      </div>
                    )}
                  </div>
                  <button
                    className="btn"
                    disabled={busy}
                    onClick={() => void onApply(t.id)}
                  >
                    Применить
                  </button>
                </li>
              ))}
            </ul>
          </details>
        ) : (
          <>
            <h2>Шаблоны</h2>
            <ul className="list">
              {templates.map((t) => (
                <li key={t.id}>
                  <div>
                    <div>
                      <strong>{t.name}</strong>{" "}
                      <span className="badge">{t.id}</span>
                    </div>
                    <div className="muted">{t.description || "—"}</div>
                    {t.imports?.length > 0 && (
                      <div className="muted">
                        импорты: {t.imports.join(", ")}
                      </div>
                    )}
                  </div>
                  <button
                    className="btn"
                    disabled={busy}
                    onClick={() => void onApply(t.id)}
                  >
                    Применить
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </div>
  );
}
