export type LanguageCode = "fa" | "en" | "de" | "fr";
export type CountryCode = "IR" | "DE" | "CA" | "EU";
export type ProjectType =
  | "residential"
  | "office"
  | "commercial"
  | "mixed_use"
  | "hospital"
  | "educational"
  | "hospitality"
  | "industrial"
  | "warehouse"
  | "retail"
  | "cultural"
  | "sports"
  | "data_center"
  | "laboratory"
  | "infrastructure"
  | "road_highway"
  | "bridge"
  | "tunnel"
  | "railway"
  | "airport"
  | "port_marine"
  | "dam_water"
  | "water_wastewater"
  | "power_energy"
  | "oil_gas"
  | "telecom"
  | "landscape_urban"
  | "renovation_fitout"
  | "other";
export type DocumentCategory = "tender" | "drawing" | "schedule" | "standard";
export type RiskSeverity = "high" | "medium" | "low";
export type UserRole = "admin" | "user";

export interface DocumentOut {
  id: number;
  category: DocumentCategory;
  original_name: string;
  content_type: string | null;
  size_bytes: number;
  has_text: boolean;
  ocr_applied?: boolean;
  extraction_phase?: string | null;
  extraction_progress?: number | null;
  extraction_message?: string | null;
  needs_manual_review?: boolean;
  created_at: string;
}

export interface ProjectOut {
  id: number;
  name: string;
  country: CountryCode;
  project_type?: ProjectType;
  country_profile_code?: string | null;
  ui_language: LanguageCode;
  report_language: LanguageCode;
  description: string | null;
  is_demo?: boolean;
  created_at: string;
  documents: DocumentOut[];
}

export interface FindingOut {
  id: number;
  code: string;
  category: string;
  severity: RiskSeverity;
  title: string;
  description: string;
  recommendation: string;
  financial_impact: string | null;
  schedule_impact: string | null;
  evidence: string | null;
  finding_category?: "risk" | "limitation" | "methodology" | "experience";
  risk_score?: number | null;
  source_excerpt?: string | null;
  cause_effect_chain?: string[];
  data_completeness_caveat?: string | null;
  estimated_impact?: string | null;
  source_layer?: string | null;
  confidence_score?: number | null;
  source_document_name?: string | null;
  source_page?: number | null;
}

export interface AnalysisOut {
  id: number;
  project_id: number;
  status: string;
  summary: string | null;
  report_language: LanguageCode;
  readiness_score: number;
  counts: Record<string, number>;
  counts_risk?: Record<string, number>;
  counts_experience?: number | null;
  aggregate_risk_score?: number | null;
  documents_with_limitations?: number | null;
  text_extraction_success_rate?: number | null;
  findings: FindingOut[];
  created_at: string;
}

export interface ProjectStandardOut {
  standard_code: string;
  title: string;
  standard_class: string;
  publisher: string;
  applicability_level: string;
  is_selected: boolean;
  selected_by: string;
  check_target: string;
  has_pdf?: boolean;
}

export interface ExperienceOut {
  id: number;
  experience_id: string;
  title: string;
  description: string;
  category: string;
  origin_kind: string;
  source: string | null;
  author: string | null;
  validation_status: string;
  confidence_level: string;
  related_risk_id: string | null;
  related_risk_category: string | null;
  related_project_types: string[];
  recommended_prevention: string | null;
  related_documents: string[];
  related_outcomes: string[];
  match_keywords: string[];
  version: number;
  is_active: boolean;
}

export interface ExperienceCreateBody {
  title: string;
  description?: string;
  category?: string;
  related_project_types?: string[];
  recommended_prevention?: string;
  match_keywords?: string[];
  confidence_level?: string;
  experience_id?: string;
}

export interface ExperienceBulkOut {
  created: ExperienceOut[];
  created_count: number;
  skipped: number;
}

export interface AuthMeOut {
  username: string;
  role: UserRole;
  is_admin: boolean;
  status?: "pending" | "approved" | "rejected";
  demo_project_id?: number | null;
  demo?: DemoLimitsOut | null;
}

export interface LoginOut {
  api_token: string;
  username: string;
  role: UserRole;
  is_admin: boolean;
  status?: "pending" | "approved" | "rejected";
  demo_project_id?: number | null;
  demo?: DemoLimitsOut | null;
}

export interface DemoLimitsOut {
  is_demo: boolean;
  expires_at: string | null;
  expired: boolean;
  days_left: number | null;
  max_documents: number;
  documents_used: number;
  documents_remaining: number;
  max_analyses: number;
  analyses_used: number;
  analyses_remaining: number;
  max_file_mb: number;
  max_total_mb: number;
  can_create_project: boolean;
  can_upload: boolean;
  can_analyze: boolean;
  locks: string[];
}

