import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  type ExtractionRun,
  type ExtractionRunOptions,
  type GraphNode,
  type LlmProfile,
  type ProjectSchema,
  type RecipeBrief,
  type RecipeInfo,
  type RecipeStep,
} from "../api/client";
import {
  SECTION_LABELS,
  STRATEGY_LABELS,
  runStatusBadgeClass,
  runStatusLabel,
  strategyLabel,
} from "../lib/labels";
import {
  computePrimaryAction,
  countLine,
  doneStepCount,
  formatRunDate,
  resolvePipelineIds,
  stepName,
  tokenTotals,
  type PrimaryAction,
} from "../lib/runProgress";
import { armRunNotification, markRunBusy, notifyRunFinished } from "../lib/browserNotify";
import PipelineStepper from "./PipelineStepper";
import RunStageIndicator from "./RunStageIndicator";

type Props = {
  documentId: number;
  onMessage?: (msg: string) => void;
  onError?: (msg: string) => void;
  onRunFinished?: (
    runId: number,
    meta?: { hasReviewCards?: boolean; stepId?: string },
  ) => void;
  onGoToReview?: (runId: number) => void;
  onActiveRunChange?: (runId: number) => void;
};

type RunPreset = "recipe" | "fill_relations";

type OverlayForm = {
  sectionInclude: string[];
  targetEntities: string[];
  targetRelations: string[];
  extraInstructions: string;
  focusLabels: string[];
  graphScope: "" | "accepted" | "focus" | "none";
  phases: "" | "both" | "entities" | "relations";
  packChunks: "" | "true" | "false";
  onEmpty: "" | "accept" | "warn" | "fail";
  copyAbbreviationsFromRunId: number | "";
};

const EMPTY_OVERLAY: OverlayForm = {
  sectionInclude: [],
  targetEntities: [],
  targetRelations: [],
  extraInstructions: "",
  focusLabels: [],
  graphScope: "",
  phases: "",
  packChunks: "",
  onEmpty: "",
  copyAbbreviationsFromRunId: "",
};

const FILL_ENTITY_TARGETS = ["Layer", "Material"];
const FILL_RELATION_TARGETS = [
  "HAS_LAYER",
  "MADE_OF",
  "IS_COMPOUND",
  "HAS_CHARACTERISTIC",
];

const FILL_RELATIONS_INSTRUCTIONS = [
  "Разбери стек устройства вида {ITO|…|mCP co 20% 2-Eu|…} на отдельные слои (Layer) в порядке записи.",
  "Для каждого слоя создай Material и связь MADE_OF.",
  "Для смеси host/guest (например «mCP co 20% 2-Eu») заведи отдельные материалы, укажи роль guest/host и долю.",
  "Гостевой допант свяжи с уже существующим Compound через IS_COMPOUND.",
  "Не создавай заново Device и Compound с теми же label — используй их как якоря.",
  "Создай недостающие Layer/Material и рёбра HAS_LAYER, MADE_OF, IS_COMPOUND, HAS_CHARACTERISTIC к уже принятым узлам.",
].join("\n");

const GRAPH_SCOPE_LABELS: Record<string, string> = {
  accepted: "принятый граф",
  focus: "якоря и соседи",
  none: "без графа в промпте",
};

const PHASE_OPTION_LABELS: Record<string, string> = {
  both: "сущности и связи",
  entities: "только сущности",
  relations: "только связи",
};

const ON_EMPTY_LABELS: Record<string, string> = {
  accept: "принять пустой шаг",
  warn: "предупредить",
  fail: "считать ошибкой",
};

function toggleValue(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
}

function uniqueIds(ids: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const id of ids) {
    if (!id || seen.has(id)) continue;
    seen.add(id);
    result.push(id);
  }
  return result;
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
}

function collectRecipeSections(
  defaults: Record<string, unknown> | undefined,
  steps: RecipeStep[],
): string[] {
  const ids: string[] = [];
  const push = (value: unknown) => {
    for (const item of stringList(value)) ids.push(item);
  };
  push(defaults?.section_include);
  push(defaults?.section_exclude);
  for (const step of steps) {
    push(step.section_include);
    push(step.section_exclude);
  }
  const seen = new Set<string>();
  const ordered: string[] = [];
  for (const key of Object.keys(SECTION_LABELS)) {
    if (ids.includes(key) && !seen.has(key)) {
      seen.add(key);
      ordered.push(key);
    }
  }
  for (const id of ids) {
    if (!seen.has(id)) {
      seen.add(id);
      ordered.push(id);
    }
  }
  return ordered.length > 0 ? ordered : Object.keys(SECTION_LABELS);
}

