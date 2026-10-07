import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  type FullExtractItem,
  type JobInfo,
  type LeaderboardRow,
  type LlmProfile,
  type PaperBrief,
  type RecipeInfo,
} from "../api/client";
import { armRunNotification, markRunBusy, notifyRunFinished } from "../lib/browserNotify";
import { useProject } from "../store/project";

type Tab = "work" | "batch" | "leaderboard" | "duplicates" | "export";
type PaperFilter = "all" | "unparsed" | "no_extract";

type CostEstimate = {
  tokenizer?: string;
  by_model?: {
    llm_profile_id: string;
    name: string;
    tokens_in: number;
    tokens_out: number;
    cost_usd: number;
  }[];
  totals?: { tokens_in: number; tokens_out: number; cost_usd: number; combinations: number };
  output_source?: string;
  avg_output_tokens_per_document?: number;
};

type DupSuggestion = {
  suggested_canonical_id: string;
  score: number;
  reasons: string[];
  nodes: {
    id: number;
    document_id: number;
    label: string;
    canonical_id: string | null;
  }[];
};

function isParsed(p: PaperBrief): boolean {
  return (p.sections_count ?? 0) > 0 && p.status !== "indexed" && p.status !== "error";
}

function stageLabel(stage: string): string {
  if (stage === "pending") return "ожидание";
  if (stage === "ingest") return "разбор";
  if (stage === "done") return "готово";
  if (stage === "failed") return "ошибка";
  if (stage.endsWith(":entities")) return "сущности";
  if (stage.endsWith(":relations")) return "связи";
  if (stage.includes("abbreviation") || stage.includes("resolve")) return "словарь";
  return stage;
}

function getFullExtractItems(job: JobInfo): FullExtractItem[] {
  const fromResult = (job.result as { items?: FullExtractItem[] } | undefined)?.items;
  if (Array.isArray(fromResult) && fromResult.length) return fromResult;
  const fromPayload = (job.payload as { items?: FullExtractItem[] } | undefined)?.items;
  return Array.isArray(fromPayload) ? fromPayload : [];
}

function paperTitle(papers: PaperBrief[], documentId: number): string {
  const p = papers.find((x) => x.id === documentId);
  return p ? p.title || p.source_stem || `#${documentId}` : `#${documentId}`;
}

function canCancel(job: JobInfo): boolean {
  return job.status === "pending" || job.status === "queued" || job.status === "running";
}

function announceJob(job: JobInfo): void {
  const kind =
    job.kind === "full_extract" ? "Рабочий прогон" : job.kind === "batch_extract" ? "Бенчмарк" : "Прогон";
  if (job.status === "completed") {
    notifyRunFinished(`${kind} #${job.id} завершён`, job.message);
    return;
  }
  if (job.status === "failed") {
    notifyRunFinished(`${kind} #${job.id} завершился с ошибкой`, job.error_message || job.message);
    return;
  }
  if (job.status === "cancelled") {
    notifyRunFinished(`${kind} #${job.id} отменён`, job.message);
  }
}

