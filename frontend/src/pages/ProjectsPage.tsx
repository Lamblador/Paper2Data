import { useEffect, useState } from "react";
import { api, type RecentProject } from "../api/client";
import { useProject } from "../store/project";

export default function ProjectsPage() {
  const { project, setProject, refresh } = useProject();
  const [recent, setRecent] = useState<RecentProject[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [manualPath, setManualPath] = useState("");

  const loadRecent = async () => {
    try {
      const data = await api.recentProjects();
      setRecent(data.projects);
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    void loadRecent();
  }, [project]);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await loadRecent();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <section className="panel">
        <h1>Проекты</h1>
        <p className="muted">
          Проект — это папка с <code>project.yaml</code>, базой{" "}
          <code>paper2data.sqlite</code>, каталогами <code>papers/</code>,{" "}
          <code>cache/</code> и <code>exports/</code>.
        </p>
        <div className="row" style={{ marginTop: "1rem" }}>
          <button
            className="btn"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                const res = await api.createWithDialog();
                if (!res.cancelled && res.project) setProject(res.project);
              })
            }
          >
            Создать проект…
          </button>
          <button
            className="btn secondary"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                const res = await api.openWithDialog();
                if (!res.cancelled && res.project) setProject(res.project);
              })
            }
          >
            Открыть проект…
          </button>
          {project && (
            <button
              className="btn secondary"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  await api.closeProject();
                  setProject(null);
                  await refresh();
                })
              }
            >
              Закрыть
            </button>
          )}
        </div>
        {error && <p className="error">{error}</p>}
      </section>

      {project && (
        <section className="panel">
          <h2>Текущий проект</h2>
          <div className="stack">
            <div>
              <strong>{project.name}</strong>{" "}
              <span className="badge">
                {project.db_ready ? "БД готова" : "БД не готова"}
              </span>
            </div>
            <div className="path">{project.path}</div>
            <div className="muted">
              LLM-профилей: {project.llm_profiles_count}
            </div>
          </div>
        </section>
      )}

      <section className="panel">
        <h2>Открыть по пути</h2>
        <div className="row">
          <input
            placeholder="D:\\data\\my-project"
            value={manualPath}
            onChange={(e) => setManualPath(e.target.value)}
          />
          <button
            className="btn secondary"
            disabled={busy || !manualPath.trim()}
            onClick={() =>
              void run(async () => {
                const res = await api.openPath(manualPath.trim());
                setProject(res.project);
              })
            }
          >
            Открыть
          </button>
          <button
            className="btn secondary"
            disabled={busy || !manualPath.trim()}
            onClick={() =>
              void run(async () => {
                const res = await api.createPath(manualPath.trim());
                setProject(res.project);
              })
            }
          >
            Создать здесь
          </button>
        </div>
      </section>

      <section className="panel">
        <h2>Недавние</h2>
        {recent.length === 0 ? (
          <p className="muted">Пока нет недавних проектов.</p>
        ) : (
          <ul className="list">
            {recent.map((item) => (
              <li key={item.path}>
                <div>
                  <div>
                    <strong>{item.name}</strong>{" "}
                    {item.exists !== "true" && (
                      <span className="badge warn">не найден</span>
                    )}
                  </div>
                  <div className="path muted">{item.path}</div>
                </div>
                <button
                  className="btn secondary"
                  disabled={busy || item.exists !== "true"}
                  onClick={() =>
                    void run(async () => {
                      const res = await api.openPath(item.path);
                      setProject(res.project);
                    })
                  }
                >
                  Открыть
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