function defaultFocusLabels(nodes: GraphNode[]): string[] {
  const wanted = new Set(["Device", "Compound"]);
  const labels: string[] = [];
  const seen = new Set<string>();
  for (const node of nodes) {
    if (node.status !== "accepted") continue;
    if (!wanted.has(node.entity_type || "")) continue;
    const label = (node.label || "").trim();
    if (!label || seen.has(label)) continue;
    seen.add(label);
    labels.push(label);
  }
  return labels;
}

function acceptedFocusChoices(nodes: GraphNode[]): { label: string; typeName: string }[] {
  const choices: { label: string; typeName: string }[] = [];
  const seen = new Set<string>();
  for (const node of nodes) {
    if (node.status !== "accepted") continue;
    const label = (node.label || "").trim();
    if (!label || seen.has(label)) continue;
    seen.add(label);
    choices.push({
      label,
      typeName: node.entity_type_name || node.entity_type || "",
    });
  }
  return choices;
}

function overlayToPayload(form: OverlayForm): ExtractionRunOptions {
  const options: ExtractionRunOptions = {};
  if (form.sectionInclude.length > 0) options.section_include = [...form.sectionInclude];
  if (form.targetEntities.length > 0) options.target_entities = [...form.targetEntities];
  if (form.targetRelations.length > 0) options.target_relations = [...form.targetRelations];
  const instructions = form.extraInstructions.trim();
  if (instructions) options.extra_instructions = instructions;
  if (form.focusLabels.length > 0) options.focus_labels = [...form.focusLabels];
  if (form.graphScope) options.graph_scope = form.graphScope;
  if (form.phases) options.phases = form.phases;
  if (form.packChunks === "true") options.pack_chunks = true;
  if (form.packChunks === "false") options.pack_chunks = false;
  if (form.onEmpty) options.on_empty = form.onEmpty;
  if (form.copyAbbreviationsFromRunId !== "") {
    options.copy_abbreviations_from_run_id = form.copyAbbreviationsFromRunId;
  }
  return options;
}

function isEmptyOptions(options: ExtractionRunOptions | null | undefined): boolean {
  if (!options) return true;
  return Object.keys(options).length === 0;
}

function fillRelationsOverlay(runs: ExtractionRun[], nodes: GraphNode[]): OverlayForm {
  const latestId = runs[0]?.id;
  return {
    sectionInclude: ["experimental"],
    targetEntities: [...FILL_ENTITY_TARGETS],
    targetRelations: [...FILL_RELATION_TARGETS],
    extraInstructions: FILL_RELATIONS_INSTRUCTIONS,
    focusLabels: defaultFocusLabels(nodes),
    graphScope: "focus",
    phases: "relations",
    packChunks: "false",
    onEmpty: "fail",
    copyAbbreviationsFromRunId: latestId ?? "",
  };
}

function schemaTypeName(
  schema: ProjectSchema | null,
  id: string,
  kind: "entity" | "relation",
): string {
  if (kind === "entity") return schema?.entity_types.find((item) => item.id === id)?.name || id;
  return schema?.relation_types.find((item) => item.id === id)?.name || id;
}

function formatOptionsLines(
  options: ExtractionRunOptions,
  schema: ProjectSchema | null,
): string[] {
  const lines: string[] = [];
  if (options.phases) lines.push(`Фазы: ${PHASE_OPTION_LABELS[options.phases] || options.phases}`);
  if (options.section_include?.length) {
    lines.push(
      `Секции: ${options.section_include.map((id) => SECTION_LABELS[id] || id).join(", ")}`,
    );
  }
  if (options.section_exclude?.length) {
    lines.push(
      `Исключить секции: ${options.section_exclude.map((id) => SECTION_LABELS[id] || id).join(", ")}`,
    );
  }
  if (options.target_entities?.length) {
    lines.push(
      `Сущности: ${options.target_entities.map((id) => schemaTypeName(schema, id, "entity")).join(", ")}`,
    );
  }
  if (options.target_relations?.length) {
    lines.push(
      `Связи: ${options.target_relations.map((id) => schemaTypeName(schema, id, "relation")).join(", ")}`,
    );
  }
  if (options.graph_scope) {
    lines.push(`Граф в промпте: ${GRAPH_SCOPE_LABELS[options.graph_scope] || options.graph_scope}`);
  }
  if (options.focus_labels?.length) {
    lines.push(`Якоря: ${options.focus_labels.join(", ")}`);
  }
  if (options.pack_chunks === false) lines.push("Чанки по секциям отдельно");
  if (options.pack_chunks === true) lines.push("Чанки склеиваются");
  if (options.on_empty) {
    lines.push(`Пустой ответ: ${ON_EMPTY_LABELS[options.on_empty] || options.on_empty}`);
  }
  if (options.copy_abbreviations_from_run_id != null) {
    lines.push(`Словарь из прогона #${options.copy_abbreviations_from_run_id}`);
  }
  return lines;
}

