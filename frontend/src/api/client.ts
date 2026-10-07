export type Project = {
  path: string;
  name: string;
  schema_template: string | null;
  active_schema: string | null;
  created_at: string;
  updated_at: string;
  db_ready: boolean;
  papers_dir: string;
  cache_dir: string;
  exports_dir: string;
  llm_profiles_count: number;
};

export type RecentProject = {
  path: string;
  name: string;
  opened_at: string;
  exists: string;
};

export type LlmProfile = {
  id: string;
  name: string;
  base_url: string;
  model: string;
  price_in_per_1m: number;
  price_out_per_1m: number;
  context_size: number;
  intelligence_level: string;
  supports_json_mode: boolean;
  has_api_key: boolean;
};

export type AttributeDef = {
  id: string;
  db_id?: number;
  name: string;
  type: string;
  required: boolean;
  unit?: string | null;
  enum_values: string[];
  llm_hint: string;
  default?: string | null;
  order_index?: number;
};

export type EntityType = {
  id: string;
  db_id?: number;
  name: string;
  description: string;
  label_attribute?: string | null;
  order_index?: number;
  attributes: AttributeDef[];
};

export type RelationType = {
  id: string;
  db_id?: number;
  name: string;
  description: string;
  from: string;
  to: string;
  cardinality: string;
  attributes: AttributeDef[] | Record<string, unknown>[];
  llm_hint: string;
  order_index?: number;
};

export type ProjectSchema = {
  schema_version_id: number;
  version: number;
  template_id: string | null;
  name: string;
  is_active: boolean;
  created_at: string | null;
  entity_types: EntityType[];
  relation_types: RelationType[];
};

export type SchemaTemplateInfo = {
  id: string;
  name: string;
  version: string;
  description: string;
  imports: string[];
  path: string;
};

export type Evidence = {
  id: number;
  target_kind: string;
  node_id: number | null;
  edge_id: number | null;
  attribute_key: string | null;
  block_id: number | null;
  quote: string;
  page: number | null;
  bbox: number[] | null;
  char_start: number | null;
  char_end: number | null;
  created_by: string;
  verified: boolean;
  created_at: string | null;
};

export type GraphNode = {
  id: number;
  document_id: number;
  entity_type_id: number;
  entity_type: string | null;
  entity_type_name: string | null;
  label: string;
  attributes: Record<string, unknown>;
  status: string;
  canonical_id: string | null;
  run_id: number | null;
  pos_x: number;
  pos_y: number;
  evidences: Evidence[];
  created_at: string | null;
  updated_at: string | null;
};

export type GraphEdge = {
  id: number;
  document_id: number;
  relation_type_id: number;
  relation_type: string | null;
  relation_type_name: string | null;
  source_node_id: number;
  target_node_id: number;
  attributes: Record<string, unknown>;
  status: string;
  run_id: number | null;
  evidences: Evidence[];
  created_at: string | null;
  updated_at: string | null;
};

