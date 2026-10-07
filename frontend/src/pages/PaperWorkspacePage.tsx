import { Link, useParams, useSearchParams } from "react-router-dom";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type EsiHint,
  type PaperBlock,
  type PaperStructure,
} from "../api/client";
import { useProject } from "../store/project";
import PdfViewer from "../components/PdfViewer";
import GraphAnnotatePane from "../components/GraphAnnotatePane";
import ReviewQueuePane from "../components/ReviewQueuePane";
import ExtractRunPane from "../components/ExtractRunPane";
import AssistantChatPanel from "../components/AssistantChatPanel";
import { SECTION_LABELS } from "../lib/labels";

const BLOCK_LABELS: Record<string, string> = {
  paragraph: "абзац",
  table: "таблица",
  table_cell: "ячейка",
  caption: "подпись",
};

type Tab = "structure" | "graph" | "extract" | "review" | "assistant";

const TAB_VALUES: Tab[] = ["structure", "graph", "extract", "review", "assistant"];

function isTab(value: string | null): value is Tab {
  return value != null && (TAB_VALUES as string[]).includes(value);
}

export default function PaperWorkspacePage() {
  const { paperId } = useParams();
  const [searchParams] = useSearchParams();
  const id = Number(paperId);
  const { project } = useProject();
  const [paper, setPaper] = useState<PaperStructure | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [selectedBlock, setSelectedBlock] = useState<PaperBlock | null>(null);
  const [quoteFocus, setQuoteFocus] = useState<{ text: string; key: number } | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("structure");
  const [esiUrl, setEsiUrl] = useState("");
  const [graphRefresh, setGraphRefresh] = useState(0);
  const [activeRunId, setActiveRunId] = useState<number | null>(null);
  const esiInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    if (!Number.isFinite(id)) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.getPaper(id);
      setPaper(data.paper);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const tab = searchParams.get("tab");
    if (isTab(tab)) setActiveTab(tab);
  }, [searchParams]);

  useEffect(() => {
    if (!paper || activeTab !== "review" || activeRunId != null) return;
    let cancelled = false;
    void api
      .listExtractionRuns(paper.id)
      .then((res) => {
        if (cancelled) return;
        const latest = res.runs[0];
        if (latest) setActiveRunId(latest.id);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [paper, activeTab, activeRunId]);

  const mainFile = useMemo(
    () => paper?.files.find((f) => f.role === "main") ?? paper?.files[0],
    [paper],
  );

  const fileUrl = useMemo(() => {
    if (!paper || !mainFile) return "";
    return api.paperFileUrl(paper.id, { fileId: mainFile.id });
  }, [paper, mainFile]);

  const blocksById = useMemo(() => {
    const map = new Map<number, PaperBlock>();
    for (const s of paper?.sections || []) {
      for (const b of s.blocks || []) map.set(b.id, b);
    }
    return map;
  }, [paper]);

  const onIngest = async () => {
    setBusy(true);
    setError(null);
    try {
      const data = await api.ingestPaper(id);
      setPaper(data.paper);
      setMessage("PDF разобран");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onAttachEsi = async (file: File | null) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const data = await api.attachEsi(id, file);
      setPaper(data.paper);
      setMessage("Файл ESI прикреплён: название совпадает со статьёй");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onSaveEsiLink = async () => {
    if (!esiUrl.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const data = await api.saveEsiLink(id, esiUrl.trim());
      setPaper(data.paper);
      setEsiUrl("");
      setMessage("Ссылка на ESI сохранена");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onDeleteEsiLink = async (url: string) => {
    setBusy(true);
    setError(null);
    try {
      const data = await api.deleteEsiLink(id, url);
      setPaper(data.paper);
      setMessage("Ссылка на ESI удалена");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onDeleteEsiFile = async (fileId: number) => {
    setBusy(true);
    setError(null);
    try {
      const data = await api.deleteEsiFile(id, fileId);
      setPaper(data.paper);
      setMessage("Файл ESI удалён");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (!project) {
    return (
      <section className="panel">
        <p className="muted">Откройте проект.</p>
      </section>
    );
  }

  if (loading) {
    return (
      <section className="panel">
        <p className="muted">Загрузка статьи…</p>
      </section>
    );
  }

  if (!paper) {
    return (
      <section className="panel">
        <p className="error">{error || "Статья не найдена"}</p>
        <Link to="/papers">← К списку</Link>
      </section>
    );
  }

  return (
    <div className="paper-workspace">
      <div className="paper-workspace-header row">
        <div>
          <Link to="/papers" className="muted">
            ← Статьи
          </Link>
          <h1>{paper.title || "Без названия"}</h1>
          <div className="row">
            <span className="badge">{statusLabel(paper.status)}</span>
            {paper.doi ? <span className="muted">DOI: {paper.doi}</span> : null}
          </div>
        </div>
        <div className="row">
          <button
            type="button"
            className="btn"
            disabled={busy}
            onClick={() => void onIngest()}
          >
            {busy ? "Разбор…" : "Разобрать PDF"}
          </button>
        </div>
      </div>

      {error ? <p className="error">{error}</p> : null}
      {message ? <p className="success">{message}</p> : null}
      {paper.error_message ? (
        <p className="error">Ошибка разбора: {paper.error_message}</p>
      ) : null}

      <EsiCard
        hints={paper.esi_hints || []}
        files={(paper.files || []).filter((f) => f.role === "esi")}
        esiUrl={esiUrl}
        setEsiUrl={setEsiUrl}
        onSaveLink={() => void onSaveEsiLink()}
        onDeleteLink={(url) => void onDeleteEsiLink(url)}
        onDeleteFile={(fileId) => void onDeleteEsiFile(fileId)}
        onPickFile={() => esiInput.current?.click()}
        busy={busy}
      />
      <input
        ref={esiInput}
        type="file"
        accept="application/pdf,.pdf"
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0] ?? null;
          e.target.value = "";
          void onAttachEsi(file);
        }}
      />

      <div className="paper-workspace-body">
        <div className="panel pdf-panel">
          {fileUrl ? (
            <PdfViewer
              fileUrl={fileUrl}
              highlightBlock={selectedBlock}
              highlightQuote={quoteFocus?.text ?? null}
              focusKey={
                quoteFocus
                  ? `q${quoteFocus.key}`
                  : selectedBlock
                    ? `b${selectedBlock.id}`
                    : null
              }
            />
          ) : (
            <p className="muted">Нет PDF-файла для просмотра.</p>
          )}
        </div>

        <div className="panel side-panel">
          <div className="tabs row">
            {(
              [
                ["structure", "Структура"],
                ["graph", "Граф"],
                ["extract", "Извлечение"],
                ["review", "Проверка"],
                ["assistant", "Ассистент"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                className={`btn secondary ${activeTab === key ? "active-tab" : ""}`}
                onClick={() => setActiveTab(key)}
              >
                {label}
              </button>
            ))}
          </div>

          {activeTab === "structure" ? (
            <StructurePane
              paper={paper}
              selectedId={selectedBlock?.id ?? null}
              onSelect={(block) => {
                setSelectedBlock(block);
                setQuoteFocus(null);
              }}
            />
          ) : null}
          {activeTab === "graph" ? (
            <GraphAnnotatePane
              documentId={paper.id}
              selectedBlock={selectedBlock}
              refreshKey={graphRefresh}
              onMessage={setMessage}
              onError={setError}
            />
          ) : null}
          {activeTab === "extract" ? (
            <ExtractRunPane
              documentId={paper.id}
              onMessage={setMessage}
              onError={setError}
              onActiveRunChange={setActiveRunId}
              onRunFinished={(runId) => {
                setActiveRunId(runId);
                setGraphRefresh((n) => n + 1);
              }}
              onGoToReview={(runId) => {
                setActiveRunId(runId);
                setGraphRefresh((n) => n + 1);
                setActiveTab("review");
              }}
            />
          ) : null}
          {activeTab === "review" ? (
            <ReviewQueuePane
              documentId={paper.id}
              runId={activeRunId}
              blocksById={blocksById}
              onHighlightBlock={setSelectedBlock}
              onFocusQuote={(quote) => {
                if (!quote) {
                  setQuoteFocus(null);
                  return;
                }
                setQuoteFocus((prev) => ({ text: quote, key: (prev?.key ?? 0) + 1 }));
              }}
              onMessage={setMessage}
              onError={setError}
              onChanged={() => setGraphRefresh((n) => n + 1)}
              onContinueExtraction={() => {
                setGraphRefresh((n) => n + 1);
                setActiveTab("review");
              }}
            />
          ) : null}
          <div hidden={activeTab !== "assistant"}>
            <AssistantChatPanel
              documentId={paper.id}
              onMessage={setMessage}
              onError={setError}
              onGraphChanged={() => setGraphRefresh((n) => n + 1)}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function statusLabel(status: string) {
  const map: Record<string, string> = {
    indexed: "проиндексирована",
    parsing: "разбор…",
    parsed: "разобрана",
    error: "ошибка",
    new: "новая",
    annotated: "размечена",
    gold: "эталон",
    extracted: "извлечена",
  };
  return map[status] || status;
}

function EsiCard({
  hints,
  files,
  esiUrl,
  setEsiUrl,
  onSaveLink,
  onDeleteLink,
  onDeleteFile,
  onPickFile,
  busy,
}: {
  hints: EsiHint[];
  files: { id: number; filename: string }[];
  esiUrl: string;
  setEsiUrl: (v: string) => void;
  onSaveLink: () => void;
  onDeleteLink: (url: string) => void;
  onDeleteFile: (fileId: number) => void;
  onPickFile: () => void;
  busy: boolean;
}) {
  const urls = hints.filter((h) => h.kind === "url");
  const notes = hints.filter((h) => h.kind !== "url");

  return (
    <section className="panel esi-card">
      <h2>ESI / Supporting Information</h2>
      {files.length === 0 && urls.length === 0 && notes.length === 0 ? (
        <p className="muted">Упоминаний ESI в тексте пока не найдено.</p>
      ) : null}

      {files.length > 0 ? (
        <ul className="list">
          {files.map((file) => (
            <li key={file.id}>
              <div>
                <span className="badge">файл</span> {file.filename}
              </div>
              <button
                type="button"
                className="btn danger"
                disabled={busy}
                onClick={() => onDeleteFile(file.id)}
              >
                Удалить файл
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {urls.length > 0 || notes.length > 0 ? (
        <ul className="list">
          {urls.map((h, i) => (
            <li key={`url-${h.value}-${i}`}>
              <div>
                <span className="badge">ссылка</span>{" "}
                <a href={h.value} target="_blank" rel="noreferrer">
                  {h.value}
                </a>
                {h.snippet ? <div className="muted">{h.snippet}</div> : null}
              </div>
              <div className="row">
                <a className="btn secondary" href={h.value} target="_blank" rel="noreferrer">
                  Открыть
                </a>
                <button
                  type="button"
                  className="btn danger"
                  disabled={busy}
                  onClick={() => onDeleteLink(h.value)}
                >
                  Удалить
                </button>
              </div>
            </li>
          ))}
          {notes.map((h, i) => (
            <li key={`${h.kind}-${h.value}-${i}`}>
              <div>
                <span className="badge">{h.kind}</span> <span>{h.value}</span>
                {h.snippet ? <div className="muted">{h.snippet}</div> : null}
              </div>
            </li>
          ))}
        </ul>
      ) : null}

      <p className="muted">
        PDF ESI принимается, только если название на первой странице совпадает с названием статьи.
        Ссылку и файл можно сохранить вместе и удалить по отдельности.
      </p>
      <div className="row">
        <button type="button" className="btn" onClick={onPickFile} disabled={busy}>
          Прикрепить файл ESI
        </button>
        <input
          placeholder="Или вставьте ссылку на ESI"
          value={esiUrl}
          onChange={(e) => setEsiUrl(e.target.value)}
        />
        <button type="button" className="btn secondary" onClick={onSaveLink} disabled={busy}>
          Сохранить ссылку
        </button>
      </div>
    </section>
  );
}

function StructurePane({
  paper,
  selectedId,
  onSelect,
}: {
  paper: PaperStructure;
  selectedId: number | null;
  onSelect: (b: PaperBlock) => void;
}) {
  return (
    <div className="structure-pane stack">
      <p className="muted">
        Секций: {paper.sections.length}, ссылок: {paper.references.length}
      </p>
      {paper.sections.map((section) => (
        <details key={section.id} open={section.section_type !== "references"}>
          <summary>
            {SECTION_LABELS[section.section_type] || section.section_type}
            {section.title ? ` — ${section.title}` : ""}
            <span className="muted">
              {" "}
              (с. {section.page_start}–{section.page_end})
            </span>
          </summary>
          <ul className="block-list">
            {section.blocks
              .filter((b) => b.kind !== "table_cell")
              .map((block) => (
                <li key={block.id}>
                  <button
                    type="button"
                    className={`block-item ${selectedId === block.id ? "selected" : ""}`}
                    onClick={() => onSelect(block)}
                  >
                    <span className="badge">
                      {BLOCK_LABELS[block.kind] || block.kind} · с. {block.page}
                    </span>
                    <span className="block-preview">
                      {block.text.slice(0, 160)}
                      {block.text.length > 160 ? "…" : ""}
                    </span>
                  </button>
                </li>
              ))}
          </ul>
        </details>
      ))}

      {paper.references.length > 0 ? (
        <details>
          <summary>DOI из библиографии ({paper.references.filter((r) => r.doi).length})</summary>
          <ul className="list">
            {paper.references
              .filter((r) => r.doi)
              .slice(0, 40)
              .map((r) => (
                <li key={r.id}>
                  <code>{r.doi}</code>
                </li>
              ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
