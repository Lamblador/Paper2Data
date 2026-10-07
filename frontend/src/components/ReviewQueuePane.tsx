import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type ExtractionRun,
  type PaperBlock,
  type RecipeStep,
  type ReviewCard,
  type ReviewQueue,
} from "../api/client";
import { armRunNotification, markRunBusy, notifyRunFinished } from "../lib/browserNotify";
import { compactBlocks, locateQuote } from "../lib/quoteLocate";
import { reviewNextAction, type ReviewNextAction } from "../lib/runProgress";
import RunStageIndicator from "./RunStageIndicator";

type Props = {
  documentId: number;
  runId?: number | null;
  blocksById: Map<number, PaperBlock>;
  onHighlightBlock: (block: PaperBlock | null) => void;
  onFocusQuote?: (quote: string | null) => void;
  onMessage?: (msg: string) => void;
  onError?: (msg: string) => void;
  onChanged?: () => void;
  onContinueExtraction?: () => void;
};

type StatusTab = "proposed" | "accepted" | "rejected" | "all";

const TAB_LABELS: Record<StatusTab, string> = {
  proposed: "К проверке",
  accepted: "Принятые",
  rejected: "Отклонённые",
  all: "Все",
};

export default function ReviewQueuePane({
  documentId,
  runId,
  blocksById,
  onHighlightBlock,
  onFocusQuote,
  onMessage,
  onError,
  onChanged,
  onContinueExtraction,
}: Props) {
  const [queue, setQueue] = useState<ReviewQueue | null>(null);
  const [statusTab, setStatusTab] = useState<StatusTab>("proposed");
  const [busy, setBusy] = useState(false);
  const [steps, setSteps] = useState<RecipeStep[]>([]);
  const [recipePipeline, setRecipePipeline] = useState<string[]>([]);
  const [fetchedRun, setFetchedRun] = useState<ExtractionRun | null>(null);
  const [metaTick, setMetaTick] = useState(0);
  const [editCard, setEditCard] = useState<ReviewCard | null>(null);
  const [editLabel, setEditLabel] = useState("");
  const [editAttrs, setEditAttrs] = useState("");

  const load = useCallback(async () => {
    const q = await api.getReviewQueue(documentId, runId ?? undefined, statusTab);
    setQueue(q);
  }, [documentId, runId, statusTab]);

  useEffect(() => {
    void load().catch((err) =>
      onError?.(err instanceof Error ? err.message : String(err)),
    );
  }, [load, onError]);

  const shownRunId = queue?.run_id ?? runId ?? null;

  useEffect(() => {
    if (shownRunId == null) {
      setFetchedRun(null);
      setSteps([]);
      setRecipePipeline([]);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const res = await api.getExtractionRun(shownRunId);
        if (cancelled) return;
        setFetchedRun(res.run);
        let loadedSteps: RecipeStep[] = [];
        let loadedPipeline: string[] = [];
        try {
          const bundled = await api.getBundledRecipe(res.run.recipe_id);
          loadedSteps = bundled.recipe.steps || [];
          loadedPipeline = bundled.recipe.pipeline || [];
        } catch {
          if (res.run.recipe_db_id != null) {
            const db = await api.getRecipe(res.run.recipe_db_id);
            if (cancelled) return;
            loadedSteps = db.recipe.steps || [];
            loadedPipeline = db.recipe.pipeline || [];
          }
        }
        if (!cancelled) {
          setSteps(loadedSteps);
          setRecipePipeline(loadedPipeline);
        }
      } catch {
        if (!cancelled) {
          setFetchedRun(null);
          setSteps([]);
          setRecipePipeline([]);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [shownRunId, metaTick]);

  const indexedBlocks = useMemo(
    () => compactBlocks(blocksById.values()),
    [blocksById],
  );

  const quotePage = (card: ReviewCard): number | null => {
    const quote = (card.quote || "").trim();
    if (!quote) return card.page;
    return locateQuote(quote, indexedBlocks).page;
  };

  const highlight = (card: ReviewCard) => {
    const quote = (card.quote || "").trim();
    const located = quote ? locateQuote(quote, indexedBlocks) : null;
    onHighlightBlock(located?.block ?? null);
    onFocusQuote?.(quote || null);
  };

  const act = async (action: "accept" | "reject" | "reopen", card: ReviewCard) => {
    setBusy(true);
    try {
      if (action === "accept") await api.reviewAccept(card.kind, card.id);
      else if (action === "reject") await api.reviewReject(card.kind, card.id);
      else await api.reviewReopen(card.kind, card.id);
      onMessage?.(
        action === "accept"
          ? "Принято"
          : action === "reject"
            ? "Отклонено"
            : "Возвращено в очередь проверки",
      );
      if (action === "reopen") setStatusTab("proposed");
      await load();
      onChanged?.();
    } catch (err) {
      onError?.(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const saveEdit = async () => {
    if (!editCard) return;
    setBusy(true);
    try {
      let attrs: Record<string, unknown> = {};
      try {
        attrs = editAttrs.trim() ? JSON.parse(editAttrs) : editCard.attributes;
      } catch {
        throw new Error("Атрибуты: невалидный JSON");
      }
      const payload: Record<string, unknown> = { attributes: attrs };
      if (editCard.kind === "node" && editLabel.trim()) {
        payload.label = editLabel.trim();
      }
      const accept = editCard.status === "proposed";
      await api.reviewEdit(editCard.kind, editCard.id, payload, accept);
      setEditCard(null);
      onMessage?.(accept ? "Изменено и принято" : "Изменения сохранены");
      await load();
      onChanged?.();
    } catch (err) {
      onError?.(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const removeEdge = async (card: ReviewCard) => {
    const name = card.type_name || card.type || "связь";
    if (!window.confirm(`Удалить связь «${name}» #${card.id}?`)) return;
    setBusy(true);
    try {
      await api.deleteEdge(card.id);
      if (editCard?.kind === "edge" && editCard.id === card.id) setEditCard(null);
      onMessage?.("Связь удалена");
      await load();
      onChanged?.();
    } catch (err) {
      onError?.(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const advance = async (next: ReviewNextAction) => {
    const id = queue?.run_id ?? runId;
    if (id == null) {
      onError?.("Нет активного прогона — вернитесь во вкладку «Извлечение»");
      return;
    }
    if (next.disabled) return;
    armRunNotification();
    markRunBusy(next.stepId && !next.usePipeline ? "Шаг выполняется…" : "Пайплайн выполняется…");
    setBusy(true);
    try {
      if (next.stepId && !next.usePipeline) {
        const res = await api.runExtractionStep(id, { step_id: next.stepId });
        const stepLabel = steps.find((step) => step.id === res.step_id)?.name || res.step_id;
        const notice = `Шаг «${stepLabel}» выполнен`;
        onMessage?.(notice);
        notifyRunFinished(notice);
      } else {
        const res = await api.runExtractionPipeline(id);
        const notice = `Продолжен пайплайн: ${res.steps.map((step) => step.step_id).join(" → ") || "пусто"}`;
        onMessage?.(notice);
        notifyRunFinished("Пайплайн завершён", notice);
      }
      setStatusTab("proposed");
      setMetaTick((value) => value + 1);
      await load();
      onChanged?.();
      onContinueExtraction?.();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      notifyRunFinished("Прогон завершился с ошибкой", message);
      onError?.(message);
      await load().catch(() => undefined);
    } finally {
      setBusy(false);
    }
  };

  if (!queue) {
    return <p className="muted">Загрузка очереди…</p>;
  }

  const abbr = queue.abbreviation_map || [];
  const sc = queue.status_counts || {
    proposed: 0,
    accepted: 0,
    rejected: 0,
    manual: 0,
    other: 0,
    no_evidence: 0,
  };
  const onlyAbbreviations =
    statusTab === "proposed" &&
    queue.cards.length === 0 &&
    abbr.length > 0 &&
    queue.run_status === "awaiting_review";

  const pipelineIds =
    queue.pipeline && queue.pipeline.length > 0
      ? queue.pipeline
      : fetchedRun?.pipeline && fetchedRun.pipeline.length > 0
        ? fetchedRun.pipeline
        : recipePipeline;
  const proposed = fetchedRun?.counts?.proposed ?? sc.proposed;
  const nextAction = reviewNextAction({
    runStatus: queue.run_status ?? fetchedRun?.status,
    pipeline: pipelineIds,
    steps,
    stepsHistory: queue.steps_history ?? fetchedRun?.steps_history,
    currentStepId: queue.current_step_id ?? fetchedRun?.current_step_id,
    stepIndex: queue.step_index ?? fetchedRun?.step_index,
    stepsTotal: queue.steps_total ?? fetchedRun?.steps_total,
    proposed,
  });

  return (
    <div className="stack review-pane">
      <section className="run-card">
        <RunStageIndicator
          runId={shownRunId}
          status={queue.run_status ?? fetchedRun?.status}
          pipeline={pipelineIds}
          stepsTotal={queue.steps_total ?? fetchedRun?.steps_total}
          stepIndex={queue.step_index ?? fetchedRun?.step_index}
          currentStepId={queue.current_step_id ?? fetchedRun?.current_step_id}
          stepsHistory={queue.steps_history ?? fetchedRun?.steps_history}
          steps={steps}
        />
        <p className="muted run-meta">
          На графе: к проверке {sc.proposed}, принятых {sc.accepted}, отклонённых{" "}
          {sc.rejected}
          {sc.no_evidence > 0 ? `, без цитаты ${sc.no_evidence}` : ""}
        </p>
        {nextAction ? (
          <button
            type="button"
            className={proposed > 0 ? "btn secondary" : "btn"}
            disabled={busy || nextAction.disabled}
            onClick={() => void advance(nextAction)}
          >
            {busy ? "Запуск…" : nextAction.label}
          </button>
        ) : null}
        {busy ? (
          <p className="muted">Если свернуть вкладку, браузер сообщит об окончании шага.</p>
        ) : null}
      </section>

      <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
        {(Object.keys(TAB_LABELS) as StatusTab[]).map((tab) => (
          <button
            key={tab}
            type="button"
            className={`btn ${statusTab === tab ? "" : "secondary"}`}
            disabled={busy}
            onClick={() => setStatusTab(tab)}
          >
            {TAB_LABELS[tab]}
            {tab === "proposed"
              ? ` (${sc.proposed})`
              : tab === "accepted"
                ? ` (${sc.accepted})`
                : tab === "rejected"
                  ? ` (${sc.rejected})`
                  : ""}
          </button>
        ))}
      </div>

      {abbr.length > 0 ? (
        <details open={onlyAbbreviations}>
          <summary>Словарь обозначений ({abbr.length})</summary>
          <p className="muted">
            Промежуточный результат шага обозначений. В граф как сущности не
            попадает — для карточек сущностей нужен следующий шаг пайплайна.
          </p>
          <ul className="list compact">
            {abbr.map((a, i) => (
              <li key={`${a.code}-${i}`}>
                <code>{a.code}</code> → {a.expansion}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {onlyAbbreviations ? (
        <p>
          Очередь «К проверке» пуста: сущности либо ещё не извлечены, либо уже
          приняты/отклонены. Словарь выше — не карточки сущностей. Кнопка в шапке
          запускает следующий шаг пайплайна.
        </p>
      ) : null}

      {statusTab === "proposed" &&
      queue.cards.length === 0 &&
      !onlyAbbreviations ? (
        <div className="stack">
          <p className="muted">
            Нет элементов со статусом «proposed». Извлечённые сущности сейчас:{" "}
            принято {sc.accepted}, отклонено {sc.rejected}. Откройте вкладку
            «Принятые» / «Отклонённые» или верните нужные в очередь.
          </p>
          {sc.accepted + sc.rejected > 0 ? (
            <div className="row">
              <button
                type="button"
                className="btn secondary"
                onClick={() => setStatusTab("accepted")}
              >
                Смотреть принятые
              </button>
              <button
                type="button"
                className="btn secondary"
                onClick={() => setStatusTab("rejected")}
              >
                Смотреть отклонённые
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {queue.cards.length > 0 ? (
        <ul className="list review-cards">
          {queue.cards.map((card) => (
            <li key={`${card.kind}-${card.id}`} className="review-card">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div>
                  <span className="badge">
                    {card.kind === "node" ? "сущность" : "связь"}
                  </span>{" "}
                  <strong>{card.type_name || card.type}</strong>{" "}
                  <span className="muted">#{card.id}</span>
                  <span className="muted"> · {card.status}</span>
                  {card.verified ? (
                    <span className="success"> · цитата ✓</span>
                  ) : card.quote ? (
                    <span className="error"> · цитата не подтверждена</span>
                  ) : (
                    <span className="error"> · нет опоры на текст</span>
                  )}
                </div>
              </div>
              <div>{card.kind === "node" ? card.label : null}</div>
              {card.kind === "edge" ? (
                <div className="stack" style={{ gap: 4 }}>
                  <div>
                    <strong>{card.source_label || `#${card.source_node_id}`}</strong>
                    {card.source_type ? (
                      <span className="muted"> ({card.source_type})</span>
                    ) : null}
                    <span className="muted"> #{card.source_node_id}</span>
                    {card.source_status && card.source_status !== "accepted" ? (
                      <span className="error"> · {card.source_status}</span>
                    ) : null}
                  </div>
                  <div className="muted">
                    ↓ {card.type_name || card.type || "связь"}
                    {Object.keys(card.attributes || {}).length > 0
                      ? ` · ${JSON.stringify(card.attributes)}`
                      : ""}
                  </div>
                  <div>
                    <strong>{card.target_label || `#${card.target_node_id}`}</strong>
                    {card.target_type ? (
                      <span className="muted"> ({card.target_type})</span>
                    ) : null}
                    <span className="muted"> #{card.target_node_id}</span>
                    {card.target_status && card.target_status !== "accepted" ? (
                      <span className="error"> · {card.target_status}</span>
                    ) : null}
                  </div>
                </div>
              ) : null}
              {card.kind === "node" &&
              Object.keys(card.attributes || {}).length > 0 ? (
                <pre className="muted" style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                  {JSON.stringify(card.attributes, null, 2)}
                </pre>
              ) : null}
              <blockquote
                className="quote-block"
                title="Показать этот фрагмент в PDF"
                onClick={() => highlight(card)}
              >
                «{card.quote || "—"}»
                {quotePage(card) != null ? (
                  <span className="muted"> (стр. {quotePage(card)})</span>
                ) : null}
              </blockquote>
              <div className="row">
                {card.status === "proposed" ? (
                  <>
                    <button
                      type="button"
                      className="btn"
                      disabled={busy}
                      onClick={() => void act("accept", card)}
                    >
                      Принять
                    </button>
                    <button
                      type="button"
                      className="btn secondary"
                      disabled={busy}
                      onClick={() => void act("reject", card)}
                    >
                      Отклонить
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    className="btn"
                    disabled={busy}
                    onClick={() => void act("reopen", card)}
                  >
                    Вернуть в проверку
                  </button>
                )}
                <button
                  type="button"
                  className="btn secondary"
                  disabled={busy}
                  onClick={() => {
                    setEditCard(card);
                    setEditLabel(card.label || "");
                    setEditAttrs(JSON.stringify(card.attributes || {}, null, 2));
                  }}
                >
                  Править
                </button>
                {card.kind === "edge" ? (
                  <button
                    type="button"
                    className="btn danger"
                    disabled={busy}
                    onClick={() => void removeEdge(card)}
                  >
                    Удалить связь
                  </button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      ) : null}

      {editCard ? (
        <div className="stack" style={{ borderTop: "1px solid #ddd", paddingTop: 12 }}>
          <h3>Правка #{editCard.id}</h3>
          {editCard.kind === "node" ? (
            <label>
              Метка
              <input
                value={editLabel}
                onChange={(e) => setEditLabel(e.target.value)}
              />
            </label>
          ) : null}
          <label>
            Атрибуты (JSON)
            <textarea
              rows={8}
              value={editAttrs}
              onChange={(e) => setEditAttrs(e.target.value)}
            />
          </label>
          <div className="row">
            <button
              type="button"
              className="btn"
              disabled={busy}
              onClick={() => void saveEdit()}
            >
              {editCard.status === "proposed" ? "Сохранить и принять" : "Сохранить"}
            </button>
            <button
              type="button"
              className="btn secondary"
              disabled={busy}
              onClick={() => setEditCard(null)}
            >
              Отмена
            </button>
          </div>
        </div>
      ) : null}

      {queue.duplicates.length > 0 ? (
        <details>
          <summary>Возможные дубликаты ({queue.duplicates.length})</summary>
          <ul className="list compact">
            {queue.duplicates.map((d) => (
              <li key={`${d.keep_id}-${d.merge_id}`}>
                {d.label_a} ≈ {d.label_b} ({Math.round(d.score)}%)
                <button
                  type="button"
                  className="btn secondary"
                  disabled={busy}
                  onClick={() => {
                    void (async () => {
                      setBusy(true);
                      try {
                        await api.reviewMerge(d.keep_id, d.merge_id);
                        onMessage?.("Объединено");
                        await load();
                        onChanged?.();
                      } catch (err) {
                        onError?.(
                          err instanceof Error ? err.message : String(err),
                        );
                      } finally {
                        setBusy(false);
                      }
                    })();
                  }}
                >
                  Объединить
                </button>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
