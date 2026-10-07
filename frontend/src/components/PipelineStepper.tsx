import { useEffect, useState } from "react";
import type { ExtractionRun, ProjectSchema, RecipeStep } from "../api/client";
import { strategyLabel } from "../lib/labels";
import {
  computeStepStates,
  describeStepWhere,
  describeStepWork,
  formatElapsed,
  formatStepResult,
  historyByStep,
  needsHumanReview,
  phaseBadge,
  proposedOf,
  resolvePipelineIds,
  stepDef,
  type StepVisualState,
} from "../lib/runProgress";

type Props = {
  steps: RecipeStep[];
  pipeline: string[];
  run: ExtractionRun | null;
  schema: ProjectSchema | null;
  selectedStep: string;
  onSelect: (stepId: string) => void;
};

const MARK: Record<StepVisualState, string> = {
  done: "✓",
  current: "→",
  next: "",
  failed: "×",
  disabled: "·",
  skipped: "–",
};

export default function PipelineStepper({
  steps,
  pipeline,
  run,
  schema,
  selectedStep,
  onSelect,
}: Props) {
  const [now, setNow] = useState(() => Date.now());
  const running =
    run?.status === "running" ||
    (run?.steps_history || []).some((item) => item.status === "running");

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 15000);
    return () => window.clearInterval(timer);
  }, [running]);

  const pipelineIds = resolvePipelineIds(run, pipeline, steps);
  const states = computeStepStates({ run, pipelineIds, steps });
  const hist = historyByStep(run?.steps_history);
  const proposed = proposedOf(run);
  const pipeSet = new Set(pipelineIds);
  const rows: { step: RecipeStep; inPipeline: boolean }[] = [
    ...pipelineIds.map((id) => ({ step: stepDef(steps, id), inPipeline: true })),
    ...steps
      .filter((step) => !pipeSet.has(step.id))
      .map((step) => ({ step, inPipeline: false })),
  ];

  if (rows.length === 0) {
    return <p className="muted">В рецепте нет шагов.</p>;
  }

  return (
    <div className="stepper" role="list">
      {rows.map(({ step, inPipeline }) => {
        const state: StepVisualState = !inPipeline
          ? step.enabled === false
            ? "disabled"
            : "next"
          : states.get(step.id) || "next";
        const histItem = hist.get(step.id);
        const spinning =
          state === "current" &&
          (run?.status === "running" || histItem?.status === "running");
        const showProposed =
          run?.status === "awaiting_review" && run.current_step_id === step.id ? proposed : null;
        let result = inPipeline ? formatStepResult(histItem, showProposed, now) : null;
        if (!result && spinning) {
          const elapsed = formatElapsed(histItem?.started_at, now);
          result = elapsed ? `выполняется ${elapsed}` : "выполняется…";
        }
        if (
          !result &&
          state === "failed" &&
          run?.current_step_id === step.id &&
          run.error_message
        ) {
          result = run.error_message;
        }
        const where = describeStepWhere(step);
        const phases = phaseBadge(step);
        const selected = selectedStep === step.id;

        return (
          <button
            key={`${inPipeline ? "pipe" : "extra"}-${step.id}`}
            type="button"
            role="listitem"
            className={`step ${state}${selected ? " selected" : ""}${spinning ? " running" : ""}${
              inPipeline ? "" : " extra"
            }`}
            aria-current={state === "current" ? "step" : undefined}
            onClick={() => onSelect(step.id)}
          >
            <span className="step-marker" aria-hidden="true">
              {spinning ? <span className="step-spinner" /> : MARK[state]}
            </span>
            <span className="step-body">
              <span className="step-title">{step.name || step.id}</span>
              <span className="muted">{describeStepWork(step, schema)}</span>
              {where ? <span className="muted">{where}</span> : null}
              <span className="step-tags">
                {step.strategy ? (
                  <span className="badge">{strategyLabel(step.strategy)}</span>
                ) : null}
                {phases ? <span className="badge">{phases}</span> : null}
                {needsHumanReview(step) ? (
                  <span className="badge warn">нужна проверка человеком</span>
                ) : null}
                {!inPipeline && state !== "disabled" ? (
                  <span className="badge info">не в пайплайне</span>
                ) : null}
                {state === "disabled" ? <span className="badge">выключен</span> : null}
                {state === "skipped" ? <span className="badge">пропущен</span> : null}
              </span>
              {result ? (
                <span className={state === "failed" ? "error" : "muted"}>{result}</span>
              ) : null}
            </span>
          </button>
        );
      })}
    </div>
  );
}
