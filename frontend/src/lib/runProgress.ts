import type {
  ExtractionRun,
  ProjectSchema,
  RecipeStep,
  RunCounts,
  RunStepHistory,
} from "../api/client";
import { ruCount, SECTION_LABELS } from "./labels";

export type StepVisualState =
  | "done"
  | "current"
  | "next"
  | "failed"
  | "disabled"
  | "skipped";

export type PrimaryAction =
  | { kind: "create"; label: string }
  | { kind: "start"; label: string; stepId: string }
  | {
      kind: "review";
      label: string;
      count: number | null;
      continueStepId?: string;
      continueLabel?: string;
    }
  | { kind: "next"; label: string; stepId: string }
  | { kind: "retry"; label: string; stepId: string }
  | { kind: "done"; label: string }
  | { kind: "running"; label: string }
  | { kind: "cancelled"; label: string };

export type ReviewNextAction = {
  label: string;
  disabled: boolean;
  stepId: string | null;
  usePipeline: boolean;
};

const PHASE_LABELS: Record<string, string> = {
  entities: "сущности",
  relations: "связи",
};

export function historyByStep(
  history: RunStepHistory[] | undefined,
): Map<string, RunStepHistory> {
  const map = new Map<string, RunStepHistory>();
  for (const item of history || []) {
    if (item?.step_id) map.set(item.step_id, item);
  }
  return map;
}

export function resolvePipelineIds(
  run: { pipeline?: string[] } | null | undefined,
  recipePipeline: string[],
  steps: RecipeStep[],
): string[] {
  if (run?.pipeline && run.pipeline.length > 0) return [...run.pipeline];
  if (recipePipeline.length > 0) return [...recipePipeline];
  return steps.map((step) => step.id);
}

export function stepDef(steps: RecipeStep[], id: string): RecipeStep {
  return steps.find((step) => step.id === id) ?? { id, name: id };
}

export function stepName(steps: RecipeStep[], id: string | null | undefined): string {
  if (!id) return "";
  return stepDef(steps, id).name || id;
}

export function displayStepIndex(
  run: {
    status?: string | null;
    step_index?: number;
    current_step_id?: string | null;
  },
  pipelineIds: string[],
): number {
  if (run.step_index != null && run.step_index > 0) return run.step_index;
  if (run.current_step_id) {
    const idx = pipelineIds.indexOf(run.current_step_id);
    if (idx >= 0) return idx + 1;
  }
  if ((run.status === "pending" || run.status === "running") && pipelineIds.length > 0) {
    return 1;
  }
  if (run.status === "completed" && pipelineIds.length > 0) return pipelineIds.length;
  return 0;
}

export function proposedOf(run: { counts?: RunCounts } | null | undefined): number | null {
  if (!run?.counts || typeof run.counts.proposed !== "number") return null;
  return run.counts.proposed;
}

/** Первый шаг пайплайна, который ещё не завершён успешно. */
export function nextOpenStepId(
  run: ExtractionRun | null | undefined,
  pipelineIds: string[],
  steps: RecipeStep[],
): string | null {
  const enabled = pipelineIds.filter((id) => stepDef(steps, id).enabled !== false);
  if (!run) return enabled[0] ?? null;

  if ((run.steps_history?.length ?? 0) > 0) {
    const hist = historyByStep(run.steps_history);
    for (const id of enabled) {
      const item = hist.get(id);
      if (!item || item.status !== "done") return id;
    }
    return null;
  }

  if (run.status === "completed") return null;
  if (run.status === "pending" || !run.current_step_id) return enabled[0] ?? null;

  const idx = enabled.indexOf(run.current_step_id);
  if (idx < 0) return enabled[0] ?? null;
  if (run.status === "awaiting_review") return enabled[idx + 1] ?? null;
  return enabled[idx] ?? null;
}

