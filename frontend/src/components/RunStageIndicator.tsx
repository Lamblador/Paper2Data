import { useEffect, useState } from "react";
import type { RecipeStep, RunStepHistory } from "../api/client";
import { runStatusLabel } from "../lib/labels";
import {
  displayStepIndex,
  formatElapsed,
  historyByStep,
  stepName,
} from "../lib/runProgress";

type Props = {
  runId: number | null;
  status?: string | null;
  pipeline?: string[];
  stepsTotal?: number;
  stepIndex?: number;
  currentStepId?: string | null;
  stepsHistory?: RunStepHistory[];
  steps?: RecipeStep[];
};

function dotClass(
  index: number,
  position: number,
  status: string | null | undefined,
  historyStatus: RunStepHistory["status"] | undefined,
): string {
  if (historyStatus === "failed") return "failed";
  if (historyStatus === "running") return "current";
  if (historyStatus === "done") return "done";
  if (status === "completed") return "done";
  if (status === "failed" && index > 0 && position + 1 === index) return "failed";
  if (status === "running" && index > 0 && position + 1 === index) return "current";
  if (status === "awaiting_review" && index > 0 && position < index) return "done";
  if (
    (status === "running" || status === "failed" || status === "cancelled") &&
    index > 0 &&
    position + 1 < index
  ) {
    return "done";
  }
  if (status === "pending" && position === 0) return "current";
  return "next";
}

export default function RunStageIndicator({
  runId,
  status,
  pipeline,
  stepsTotal,
  stepIndex,
  currentStepId,
  stepsHistory,
  steps,
}: Props) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (status !== "running") return;
    const timer = window.setInterval(() => setNow(Date.now()), 15000);
    return () => window.clearInterval(timer);
  }, [status]);

  if (runId == null) return null;

  const ids = pipeline && pipeline.length > 0 ? pipeline : [];
  const index = displayStepIndex(
    { status, step_index: stepIndex, current_step_id: currentStepId },
    ids,
  );
  const total = stepsTotal != null && stepsTotal > 0 ? stepsTotal : ids.length;
  const stepId = (index > 0 ? ids[index - 1] : undefined) || currentStepId || "";
  const name = stepName(steps || [], stepId);
  const runningItem = (stepsHistory || []).find((item) => item.status === "running");
  const elapsed = status === "running" ? formatElapsed(runningItem?.started_at, now) : null;
  const statusText = elapsed ? `выполняется ${elapsed}` : runStatusLabel(status);
  const head =
    index > 0 && total > 0
      ? `Прогон #${runId} · шаг ${index} из ${total}${name ? ` «${name}»` : ""}${
          statusText ? ` · ${statusText}` : ""
        }`
      : `Прогон #${runId}${statusText ? ` · ${statusText}` : ""}`;

  const dotCount = ids.length > 0 ? ids.length : total;
  const hist = historyByStep(stepsHistory);

  return (
    <div className="stage-indicator">
      <div className="stage-line">{head}</div>
      {dotCount > 0 ? (
        <div className="stage-track" aria-hidden="true">
          {Array.from({ length: dotCount }, (_, position) => {
            const id = ids[position];
            const historyStatus = id ? hist.get(id)?.status : undefined;
            return (
              <span
                key={id || position}
                className={`stage-dot ${dotClass(index, position, status, historyStatus)}`}
              />
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