export interface DemoRequestOut {
  id: number;
  username: string;
  email: string | null;
  full_name: string | null;
  company: string | null;
  phone: string | null;
  message: string | null;
  status: "pending" | "approved" | "rejected";
  demo_project_id: number | null;
  created_at: string;
}

export interface DemoRequestActionOut {
  id: number;
  status: "pending" | "approved" | "rejected";
  demo_project_id: number | null;
  detail: string | null;
}

export interface CatalogStandardOut {
  standard_code: string;
  title: string;
  standard_class: string;
  publisher: string | null;
  original_name: string;
  content_type: string | null;
  size_bytes: number;
  has_pdf: boolean;
  created_at: string;
}

const TOKEN_KEY = "tenderrisk_api_token";

export function getApiToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setApiToken(token: string) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

function authHeaders(extra?: HeadersInit): HeadersInit {
  const token = getApiToken();
  const base: Record<string, string> = {};
  if (token) base["X-API-Token"] = token;
  if (extra) {
    if (extra instanceof Headers) {
      extra.forEach((v, k) => {
        base[k] = v;
      });
    } else if (Array.isArray(extra)) {
      for (const [k, v] of extra) base[k] = v;
    } else {
      Object.assign(base, extra);
    }
  }
  return base;
}

export interface UploadErrorOut {
  filename: string;
  detail: string;
}

export interface UploadBatchOut {
  documents: DocumentOut[];
  errors: UploadErrorOut[];
}

const API_BASE =
  import.meta.env.VITE_API_BASE || "https://construction-ai-production-1d78.up.railway.app/api";

/** Keep each request small so Railway/proxy do not time out on bulk uploads. */
export const UPLOAD_CHUNK_SIZE = 4;

const FILE_ACCEPT =
  ".pdf,.docx,.doc,.xlsx,.xls,.csv,.txt,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.dwg,.dxf,.rvt,.rfa,.rte,.rft,.ifc,.x81,.x82,.x83,.x84,.x85,.x86,.d81,.d82,.d83,.d84,.d85,.d86";

/** Per-category accept lists so the file picker surfaces the right formats. */
export const FILE_ACCEPT_BY_CATEGORY: Record<DocumentCategory, string> = {
  tender:
    ".pdf,.docx,.doc,.xlsx,.xls,.csv,.txt,.x81,.x82,.x83,.x84,.x85,.x86,.d81,.d82,.d83,.d84,.d85,.d86",
  drawing: ".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.dwg,.dxf,.rvt,.rfa,.rte,.rft,.ifc",
  schedule: ".pdf,.docx,.doc,.xlsx,.xls,.csv,.txt",
  standard: ".pdf,.docx,.doc,.xlsx,.xls,.csv,.txt",
};

export { FILE_ACCEPT };