export function computePrimaryAction(
  run: ExtractionRun | null,
  pipelineIds: string[],
  steps: RecipeStep[],
): PrimaryAction {
  if (!run) return { kind: "create", label: "Создать прогон" };
  if (run.status === "running") return { kind: "running", label: "Выполняется…" };
  if (run.status === "cancelled") return { kind: "cancelled", label: "Прогон отменён" };

  const openId = nextOpenStepId(run, pipelineIds, steps);

  if (run.status === "failed") {
    const failedHist = (run.steps_history || []).find((item) => item.status === "failed");
    const stepId = failedHist?.step_id || run.current_step_id || openId || pipelineIds[0] || "";
    const name = stepName(steps, stepId) || "шаг";
    return { kind: "retry", label: `Повторить шаг: ${name}`, stepId };
  }

  if (run.status === "completed") return { kind: "done", label: "Пайплайн завершён" };

  if (pipelineIds.length === 0) {
    if (run.status === "pending") return { kind: "start", label: "Запустить шаг 1", stepId: "" };
    return { kind: "running", label: "Загрузка шагов…" };
  }

  if (run.status === "pending") {
    const stepId = openId || pipelineIds[0] || "";
    const index = Math.max(0, pipelineIds.indexOf(stepId));
    const name = stepName(steps, stepId) || "шаг";
    return {
      kind: "start",
      label: `Запустить шаг ${index + 1}: ${name}`,
      stepId,
    };
  }

  const proposed = proposedOf(run);
  if (run.status === "awaiting_review") {
    const continueLabel = openId ? `Продолжить: шаг ${stepName(steps, openId)}` : undefined;
    if (proposed != null && proposed > 0) {
      return {
        kind: "review",
        label: `Проверить ${ruCount(proposed, "карточку", "карточки", "карточек")}`,
        count: proposed,
        continueStepId: openId || undefined,
        continueLabel,
      };
    }
    if (proposed === 0) {
      if (!openId) return { kind: "done", label: "Пайплайн завершён" };
      return {
        kind: "next",
        label: `Запустить следующий шаг: ${stepName(steps, openId)}`,
        stepId: openId,
      };
    }
    return {
      kind: "review",
      label: "Проверить карточки",
      count: null,
      continueStepId: openId || undefined,
      continueLabel,
    };
  }

  if (!openId) return { kind: "done", label: "Пайплайн завершён" };
  return {
    kind: "next",
    label: `Запустить следующий шаг: ${stepName(steps, openId)}`,
    stepId: openId,
  };
}

export function computeStepStates(args: {
  run: ExtractionRun | null;
  pipelineIds: string[];
  steps: RecipeStep[];
}): Map<string, StepVisualState> {
  const { run, pipelineIds, steps } = args;
  const states = new Map<string, StepVisualState>();
  const hist = historyByStep(run?.steps_history);
  const hasHistory = (run?.steps_history?.length ?? 0) > 0;
  const action = computePrimaryAction(run, pipelineIds, steps);
  const arrowId =
    action.kind === "start" || action.kind === "next" ? action.stepId : null;
  const proposed = run ? proposedOf(run) : null;
  const currentIdx =
    run?.current_step_id != null ? pipelineIds.indexOf(run.current_step_id) : -1;

  const runningId = (() => {
    const fromHist = (run?.steps_history || []).find((item) => item.status === "running")?.step_id;
    if (fromHist) return fromHist;
    if (run?.status === "running") {
      return run.current_step_id || nextOpenStepId(run, pipelineIds, steps);
    }
    return null;
  })();

  const laterProgressed = (id: string) => {
    const idx = pipelineIds.indexOf(id);
    if (idx < 0) return false;
    return pipelineIds.slice(idx + 1).some((nextId) => {
      const item = hist.get(nextId);
      return item?.status === "done" || item?.status === "running" || item?.status === "failed";
    });
  };

  for (const id of pipelineIds) {
    const step = stepDef(steps, id);
    if (step.enabled === false) {
      states.set(id, "disabled");
      continue;
    }
    const item = hist.get(id);
    if (item?.status === "failed" || (run?.status === "failed" && run.current_step_id === id && item?.status !== "done")) {
      states.set(id, "failed");
      continue;
    }
    if (id === runningId) {
      states.set(id, "current");
      continue;
    }
    if (item?.status === "done") {
      states.set(id, "done");
      continue;
    }
    if (!run) {
      states.set(id, "next");
      continue;
    }
    if (hasHistory) {
      if (laterProgressed(id)) states.set(id, "skipped");
      else if (id === arrowId) states.set(id, "current");
      else states.set(id, "next");
      continue;
    }

    const idx = pipelineIds.indexOf(id);
    if (run.status === "completed") {
      states.set(id, "done");
      continue;
    }
    if (run.status === "pending") {
      states.set(id, id === arrowId ? "current" : "next");
      continue;
    }
    if (currentIdx < 0) {
      states.set(id, id === arrowId ? "current" : "next");
      continue;
    }
    if (run.status === "failed" || run.status === "cancelled") {
      if (idx < currentIdx) states.set(id, "done");
      else if (idx === currentIdx) states.set(id, "failed");
      else states.set(id, "next");
      continue;
    }
    if (run.status === "awaiting_review") {
      if (idx <= currentIdx) states.set(id, "done");
      else if (proposed === 0 && id === arrowId) states.set(id, "current");
      else states.set(id, "next");
      continue;
    }
    states.set(id, id === arrowId ? "current" : "next");
  }

  return states;
}

