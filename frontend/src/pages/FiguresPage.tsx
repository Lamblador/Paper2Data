import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  api,
  type FigureClass,
  type FigureItem,
  type PaperBrief,
} from "../api/client";
import { useProject } from "../store/project";

export default function FiguresPage() {
  const { project } = useProject();
  const [params, setParams] = useSearchParams();
  const documentFilter = params.get("document_id");
  const docId = documentFilter ? Number(documentFilter) : null;

  const [figures, setFigures] = useState<FigureItem[]>([]);
  const [classes, setClasses] = useState<FigureClass[]>([]);
  const [papers, setPapers] = useState<PaperBrief[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState<"all" | "uncertain">("all");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [statusNote, setStatusNote] = useState<string>("");
  const [newSlug, setNewSlug] = useState("");
  const [newName, setNewName] = useState("");

  const selected = useMemo(
    () => figures.find((f) => f.id === selectedId) ?? null,
    [figures, selectedId],
  );

  const refresh = useCallback(async () => {
    if (!project) {
      setFigures([]);
      setClasses([]);
      return;
    }
    setError(null);
    try {
      const [figRes, classRes, papersRes, statusRes] = await Promise.all([
        api.listFigures({
          document_id: Number.isFinite(docId as number) ? (docId as number) : undefined,
          uncertain_only: filter === "uncertain",
        }),
        api.listFigureClasses(),
        api.listPapers(),
        api.figuresStatus(),
      ]);
      setFigures(figRes.figures);
      setClasses(classRes.classes);
      setPapers(papersRes.papers);
      const emb = statusRes.embedding;
      setStatusNote(
        emb.is_stub
          ? `Эмбеддинг: stub (${emb.note || "CLIP не установлен"})`
          : `Эмбеддинг: ${emb.backend}`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [project, docId, filter]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (figures.length && selectedId == null) {
      setSelectedId(figures[0].id);
    } else if (selectedId != null && !figures.some((f) => f.id === selectedId)) {
      setSelectedId(figures[0]?.id ?? null);
    }
  }, [figures, selectedId]);

  const onExtract = async () => {
    if (!Number.isFinite(docId as number)) {
      setError("Выберите статью для извлечения рисунков");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.extractFigures(docId as number);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onClassify = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.classifyFigures({
        document_id: Number.isFinite(docId as number) ? (docId as number) : undefined,
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onAssign = async (classId: number | null) => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const data = await api.assignFigureClass(selected.id, classId);
      setFigures((prev) =>
        prev.map((f) => (f.id === data.figure.id ? data.figure : f)),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onCreateClass = async () => {
    if (!newSlug.trim() || !newName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const data = await api.createFigureClass({
        slug: newSlug.trim(),
        name: newName.trim(),
      });
      setClasses((prev) => [...prev, data.class]);
      setNewSlug("");
      setNewName("");
      if (selected) {
        await api.assignFigureClass(selected.id, data.class.id);
        await refresh();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (!project) {
    return (
      <section className="panel">
        <h1>Рисунки</h1>
        <p className="muted">Откройте проект, чтобы работать с галереей.</p>
      </section>
    );
  }

  return (
    <section className="stack">
      <div className="panel">
        <div className="row paper-workspace-header">
          <div>
            <h1>Рисунки</h1>
            <p className="muted">
              Галерея по проекту или статье. Ручная разметка обучает CLIP+kNN на лету.
            </p>
            {statusNote ? <p className="muted">{statusNote}</p> : null}
          </div>
          <div className="row">
            <select
              style={{ width: "auto", minWidth: 220 }}
              value={documentFilter ?? ""}
              onChange={(e) => {
                const v = e.target.value;
                const next = new URLSearchParams(params);
                if (v) next.set("document_id", v);
                else next.delete("document_id");
                setParams(next);
                setSelectedId(null);
              }}
            >
              <option value="">Все статьи</option>
              {papers.map((p) => (
                <option key={p.id} value={p.id}>
                  #{p.id} {p.title}
                </option>
              ))}
            </select>
            <button
              type="button"
              className={`btn secondary ${filter === "all" ? "active-tab" : ""}`}
              onClick={() => setFilter("all")}
            >
              Все
            </button>
            <button
              type="button"
              className={`btn secondary ${filter === "uncertain" ? "active-tab" : ""}`}
              onClick={() => setFilter("uncertain")}
            >
              Не уверен
            </button>
            <button
              type="button"
              className="btn secondary"
              disabled={busy || !docId}
              onClick={() => void onExtract()}
            >
              Извлечь
            </button>
            <button
              type="button"
              className="btn"
              disabled={busy}
              onClick={() => void onClassify()}
            >
              Классифицировать
            </button>
          </div>
        </div>
        {error ? <p className="error">{error}</p> : null}
      </div>

      <div className="figures-layout">
        <div className="panel figures-grid-panel">
          {figures.length === 0 ? (
            <p className="muted">
              Рисунков нет. Разберите статью (ingest) или нажмите «Извлечь».
            </p>
          ) : (
            <div className="figures-grid">
              {figures.map((fig) => (
                <button
                  key={fig.id}
                  type="button"
                  className={`figure-card ${selectedId === fig.id ? "selected" : ""}`}
                  onClick={() => setSelectedId(fig.id)}
                >
                  <img src={fig.image_url} alt={fig.caption || `рис. ${fig.id}`} />
                  <div className="figure-card-meta">
                    <span className="badge">стр. {fig.page}</span>
                    {fig.uncertain ? (
                      <span className="badge warn">Не уверен</span>
                    ) : fig.class_name ? (
                      <span className="badge">{fig.class_name}</span>
                    ) : null}
                  </div>
                  <div className="figure-card-caption">
                    {fig.caption || "Без подписи"}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        <aside className="panel stack">
          <h2>Карточка</h2>
          {!selected ? (
            <p className="muted">Выберите рисунок</p>
          ) : (
            <>
              <img
                className="figure-preview"
                src={selected.image_url}
                alt={selected.caption || ""}
              />
              <p>
                <Link to={`/papers/${selected.document_id}`}>
                  Статья #{selected.document_id}
                </Link>
                {" · "}стр. {selected.page} · {selected.source_kind}
              </p>
              <p className="muted">{selected.caption || "Без подписи"}</p>
              {selected.confidence != null ? (
                <p className="muted">
                  Уверенность: {(selected.confidence * 100).toFixed(0)}%
                  {selected.manual_label ? " (ручная метка)" : ""}
                </p>
              ) : null}

              <label>
                Класс
                <select
                  value={selected.class_id ?? ""}
                  disabled={busy}
                  onChange={(e) => {
                    const v = e.target.value;
                    void onAssign(v === "" ? null : Number(v));
                  }}
                >
                  <option value="">— не задан —</option>
                  {classes.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name} ({c.slug})
                    </option>
                  ))}
                </select>
              </label>

              {selected.uncertain ? (
                <div className="stack" style={{ marginTop: "0.5rem" }}>
                  <p className="badge warn" style={{ width: "fit-content" }}>
                    Корзина «Не уверен»
                  </p>
                  <p className="muted">
                    Назначьте класс вручную или создайте новый — классификатор
                    обучится на этом примере.
                  </p>
                </div>
              ) : null}

              <h2>Новый класс</h2>
              <label>
                Идентификатор (slug)
                <input
                  value={newSlug}
                  onChange={(e) => setNewSlug(e.target.value)}
                  placeholder="my_spectrum"
                />
              </label>
              <label>
                Название
                <input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="Мой спектр"
                />
              </label>
              <button
                type="button"
                className="btn"
                disabled={busy || !newSlug.trim() || !newName.trim()}
                onClick={() => void onCreateClass()}
              >
                Создать класс{selected.uncertain ? " и назначить" : ""}
              </button>
            </>
          )}
        </aside>
      </div>
    </section>
  );
}
