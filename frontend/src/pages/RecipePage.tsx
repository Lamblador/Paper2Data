import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  type RecipeBody,
  type RecipeBrief,
  type RecipeInfo,
  type RecipeStep,
} from "../api/client";
import { useProject } from "../store/project";

export default function RecipePage() {
  const { project } = useProject();
  const [bundled, setBundled] = useState<RecipeBrief[]>([]);
  const [recipes, setRecipes] = useState<RecipeInfo[]>([]);
  const [body, setBody] = useState<RecipeBody | null>(null);
  const [selectedStep, setSelectedStep] = useState<RecipeStep | null>(null);
  const [promptPreview, setPromptPreview] = useState("");
  const [documentId, setDocumentId] = useState<number | "">("");
  const [documents, setDocuments] = useState<{ id: number; title: string }[]>(
    [],
  );
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [rec, docs] = await Promise.all([
      api.listRecipes(),
      api.listDocuments(),
    ]);
    setBundled(rec.bundled);
    setRecipes(rec.recipes);
    setDocuments(docs.documents.map((d) => ({ id: d.id, title: d.title })));
    if (!documentId && docs.documents[0]) setDocumentId(docs.documents[0].id);
  }, [documentId]);

  useEffect(() => {
    if (!project) return;
    void load().catch((err) =>
      setError(err instanceof Error ? err.message : String(err)),
    );
  }, [project, load]);

  const openRecipe = async (id: string) => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.getBundledRecipe(id);
      setBody(res.recipe);
      setSelectedStep(res.recipe.steps?.[0] || null);
      setPromptPreview("");
    } catch (err) {
      const fromDb = recipes.find((r) => r.id === id);
      if (fromDb?.body) {
        setBody(fromDb.body);
        setSelectedStep(fromDb.body.steps?.[0] || null);
      } else if (fromDb) {
        const full = await api.getRecipe(fromDb.db_id);
        setBody(full.recipe.body || null);
        setSelectedStep(full.recipe.steps?.[0] || null);
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setBusy(false);
    }
  };

  const moveStep = (index: number, dir: -1 | 1) => {
    if (!body) return;
    const next = [...body.steps];
    const j = index + dir;
    if (j < 0 || j >= next.length) return;
    [next[index], next[j]] = [next[j], next[index]];
    const pipeline = next.map((s) => s.id);
    setBody({ ...body, steps: next, pipeline });
  };

  const updateStepStrategy = (stepId: string, strategy: string) => {
    if (!body) return;
    setBody({
      ...body,
      steps: body.steps.map((s) =>
        s.id === stepId ? { ...s, strategy } : s,
      ),
    });
  };

  if (!project) {
    return (
      <section className="panel">
        <h1>Рецепты извлечения</h1>
        <p className="muted">Откройте проект.</p>
      </section>
    );
  }

  return (
    <div className="stack">
      <section className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <h1>Редактор рецепта</h1>
            <p className="muted">
              Шаги, стратегия, превью промпта, прогон шага на статье.
            </p>
          </div>
          <div className="row">
            <button
              type="button"
              className="btn secondary"
              disabled={busy}
              onClick={() =>
                void (async () => {
                  setBusy(true);
                  try {
                    const res = await api.generateRecipe({
                      document_id: documentId || undefined,
                      intelligence_level: "medium",
                      save: true,
                    });
                    setMessage("Рецепт сгенерирован из схемы и эталона");
                    await load();
                    const gen = res.generated;
                    setBody(gen);
                    setSelectedStep(gen.steps?.[0] || null);
                  } catch (err) {
                    setError(err instanceof Error ? err.message : String(err));
                  } finally {
                    setBusy(false);
                  }
                })()
              }
            >
              Сгенерировать из схемы+эталона
            </button>
            <button
              type="button"
              className="btn"
              disabled={busy || !body}
              onClick={() =>
                void (async () => {
                  if (!body) return;
                  setBusy(true);
                  try {
                    await api.saveRecipe(body as unknown as Record<string, unknown>);
                    setMessage("Рецепт сохранён в проект");
                    await load();
                  } catch (err) {
                    setError(err instanceof Error ? err.message : String(err));
                  } finally {
                    setBusy(false);
                  }
                })()
              }
            >
              Сохранить
            </button>
          </div>
        </div>
        {error ? <p className="error">{error}</p> : null}
        {message ? <p className="success">{message}</p> : null}
      </section>

      <div className="annotate-layout">
        <section className="panel">
          <h2>Доступные рецепты</h2>
          <h3>Шаблоны</h3>
          <ul className="list compact">
            {bundled.map((b) => (
              <li key={b.id}>
                <button
                  type="button"
                  className="btn secondary"
                  onClick={() => void openRecipe(b.id)}
                >
                  {b.name}
                </button>
              </li>
            ))}
          </ul>
          <h3>В проекте</h3>
          <ul className="list compact">
            {recipes.map((r) => (
              <li key={r.db_id}>
                <button
                  type="button"
                  className="btn secondary"
                  onClick={() => void openRecipe(r.id)}
                >
                  {r.name} {r.is_active ? "· активный" : ""}
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section className="panel">
          <h2>Шаги {body ? `«${body.name}»` : ""}</h2>
          {!body ? (
            <p className="muted">Выберите рецепт слева.</p>
          ) : (
            <ul className="list step-editor">
              {body.steps.map((s, i) => (
                <li key={s.id} className={selectedStep?.id === s.id ? "selected" : ""}>
                  <button
                    type="button"
                    className="block-item"
                    onClick={() => setSelectedStep(s)}
                  >
                    <strong>
                      {i + 1}. {s.name}
                    </strong>
                    <div className="muted">{s.id}</div>
                  </button>
                  <div className="row">
                    <label>
                      Стратегия
                      <select
                        value={s.strategy || ""}
                        onChange={(e) =>
                          updateStepStrategy(s.id, e.target.value)
                        }
                      >
                        <option value="iterative">iterative</option>
                        <option value="entities_first">entities_first</option>
                        <option value="one_shot">one_shot</option>
                      </select>
                    </label>
                    <button
                      type="button"
                      className="btn secondary"
                      onClick={() => moveStep(i, -1)}
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      className="btn secondary"
                      onClick={() => moveStep(i, 1)}
                    >
                      ↓
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="panel">
          <h2>Превью / прогон</h2>
          <label>
            Документ для превью
            <select
              value={documentId}
              onChange={(e) =>
                setDocumentId(e.target.value ? Number(e.target.value) : "")
              }
            >
              <option value="">—</option>
              {documents.map((d) => (
                <option key={d.id} value={d.id}>
                  #{d.id} {d.title}
                </option>
              ))}
            </select>
          </label>
          <div className="row">
            <button
              type="button"
              className="btn secondary"
              disabled={busy || !body || !selectedStep || !documentId}
              onClick={() =>
                void (async () => {
                  if (!body || !selectedStep || !documentId) return;
                  setBusy(true);
                  try {
                    const res = await api.previewPrompt({
                      document_id: Number(documentId),
                      recipe_id: body.id,
                      step_id: selectedStep.id,
                    });
                    setPromptPreview(res.preview.prompt);
                  } catch (err) {
                    setError(err instanceof Error ? err.message : String(err));
                  } finally {
                    setBusy(false);
                  }
                })()
              }
            >
              Превью промпта
            </button>
            {documentId ? (
              <Link className="btn" to={`/papers/${documentId}`}>
                Открыть статью
              </Link>
            ) : null}
          </div>
          {selectedStep ? (
            <div className="step-detail">
              <p className="muted">
                Шаблон: {selectedStep.prompt_template || "—"}
                {selectedStep.strategy ? ` · ${selectedStep.strategy}` : ""}
              </p>
              {selectedStep.instructions || selectedStep.description ? (
                <p>
                  <strong>Инструкции:</strong>{" "}
                  {selectedStep.instructions || selectedStep.description}
                </p>
              ) : null}
              {selectedStep.targets?.entities?.length ? (
                <p>
                  <strong>Сущности:</strong>{" "}
                  {selectedStep.targets.entities.join(", ")}
                </p>
              ) : null}
              {selectedStep.targets?.relations?.length ? (
                <p>
                  <strong>Связи:</strong>{" "}
                  {selectedStep.targets.relations.join(", ")}
                </p>
              ) : null}
              {selectedStep.section_include?.length ? (
                <p className="muted">
                  Секции: {selectedStep.section_include.join(", ")}
                  {selectedStep.section_exclude?.length
                    ? ` (исключено: ${selectedStep.section_exclude.join(", ")})`
                    : ""}
                </p>
              ) : null}
            </div>
          ) : null}
          {promptPreview ? (
            <pre className="prompt-preview">{promptPreview}</pre>
          ) : null}
        </section>
      </div>
    </div>
  );
}