export function doneStepCount(
  run: ExtractionRun,
  pipelineIds: string[],
): { done: number; total: number } {
  const total =
    run.steps_total != null && run.steps_total > 0 ? run.steps_total : pipelineIds.length;
  if ((run.steps_history?.length ?? 0) > 0 && pipelineIds.length > 0) {
    const hist = historyByStep(run.steps_history);
    const done = pipelineIds.filter((id) => hist.get(id)?.status === "done").length;
    return { done, total: total || pipelineIds.length };
  }
  if ((run.steps_history?.length ?? 0) > 0) {
    const done = (run.steps_history || []).filter((item) => item.status === "done").length;
    return { done, total: total || (run.steps_history || []).length };
  }
  if (!total) return { done: 0, total: 0 };
  if (run.status === "completed") return { done: total, total };
  if (run.status === "pending") return { done: 0, total };
  const index = displayStepIndex(run, pipelineIds);
  if (run.status === "awaiting_review") return { done: Math.min(index, total), total };
  if (run.status === "running" || run.status === "failed" || run.status === "cancelled") {
    return { done: Math.max(0, Math.min(index - 1, total)), total };
  }
  return { done: 0, total };
}

export function formatElapsed(iso: string | null | undefined, now = Date.now()): string | null {
  if (!iso) return null;
  const started = Date.parse(iso);
  if (!Number.isFinite(started)) return null;
  const sec = Math.max(0, Math.round((now - started) / 1000));
  if (sec < 60) return `${sec} с`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} мин`;
  const hours = Math.floor(min / 60);
  const rest = min % 60;
  return rest ? `${hours} ч ${rest} мин` : `${hours} ч`;
}

export function formatStepResult(
  item: RunStepHistory | undefined,
  proposed: number | null,
  now = Date.now(),
): string | null {
  if (!item) return null;
  if (item.status === "running") {
    const elapsed = formatElapsed(item.started_at, now);
    return elapsed ? `выполняется ${elapsed}` : "выполняется…";
  }
  if (item.status === "failed") return item.error || "ошибка шага";

  const nodes = item.nodes || 0;
  const edges = item.edges || 0;
  const abbr = item.abbreviations || 0;
  const parts: string[] = [];
  if (abbr > 0 && nodes === 0 && edges === 0) {
    parts.push(`словарь: ${ruCount(abbr, "шифр", "шифра", "шифров")}`);
  } else {
    if (nodes > 0) parts.push(`+${ruCount(nodes, "сущность", "сущности", "сущностей")}`);
    if (edges > 0) parts.push(`+${ruCount(edges, "связь", "связи", "связей")}`);
    if (abbr > 0) parts.push(`шифров: ${abbr}`);
  }
  if (proposed != null && proposed > 0) parts.push(`${proposed} к проверке`);
  return parts.length > 0 ? parts.join(", ") : "готово";
}

export function describeStepWork(step: RecipeStep, schema: ProjectSchema | null): string {
  if (step.output_key === "abbreviation_map" || step.prompt_template === "resolve_codes") {
    return "Собирает словарь шифров; сущности не создаёт";
  }
  const entityName = (id: string) => schema?.entity_types.find((item) => item.id === id)?.name || id;
  const relationName = (id: string) =>
    schema?.relation_types.find((item) => item.id === id)?.name || id;
  const entities = (step.targets?.entities || []).filter(Boolean);
  const relations = (step.targets?.relations || []).filter(Boolean);
  const parts: string[] = [];
  if (entities.length > 0) parts.push(`Ищет: ${entities.map(entityName).join(", ")}`);
  if (relations.length > 0) parts.push(`Связи: ${relations.map(relationName).join(", ")}`);
  if (parts.length > 0) return parts.join(" · ");
  const description = step.description?.replace(/\s+/g, " ").trim();
  return description || "Шаг пайплайна";
}

export function describeStepWhere(step: RecipeStep): string | null {
  const sections = step.section_include || [];
  if (sections.length === 0) return null;
  return `Где: ${sections.map((section) => SECTION_LABELS[section] || section).join(", ")}`;
}

export function phaseBadge(step: RecipeStep): string | null {
  if (step.strategy !== "entities_first") return null;
  const phases = step.phases || [];
  if (phases.length === 0) return "сущности → связи";
  return phases.map((phase) => PHASE_LABELS[phase.name] || phase.name).join(" → ");
}

export function needsHumanReview(step: RecipeStep): boolean {
  if (step.strategy === "entities_first" && step.phases && step.phases.length > 0) {
    return step.phases.some((phase) => phase.human_review !== false);
  }
  return step.human_review !== false;
}

function numStat(stats: Record<string, unknown> | undefined, key: string): number {
  const value = stats?.[key];
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
}

export function tokenTotals(run: ExtractionRun): { prompt: number; completion: number } | null {
  const history = run.steps_history || [];
  let prompt = history.reduce((sum, item) => sum + (Number(item.prompt_tokens) || 0), 0);
  let completion = history.reduce((sum, item) => sum + (Number(item.completion_tokens) || 0), 0);
  if (!prompt && !completion) {
    prompt = numStat(run.stats, "prompt_tokens");
    completion = numStat(run.stats, "completion_tokens");
  }
  if (!prompt && !completion) return null;
  return { prompt, completion };
}

export function formatRunDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("ru-RU", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function reviewNextAction(input: {
  runStatus?: string | null;
  pipeline?: string[];
  steps: RecipeStep[];
  stepsHistory?: RunStepHistory[];
  currentStepId?: string | null;
  stepIndex?: number;
  stepsTotal?: number;
  proposed: number;
}): ReviewNextAction | null {
  if (!input.runStatus) return null;

  const pseudo: ExtractionRun = {
    id: 0,
    document_id: 0,
    recipe_db_id: null,
    recipe_id: "",
    llm_profile_id: "",
    strategy: "",
    status: input.runStatus,
    current_step_id: input.currentStepId ?? null,
    abbreviation_map: [],
    stats: {},
    error_message: null,
    created_at: null,
    updated_at: null,
    pipeline: input.pipeline,
    steps_total: input.stepsTotal,
    step_index: input.stepIndex,
    steps_history: input.stepsHistory,
    counts: {
      proposed: input.proposed,
      accepted: 0,
      rejected: 0,
      nodes: 0,
      edges: 0,
    },
  };
  const ids = resolvePipelineIds(pseudo, input.pipeline || [], input.steps);

  if (pseudo.status === "running") {
    return { label: "Выполняется…", disabled: true, stepId: null, usePipeline: false };
  }
  if (pseudo.status === "completed" || pseudo.status === "cancelled") {
    return {
      label: pseudo.status === "completed" ? "Пайплайн завершён" : "Прогон отменён",
      disabled: true,
      stepId: null,
      usePipeline: false,
    };
  }

  const openId = nextOpenStepId(pseudo, ids, input.steps);
  const name = openId ? stepName(input.steps, openId) : "";

  if (pseudo.status === "failed") {
    const stepId =
      (input.stepsHistory || []).find((item) => item.status === "failed")?.step_id ||
      input.currentStepId ||
      openId ||
      null;
    const failedName = stepName(input.steps, stepId) || "шаг";
    return {
      label: stepId ? `Повторить шаг: ${failedName}` : "Повторить шаг",
      disabled: false,
      stepId,
      usePipeline: !stepId,
    };
  }

  if (pseudo.status === "pending" && openId) {
    return {
      label: `Запустить шаг 1: ${name}`,
      disabled: false,
      stepId: openId,
      usePipeline: false,
    };
  }

  if (!openId) {
    if (input.proposed > 0) return null;
    if (ids.length === 0) return null;
    return { label: "Пайплайн завершён", disabled: true, stepId: null, usePipeline: false };
  }

  if (input.proposed > 0) {
    return {
      label: `Продолжить: шаг ${name}`,
      disabled: false,
      stepId: openId,
      usePipeline: false,
    };
  }

  return {
    label: "Все карточки проверены — продолжить",
    disabled: false,
    stepId: openId,
    usePipeline: false,
  };
}

export function countLine(counts: RunCounts | undefined): string | null {
  if (!counts) return null;
  const rejected = counts.rejected > 0 ? ` · отклонено ${counts.rejected}` : "";
  return `к проверке ${counts.proposed} · принято ${counts.accepted}${rejected} · узлов ${counts.nodes} · связей ${counts.edges}`;
}