function CheckboxList({
  items,
  selected,
  onToggle,
  emptyText,
}: {
  items: { id: string; label: string }[];
  selected: string[];
  onToggle: (id: string) => void;
  emptyText: string;
}) {
  if (items.length === 0) return <p className="muted">{emptyText}</p>;
  return (
    <div className="option-checks">
      {items.map((item) => (
        <label key={item.id} className="check-item">
          <input
            type="checkbox"
            checked={selected.includes(item.id)}
            onChange={() => onToggle(item.id)}
          />
          <span>{item.label}</span>
        </label>
      ))}
    </div>
  );
}

export default function ExtractRunPane({
  documentId,
  onMessage,
  onError,
  onRunFinished,
  onGoToReview,
  onActiveRunChange,
}: Props) {
  const [profiles, setProfiles] = useState<LlmProfile[]>([]);
  const [bundled, setBundled] = useState<RecipeBrief[]>([]);
  const [recipes, setRecipes] = useState<RecipeInfo[]>([]);
  const [recipeId, setRecipeId] = useState("example_coordination_extract");
  const [profileId, setProfileId] = useState("");
  const [strategy, setStrategy] = useState("");
  const [steps, setSteps] = useState<RecipeStep[]>([]);
  const [pipeline, setPipeline] = useState<string[]>([]);
  const [selectedStep, setSelectedStep] = useState("");
  const [promptPreview, setPromptPreview] = useState("");
  const [run, setRun] = useState<ExtractionRun | null>(null);
  const [runs, setRuns] = useState<ExtractionRun[]>([]);
  const [schema, setSchema] = useState<ProjectSchema | null>(null);
  const [recipeDefaults, setRecipeDefaults] = useState<Record<string, unknown>>({});
  const [acceptedNodes, setAcceptedNodes] = useState<GraphNode[]>([]);
  const [preset, setPreset] = useState<RunPreset>("recipe");
  const [overlay, setOverlay] = useState<OverlayForm>(EMPTY_OVERLAY);
  const [busy, setBusy] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(true);
  const didAutoSelect = useRef(false);
  const manualStep = useRef(false);
  const seenRunId = useRef<number | null | undefined>(undefined);
  const requestGen = useRef(0);
  const pendingFocusRef = useRef(false);
  const pendingAbbrRef = useRef(false);

  const refresh = useCallback(async () => {
    const gen = ++requestGen.current;
    const [prof, rec, runList, graph] = await Promise.all([
      api.listProfiles(),
      api.listRecipes(),
      api.listExtractionRuns(documentId),
      api.getDocumentGraph(documentId).catch(() => ({
        document_id: documentId,
        nodes: [] as GraphNode[],
        edges: [],
      })),
    ]);
    if (gen !== requestGen.current) return;
    setProfiles(prof.profiles);
    setBundled(rec.bundled);
    setRecipes(rec.recipes);
    setRuns(runList.runs);
    setAcceptedNodes(graph.nodes.filter((node) => node.status === "accepted"));
    setRun((prev) => {
      if (!prev) return prev;
      const latest = runList.runs.find((item) => item.id === prev.id);
      if (!latest) return prev;
      return {
        ...latest,
        options: latest.options ?? prev.options,
      };
    });
    setProfileId((prev) => prev || prof.profiles[0]?.id || "");
  }, [documentId]);

  useEffect(() => {
    void refresh().catch((err) =>
      onError?.(err instanceof Error ? err.message : String(err)),
    );
  }, [refresh, onError]);

  useEffect(() => {
    void api
      .currentSchema()
      .then((res) => setSchema(res.schema))
      .catch(() => setSchema(null));
  }, []);

  const displayRecipeId = run?.recipe_id || recipeId;

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const apply = (
        nextSteps: RecipeStep[],
        nextPipeline: string[],
        defaults?: Record<string, unknown>,
      ) => {
        if (cancelled) return;
        setSteps(nextSteps);
        setPipeline(nextPipeline);
        setRecipeDefaults(defaults || {});
        const fallback = String(defaults?.strategy || "");
        if (fallback) setStrategy((prev) => prev || fallback);
      };
      try {
        const res = await api.getBundledRecipe(displayRecipeId);
        apply(res.recipe.steps || [], res.recipe.pipeline || [], res.recipe.defaults);
      } catch {
        const fromDb = recipes.find((item) => item.id === displayRecipeId);
        if (fromDb) {
          apply(
            fromDb.steps || [],
            fromDb.pipeline || fromDb.steps?.map((step) => step.id) || [],
            fromDb.defaults,
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [displayRecipeId, recipes]);

  useEffect(() => {
    const profile = profiles.find((item) => item.id === profileId);
    if (!profile || strategy) return;
    void api.defaultStrategy(profile.intelligence_level).then((res) => {
      setStrategy((prev) => prev || res.strategy);
    });
  }, [profileId, profiles, strategy]);

  useEffect(() => {
    didAutoSelect.current = false;
    seenRunId.current = undefined;
    setRun(null);
    setRuns([]);
    setPromptPreview("");
    setPreset("recipe");
    setOverlay(EMPTY_OVERLAY);
    setAcceptedNodes([]);
    pendingFocusRef.current = false;
    pendingAbbrRef.current = false;
  }, [documentId]);

  useEffect(() => {
    if (run || runs.length === 0 || didAutoSelect.current) return;
    didAutoSelect.current = true;
    const latest = runs[0];
    setRun(latest);
    setRecipeId(latest.recipe_id);
    if (latest.llm_profile_id) setProfileId(latest.llm_profile_id);
    if (latest.strategy) setStrategy(latest.strategy);
  }, [run, runs]);

  useEffect(() => {
    if (seenRunId.current === (run?.id ?? null)) return;
    seenRunId.current = run?.id ?? null;
    setSettingsOpen(run == null);
  }, [run?.id]);

  useEffect(() => {
    manualStep.current = false;
  }, [run?.id, run?.status, run?.current_step_id]);

  useEffect(() => {
    if (run) onActiveRunChange?.(run.id);
  }, [run, onActiveRunChange]);

  useEffect(() => {
    if (!pendingFocusRef.current || preset !== "fill_relations") return;
    const labels = defaultFocusLabels(acceptedNodes);
    if (labels.length === 0) return;
    pendingFocusRef.current = false;
    setOverlay((prev) =>
      prev.focusLabels.length > 0 ? prev : { ...prev, focusLabels: labels },
    );
  }, [acceptedNodes, preset]);

  useEffect(() => {
    if (!pendingAbbrRef.current || preset !== "fill_relations") return;
    const latest = runs[0]?.id;
    if (latest == null) return;
    pendingAbbrRef.current = false;
    setOverlay((prev) =>
      prev.copyAbbreviationsFromRunId === ""
        ? { ...prev, copyAbbreviationsFromRunId: latest }
        : prev,
    );
  }, [preset, runs]);

  const pipelineIds = resolvePipelineIds(run, pipeline, steps);

  useEffect(() => {
    if (!run || manualStep.current) return;
    const ids = resolvePipelineIds(run, pipeline, steps);
    const next = computePrimaryAction(run, ids, steps);
    const picked =
      next.kind === "start" || next.kind === "next" || next.kind === "retry"
        ? next.stepId
        : next.kind === "review" && next.continueStepId
          ? next.continueStepId
          : run.current_step_id || ids[0] || "";
    if (picked) setSelectedStep(picked);
  }, [run, pipeline, steps]);

  const recipeTitle =
    bundled.find((item) => item.id === recipeId)?.name ||
    recipes.find((item) => item.id === recipeId)?.name ||
    recipeId;
  const profileTitle =
    profiles.find((item) => item.id === profileId)?.name || (profileId ? profileId : "не выбран");

  const recipeOptions = [
    ...bundled.map((item) => ({ id: item.id, label: `${item.name} (шаблон)` })),
    ...recipes.map((item) => ({ id: item.id, label: `${item.name} (проект #${item.db_id})` })),
  ];
  const seen = new Set<string>();
  const uniqueOptions = recipeOptions.filter((option) => {
    if (seen.has(option.id)) return false;
    seen.add(option.id);
    return true;
  });

  const applyRecipePreset = () => {
    pendingFocusRef.current = false;
    pendingAbbrRef.current = false;
    setPreset("recipe");
    setOverlay(EMPTY_OVERLAY);
  };

  const applyFillRelationsPreset = () => {
    const next = fillRelationsOverlay(runs, acceptedNodes);
    pendingFocusRef.current = next.focusLabels.length === 0;
    pendingAbbrRef.current = next.copyAbbreviationsFromRunId === "";
    setPreset("fill_relations");
    setOverlay(next);
  };

  const onPreview = async () => {
    if (!selectedStep) return;
    setBusy(true);
    try {
      const res = await api.previewPrompt({
        document_id: documentId,
        recipe_id: displayRecipeId,
        step_id: selectedStep,
        run_id: run?.id,
      });
      setPromptPreview(res.preview.prompt);
      onMessage?.(
        `Превью промпта (${res.preview.prompt_template}), чанков: ${res.preview.chunks_count}`,
      );
    } catch (err) {
      onError?.(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const onCreateRun = async () => {
    setBusy(true);
    try {
      const options = overlayToPayload(overlay);
      const res = await api.createExtractionRun({
        document_id: documentId,
        recipe_id: recipeId,
        llm_profile_id: profileId || undefined,
        strategy: strategy || undefined,
        options,
      });
      setRun({ ...res.run, options: res.run.options ?? options });
      setRecipeId(res.run.recipe_id);
      await refresh();
      onMessage?.(
        `Прогон #${res.run.id} создан (${strategyLabel(res.run.strategy)})`,
      );
    } catch (err) {
      onError?.(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const showFailedRun = async (runId: number, err: unknown) => {
    onError?.(err instanceof Error ? err.message : String(err));
    try {
      const latest = await api.getExtractionRun(runId);
      setRun((prev) => ({
        ...latest.run,
        options: latest.run.options ?? prev?.options,
      }));
      await refresh();
    } catch {
      // текст ошибки уже показан
    }
  };

  const executeStep = async (stepId: string) => {
    if (!run) {
      onError?.("Сначала создайте прогон");
      return;
    }
    if (!stepId) {
      onError?.("Выберите шаг");
      return;
    }
    armRunNotification();
    markRunBusy("Шаг выполняется…");
    setSelectedStep(stepId);
    setBusy(true);
    try {
      const res = await api.runExtractionStep(run.id, { step_id: stepId });
      setRun((prev) => ({
        ...res.run,
        options: res.run.options ?? prev?.options,
      }));
      await refresh();
      const name = stepName(steps, res.step_id);
      const hasReviewCards = res.created_nodes.length > 0 || res.created_edges.length > 0;
      let notice: string;
      if (hasReviewCards) {
        notice = `Шаг «${name}»: +${res.created_nodes.length} узлов, +${res.created_edges.length} связей — смотрите вкладку «Проверка»`;
      } else if ((res.abbreviation_map || []).length > 0) {
        notice = `Шаг «${name}»: словарь обозначений (${res.abbreviation_map.length}). Проверьте список ниже и запустите следующий шаг.`;
      } else {
        notice = `Шаг «${name}»: сущностей не создано.`;
      }
      onMessage?.(notice);
      notifyRunFinished(`Шаг «${name}» завершён`, notice);
      onRunFinished?.(run.id, { hasReviewCards, stepId: res.step_id });
    } catch (err) {
      notifyRunFinished(
        "Шаг завершился с ошибкой",
        err instanceof Error ? err.message : String(err),
      );
      await showFailedRun(run.id, err);
    } finally {
      setBusy(false);
    }
  };

  const onRunPipeline = async () => {
    if (!run) {
      onError?.("Сначала создайте прогон");
      return;
    }
    armRunNotification();
    markRunBusy("Пайплайн выполняется…");
    setBusy(true);
    try {
      const res = await api.runExtractionPipeline(run.id);
      setRun((prev) => ({
        ...res.run,
        options: res.run.options ?? prev?.options,
      }));
      await refresh();
      const last = res.steps[res.steps.length - 1];
      const hasReviewCards = res.steps.some((item) => item.nodes > 0 || item.edges > 0);
      const notice = `Пайплайн: ${res.steps.map((item) => stepName(steps, item.step_id)).join(" → ") || "пусто"}`;
      onMessage?.(notice);
      notifyRunFinished("Пайплайн завершён", notice);
      onRunFinished?.(run.id, { hasReviewCards, stepId: last?.step_id });
    } catch (err) {
      notifyRunFinished(
        "Пайплайн завершился с ошибкой",
        err instanceof Error ? err.message : String(err),
      );
      await showFailedRun(run.id, err);
    } finally {
      setBusy(false);
    }
  };

  const focusRun = (item: ExtractionRun) => {
    manualStep.current = false;
    setRun(item);
    setPromptPreview("");
    setRecipeId(item.recipe_id);
    if (item.llm_profile_id) setProfileId(item.llm_profile_id);
    if (item.strategy) setStrategy(item.strategy);
  };

  const onPrimary = async (action: PrimaryAction) => {
    if (action.kind === "create") {
      await onCreateRun();
      return;
    }
    if (action.kind === "review") {
      if (run) onGoToReview?.(run.id);
      return;
    }
    if (action.kind === "start" || action.kind === "next" || action.kind === "retry") {
      if (action.stepId) await executeStep(action.stepId);
    }
  };

  const action = computePrimaryAction(run, pipelineIds, steps);
  const tokens = run ? tokenTotals(run) : null;
  const runRecipeName = run
    ? bundled.find((item) => item.id === run.recipe_id)?.name ||
      recipes.find((item) => item.id === run.recipe_id)?.name ||
      run.recipe_id
    : "";
  const runProfileName = run
    ? profiles.find((item) => item.id === run.llm_profile_id)?.name || run.llm_profile_id
    : "";
  const runCounts = run ? countLine(run.counts) : null;
  const runOptionLines = run && !isEmptyOptions(run.options) ? formatOptionsLines(run.options!, schema) : [];
  const emptyResult = run?.stats?.empty_result === true;
  const sectionChoices = collectRecipeSections(recipeDefaults, steps);
  const entityChoices = uniqueIds([
    ...(schema?.entity_types.map((item) => item.id) ?? []),
    ...(preset === "fill_relations" ? FILL_ENTITY_TARGETS : []),
    ...overlay.targetEntities,
  ]);
  const relationChoices = uniqueIds([
    ...(schema?.relation_types.map((item) => item.id) ?? []),
    ...(preset === "fill_relations" ? FILL_RELATION_TARGETS : []),
    ...overlay.targetRelations,
  ]);
  const focusChoices = acceptedFocusChoices(acceptedNodes);

  const settingsFields = (
    <>
      <label>
        Рецепт
        <select value={recipeId} onChange={(e) => setRecipeId(e.target.value)}>
          {uniqueOptions.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        LLM-профиль
        <select value={profileId} onChange={(e) => setProfileId(e.target.value)}>
          <option value="">—</option>
          {profiles.map((profile) => (
            <option key={profile.id} value={profile.id}>
              {profile.name} ({profile.intelligence_level})
            </option>
          ))}
        </select>
      </label>
      <label>
        Стратегия
        <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
          <option value="">из профиля / рецепта</option>
          {Object.entries(STRATEGY_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <div className="option-group">
        <span className="option-group-title">Пресет опций</span>
        <div className="row">
          <button
            type="button"
            className={preset === "recipe" ? "btn" : "btn secondary"}
            onClick={applyRecipePreset}
          >
            По рецепту
          </button>
          <button
            type="button"
            className={preset === "fill_relations" ? "btn" : "btn secondary"}
            onClick={applyFillRelationsPreset}
          >
            Дозаполнить связи
          </button>
        </div>
        <p className="muted preset-help">
          {preset === "fill_relations"
            ? "Оверлей: только связи (можно включить сущности), слои и материалы, якоря из принятых узлов, эксперимент, пустой шаг — ошибка."
            : "Пустой оверлей: секции, типы и фазы как в рецепте."}
        </p>
      </div>
      <div className="option-group">
        <span className="option-group-title">Секции</span>
        <p className="muted preset-help">Не выбрано — как в рецепте.</p>
        <CheckboxList
          items={sectionChoices.map((id) => ({
            id,
            label: SECTION_LABELS[id] || id,
          }))}
          selected={overlay.sectionInclude}
          onToggle={(id) =>
            setOverlay((prev) => ({
              ...prev,
              sectionInclude: toggleValue(prev.sectionInclude, id),
            }))
          }
          emptyText="В рецепте нет списка секций."
        />
      </div>
      <div className="option-group">
        <span className="option-group-title">Типы сущностей</span>
        <p className="muted preset-help">Не выбрано — цели шага из рецепта.</p>
        <CheckboxList
          items={entityChoices.map((id) => ({
            id,
            label: schemaTypeName(schema, id, "entity"),
          }))}
          selected={overlay.targetEntities}
          onToggle={(id) =>
            setOverlay((prev) => ({
              ...prev,
              targetEntities: toggleValue(prev.targetEntities, id),
            }))
          }
          emptyText="Нет типов сущностей в схеме."
        />
      </div>
      <div className="option-group">
        <span className="option-group-title">Типы связей</span>
        <p className="muted preset-help">Не выбрано — цели шага из рецепта.</p>
        <CheckboxList
          items={relationChoices.map((id) => ({
            id,
            label: schemaTypeName(schema, id, "relation"),
          }))}
          selected={overlay.targetRelations}
          onToggle={(id) =>
            setOverlay((prev) => ({
              ...prev,
              targetRelations: toggleValue(prev.targetRelations, id),
            }))
          }
          emptyText="Нет типов связей в схеме."
        />
      </div>
      <div className="option-group">
        <span className="option-group-title">Якоря (принятые узлы)</span>
        <p className="muted preset-help">
          Для области «якоря и соседи» отметьте label из принятого графа статьи.
        </p>
        <CheckboxList
          items={focusChoices.map((item) => ({
            id: item.label,
            label: item.typeName ? `${item.label} (${item.typeName})` : item.label,
          }))}
          selected={overlay.focusLabels}
          onToggle={(id) =>
            setOverlay((prev) => ({
              ...prev,
              focusLabels: toggleValue(prev.focusLabels, id),
            }))
          }
          emptyText="Нет принятых узлов у этой статьи."
        />
      </div>
      <label>
        Дополнительные инструкции
        <textarea
          rows={6}
          value={overlay.extraInstructions}
          onChange={(e) =>
            setOverlay((prev) => ({ ...prev, extraInstructions: e.target.value }))
          }
          placeholder="Пусто — только инструкции рецепта"
        />
      </label>
      <div className="grid-2">
        <label>
          Фазы
          <select
            value={overlay.phases}
            onChange={(e) =>
              setOverlay((prev) => ({
                ...prev,
                phases: e.target.value as OverlayForm["phases"],
              }))
            }
          >
            <option value="">как в рецепте</option>
            <option value="both">{PHASE_OPTION_LABELS.both}</option>
            <option value="entities">{PHASE_OPTION_LABELS.entities}</option>
            <option value="relations">{PHASE_OPTION_LABELS.relations}</option>
          </select>
        </label>
        <label>
          Граф в промпте
          <select
            value={overlay.graphScope}
            onChange={(e) =>
              setOverlay((prev) => ({
                ...prev,
                graphScope: e.target.value as OverlayForm["graphScope"],
              }))
            }
          >
            <option value="">как сейчас (принятый)</option>
            <option value="accepted">{GRAPH_SCOPE_LABELS.accepted}</option>
            <option value="focus">{GRAPH_SCOPE_LABELS.focus}</option>
            <option value="none">{GRAPH_SCOPE_LABELS.none}</option>
          </select>
        </label>
        <label>
          Склейка чанков
          <select
            value={overlay.packChunks}
            onChange={(e) =>
              setOverlay((prev) => ({
                ...prev,
                packChunks: e.target.value as OverlayForm["packChunks"],
              }))
            }
          >
            <option value="">как в рецепте</option>
            <option value="true">склеивать</option>
            <option value="false">по секциям отдельно</option>
          </select>
        </label>
        <label>
          Пустой ответ модели
          <select
            value={overlay.onEmpty}
            onChange={(e) =>
              setOverlay((prev) => ({
                ...prev,
                onEmpty: e.target.value as OverlayForm["onEmpty"],
              }))
            }
          >
            <option value="">как сейчас (принять)</option>
            <option value="accept">{ON_EMPTY_LABELS.accept}</option>
            <option value="warn">{ON_EMPTY_LABELS.warn}</option>
            <option value="fail">{ON_EMPTY_LABELS.fail}</option>
          </select>
        </label>
      </div>
      {preset === "fill_relations" ? (
        <p className="muted preset-help">
          Сначала только связи. Если слоёв ещё нет — выберите «сущности и связи».
        </p>
      ) : null}
      <label>
        Словарь обозначений
        <select
          value={overlay.copyAbbreviationsFromRunId === "" ? "" : String(overlay.copyAbbreviationsFromRunId)}
          onChange={(e) =>
            setOverlay((prev) => ({
              ...prev,
              copyAbbreviationsFromRunId: e.target.value ? Number(e.target.value) : "",
            }))
          }
        >
          <option value="">не копировать</option>
          {runs.map((item) => (
            <option key={item.id} value={item.id}>
              прогон #{item.id}
            </option>
          ))}
        </select>
      </label>
    </>
  );

  return (
    <div className="stack extract-pane">
      <details
        className="settings-block"
        open={settingsOpen}
      >
        <summary
          onClick={(event) => {
            event.preventDefault();
            setSettingsOpen((open) => !open);
          }}
        >
          {run
            ? `Рецепт ${recipeTitle} · Профиль ${profileTitle} · стратегия ${
                strategy ? strategyLabel(strategy) : "по умолчанию"
              }`
            : "Настройки прогона"}
        </summary>
        <div className="stack">{settingsFields}</div>
      </details>

      {run ? (
        <section className="run-card">
          <div className="row run-card-head">
            <RunStageIndicator
              runId={run.id}
              status={run.status}
              pipeline={pipelineIds}
              stepsTotal={run.steps_total}
              stepIndex={run.step_index}
              currentStepId={run.current_step_id}
              stepsHistory={run.steps_history}
              steps={steps}
            />
            <span className={runStatusBadgeClass(run.status)}>{runStatusLabel(run.status)}</span>
          </div>
          <p className="muted run-meta">
            {runRecipeName}
            {runProfileName ? ` · ${runProfileName}` : ""}
            {` · ${strategyLabel(run.strategy)}`}
            {tokens ? ` · токены ${tokens.prompt} + ${tokens.completion}` : ""}
          </p>
          {runCounts ? <p className="muted run-meta">{runCounts}</p> : null}
          <div className="run-options">
            <span className="option-group-title">Опции прогона</span>
            {isEmptyOptions(run.options) ? (
              <p className="muted run-meta">По рецепту</p>
            ) : (
              <ul className="run-options-list">
                {runOptionLines.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            )}
            {run.options?.extra_instructions ? (
              <p className="run-options-text">{run.options.extra_instructions}</p>
            ) : null}
          </div>
          {emptyResult ? (
            <p className="run-empty-warn">Шаг не дал новых узлов и связей.</p>
          ) : null}
          {typeof run.stats?.incomplete_device_stacks_summary === "string" &&
          run.stats.incomplete_device_stacks_summary ? (
            <p className="run-empty-warn">{String(run.stats.incomplete_device_stacks_summary)}</p>
          ) : null}
          {run.error_message ? <p className="error">{run.error_message}</p> : null}
        </section>
      ) : null}

      <div className="stack">
        <h3>Шаги пайплайна</h3>
        <PipelineStepper
          steps={steps}
          pipeline={pipeline}
          run={run}
          schema={schema}
          selectedStep={selectedStep}
          onSelect={(stepId) => {
            manualStep.current = true;
            setSelectedStep(stepId);
          }}
        />
      </div>

      {busy ? (
        <p className="muted">
          Запрос к модели… локальный прогон может занять около минуты. Если свернуть вкладку,
          браузер сообщит об окончании.
        </p>
      ) : null}

      <div className="row">
        {action.kind === "done" || action.kind === "cancelled" ? (
          <>
            <button type="button" className="btn secondary" disabled>
              {action.label}
            </button>
            <button type="button" className="btn" disabled={busy} onClick={() => void onCreateRun()}>
              Новый прогон
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              className="btn"
              disabled={
                busy ||
                action.kind === "running" ||
                ((action.kind === "start" || action.kind === "next" || action.kind === "retry") &&
                  !action.stepId)
              }
              onClick={() => void onPrimary(action)}
            >
              {busy ? "Запуск…" : action.label}
            </button>
            {action.kind === "review" && action.continueStepId && action.continueLabel ? (
              <button
                type="button"
                className="btn secondary"
                disabled={busy}
                onClick={() => void executeStep(action.continueStepId || "")}
              >
                {action.continueLabel}
              </button>
            ) : null}
          </>
        )}
      </div>

      <details className="extra-actions">
        <summary>Дополнительно</summary>
        <div className="row">
          {run && action.kind !== "done" && action.kind !== "cancelled" ? (
            <button
              type="button"
              className="btn secondary"
              disabled={busy}
              onClick={() => void onCreateRun()}
            >
              Новый прогон
            </button>
          ) : null}
          <button
            type="button"
            className="btn secondary"
            disabled={busy || !selectedStep}
            onClick={() => void onPreview()}
          >
            Превью промпта
          </button>
          <button
            type="button"
            className="btn secondary"
            disabled={busy || !run || !selectedStep}
            onClick={() => void executeStep(selectedStep)}
          >
            Прогнать выбранный шаг
          </button>
          <button
            type="button"
            className="btn secondary"
            disabled={busy || !run}
            onClick={() => void onRunPipeline()}
          >
            Пройти весь пайплайн
          </button>
        </div>
      </details>

      {run?.abbreviation_map?.length ? (
        <details open>
          <summary>Словарь обозначений ({run.abbreviation_map.length})</summary>
          <p className="muted">
            Словарь проверяется здесь и в граф как сущности не попадает. Чтобы получить
            карточки, запустите следующий шаг.
          </p>
          <ul className="list compact">
            {run.abbreviation_map.map((item, index) => (
              <li key={`${item.code}-${index}`}>
                <code>{item.code}</code> → {item.expansion}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {promptPreview ? (
        <details open>
          <summary>Превью промпта</summary>
          <pre className="prompt-preview">{promptPreview}</pre>
        </details>
      ) : null}

      {runs.length > 0 ? (
        <section className="stack">
          <h3>История прогонов</h3>
          <div className="stack">
            {runs.map((item) => {
              const ids = item.pipeline?.length ? item.pipeline : [];
              const progress = doneStepCount(item, ids);
              const progressText = progress.total > 0 ? `${progress.done}/${progress.total}` : "";
              const counts = countLine(item.counts);
              const when = formatRunDate(item.updated_at || item.created_at);
              const name =
                bundled.find((entry) => entry.id === item.recipe_id)?.name ||
                recipes.find((entry) => entry.id === item.recipe_id)?.name ||
                item.recipe_id;
              return (
                <button
                  key={item.id}
                  type="button"
                  className={`run-history-card${run?.id === item.id ? " selected" : ""}`}
                  onClick={() => focusRun(item)}
                >
                  <span className="row run-card-head">
                    <strong>Прогон #{item.id}</strong>
                    <span className={runStatusBadgeClass(item.status)}>
                      {runStatusLabel(item.status)}
                    </span>
                  </span>
                  <span className="muted run-meta">
                    {name} · {strategyLabel(item.strategy)}
                    {progressText ? ` · ${progressText}` : ""}
                    {when ? ` · ${when}` : ""}
                  </span>
                  {counts ? <span className="muted run-meta">{counts}</span> : null}
                  {item.error_message ? <span className="error">{item.error_message}</span> : null}
                </button>
              );
            })}
          </div>
        </section>
      ) : null}
    </div>
  );
}