export default function BatchPage() {
  const { project } = useProject();
  const [tab, setTab] = useState<Tab>("work");
  const [papers, setPapers] = useState<PaperBrief[]>([]);
  const [profiles, setProfiles] = useState<LlmProfile[]>([]);
  const [recipes, setRecipes] = useState<RecipeInfo[]>([]);
  const [selectedDocs, setSelectedDocs] = useState<number[]>([]);
  const [selectedProfiles, setSelectedProfiles] = useState<string[]>([]);
  const [workProfileId, setWorkProfileId] = useState<string>("");
  const [recipeId, setRecipeId] = useState<string>("");
  const [strategy, setStrategy] = useState<string>("");
  const [ingestMissing, setIngestMissing] = useState(true);
  const [reparse, setReparse] = useState(false);
  const [paperFilter, setPaperFilter] = useState<PaperFilter>("all");
  const [estimate, setEstimate] = useState<CostEstimate | null>(null);
  const [job, setJob] = useState<JobInfo | null>(null);
  const [batchJobs, setBatchJobs] = useState<JobInfo[]>([]);
  const [workJobs, setWorkJobs] = useState<JobInfo[]>([]);
  const [leaderboard, setLeaderboard] = useState<LeaderboardRow[]>([]);
  const [duplicates, setDuplicates] = useState<DupSuggestion[]>([]);
  const [exportResult, setExportResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  const goldDocs = useMemo(() => papers.filter((p) => p.has_gold === true), [papers]);

  const filteredWorkPapers = useMemo(() => {
    if (paperFilter === "unparsed") {
      return papers.filter((p) => !isParsed(p));
    }
    if (paperFilter === "no_extract") {
      return papers.filter((p) => p.status !== "extracted");
    }
    return papers;
  }, [papers, paperFilter]);

  const unparsedSelected = useMemo(
    () =>
      selectedDocs.filter((id) => {
        const p = papers.find((x) => x.id === id);
        return p ? !isParsed(p) : false;
      }),
    [selectedDocs, papers],
  );

  const refresh = useCallback(async () => {
    if (!project) return;
    setError(null);
    try {
      const [papersRes, profilesRes, recipesRes, batchJobsRes, workJobsRes] = await Promise.all([
        api.listPapers(),
        api.listProfiles(),
        api.listRecipes(),
        api.listEvalJobs("batch_extract"),
        api.listEvalJobs("full_extract"),
      ]);
      setPapers(papersRes.papers);
      setProfiles(profilesRes.profiles);
      setRecipes(recipesRes.recipes);
      setBatchJobs(batchJobsRes.jobs);
      setWorkJobs(workJobsRes.jobs);
      if (!recipeId && recipesRes.recipes[0]) {
        setRecipeId(recipesRes.recipes[0].id);
      }
      if (!workProfileId && profilesRes.profiles[0]) {
        setWorkProfileId(profilesRes.profiles[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [project, recipeId, workProfileId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    return () => {
      esRef.current?.close();
    };
  }, []);

  const toggleDoc = (id: number) => {
    setSelectedDocs((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  const toggleProfile = (id: string) => {
    setSelectedProfiles((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  const selectGoldDocs = () => {
    setSelectedDocs(goldDocs.map((p) => p.id));
  };

  const onEstimate = async (profileIds: string[]) => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const res = await api.estimateBatch({
        document_ids: selectedDocs,
        llm_profile_ids: profileIds,
        recipe_id: recipeId || null,
      });
      setEstimate(res.estimate as CostEstimate);
      setMessage("Оценка стоимости готова.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const watchJob = (jobId: number) => {
    esRef.current?.close();
    const es = api.jobEvents(jobId);
    esRef.current = es;
    let announced = false;
    markRunBusy("Прогон выполняется…");
    es.onmessage = (ev) => {
      if (esRef.current !== es || announced) return;
      try {
        const data = JSON.parse(ev.data) as JobInfo;
        setJob(data);
        if (data.status === "running" || data.status === "queued") {
          markRunBusy(data.kind === "batch_extract" ? "Бенчмарк выполняется…" : "Прогон выполняется…");
        }
        if (["completed", "failed", "cancelled"].includes(data.status)) {
          es.close();
          if (!announced) {
            announced = true;
            announceJob(data);
          }
          void refresh();
          if (data.kind === "batch_extract") void loadLeaderboard();
        }
      } catch {
        /* ignore */
      }
    };
    es.onerror = () => {
      /* poll fallback handled by keepalive; close on hard fail */
    };
  };

  const onCancelJob = async (jobId: number) => {
    setError(null);
    try {
      const res = await api.cancelJob(jobId);
      setJob(res.job);
      setMessage(
        `Задача #${jobId} отменена. Статья, которая уже считается, дойдёт до конца шага, остальные не начнутся.`,
      );
      void refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const onStartBatch = async () => {
    if (!estimate) {
      setError("Сначала выполните оценку стоимости");
      return;
    }
    armRunNotification();
    setBusy(true);
    setError(null);
    try {
      const res = await api.startBatch({
        document_ids: selectedDocs,
        llm_profile_ids: selectedProfiles,
        recipe_id: recipeId || null,
        strategy: strategy || null,
        evaluate: true,
      });
      setJob(res.job);
      setMessage(`Задача #${res.job.id} запущена`);
      watchJob(res.job.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onStartFullExtract = async () => {
    if (!workProfileId) {
      setError("Выберите LLM-профиль");
      return;
    }
    if (!selectedDocs.length) {
      setError("Выберите хотя бы одну статью");
      return;
    }
    if (unparsedSelected.length && !ingestMissing && !reparse) {
      setError(
        `Среди выбранных ${unparsedSelected.length} без разбора текста. Включите «Разобрать текст, если не разобран» или уберите их.`,
      );
      return;
    }
    armRunNotification();
    setBusy(true);
    setError(null);
    try {
      if (unparsedSelected.length) {
        setMessage(
          `Внимание: ${unparsedSelected.length} статей ещё без разбора — оценка стоимости может быть неполной.`,
        );
      }
      const res = await api.startFullExtract({
        document_ids: selectedDocs,
        llm_profile_id: workProfileId,
        recipe_id: recipeId || null,
        strategy: strategy || null,
        ingest_missing: ingestMissing,
        reparse,
      });
      setJob(res.job);
      setMessage(`Рабочий прогон #${res.job.id} запущен`);
      watchJob(res.job.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const loadLeaderboard = async () => {
    try {
      const res = await api.leaderboard();
      setLeaderboard(res.leaderboard);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const loadDuplicates = async () => {
    setBusy(true);
    try {
      const res = await api.listDuplicates("Compound");
      setDuplicates(res.suggestions as DupSuggestion[]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const applyCanonical = async (s: DupSuggestion) => {
    setBusy(true);
    try {
      await api.applyCanonical(
        s.nodes.map((n) => n.id),
        s.suggested_canonical_id,
      );
      setMessage(`Назначен canonical_id ${s.suggested_canonical_id}`);
      await loadDuplicates();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onExport = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.exportCorpus({
        document_ids: selectedDocs.length ? selectedDocs : null,
        include_sdf: true,
      });
      setExportResult(res.export);
      setMessage("Экспорт записан в exports/");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (tab === "leaderboard") void loadLeaderboard();
    if (tab === "duplicates") void loadDuplicates();
  }, [tab]);

  const openJob = (j: JobInfo) => {
    setJob(j);
    if (j.status === "running" || j.status === "queued") {
      armRunNotification();
      watchJob(j.id);
    }
  };

  const fullExtractItems =
    job && job.kind === "full_extract" ? getFullExtractItems(job) : [];

  if (!project) {
    return (
      <section className="panel">
        <h1>Пакетные прогоны</h1>
        <p className="muted">Сначала откройте или создайте проект.</p>
      </section>
    );
  }

  return (
    <div className="stack">
      <section className="panel">
        <h1>Пакетные прогоны и лидерборд</h1>
        <p className="muted">
          Рабочий полный цикл (разбор → извлечение) или бенчмарк на статьях с эталоном.
        </p>
        <div className="row gap">
          {(
            [
              ["work", "Рабочий прогон"],
              ["batch", "Бенчмарк"],
              ["leaderboard", "Лидерборд"],
              ["duplicates", "Дубли"],
              ["export", "Экспорт"],
            ] as [Tab, string][]
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={tab === id ? "btn" : "btn secondary"}
              onClick={() => {
                setTab(id);
                setEstimate(null);
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </section>

      {error && <div className="banner error">{error}</div>}
      {message && <div className="banner ok">{message}</div>}

      {tab === "work" && (
        <>
          <section className="panel">
            <h2>Документы</h2>
            <div className="row gap">
              {(
                [
                  ["all", "Все"],
                  ["unparsed", "Не разобранные"],
                  ["no_extract", "Без извлечения"],
                ] as [PaperFilter, string][]
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  className={paperFilter === id ? "btn" : "btn secondary"}
                  onClick={() => setPaperFilter(id)}
                >
                  {label}
                </button>
              ))}
              <button
                type="button"
                className="btn secondary"
                onClick={() => setSelectedDocs(filteredWorkPapers.map((p) => p.id))}
              >
                Выбрать видимые
              </button>
              <button type="button" className="btn secondary" onClick={() => setSelectedDocs([])}>
                Сбросить
              </button>
            </div>
            <div className="check-grid">
              {filteredWorkPapers.map((p) => (
                <label key={p.id} className="check-item">
                  <input
                    type="checkbox"
                    checked={selectedDocs.includes(p.id)}
                    onChange={() => toggleDoc(p.id)}
                  />
                  <span>
                    #{p.id} {p.title || p.source_stem}{" "}
                    <span className="muted">
                      ({p.status}
                      {isParsed(p)
                        ? `, секций: ${p.sections_count}`
                        : ", текст не разобран"}
                      )
                    </span>
                  </span>
                </label>
              ))}
            </div>
            {!filteredWorkPapers.length && (
              <p className="muted">Нет статей по выбранному фильтру.</p>
            )}
          </section>

          <section className="panel">
            <h2>Параметры прогона</h2>
            <div className="check-grid">
              {profiles.map((p) => (
                <label key={p.id} className="check-item">
                  <input
                    type="radio"
                    name="work-profile"
                    checked={workProfileId === p.id}
                    onChange={() => setWorkProfileId(p.id)}
                  />
                  <span>
                    {p.name}{" "}
                    <span className="muted">
                      ({p.model}, ${p.price_in_per_1m}/{p.price_out_per_1m} за 1M)
                    </span>
                  </span>
                </label>
              ))}
            </div>
            <div className="row" style={{ marginTop: "1rem", alignItems: "end" }}>
              <label style={{ flex: 1, minWidth: "12rem" }}>
                Рецепт
                <select value={recipeId} onChange={(e) => setRecipeId(e.target.value)}>
                  <option value="">Активный</option>
                  {recipes.map((r) => (
                    <option key={r.db_id} value={r.id}>
                      {r.name} ({r.id})
                    </option>
                  ))}
                </select>
              </label>
              <label style={{ flex: 1, minWidth: "12rem" }}>
                Стратегия (опц.)
                <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
                  <option value="">По умолчанию</option>
                  <option value="entities_first">entities_first</option>
                  <option value="one_shot">one_shot</option>
                  <option value="iterative">iterative</option>
                </select>
              </label>
            </div>
            <div className="check-grid" style={{ marginTop: "1rem" }}>
              <label className="check-item">
                <input
                  type="checkbox"
                  checked={ingestMissing}
                  onChange={(e) => setIngestMissing(e.target.checked)}
                />
                <span>Разобрать текст, если не разобран</span>
              </label>
              <label className="check-item">
                <input
                  type="checkbox"
                  checked={reparse}
                  onChange={(e) => setReparse(e.target.checked)}
                />
                <span>Переразобрать</span>
              </label>
            </div>
            {unparsedSelected.length > 0 && (
              <p className="muted" style={{ marginTop: "0.75rem" }}>
                Среди выбранных {unparsedSelected.length} без разбора текста — оценка стоимости
                будет неполной, пока статьи не разобраны.
              </p>
            )}
            <div className="row gap" style={{ marginTop: "1rem" }}>
              <button
                type="button"
                className="btn secondary"
                disabled={busy || !selectedDocs.length || !workProfileId}
                onClick={() => void onEstimate([workProfileId])}
              >
                Оценить стоимость (опц.)
              </button>
              <button
                type="button"
                className="btn"
                disabled={busy || !selectedDocs.length || !workProfileId}
                onClick={() => void onStartFullExtract()}
              >
                Запустить рабочий прогон
              </button>
            </div>
          </section>

          {estimate && (
            <EstimatePanel estimate={estimate} />
          )}

          {job && job.kind === "full_extract" && (
            <section className="panel">
              <h2>Текущая задача #{job.id}</h2>
              <p>
                Статус: <strong>{job.status}</strong> — {job.message}
              </p>
              <div className="progress-bar">
                <div style={{ width: `${Math.round((job.progress || 0) * 100)}%` }} />
              </div>
              {job.error_message && <p className="error-text">{job.error_message}</p>}
              {(job.status === "running" || job.status === "queued") && (
                <p className="muted">Если свернуть вкладку, браузер сообщит об окончании прогона.</p>
              )}
              {canCancel(job) && (
                <>
                  <button type="button" className="btn danger" onClick={() => void onCancelJob(job.id)}>
                    Отменить прогон
                  </button>
                  <p className="muted">Текущая статья дойдёт до конца шага, остальные не начнутся.</p>
                </>
              )}
              {job.status === "failed" && (
                <button
                  type="button"
                  className="btn secondary"
                  onClick={() => {
                    armRunNotification();
                    void api.resumeJob(job.id).then((r) => {
                      setJob(r.job);
                      watchJob(r.job.id);
                    });
                  }}
                >
                  Возобновить
                </button>
              )}
              {fullExtractItems.length > 0 && (
                <FullExtractProgressTable items={fullExtractItems} papers={papers} />
              )}
            </section>
          )}

          {workJobs.length > 0 && (
            <section className="panel">
              <h2>Недавние задачи</h2>
              <ul className="plain-list">
                {workJobs.slice(0, 8).map((j) => (
                  <li key={j.id}>
                    #{j.id} {j.status} — {(j.progress * 100).toFixed(0)}% — {j.message}{" "}
                    <button type="button" className="linkish" onClick={() => openJob(j)}>
                      открыть
                    </button>
                    {canCancel(j) && (
                      <button type="button" className="linkish" onClick={() => void onCancelJob(j.id)}>
                        отменить
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}

      {tab === "batch" && (
        <>
          <section className="panel">
            <h2>Документы с эталоном</h2>
            <div className="row gap">
              <button type="button" className="btn secondary" onClick={selectGoldDocs}>
                Выбрать с эталоном
              </button>
              <button type="button" className="btn secondary" onClick={() => setSelectedDocs([])}>
                Сбросить
              </button>
            </div>
            <div className="check-grid">
              {goldDocs.map((p) => (
                <label key={p.id} className="check-item">
                  <input
                    type="checkbox"
                    checked={selectedDocs.includes(p.id)}
                    onChange={() => toggleDoc(p.id)}
                  />
                  <span>
                    #{p.id} {p.title || p.source_stem}{" "}
                    <span className="muted">({p.status})</span>
                  </span>
                </label>
              ))}
            </div>
            {!goldDocs.length && (
              <p className="muted">Нет статей с эталоном (GoldSnapshot).</p>
            )}
          </section>

          <section className="panel">
            <h2>LLM-профили</h2>
            <div className="check-grid">
              {profiles.map((p) => (
                <label key={p.id} className="check-item">
                  <input
                    type="checkbox"
                    checked={selectedProfiles.includes(p.id)}
                    onChange={() => toggleProfile(p.id)}
                  />
                  <span>
                    {p.name}{" "}
                    <span className="muted">
                      ({p.model}, ${p.price_in_per_1m}/{p.price_out_per_1m} за 1M)
                    </span>
                  </span>
                </label>
              ))}
            </div>
            <div className="row" style={{ marginTop: "1rem", alignItems: "end" }}>
              <label style={{ flex: 1, minWidth: "12rem" }}>
                Рецепт
                <select value={recipeId} onChange={(e) => setRecipeId(e.target.value)}>
                  <option value="">Активный</option>
                  {recipes.map((r) => (
                    <option key={r.db_id} value={r.id}>
                      {r.name} ({r.id})
                    </option>
                  ))}
                </select>
              </label>
              <label style={{ flex: 1, minWidth: "12rem" }}>
                Стратегия (опц.)
                <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
                  <option value="">По умолчанию</option>
                  <option value="entities_first">entities_first</option>
                  <option value="one_shot">one_shot</option>
                  <option value="iterative">iterative</option>
                </select>
              </label>
            </div>
            <div className="row gap" style={{ marginTop: "1rem" }}>
              <button
                type="button"
                className="btn"
                disabled={busy || !selectedDocs.length || !selectedProfiles.length}
                onClick={() => void onEstimate(selectedProfiles)}
              >
                Оценить стоимость
              </button>
              <button
                type="button"
                className="btn secondary"
                disabled={busy || !estimate}
                onClick={() => void onStartBatch()}
              >
                Запустить бенчмарк
              </button>
            </div>
          </section>

          {estimate && <EstimatePanel estimate={estimate} />}

          {job && job.kind === "batch_extract" && (
            <section className="panel">
              <h2>Текущая задача #{job.id}</h2>
              <p>
                Статус: <strong>{job.status}</strong> — {job.message}
              </p>
              <div className="progress-bar">
                <div style={{ width: `${Math.round((job.progress || 0) * 100)}%` }} />
              </div>
              {job.error_message && <p className="error-text">{job.error_message}</p>}
              {(job.status === "running" || job.status === "queued") && (
                <p className="muted">Если свернуть вкладку, браузер сообщит об окончании прогона.</p>
              )}
              {canCancel(job) && (
                <>
                  <button type="button" className="btn danger" onClick={() => void onCancelJob(job.id)}>
                    Отменить прогон
                  </button>
                  <p className="muted">Текущая статья дойдёт до конца шага, остальные не начнутся.</p>
                </>
              )}
              {job.status === "failed" && (
                <button
                  type="button"
                  className="btn secondary"
                  onClick={() => {
                    armRunNotification();
                    void api.resumeJob(job.id).then((r) => {
                      setJob(r.job);
                      watchJob(r.job.id);
                    });
                  }}
                >
                  Возобновить
                </button>
              )}
            </section>
          )}

          {batchJobs.length > 0 && (
            <section className="panel">
              <h2>Недавние задачи</h2>
              <ul className="plain-list">
                {batchJobs.slice(0, 8).map((j) => (
                  <li key={j.id}>
                    #{j.id} {j.status} — {(j.progress * 100).toFixed(0)}% — {j.message}{" "}
                    <button type="button" className="linkish" onClick={() => openJob(j)}>
                      открыть
                    </button>
                    {canCancel(j) && (
                      <button type="button" className="linkish" onClick={() => void onCancelJob(j.id)}>
                        отменить
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}

      {tab === "leaderboard" && (
        <section className="panel">
          <h2>Лидерборд на эталонных статьях</h2>
          <button type="button" className="btn secondary" onClick={() => void loadLeaderboard()}>
            Обновить
          </button>
          <table className="data-table">
            <thead>
              <tr>
                <th>Модель</th>
                <th>Стратегия</th>
                <th>Док.</th>
                <th>F1</th>
                <th>P</th>
                <th>R</th>
                <th>Атрибуты</th>
                <th>Рёбра F1</th>
                <th>Цитаты</th>
                <th>Токены</th>
                <th>$</th>
              </tr>
            </thead>
            <tbody>
              {leaderboard.map((row) => (
                <tr key={`${row.llm_profile_id}:${row.strategy || ""}`}>
                  <td>
                    {row.name}
                    <div className="muted">{row.model}</div>
                  </td>
                  <td>{row.strategy || "—"}</td>
                  <td>{row.n_docs}</td>
                  <td>{row.avg_f1.toFixed(3)}</td>
                  <td>{row.avg_precision.toFixed(3)}</td>
                  <td>{row.avg_recall.toFixed(3)}</td>
                  <td>
                    {row.avg_attribute_accuracy != null
                      ? row.avg_attribute_accuracy.toFixed(3)
                      : "—"}
                  </td>
                  <td>{row.avg_edge_f1 != null ? row.avg_edge_f1.toFixed(3) : "—"}</td>
                  <td>{row.avg_verified_quote_rate.toFixed(3)}</td>
                  <td>
                    {row.tokens_in}/{row.tokens_out}
                  </td>
                  <td>{row.cost_usd.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!leaderboard.length && (
            <p className="muted">Пока нет оценок — запустите бенчмарк на документах с эталоном.</p>
          )}
        </section>
      )}

      {tab === "duplicates" && (
        <section className="panel">
          <h2>Дубли Compounds между статьями</h2>
          <button
            type="button"
            className="btn secondary"
            disabled={busy}
            onClick={() => void loadDuplicates()}
          >
            Найти
          </button>
          {duplicates.map((s, i) => (
            <div key={i} className="dup-card">
              <div>
                <strong>{s.suggested_canonical_id}</strong> — score {s.score.toFixed(2)} (
                {s.reasons.join(", ")})
              </div>
              <ul>
                {s.nodes.map((n) => (
                  <li key={n.id}>
                    doc#{n.document_id} node#{n.id} «{n.label}»{" "}
                    {n.canonical_id ? `(уже ${n.canonical_id})` : ""}
                  </li>
                ))}
              </ul>
              <button type="button" className="btn" onClick={() => void applyCanonical(s)}>
                Назначить canonical_id
              </button>
            </div>
          ))}
          {!duplicates.length && <p className="muted">Совпадений не найдено.</p>}
        </section>
      )}

      {tab === "export" && (
        <section className="panel">
          <h2>Полный экспорт</h2>
          <p className="muted">
            CSV/XLSX по типам, JSON графа, GraphML; SDF — если установлен RDKit.
            {selectedDocs.length
              ? ` Выбрано документов: ${selectedDocs.length}.`
              : " Без выбора — весь корпус."}
          </p>
          <button type="button" className="btn" disabled={busy} onClick={() => void onExport()}>
            Экспортировать
          </button>
          {exportResult && (
            <pre className="code-block">{JSON.stringify(exportResult, null, 2)}</pre>
          )}
        </section>
      )}
    </div>
  );
}

function EstimatePanel({ estimate }: { estimate: CostEstimate }) {
  return (
    <section className="panel">
      <h2>Оценка до запуска</h2>
      <p className="muted">
        Токенизатор: {estimate.tokenizer}; выход: {estimate.output_source}; ср. out/док:{" "}
        {estimate.avg_output_tokens_per_document}
      </p>
      <table className="data-table">
        <thead>
          <tr>
            <th>Модель</th>
            <th>In</th>
            <th>Out</th>
            <th>Стоимость USD</th>
          </tr>
        </thead>
        <tbody>
          {(estimate.by_model || []).map((m) => (
            <tr key={m.llm_profile_id}>
              <td>{m.name}</td>
              <td>{m.tokens_in}</td>
              <td>{m.tokens_out}</td>
              <td>{m.cost_usd.toFixed(4)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {estimate.totals && (
        <p>
          Итого: in={estimate.totals.tokens_in}, out={estimate.totals.tokens_out}, $
          {estimate.totals.cost_usd.toFixed(4)} ({estimate.totals.combinations} комбинаций)
        </p>
      )}
    </section>
  );
}

function FullExtractProgressTable({
  items,
  papers,
}: {
  items: FullExtractItem[];
  papers: PaperBrief[];
}) {
  return (
    <table className="data-table" style={{ marginTop: "1rem" }}>
      <thead>
        <tr>
          <th>Статья</th>
          <th>Стадия</th>
          <th>Узлы</th>
          <th>Связи</th>
          <th>Токены</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.document_id}>
            <td>
              #{item.document_id} {paperTitle(papers, item.document_id)}
              {item.error ? <div className="error-text">{item.error}</div> : null}
              {item.stack_warning ? (
                <div className="error-text">{item.stack_warning}</div>
              ) : null}
            </td>
            <td>{stageLabel(item.stage)}</td>
            <td>{item.nodes ?? 0}</td>
            <td>{item.edges ?? 0}</td>
            <td>{item.tokens ?? "—"}</td>
            <td>
              <Link to={`/papers/${item.document_id}?tab=review`} className="linkish">
                Проверка
              </Link>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