export function parseApiError(err: unknown): string {
  if (!(err instanceof Error)) return String(err);
  const msg = err.message;
  try {
    const parsed = JSON.parse(msg) as { detail?: string | { msg?: string }[] };
    if (typeof parsed.detail === "string") return parsed.detail;
    if (Array.isArray(parsed.detail)) {
      return parsed.detail.map((d) => d.msg || String(d)).join(", ");
    }
  } catch {
    /* plain text */
  }
  return msg;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = authHeaders(init?.headers);
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") || "";
  if (!ct.includes("application/json")) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  listProjects: () => request<ProjectOut[]>("/projects"),
  createProject: (body: {
    name: string;
    country: CountryCode;
    project_type: ProjectType;
    ui_language: LanguageCode;
    report_language: LanguageCode;
    description?: string;
  }) =>
    request<ProjectOut>("/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getProject: (id: number) => request<ProjectOut>(`/projects/${id}`),
  updateProject: (
    id: number,
    body: Partial<{
      name: string;
      country: CountryCode;
      project_type: ProjectType;
      ui_language: LanguageCode;
      report_language: LanguageCode;
      description: string;
    }>,
  ) =>
    request<ProjectOut>(`/projects/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  authMe: () => request<AuthMeOut>("/auth/me"),
  login: (email: string, password: string) =>
    request<LoginOut>("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    }),
  requestDemo: (body: {
    full_name: string;
    email: string;
    password: string;
    company?: string;
    phone?: string;
    message?: string;
  }) =>
    request<DemoRequestOut>("/auth/demo-request", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  listDemoRequests: () => request<DemoRequestOut[]>("/auth/demo-requests"),
  approveDemoRequest: (userId: number) =>
    request<DemoRequestActionOut>(`/auth/demo-requests/${userId}/approve`, { method: "POST" }),
  rejectDemoRequest: (userId: number) =>
    request<DemoRequestActionOut>(`/auth/demo-requests/${userId}/reject`, { method: "POST" }),
  deleteDemoRequests: (userIds: number[]) =>
    request<{ deleted_count: number; deleted_ids: number[]; detail: string | null }>(
      "/auth/demo-requests/delete",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_ids: userIds }),
      },
    ),
  uploadDocuments: async (projectId: number, category: DocumentCategory, files: FileList | File[]) => {
    const form = new FormData();
    form.append("category", category);
    Array.from(files).forEach((f) => form.append("files", f, f.name));
    return request<UploadBatchOut>(`/projects/${projectId}/documents`, {
      method: "POST",
      body: form,
    });
  },
  uploadCatalogStandard: async (params: {
    file: File;
    standard_code: string;
    title: string;
    project_id?: number;
    standard_class?: string;
    publisher?: string;
  }) => {
    const form = new FormData();
    form.append("file", params.file, params.file.name);
    form.append("standard_code", params.standard_code);
    form.append("title", params.title);
    form.append("standard_class", params.standard_class || "technical");
    if (params.publisher) form.append("publisher", params.publisher);
    if (params.project_id != null) form.append("project_id", String(params.project_id));
    return request<CatalogStandardOut>("/standards/catalog", {
      method: "POST",
      body: form,
    });
  },
  downloadProjectStandardPdf: async (projectId: number, standardCode: string) => {
    const res = await fetch(
      `${API_BASE}/projects/${projectId}/standards/${encodeURIComponent(standardCode)}/download`,
      { headers: authHeaders() },
    );
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || res.statusText);
    }
    const blob = await res.blob();
    const cd = res.headers.get("content-disposition") || "";
    const match = /filename="?([^";]+)"?/i.exec(cd);
    const filename = match?.[1] || `${standardCode}.pdf`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
  listProjectStandards: (projectId: number) =>
    request<ProjectStandardOut[]>(`/projects/${projectId}/standards`),
  updateProjectStandards: (projectId: number, items: { standard_code: string; is_selected: boolean }[]) =>
    request<ProjectStandardOut[]>(`/projects/${projectId}/standards`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    }),
  deleteDocument: (projectId: number, documentId: number) =>
    request<{ ok: boolean }>(`/projects/${projectId}/documents/${documentId}`, {
      method: "DELETE",
    }),
  bulkDeleteDocuments: (projectId: number, documentIds: number[], force = false) =>
    request<{
      deleted_count: number;
      failed_count: number;
      results: Array<{
        document_id: number;
        original_name: string | null;
        status: "deleted" | "not_found" | "blocked_referenced" | "error";
        detail: string | null;
      }>;
    }>(`/projects/${projectId}/documents/bulk-delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_ids: documentIds, force }),
    }),
  reextractDocument: (projectId: number, documentId: number) =>
    request<DocumentOut>(`/projects/${projectId}/documents/${documentId}/reextract`, {
      method: "POST",
    }),
  analyze: (projectId: number, report_language?: LanguageCode) =>
    request<AnalysisOut>(`/projects/${projectId}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ report_language }),
    }),
  latestAnalysis: (projectId: number) =>
    request<AnalysisOut>(`/projects/${projectId}/analyses/latest`),
  listExperience: (params?: { active_only?: boolean; category?: string; q?: string }) => {
    const qs = new URLSearchParams();
    if (params?.active_only != null) qs.set("active_only", String(params.active_only));
    if (params?.category) qs.set("category", params.category);
    if (params?.q) qs.set("q", params.q);
    const suffix = qs.toString() ? `?${qs}` : "";
    return request<ExperienceOut[]>(`/experience${suffix}`);
  },
  createExperience: (body: ExperienceCreateBody) =>
    request<ExperienceOut>("/experience", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  bulkCreateExperience: (body: {
    raw_text?: string;
    items?: ExperienceCreateBody[];
    default_category?: string;
    default_project_types?: string[];
    auto_categorize?: boolean;
  }) =>
    request<ExperienceBulkOut>("/experience/bulk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  patchExperience: (
    experienceId: string,
    body: Partial<ExperienceCreateBody> & { is_active?: boolean },
  ) =>
    request<ExperienceOut>(`/experience/${encodeURIComponent(experienceId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteExperience: (experienceId: string) =>
    request<void>(`/experience/${encodeURIComponent(experienceId)}`, {
      method: "DELETE",
    }),
  suggestExperience: (text: string) =>
    request<{ category: string; match_keywords: string[]; title_suggestion: string | null }>(
      "/experience/suggest",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      },
    ),
  listExperienceCategories: () =>
    request<{ categories: { code: string; keywords_sample: string[] }[] }>("/experience/categories"),
};
