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
  finding_category?: "risk" | "limitation" | "methodology";
  risk_score?: number | null;
  source_excerpt?: string | null;
  cause_effect_chain?: string[];
  data_completeness_caveat?: string | null;
  estimated_impact?: string | null;
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
  ".pdf,.docx,.doc,.xlsx,.xls,.csv,.txt,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.dwg,.dxf";

export { FILE_ACCEPT };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
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
  uploadDocuments: async (projectId: number, category: DocumentCategory, files: FileList | File[]) => {
    const form = new FormData();
    form.append("category", category);
    Array.from(files).forEach((f) => form.append("files", f, f.name));
    return request<UploadBatchOut>(`/projects/${projectId}/documents`, {
      method: "POST",
      body: form,
    });
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
};
