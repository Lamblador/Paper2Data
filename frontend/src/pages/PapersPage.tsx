import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, type PaperBrief } from "../api/client";
import { useProject } from "../store/project";

const STATUS_RU: Record<string, string> = {
  indexed: "проиндексирована",
  parsing: "разбор…",
  parsed: "разобрана",
  error: "ошибка",
  new: "новая",
  annotated: "размечена",
  gold: "эталон",
  extracted: "извлечена",
};

export default function PapersPage() {
  const { project } = useProject();
  const [papers, setPapers] = useState<PaperBrief[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ingestingId, setIngestingId] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    if (!project) {
      setPapers([]);
      return;
    }
    setError(null);
    try {
      const data = await api.listPapers();
      setPapers(data.papers);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [project]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onIndex = async () => {
    setBusy(true);
    setError(null);
    try {
      const data = await api.indexPapers();
      setPapers(data.papers);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onUpload = async (file: File | null) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      await api.uploadPaper(file);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onIngest = async (id: number) => {
    setIngestingId(id);
    setError(null);
    try {
      await api.ingestPaper(id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      await refresh();
    } finally {
      setIngestingId(null);
    }
  };

  if (!project) {
    return (
      <section className="panel">
        <h1>Статьи</h1>
        <p className="muted">Откройте проект, чтобы работать со статьями.</p>
      </section>
    );
  }

  return (
    <section className="panel">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1>Статьи</h1>
        <div className="row">
          <button
            type="button"
            className="btn secondary"
            disabled={busy}
            onClick={() => void onIndex()}
          >
            Индексировать papers/
          </button>
          <button
            type="button"
            className="btn"
            disabled={busy}
            onClick={() => fileRef.current?.click()}
          >
            Загрузить PDF
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="application/pdf,.pdf"
            hidden
            onChange={(e) => void onUpload(e.target.files?.[0] ?? null)}
          />
        </div>
      </div>

      <p className="muted">
        Каталог: <span className="path">{project.papers_dir}</span>
      </p>

      {error ? <p className="error">{error}</p> : null}

      {papers.length === 0 ? (
        <p className="muted">
          Пока нет статей. Положите PDF в papers/ и нажмите «Индексировать», либо
          загрузите файл.
        </p>
      ) : (
        <ul className="list">
          {papers.map((p) => (
            <li key={p.id}>
              <div>
                <div>
                  <strong>{p.title || "Без названия"}</strong>{" "}
                  <span className={`badge ${p.status === "error" ? "danger" : ""}`}>
                    {STATUS_RU[p.status] || p.status}
                  </span>
                </div>
                <div className="muted">
                  {p.main_file?.filename || p.source_path || "—"}
                  {p.doi ? ` · DOI ${p.doi}` : ""}
                  {p.sections_count ? ` · секций: ${p.sections_count}` : ""}
                  {p.esi_hints_count
                    ? ` · ESI-подсказок: ${p.esi_hints_count}`
                    : ""}
                </div>
                {p.error_message ? (
                  <div className="error">{p.error_message}</div>
                ) : null}
              </div>
              <div className="row">
                <button
                  type="button"
                  className="btn secondary"
                  disabled={ingestingId === p.id}
                  onClick={() => void onIngest(p.id)}
                >
                  {ingestingId === p.id ? "Разбор…" : "Разобрать"}
                </button>
                <Link className="btn" to={`/papers/${p.id}`}>
                  Открыть
                </Link>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