export type DocumentInfo = {
  id: number;
  title: string;
  doi: string | null;
  status: string;
  source_path: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type PaperBrief = {
  id: number;
  title: string;
  status: string;
  doi: string | null;
  error_message: string | null;
  source_stem: string;
  source_path?: string | null;
  main_file: {
    id: number;
    filename: string;
    relative_path: string;
    page_count: number | null;
  } | null;
  esi_files_count: number;
  esi_hints_count: number;
  sections_count: number;
  has_gold?: boolean;
  updated_at: string | null;
};

export type FullExtractStep = {
  step_id: string;
  phase?: string | null;
  nodes: number;
  edges: number;
};

export type FullExtractItem = {
  document_id: number;
  stage: string;
  run_id: number | null;
  nodes?: number;
  edges?: number;
  tokens?: number;
  error?: string | null;
  steps?: FullExtractStep[];
  incomplete_device_stacks?: Array<{
    device_id?: number;
    label?: string;
    layer_count?: number;
    missing_roles?: string[];
    present_roles?: string[];
  }>;
  stack_warning?: string | null;
};

export type FullExtractResult = {
  done: number;
  failed: number;
  total: number;
  items: FullExtractItem[];
};

export type PaperBlock = {
  id: number;
  block_type: string;
  kind: string;
  text: string;
  page: number | null;
  bbox: number[] | null;
  page_width: number | null;
  page_height: number | null;
  order_index: number;
  meta: Record<string, unknown>;
};

export type PaperSection = {
  id: number;
  section_type: string;
  title: string;
  page_start: number | null;
  page_end: number | null;
  useful: boolean;
  useful_default: boolean;
  order_index: number;
  doc_file_id: number | null;
  blocks: PaperBlock[];
};

export type EsiHint = {
  kind: string;
  value: string;
  snippet?: string;
  manual?: boolean;
};

export type PaperStructure = {
  id: number;
  title: string;
  status: string;
  doi: string | null;
  error_message: string | null;
  esi_hints: EsiHint[];
  meta: Record<string, unknown>;
  files: {
    id: number;
    role: string;
    relative_path: string;
    filename: string;
    page_count: number | null;
  }[];
  sections: PaperSection[];
  references: {
    id: number;
    raw_text: string;
    doi: string | null;
    page: number | null;
    order_index: number;
  }[];
};

export type FigureClass = {
  id: number;
  slug: string;
  name: string;
  description: string;
  is_builtin: boolean;
  created_at: string | null;
};

export type FigureItem = {
  id: number;
  document_id: number;
  page: number;
  caption: string;
  image_path: string;
  bbox: number[] | null;
  source_kind: string;
  class_id: number | null;
  class_slug: string | null;
  class_name: string | null;
  confidence: number | null;
  manual_label: boolean;
  uncertain: boolean;
  order_index: number;
  meta: Record<string, unknown>;
  created_at: string | null;
  image_url: string;
};

export type JobInfo = {
  id: number;
  kind: string;
  status: string;
  payload: Record<string, unknown>;
  progress: number;
  message: string;
  result: Record<string, unknown>;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type LeaderboardRow = {
  llm_profile_id: string;
  strategy?: string;
  name: string;
  model: string | null;
  n_docs: number;
  avg_f1: number;
  avg_precision: number;
  avg_recall: number;
  avg_attribute_accuracy: number | null;
  avg_edge_f1: number | null;
  avg_verified_quote_rate: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  evaluations: EvaluationRow[];
};

export type EvaluationRow = {
  id: number;
  extraction_run_id: number;
  gold_snapshot_id: number | null;
  document_id: number;
  precision: number | null;
  recall: number | null;
  f1: number | null;
  attribute_accuracy: number | null;
  edge_f1: number | null;
  verified_quote_rate: number | null;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  metrics: Record<string, unknown>;
  created_at: string | null;
  run: {
    id: number | null;
    llm_profile_id: string | null;
    recipe_id: string | null;
    strategy: string | null;
    status: string | null;
  } | null;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail =
      typeof data?.detail === "string"
        ? data.detail
        : JSON.stringify(data?.detail ?? data);
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return data as T;
}

export const api = {
  health: () => request<{ status: string; version: string }>("/api/health"),
  currentProject: () =>
    request<{ project: Project | null }>("/api/projects/current"),
  recentProjects: () =>
    request<{ projects: RecentProject[] }>("/api/projects/recent"),
  createWithDialog: () =>
    request<{ cancelled: boolean; project: Project | null }>(
      "/api/projects/create-with-dialog",
      { method: "POST" },
    ),
  openWithDialog: () =>
    request<{ cancelled: boolean; project: Project | null }>(
      "/api/projects/open-with-dialog",
      { method: "POST" },
    ),
  openPath: (path: string) =>
    request<{ project: Project }>("/api/projects/open", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  createPath: (path: string, name?: string) =>
    request<{ project: Project }>("/api/projects/create", {
      method: "POST",
      body: JSON.stringify({ path, name }),
    }),
  closeProject: () =>
    request<{ ok: boolean }>("/api/projects/close", { method: "POST" }),
  listProfiles: () =>
    request<{ profiles: LlmProfile[] }>("/api/llm/profiles"),
  addProfile: (body: Record<string, unknown>) =>
    request<{ profile: LlmProfile }>("/api/llm/profiles", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateProfile: (id: string, body: Record<string, unknown>) =>
    request<{ profile: LlmProfile }>(`/api/llm/profiles/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteProfile: (id: string) =>
    request<{ ok: boolean }>(`/api/llm/profiles/${id}`, { method: "DELETE" }),
  testProfile: (id: string) =>
    request<{
      ok: boolean;
      model?: string;
      reply_preview?: string;
      error?: string;
    }>(`/api/llm/profiles/${id}/test`, { method: "POST" }),

  // Schema
  listSchemaTemplates: () =>
    request<{ templates: SchemaTemplateInfo[] }>("/api/schema/templates"),
  getSchemaTemplate: (id: string) =>
    request<{ template: Record<string, unknown> }>(`/api/schema/templates/${id}`),
  currentSchema: () =>
    request<{ schema: ProjectSchema | null }>("/api/schema/current"),
  applySchemaTemplate: (template_id: string) =>
    request<{ schema: ProjectSchema }>("/api/schema/apply", {
      method: "POST",
      body: JSON.stringify({ template_id }),
    }),
  upsertEntityType: (body: Record<string, unknown>) =>
    request<{ schema: ProjectSchema }>("/api/schema/entity-types", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteEntityType: (typeId: string) =>
    request<{ schema: ProjectSchema }>(`/api/schema/entity-types/${typeId}`, {
      method: "DELETE",
    }),
  upsertAttribute: (entityTypeId: string, body: Record<string, unknown>) =>
    request<{ schema: ProjectSchema }>(
      `/api/schema/entity-types/${entityTypeId}/attributes`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  deleteAttribute: (entityTypeId: string, attrId: string) =>
    request<{ schema: ProjectSchema }>(
      `/api/schema/entity-types/${entityTypeId}/attributes/${attrId}`,
      { method: "DELETE" },
    ),
  upsertRelationType: (body: Record<string, unknown>) =>
    request<{ schema: ProjectSchema }>("/api/schema/relation-types", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteRelationType: (typeId: string) =>
    request<{ schema: ProjectSchema }>(`/api/schema/relation-types/${typeId}`, {
      method: "DELETE",
    }),

  // Graph / documents
  listDocuments: () =>
    request<{ documents: DocumentInfo[] }>("/api/graph/documents"),
  createDocument: (body: { title: string; doi?: string }) =>
    request<{ document: DocumentInfo }>("/api/graph/documents", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getDocumentGraph: (documentId: number) =>
    request<{ document_id: number; nodes: GraphNode[]; edges: GraphEdge[] }>(
      `/api/graph/documents/${documentId}/graph`,
    ),
  createNode: (documentId: number, body: Record<string, unknown>) =>
    request<{ node: GraphNode }>(`/api/graph/documents/${documentId}/nodes`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateNode: (nodeId: number, body: Record<string, unknown>) =>
    request<{ node: GraphNode }>(`/api/graph/nodes/${nodeId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteNode: (nodeId: number) =>
    request<{ ok: boolean }>(`/api/graph/nodes/${nodeId}`, { method: "DELETE" }),
  createEdge: (documentId: number, body: Record<string, unknown>) =>
    request<{ edge: GraphEdge }>(`/api/graph/documents/${documentId}/edges`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateEdge: (edgeId: number, body: Record<string, unknown>) =>
    request<{ edge: GraphEdge }>(`/api/graph/edges/${edgeId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteEdge: (edgeId: number) =>
    request<{ ok: boolean }>(`/api/graph/edges/${edgeId}`, { method: "DELETE" }),
  createEvidence: (body: Record<string, unknown>) =>
    request<{ evidence: Evidence }>("/api/graph/evidences", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  saveGold: (documentId: number, body?: { label?: string; only_accepted?: boolean }) =>
    request<{ snapshot: Record<string, unknown> }>(
      `/api/graph/documents/${documentId}/gold`,
      { method: "POST", body: JSON.stringify(body ?? {}) },
    ),
  listGold: (documentId: number) =>
    request<{ snapshots: Record<string, unknown>[] }>(
      `/api/graph/documents/${documentId}/gold`,
    ),
  exportGraph: (documentId: number) =>
    request<{ export: Record<string, unknown> }>(
      `/api/graph/documents/${documentId}/export`,
      { method: "POST" },
    ),

  // Papers / ingest (M1)
  listPapers: () => request<{ papers: PaperBrief[] }>("/api/papers"),
  indexPapers: () =>
    request<{ papers: PaperBrief[]; count: number }>("/api/papers/index", {
      method: "POST",
    }),
  uploadPaper: async (file: File) => {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch("/api/papers/upload", {
      method: "POST",
      body,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(
        typeof data?.detail === "string"
          ? data.detail
          : JSON.stringify(data?.detail ?? data),
      );
    }
    return data as { paper: PaperBrief };
  },
  ingestPaper: (id: number) =>
    request<{ paper: PaperStructure }>(`/api/papers/${id}/ingest`, {
      method: "POST",
    }),
  getPaper: (id: number) =>
    request<{ paper: PaperStructure }>(`/api/papers/${id}`),
  paperFileUrl: (id: number, opts?: { fileId?: number; role?: string }) => {
    const params = new URLSearchParams();
    if (opts?.fileId != null) params.set("file_id", String(opts.fileId));
    if (opts?.role) params.set("role", opts.role);
    const q = params.toString();
    return `/api/papers/${id}/file${q ? `?${q}` : ""}`;
  },
  attachEsi: async (id: number, file: File) => {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch(`/api/papers/${id}/esi/attach`, {
      method: "POST",
      body,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(
        typeof data?.detail === "string"
          ? data.detail
          : JSON.stringify(data?.detail ?? data),
      );
    }
    return data as { paper: PaperStructure };
  },
  saveEsiLink: (id: number, url: string) =>
    request<{ paper: PaperStructure }>(`/api/papers/${id}/esi/link`, {
      method: "POST",
      body: JSON.stringify({ url }),
    }),
  deleteEsiLink: (id: number, url: string) =>
    request<{ paper: PaperStructure }>(`/api/papers/${id}/esi/link`, {
      method: "DELETE",
      body: JSON.stringify({ url }),
    }),
  deleteEsiFile: (id: number, fileId: number) =>
    request<{ paper: PaperStructure }>(`/api/papers/${id}/esi/files/${fileId}`, {
      method: "DELETE",
    }),

  // Figures (M5)
  figuresStatus: () =>
    request<{
      embedding: { backend: string; dim: number; is_stub: boolean; note: string };
      confidence_threshold: number;
      detection: { method: string; yolo_doclayout: boolean; note: string };
    }>("/api/figures/status"),
  listFigureClasses: () =>
    request<{ classes: FigureClass[] }>("/api/figures/classes"),
  createFigureClass: (body: {
    slug: string;
    name: string;
    description?: string;
  }) =>
    request<{ class: FigureClass }>("/api/figures/classes", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listFigures: (opts?: {
    document_id?: number;
    uncertain_only?: boolean;
    class_id?: number;
  }) => {
    const params = new URLSearchParams();
    if (opts?.document_id != null)
      params.set("document_id", String(opts.document_id));
    if (opts?.uncertain_only) params.set("uncertain_only", "true");
    if (opts?.class_id != null) params.set("class_id", String(opts.class_id));
    const q = params.toString();
    return request<{ figures: FigureItem[]; count: number }>(
      `/api/figures${q ? `?${q}` : ""}`,
    );
  },
  extractFigures: (documentId: number, autoClassify = true) =>
    request<{ figures: FigureItem[]; count: number }>(
      `/api/figures/documents/${documentId}/extract?auto_classify=${autoClassify}`,
      { method: "POST" },
    ),
  classifyFigures: (opts?: {
    document_id?: number;
    only_unlabeled?: boolean;
  }) => {
    const params = new URLSearchParams();
    if (opts?.document_id != null)
      params.set("document_id", String(opts.document_id));
    if (opts?.only_unlabeled === false) params.set("only_unlabeled", "false");
    const q = params.toString();
    return request<{ classified: number; uncertain: number }>(
      `/api/figures/classify${q ? `?${q}` : ""}`,
      { method: "POST" },
    );
  },
  assignFigureClass: (figureId: number, classId: number | null) =>
    request<{ figure: FigureItem }>(`/api/figures/${figureId}/assign`, {
      method: "POST",
      body: JSON.stringify({ class_id: classId }),
    }),

  // Extraction / recipes / review (M3)
  listRecipes: () =>
    request<{
      recipes: RecipeInfo[];
      bundled: RecipeBrief[];
      project_files: RecipeBrief[];
    }>("/api/extraction/recipes"),
  getBundledRecipe: (id: string) =>
    request<{ recipe: RecipeBody }>(`/api/extraction/recipes/bundled/${id}`),
  getRecipe: (dbId: number) =>
    request<{ recipe: RecipeInfo }>(`/api/extraction/recipes/${dbId}`),
  saveRecipe: (recipe: Record<string, unknown>, activate = true) =>
    request<{ recipe: RecipeInfo }>("/api/extraction/recipes", {
      method: "POST",
      body: JSON.stringify({ recipe, activate }),
    }),
  generateRecipe: (body: Record<string, unknown>) =>
    request<{ recipe: RecipeInfo | RecipeBody; generated: RecipeBody }>(
      "/api/extraction/recipes/generate",
      { method: "POST", body: JSON.stringify(body) },
    ),
  previewPrompt: (body: {
    document_id: number;
    recipe_id?: string;
    step_id: string;
    run_id?: number;
  }) =>
    request<{ preview: PromptPreview }>("/api/extraction/recipes/preview-prompt", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  defaultStrategy: (intelligence_level: string) =>
    request<{ intelligence_level: string; strategy: string }>(
      `/api/extraction/strategies/default?intelligence_level=${encodeURIComponent(intelligence_level)}`,
    ),
  createExtractionRun: (body: {
    document_id: number;
    recipe_id?: string;
    llm_profile_id?: string;
    strategy?: string;
    options?: ExtractionRunOptions;
  }) =>
    request<{ run: ExtractionRun }>("/api/extraction/runs", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listExtractionRuns: (documentId?: number) =>
    request<{ runs: ExtractionRun[] }>(
      `/api/extraction/runs${documentId != null ? `?document_id=${documentId}` : ""}`,
    ),
  getExtractionRun: (runId: number) =>
    request<{ run: ExtractionRun }>(`/api/extraction/runs/${runId}`),
  runExtractionStep: (
    runId: number,
    body?: { step_id?: string; phase?: string; dry_run?: boolean },
  ) =>
    request<{
      run: ExtractionRun;
      step_id: string;
      strategy: string;
      created_nodes: GraphNode[];
      created_edges: GraphEdge[];
      abbreviation_map: AbbreviationItem[];
      prompts_preview: string[];
    }>(`/api/extraction/runs/${runId}/steps`, {
      method: "POST",
      body: JSON.stringify(body ?? {}),
    }),
  runExtractionPipeline: (runId: number, stop_after_step?: string) =>
    request<{ run: ExtractionRun; steps: { step_id: string; nodes: number; edges: number }[] }>(
      `/api/extraction/runs/${runId}/pipeline`,
      {
        method: "POST",
        body: JSON.stringify({ stop_after_step }),
      },
    ),
  getReviewQueue: (documentId: number, runId?: number, status?: string) =>
    request<ReviewQueue>(
      `/api/extraction/review/${documentId}?${new URLSearchParams({
        ...(runId != null ? { run_id: String(runId) } : {}),
        ...(status ? { status } : {}),
      }).toString()}`.replace(/\?$/, ""),
    ),
  reviewAccept: (kind: string, id: number) =>
    request<{ item: GraphNode | GraphEdge }>("/api/extraction/review/accept", {
      method: "POST",
      body: JSON.stringify({ kind, id }),
    }),
  reviewReject: (kind: string, id: number) =>
    request<{ item: GraphNode | GraphEdge }>("/api/extraction/review/reject", {
      method: "POST",
      body: JSON.stringify({ kind, id }),
    }),
  reviewReopen: (kind: string, id: number) =>
    request<{ item: GraphNode | GraphEdge }>("/api/extraction/review/reopen", {
      method: "POST",
      body: JSON.stringify({ kind, id }),
    }),
  reviewEdit: (
    kind: string,
    id: number,
    payload: Record<string, unknown>,
    accept = true,
  ) =>
    request<{ item: GraphNode | GraphEdge }>("/api/extraction/review/edit", {
      method: "POST",
      body: JSON.stringify({ kind, id, payload, accept }),
    }),
  reviewMerge: (keep_id: number, merge_id: number) =>
    request<{ node: GraphNode }>("/api/extraction/review/merge", {
      method: "POST",
      body: JSON.stringify({ keep_id, merge_id }),
    }),
  verifyQuote: (quote: string, text: string, threshold = 90) =>
    request<{ verified: boolean; score: number; matched_text: string | null }>(
      "/api/extraction/verify-quote",
      {
        method: "POST",
        body: JSON.stringify({ quote, text, threshold }),
      },
    ),

  // Chem enrichment (M6)
  chemStatus: () =>
    request<{ status: ChemStatus }>("/api/chem/status"),
  chemValidate: (body: { smiles?: string; inchi?: string }) =>
    request<{ result: ChemValidateResult }>("/api/chem/validate", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  chemSvg: (body: { smiles: string; width?: number; height?: number }) =>
    request<{ result: ChemSvgResult }>("/api/chem/svg", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  chemNameToStructure: (body: {
    name: string;
    prefer_opsin?: boolean;
    use_pubchem?: boolean;
  }) =>
    request<{ result: NameToStructureResult }>("/api/chem/name-to-structure", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  chemCrossref: (doi: string) =>
    request<{ result: CrossrefResult }>("/api/chem/crossref", {
      method: "POST",
      body: JSON.stringify({ doi }),
    }),
  chemApplyStructure: (body: {
    node_id: number;
    smiles?: string;
    inchi?: string;
    iupac?: string;
  }) =>
    request<{ node: GraphNode; ok: boolean }>("/api/chem/apply-structure", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  chemApplyCrossref: (body: {
    node_id: number;
    doi?: string;
    title?: string;
  }) =>
    request<{ node: GraphNode; ok: boolean }>("/api/chem/apply-crossref", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // Assistant (M6)
  assistantTools: () =>
    request<{ tools: unknown[] }>("/api/assistant/tools"),
  assistantThread: (documentId: number) =>
    request<AssistantThread>(`/api/assistant/threads/${documentId}`),
  assistantChat: (body: {
    document_id: number;
    content: string;
    llm_profile_id?: string;
    max_rounds?: number;
  }) =>
    request<AssistantChatResponse>("/api/assistant/chat", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  assistantConfirm: (body: {
    document_id: number;
    mutations: PendingMutation[];
  }) =>
    request<
      AssistantThread & {
        ok: boolean;
        applied: { id?: string; action?: string; result?: unknown }[];
        errors: { id?: string; action?: string; error: string }[];
      }
    >("/api/assistant/confirm", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  assistantReject: (body: { document_id: number; mutation_ids: string[] }) =>
    request<AssistantThread>("/api/assistant/reject", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // Evaluation / batch / leaderboard (M4)
  estimateBatch: (body: {
    document_ids: number[];
    llm_profile_ids: string[];
    recipe_id?: string | null;
  }) =>
    request<{ estimate: Record<string, unknown> }>("/api/evaluation/estimate", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  startBatch: (body: {
    document_ids: number[];
    llm_profile_ids: string[];
    recipe_id?: string | null;
    strategy?: string | null;
    evaluate?: boolean;
  }) =>
    request<{ job: JobInfo }>("/api/evaluation/batch", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  startFullExtract: (body: {
    document_ids: number[];
    llm_profile_id: string;
    recipe_id?: string | null;
    strategy?: string | null;
    ingest_missing?: boolean;
    reparse?: boolean;
  }) =>
    request<{ job: JobInfo }>("/api/evaluation/full-extract", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listEvalJobs: (kind?: string) => {
    const q = kind ? `?kind=${encodeURIComponent(kind)}` : "";
    return request<{ jobs: JobInfo[] }>(`/api/evaluation/jobs${q}`);
  },
  getEvalJob: (id: number) =>
    request<{ job: JobInfo }>(`/api/evaluation/jobs/${id}`),
  cancelJob: (id: number) =>
    request<{ job: JobInfo }>(`/api/evaluation/jobs/${id}/cancel`, {
      method: "POST",
    }),
  resumeJob: (id: number) =>
    request<{ job: JobInfo }>(`/api/evaluation/jobs/${id}/resume`, {
      method: "POST",
    }),
  jobEvents: (id: number) =>
    new EventSource(`/api/evaluation/jobs/${id}/events`),
  evaluateRun: (
    runId: number,
    body?: { gold_snapshot_id?: number | null; persist?: boolean },
  ) =>
    request<Record<string, unknown>>(`/api/evaluation/runs/${runId}/evaluate`, {
      method: "POST",
      body: JSON.stringify(body || {}),
    }),
  listEvaluations: (opts?: { document_id?: number; llm_profile_id?: string }) => {
    const params = new URLSearchParams();
    if (opts?.document_id != null)
      params.set("document_id", String(opts.document_id));
    if (opts?.llm_profile_id)
      params.set("llm_profile_id", opts.llm_profile_id);
    const q = params.toString();
    return request<{ evaluations: unknown[] }>(
      `/api/evaluation/evaluations${q ? `?${q}` : ""}`,
    );
  },
  leaderboard: () =>
    request<{ leaderboard: LeaderboardRow[]; count: number }>(
      "/api/evaluation/leaderboard",
    ),
  listDuplicates: (entityType = "Compound", minScore = 0.75) =>
    request<{ suggestions: unknown[]; count: number }>(
      `/api/evaluation/duplicates?entity_type=${encodeURIComponent(entityType)}&min_score=${minScore}`,
    ),
  applyCanonical: (nodeIds: number[], canonicalId: string) =>
    request<{ nodes: GraphNode[]; canonical_id: string }>(
      "/api/evaluation/duplicates/apply",
      {
        method: "POST",
        body: JSON.stringify({ node_ids: nodeIds, canonical_id: canonicalId }),
      },
    ),
  exportCorpus: (body?: {
    document_ids?: number[] | null;
    include_sdf?: boolean;
  }) =>
    request<{ export: Record<string, unknown> }>("/api/evaluation/export", {
      method: "POST",
      body: JSON.stringify(body || {}),
    }),
};

export type AbbreviationItem = {
  code: string;
  expansion: string;
  quote?: string;
  block_hint?: string;
};

export type RecipeBrief = {
  id: string;
  name: string;
  version: string;
  schema_id: string;
  description: string;
  steps_count: number;
  source: string;
  path: string;
};

export type RecipeStep = {
  id: string;
  name: string;
  description?: string;
  instructions?: string;
  strategy?: string;
  enabled?: boolean;
  prompt_template?: string;
  output_key?: string;
  human_review?: boolean;
  targets?: {
    entities?: string[];
    relations?: string[];
    primary_entity?: string;
  };
  phases?: { name: string; prompt_template?: string; human_review?: boolean }[];
  section_include?: string[];
  section_exclude?: string[];
};

export type RecipeBody = {
  version: string;
  id: string;
  name: string;
  kind: string;
  schema_id: string;
  description?: string;
  defaults?: Record<string, unknown>;
  prompt_templates?: Record<string, string>;
  steps: RecipeStep[];
  pipeline?: string[];
};

export type RecipeInfo = {
  db_id: number;
  id: string;
  name: string;
  schema_id: string | null;
  version: string;
  description: string;
  is_active: boolean;
  source_path: string | null;
  steps: RecipeStep[];
  pipeline: string[];
  defaults: Record<string, unknown>;
  prompt_templates: string[];
  body?: RecipeBody;
  created_at: string | null;
  updated_at: string | null;
};

export type RunStepHistory = {
  step_id: string;
  status: "running" | "done" | "failed";
  started_at: string | null;
  finished_at: string | null;
  nodes: number;
  edges: number;
  abbreviations: number;
  prompt_tokens: number;
  completion_tokens: number;
  error: string | null;
};

export type RunCounts = {
  proposed: number;
  accepted: number;
  rejected: number;
  nodes: number;
  edges: number;
};

export type ExtractionRunOptions = {
  section_include?: string[];
  section_exclude?: string[];
  target_entities?: string[];
  target_relations?: string[];
  extra_instructions?: string;
  focus_labels?: string[];
  graph_scope?: "accepted" | "focus" | "none";
  phases?: "both" | "entities" | "relations";
  pack_chunks?: boolean;
  on_empty?: "accept" | "warn" | "fail";
  copy_abbreviations_from_run_id?: number;
};

export type ExtractionRun = {
  id: number;
  document_id: number;
  recipe_db_id: number | null;
  recipe_id: string;
  llm_profile_id: string;
  strategy: string;
  status: string;
  current_step_id: string | null;
  abbreviation_map: AbbreviationItem[];
  stats: Record<string, unknown>;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
  pipeline?: string[];
  steps_total?: number;
  /** 1-based; 0, если шаг ещё неизвестен. */
  step_index?: number;
  steps_history?: RunStepHistory[];
  counts?: RunCounts;
  options?: ExtractionRunOptions;
};

export type PromptPreview = {
  step_id: string;
  prompt_template: string;
  prompt: string;
  context_keys: string[];
  chunks_count: number;
  json_schema_preview?: string;
};

export type ReviewCard = {
  kind: "node" | "edge" | string;
  id: number;
  run_id: number | null;
  label: string | null;
  type: string | null;
  type_name: string | null;
  attributes: Record<string, unknown>;
  status: string;
  quote: string;
  verified: boolean;
  block_id: number | null;
  page: number | null;
  bbox: number[] | null;
  evidence_id?: number;
  source_node_id?: number;
  target_node_id?: number;
  source_label?: string | null;
  target_label?: string | null;
  source_type?: string | null;
  target_type?: string | null;
  source_status?: string | null;
  target_status?: string | null;
  payload: GraphNode | GraphEdge;
};

export type DuplicateSuggestion = {
  keep_id: number;
  merge_id: number;
  score: number;
  label_a: string;
  label_b: string;
  entity_type: string | null;
  reason: string;
};

export type ReviewQueue = {
  document_id: number;
  run_id: number | null;
  run_status?: string | null;
  current_step_id?: string | null;
  status_filter?: string;
  abbreviation_map?: AbbreviationItem[];
  cards: ReviewCard[];
  duplicates: DuplicateSuggestion[];
  counts: { nodes: number; edges: number; total: number };
  pipeline?: string[];
  steps_total?: number;
  /** 1-based; 0, если шаг ещё неизвестен. */
  step_index?: number;
  steps_history?: RunStepHistory[];
  status_counts?: {
    proposed: number;
    accepted: number;
    rejected: number;
    manual: number;
    other: number;
    no_evidence: number;
  };
};

export type ChemStatus = {
  rdkit: { available: boolean; note: string };
  opsin: { available: boolean; note: string };
  pubchem: { available: boolean; note: string };
  crossref: { available: boolean; note: string };
};

export type ChemValidateResult = {
  ok?: boolean;
  valid?: boolean;
  smiles?: string;
  inchi?: string;
  canonical_smiles?: string | null;
  backend?: string;
  stub?: boolean;
  error?: string | null;
  note?: string;
  smiles_check?: ChemValidateResult;
  inchi_check?: ChemValidateResult;
  svg?: ChemSvgResult;
  rdkit_available?: boolean;
};

export type ChemSvgResult = {
  ok: boolean;
  svg: string | null;
  backend: string;
  stub?: boolean;
  note?: string;
  error?: string | null;
};

export type StructureProposal = {
  smiles?: string;
  inchi?: string;
  iupac?: string;
  title?: string;
  source?: string;
  name?: string;
  needs_confirm?: boolean;
};

export type NameToStructureResult = {
  ok: boolean;
  name: string;
  proposals: StructureProposal[];
  needs_confirm?: boolean;
  opsin_available?: boolean;
  errors?: string[];
  note?: string;
};

export type CrossrefResult = {
  ok: boolean;
  doi?: string;
  title?: string | null;
  authors?: string | null;
  year?: number | null;
  container_title?: string | null;
  error?: string;
  suggested_attributes?: { doi?: string; title?: string | null };
  needs_confirm?: boolean;
};

export type AssistantMessage = {
  role: string;
  content?: string | null;
  tool_calls?: unknown;
  tool_call_id?: string;
  name?: string;
};

export type AssistantEvent = {
  id: string;
  kind: "user" | "assistant" | "tool" | "decision" | string;
  content: string;
  tool?: string;
  mutation_id?: string;
  status?: string;
};

export type PendingMutation = {
  id?: string;
  needs_confirm?: boolean;
  mutating?: boolean;
  tool?: string;
  action?: string;
  args?: Record<string, unknown>;
  summary?: string;
  status?: string;
};

export type AssistantChatResponse = {
  reply: string;
  messages: AssistantMessage[];
  pending_mutations: PendingMutation[];
  events: AssistantEvent[];
  tool_trace: unknown[];
  usage: Record<string, number>;
  document_id: number;
};

export type AssistantThread = {
  document_id: number;
  events: AssistantEvent[];
  pending_mutations: PendingMutation[];
};

