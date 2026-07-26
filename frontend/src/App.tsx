import { useEffect, useMemo, useState } from "react";
import {
  api,
  FILE_ACCEPT,
  FILE_ACCEPT_BY_CATEGORY,
  UPLOAD_CHUNK_SIZE,
  type AnalysisOut,
  type CountryCode,
  type DocumentCategory,
  type LanguageCode,
  type ProjectOut,
  type ProjectStandardOut,
  type ProjectType,
} from "./api";
import { countryOptions, displayImpact, languageOptions, projectTypeOptions, t } from "./i18n";
import { BulkFileList } from "./BulkFileList";
import "./App.css";

const uploadCategories: { key: DocumentCategory; labelKey: string; optional?: boolean }[] = [
  { key: "tender", labelKey: "tenderDocs" },
  { key: "drawing", labelKey: "drawings", optional: true },
  { key: "schedule", labelKey: "schedule", optional: true },
  // standards has a dedicated selection panel + custom upload
];

function findingTier(f: { finding_category?: string | null; code?: string }): "limitation" | "methodology" | "risk" {
  const cat = f.finding_category || "risk";
  if (cat === "limitation" || cat === "methodology") return cat;
  const code = (f.code || "").toUpperCase();
  if (code.startsWith("EXTRACT-") || code.startsWith("OCR-")) return "limitation";
  if (code.startsWith("STD-SELECT")) return "methodology";
  return "risk";
}

function shortenText(text: string, max = 280): string {
  const t = (text || "").trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max)}…`;
}

type StagingItem = { key: string; file: File; selected: boolean };
type StagingQueue = { category: DocumentCategory; items: StagingItem[] };

function App() {
  const [uiLang, setUiLang] = useState<LanguageCode>(() => {
    return (localStorage.getItem("ui_lang") as LanguageCode) || "fa";
  });
  const [projects, setProjects] = useState<ProjectOut[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [project, setProject] = useState<ProjectOut | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisOut | null>(null);
  const [projectStandards, setProjectStandards] = useState<ProjectStandardOut[]>([]);
  const [standardsLoading, setStandardsLoading] = useState(false);
  const [standardsError, setStandardsError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{
    done: number;
    total: number;
    category: DocumentCategory;
  } | null>(null);
  const [staging, setStaging] = useState<StagingQueue | null>(null);
  const [notice, setNotice] = useState<{ text: string; kind: "success" | "error" } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [country, setCountry] = useState<CountryCode>("IR");
  const [projectType, setProjectType] = useState<ProjectType>("office");
  const [description, setDescription] = useState("");

  const dir = uiLang === "fa" ? "rtl" : "ltr";

  function setAppLang(lang: LanguageCode) {
    setUiLang(lang);
  }

  useEffect(() => {
    localStorage.setItem("ui_lang", uiLang);
    document.documentElement.lang = uiLang;
    document.documentElement.dir = dir;
  }, [uiLang, dir]);

  useEffect(() => {
    void refreshProjects();
  }, []);

  useEffect(() => {
    if (selectedId == null) {
      setProject(null);
      setAnalysis(null);
      setProjectStandards([]);
      setStandardsError(false);
      setStandardsLoading(false);
      setStaging(null);
      setNotice(null);
      return;
    }
    void loadProject(selectedId);
  }, [selectedId]);

  // Poll while any document is still in the OCR/extraction pipeline.
  useEffect(() => {
    if (!project) return;
    const busyDocs = project.documents.some((d) => {
      const phase = d.extraction_phase;
      return phase && phase !== "completed" && phase !== "failed";
    });
    if (!busyDocs) return;
    const timer = window.setInterval(() => {
      void loadProject(project.id);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [project]);

  async function refreshProjects() {
    try {
      const list = await api.listProjects();
      setProjects(list);
    } catch (e) {
      setError(String(e));
    }
  }

  async function loadStandards(id: number) {
    setStandardsLoading(true);
    setStandardsError(false);
    try {
      const standards = await api.listProjectStandards(id);
      setProjectStandards(standards);
    } catch {
      setProjectStandards([]);
      setStandardsError(true);
    } finally {
      setStandardsLoading(false);
    }
  }

  async function loadProject(id: number) {
    setError(null);
    try {
      const p = await api.getProject(id);
      setProject(p);
      // One language drives both UI and analysis for this project.
      setAppLang(p.report_language || p.ui_language);
      void loadStandards(id);
      try {
        const a = await api.latestAnalysis(id);
        setAnalysis(a);
      } catch {
        setAnalysis(null);
      }
    } catch (e) {
      setError(String(e));
    }
  }

  async function toggleStandard(code: string, next: boolean) {
    if (!project) return;
    // Optimistic + merge — never replace whole list (avoids reorder "hang" feel).
    setProjectStandards((rows) =>
      rows.map((s) =>
        s.standard_code === code
          ? { ...s, is_selected: next, selected_by: "user_override" }
          : s,
      ),
    );
    try {
      const updated = await api.updateProjectStandards(project.id, [
        { standard_code: code, is_selected: next },
      ]);
      if (updated.length) {
        const byCode = new Map(updated.map((u) => [u.standard_code, u]));
        setProjectStandards((rows) =>
          rows.map((s) => {
            const u = byCode.get(s.standard_code);
            return u ? { ...s, ...u } : s;
          }),
        );
      }
    } catch (e) {
      setProjectStandards((rows) =>
        rows.map((s) =>
          s.standard_code === code
            ? { ...s, is_selected: !next }
            : s,
        ),
      );
      setError(String(e));
    }
  }

  async function createProject() {
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const p = await api.createProject({
        name: name.trim(),
        country,
        project_type: projectType,
        ui_language: uiLang,
        report_language: uiLang,
        description: description.trim() || undefined,
      });
      setName("");
      setDescription("");
      await refreshProjects();
      setSelectedId(p.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveLanguages(nextLang?: LanguageCode) {
    if (!project) return;
    const lang = nextLang ?? uiLang;
    setBusy(true);
    try {
      const updated = await api.updateProject(project.id, {
        ui_language: lang,
        report_language: lang,
      });
      setProject(updated);
      setAppLang(lang);
      void loadStandards(project.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onUpload(category: DocumentCategory, files: FileList | null) {
    if (!project || !files?.length) return;
    const list = Array.from(files);
    setBusy(true);
    setError(null);
    setUploadProgress({ done: 0, total: list.length, category });
    const failed: string[] = [];
    try {
      for (let i = 0; i < list.length; i += UPLOAD_CHUNK_SIZE) {
        const chunk = list.slice(i, i + UPLOAD_CHUNK_SIZE);
        try {
          const result = await api.uploadDocuments(project.id, category, chunk);
          for (const err of result.errors) {
            failed.push(`${err.filename}: ${err.detail}`);
          }
        } catch (e) {
          failed.push(...chunk.map((f) => `${f.name}: ${String(e)}`));
        }
        setUploadProgress({
          done: Math.min(i + chunk.length, list.length),
          total: list.length,
          category,
        });
      }
      await loadProject(project.id);
      if (failed.length) {
        const preview = failed.slice(0, 5).join("\n");
        const more = failed.length > 5 ? `\n… +${failed.length - 5}` : "";
        setError(`${t(uiLang, "uploadPartial")}\n${preview}${more}`);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
      setUploadProgress(null);
    }
  }

  function queueFiles(category: DocumentCategory, files: FileList | null) {
    if (!files?.length) return;
    const incoming = Array.from(files).map((file, i) => ({
      key: `${category}-${Date.now()}-${i}-${file.name}-${file.size}`,
      file,
      selected: true,
    }));
    setStaging((prev) => {
      if (prev && prev.category === category) {
        const existingNames = new Set(prev.items.map((x) => `${x.file.name}:${x.file.size}`));
        const merged = [...prev.items];
        for (const item of incoming) {
          const id = `${item.file.name}:${item.file.size}`;
          if (!existingNames.has(id)) merged.push(item);
        }
        return { category, items: merged };
      }
      return { category, items: incoming };
    });
  }

  function setStagingSelected(all: boolean) {
    setStaging((prev) =>
      prev ? { ...prev, items: prev.items.map((x) => ({ ...x, selected: all })) } : prev,
    );
  }

  function toggleStagingItem(key: string, selected: boolean) {
    setStaging((prev) =>
      prev
        ? {
            ...prev,
            items: prev.items.map((x) => (x.key === key ? { ...x, selected } : x)),
          }
        : prev,
    );
  }

  function removeStagingUnchecked() {
    setStaging((prev) => {
      if (!prev) return prev;
      const items = prev.items.filter((x) => x.selected);
      return items.length ? { ...prev, items } : null;
    });
  }

  async function uploadFiles(category: DocumentCategory, files: File[]) {
    if (!files.length) {
      setError(t(uiLang, "stagingEmpty"));
      return;
    }
    const dt = new DataTransfer();
    files.forEach((f) => dt.items.add(f));
    setStaging(null);
    await onUpload(category, dt.files);
  }

  async function onDeleteDoc(docId: number) {
    if (!project) return;
    setBusy(true);
    setError(null);
    try {
      await api.deleteDocument(project.id, docId);
      await loadProject(project.id);
      setNotice({ text: t(uiLang, "bulkDeleteSuccess").replace("{n}", "1"), kind: "success" });
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onBulkDeleteFiles(ids: number[], opts: { force: boolean }) {
    if (!project) {
      return { deleted_count: 0, failed_count: ids.length, results: [] };
    }
    const result = await api.bulkDeleteDocuments(project.id, ids, opts.force);
    await loadProject(project.id);
    return result;
  }

  async function onReextract(docId: number) {
    if (!project) return;
    setBusy(true);
    setError(null);
    try {
      await api.reextractDocument(project.id, docId);
      await loadProject(project.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runAnalysis() {
    if (!project) return;
    setBusy(true);
    setError(null);
    try {
      const a = await api.analyze(project.id, uiLang);
      setAnalysis(a);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const docsByCategory = useMemo(() => {
    const map: Record<DocumentCategory, ProjectOut["documents"]> = {
      tender: [],
      drawing: [],
      schedule: [],
      standard: [],
    };
    project?.documents.forEach((d) => map[d.category].push(d));
    return map;
  }, [project]);

  return (
    <div className="app-shell" dir={dir}>
      <header className="hero">
        <div className="hero-inner">
          <p className="eyebrow">{t(uiLang, "audience")}</p>
          <h1>{t(uiLang, "appName")}</h1>
          <p className="tagline">{t(uiLang, "tagline")}</p>
          <div className="lang-bar">
            <label>
              {t(uiLang, "appLanguage")}
              <select
                value={uiLang}
                onChange={(e) => {
                  const lang = e.target.value as LanguageCode;
                  setAppLang(lang);
                  if (project) void saveLanguages(lang);
                }}
              >
                {languageOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <p className="muted lang-hint">{t(uiLang, "languageHint")}</p>
          </div>
        </div>
      </header>

      <main className="layout">
        {error && <div className="error-banner">{error}</div>}
        {notice && (
          <div className={notice.kind === "success" ? "success-banner" : "error-banner"} role="status">
            {notice.text}
            <button type="button" className="linkish" onClick={() => setNotice(null)}>
              ×
            </button>
          </div>
        )}

        {!selectedId && (
          <section className="panel">
            <h2>{t(uiLang, "newProject")}</h2>
            <div className="form-grid">
              <label>
                {t(uiLang, "projectName")}
                <input value={name} onChange={(e) => setName(e.target.value)} />
              </label>
              <label>
                {t(uiLang, "country")}
                <select
                  value={country}
                  onChange={(e) => setCountry(e.target.value as CountryCode)}
                >
                  {countryOptions.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t(uiLang, "projectType")}
                <select
                  value={projectType}
                  onChange={(e) => setProjectType(e.target.value as ProjectType)}
                >
                  {projectTypeOptions.map((o) => (
                    <option key={o.value} value={o.value}>
                      {t(uiLang, o.labelKey)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="full">
                {t(uiLang, "description")}
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={3}
                />
              </label>
            </div>
            <button className="primary" disabled={busy} onClick={() => void createProject()}>
              {t(uiLang, "create")}
            </button>

            <h2 className="mt">{t(uiLang, "projects")}</h2>
            {projects.length === 0 ? (
              <p className="muted">{t(uiLang, "empty")}</p>
            ) : (
              <ul className="project-list">
                {projects.map((p) => (
                  <li key={p.id}>
                    <div>
                      <strong>{p.name}</strong>
                      <span>
                        {p.country} · {p.project_type || "infrastructure"} · {p.documents.length}{" "}
                        {t(uiLang, "files")}
                      </span>
                    </div>
                    <button onClick={() => setSelectedId(p.id)}>{t(uiLang, "open")}</button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {selectedId && project && (
          <section className="panel">
            <div className="row-between">
              <button className="ghost" onClick={() => setSelectedId(null)}>
                {t(uiLang, "back")}
              </button>
              <div className="meta">
                <strong>{project.name}</strong>
                <span>
                  {project.country} · {project.project_type || "infrastructure"}
                  {project.country_profile_code ? ` · ${project.country_profile_code}` : ""}
                </span>
              </div>
            </div>

            <div className="form-grid compact">
              <label>
                {t(uiLang, "appLanguage")}
                <select
                  value={uiLang}
                  onChange={(e) => void saveLanguages(e.target.value as LanguageCode)}
                >
                  {languageOptions.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>
              <div className="actions">
                <button className="primary" disabled={busy} onClick={() => void runAnalysis()}>
                  {busy ? t(uiLang, "analyzing") : t(uiLang, "analyze")}
                </button>
              </div>
            </div>
            <p className="muted upload-hint">{t(uiLang, "languageHint")}</p>

            {uploadProgress && (
              <p className="upload-progress" role="status">
                {t(uiLang, "uploadingProgress")
                  .replace("{done}", String(uploadProgress.done))
                  .replace("{total}", String(uploadProgress.total))}
              </p>
            )}

            {staging && (
              <article className="upload-card staging-panel">
                <h3>
                  {t(uiLang, "stagingTitle")}
                  <span className="optional-badge">
                    {" "}
                    · {t(uiLang, staging.category === "drawing" ? "drawings" : staging.category === "tender" ? "tenderDocs" : staging.category === "schedule" ? "schedule" : "standards")}
                  </span>
                </h3>
                <div className="file-toolbar">
                  <button type="button" className="linkish" disabled={busy} onClick={() => setStagingSelected(true)}>
                    {t(uiLang, "stagingSelectAll")}
                  </button>
                  <button type="button" className="linkish" disabled={busy} onClick={() => setStagingSelected(false)}>
                    {t(uiLang, "stagingDeselectAll")}
                  </button>
                  <button type="button" className="linkish" disabled={busy} onClick={() => removeStagingUnchecked()}>
                    {t(uiLang, "stagingRemoveUnchecked")}
                  </button>
                  <span className="muted">
                    {t(uiLang, "selectedCount").replace(
                      "{n}",
                      String(staging.items.filter((x) => x.selected).length),
                    )}
                    {" / "}
                    {staging.items.length}
                  </span>
                </div>
                <ul className="file-list staging-list">
                  {staging.items.map((item) => (
                    <li key={item.key}>
                      <label className="file-check">
                        <input
                          type="checkbox"
                          checked={item.selected}
                          disabled={busy}
                          onChange={(e) => toggleStagingItem(item.key, e.target.checked)}
                        />
                        <span title={item.file.name}>{item.file.name}</span>
                      </label>
                      <button
                        type="button"
                        className="linkish"
                        disabled={busy}
                        onClick={() =>
                          setStaging((prev) => {
                            if (!prev) return prev;
                            const items = prev.items.filter((x) => x.key !== item.key);
                            return items.length ? { ...prev, items } : null;
                          })
                        }
                      >
                        {t(uiLang, "delete")}
                      </button>
                    </li>
                  ))}
                </ul>
                <div className="file-toolbar actions-row">
                  <button
                    type="button"
                    className="primary"
                    disabled={busy || !staging.items.some((x) => x.selected)}
                    onClick={() =>
                      void uploadFiles(
                        staging.category,
                        staging.items.filter((x) => x.selected).map((x) => x.file),
                      )
                    }
                  >
                    {t(uiLang, "stagingUploadSelected")}
                  </button>
                  <button type="button" className="ghost" disabled={busy} onClick={() => setStaging(null)}>
                    {t(uiLang, "stagingCancel")}
                  </button>
                </div>
              </article>
            )}

            <article className="upload-card standards-panel">
              <h3>
                {t(uiLang, "standards")}
                <span className="optional-badge"> {t(uiLang, "optional")}</span>
              </h3>
              <p className="muted upload-hint">{t(uiLang, "standardsSelectHint")}</p>
              {standardsLoading ? (
                <p className="muted">{t(uiLang, "standardsLoading")}</p>
              ) : standardsError ? (
                <div className="file-list-meta">
                  <span>{t(uiLang, "standardsLoadError")}</span>
                  <button
                    className="linkish"
                    disabled={busy || selectedId == null}
                    onClick={() => selectedId != null && void loadStandards(selectedId)}
                  >
                    {t(uiLang, "standardsRetry")}
                  </button>
                </div>
              ) : projectStandards.length === 0 ? (
                <div className="file-list-meta">
                  <span>{t(uiLang, "standardsLoadError")}</span>
                  <button
                    className="linkish"
                    disabled={busy || selectedId == null}
                    onClick={() => selectedId != null && void loadStandards(selectedId)}
                  >
                    {t(uiLang, "standardsRetry")}
                  </button>
                </div>
              ) : (
                <ul className="standards-checklist">
                  {projectStandards.map((s) => (
                    <li key={s.standard_code} className={s.is_selected ? "selected" : ""}>
                      <label>
                        <input
                          type="checkbox"
                          checked={s.is_selected}
                          onChange={(e) => void toggleStandard(s.standard_code, e.target.checked)}
                        />
                        <span className="std-main">
                          <strong>{s.title}</strong>
                          <small>
                            {s.standard_class} · {s.applicability_level}
                            {s.selected_by === "user_override" ? ` · ${t(uiLang, "userOverride")}` : ""}
                            {" · "}
                            {s.check_target}
                          </small>
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
              <p className="muted upload-hint">{t(uiLang, "standardsCustomHint")}</p>
              <p className="format-line">{t(uiLang, "formatsStandard")}</p>
              <label className={`file-btn${busy ? " disabled" : ""}`}>
                {busy && uploadProgress?.category === "standard"
                  ? t(uiLang, "uploading")
                  : t(uiLang, "uploadCustomStandard")}
                <input
                  type="file"
                  multiple
                  accept={FILE_ACCEPT_BY_CATEGORY.standard}
                  disabled={busy}
                  onChange={(e) => {
                    queueFiles("standard", e.target.files);
                    e.target.value = "";
                  }}
                />
              </label>
              {docsByCategory.standard.length === 0 ? (
                <p className="muted">{t(uiLang, "noCustomStandards")}</p>
              ) : (
                <BulkFileList
                  uiLang={uiLang}
                  category="standard"
                  files={docsByCategory.standard}
                  emptyLabel={t(uiLang, "noCustomStandards")}
                  busy={busy}
                  onDeleteOne={(id) => onDeleteDoc(id)}
                  onBulkDelete={onBulkDeleteFiles}
                  onNotify={(text, kind) => {
                    setNotice({ text, kind });
                    if (kind === "error") setError(text);
                  }}
                />
              )}
            </article>

            <div className="upload-grid">
              {uploadCategories.map((cat) => (
                <article
                  key={cat.key}
                  className={`upload-card${cat.key === "drawing" ? " wide" : ""}`}
                >
                  <h3>
                    {t(uiLang, cat.labelKey)}
                    {cat.optional ? (
                      <span className="optional-badge"> {t(uiLang, "optional")}</span>
                    ) : null}
                  </h3>
                  <p className="muted upload-hint">
                    {cat.key === "schedule"
                      ? t(uiLang, "scheduleOptionalHint")
                      : cat.key === "drawing"
                        ? t(uiLang, "drawingsNoTextHint")
                        : t(uiLang, "uploadHint")}
                  </p>
                  <p className="format-line">
                    {t(
                      uiLang,
                      cat.key === "drawing"
                        ? "formatsDrawing"
                        : cat.key === "schedule"
                          ? "formatsSchedule"
                          : "formatsTender",
                    )}
                  </p>
                  <label className={`file-btn${busy ? " disabled" : ""}`}>
                    {busy && uploadProgress?.category === cat.key
                      ? t(uiLang, "uploading")
                      : t(uiLang, "upload")}
                    <input
                      type="file"
                      multiple
                      accept={FILE_ACCEPT_BY_CATEGORY[cat.key] || FILE_ACCEPT}
                      disabled={busy}
                      onChange={(e) => {
                        queueFiles(cat.key, e.target.files);
                        e.target.value = "";
                      }}
                    />
                  </label>
                  <BulkFileList
                    uiLang={uiLang}
                    category={cat.key}
                    files={docsByCategory[cat.key]}
                    emptyLabel={t(uiLang, "noFiles")}
                    busy={busy}
                    showReextract
                    onDeleteOne={(id) => onDeleteDoc(id)}
                    onBulkDelete={onBulkDeleteFiles}
                    onReextract={(id) => void onReextract(id)}
                    onNotify={(text, kind) => {
                      setNotice({ text, kind });
                      if (kind === "error") setError(text);
                    }}
                  />
                </article>
              ))}
            </div>

            {analysis && (
              <div className="report">
                <div className="score-row">
                  <div>
                    <h2>{t(uiLang, "summary")}</h2>
                    <p>{analysis.summary}</p>
                    {analysis.status === "blocked" && (
                      <p className="blocked-note">{t(uiLang, "analysisBlocked")}</p>
                    )}
                  </div>
                  <div className="score">
                    <span>{t(uiLang, "readiness")}</span>
                    <strong>{analysis.readiness_score}%</strong>
                    <small>
                      {t(uiLang, "realRisks")}: {t(uiLang, "high")}{" "}
                      {(analysis.counts_risk || analysis.counts).high || 0} · {t(uiLang, "medium")}{" "}
                      {(analysis.counts_risk || analysis.counts).medium || 0} · {t(uiLang, "low")}{" "}
                      {(analysis.counts_risk || analysis.counts).low || 0}
                    </small>
                    {analysis.aggregate_risk_score != null && (
                      <small>
                        {t(uiLang, "avgRiskScore")}: {analysis.aggregate_risk_score}
                      </small>
                    )}
                    {analysis.documents_with_limitations != null && (
                      <small>
                        {t(uiLang, "docsLimited")}: {analysis.documents_with_limitations}
                      </small>
                    )}
                  </div>
                </div>

                {(() => {
                  const unique = new Map<number, (typeof analysis.findings)[0]>();
                  for (const f of analysis.findings) unique.set(f.id, f);
                  const all = [...unique.values()];
                  const limitations = all.filter((f) => findingTier(f) === "limitation");
                  const risks = all.filter((f) => findingTier(f) === "risk");
                  const methodology = all.filter((f) => findingTier(f) === "methodology");
                  return (
                    <>
                      {limitations.length > 0 && (
                        <div className="limitation-banners">
                          {limitations.map((f) => (
                            <aside key={f.id} className="limitation-banner">
                              <strong>{f.title}</strong>
                              <p>{shortenText(f.description, 360)}</p>
                              <p>
                                <em>{f.recommendation}</em>
                              </p>
                            </aside>
                          ))}
                        </div>
                      )}

                      <h2>{t(uiLang, "findings")}</h2>
                      {risks.length === 0 ? (
                        <p className="muted">
                          {analysis.status === "blocked"
                            ? t(uiLang, "noRisksBlocked")
                            : t(uiLang, "noRealRisks")}
                        </p>
                      ) : (
                        <div className="findings">
                          {risks.map((f) => (
                            <article key={f.id} className={`finding sev-${f.severity} finding-risk`}>
                              <header>
                                <span className="badge score-badge">
                                  {f.risk_score != null ? f.risk_score : "—"}
                                </span>
                                <span className="badge">{t(uiLang, f.severity)}</span>
                              </header>
                              <h3>{f.title}</h3>
                              <p>{f.description}</p>
                              {(f.source_excerpt || f.evidence) && (
                                <blockquote className="source-excerpt">
                                  {shortenText(f.source_excerpt || f.evidence || "", 220)}
                                </blockquote>
                              )}
                              {f.cause_effect_chain && f.cause_effect_chain.length > 0 && (
                                <div className="cause-chain">
                                  <span className="chain-label">{t(uiLang, "causeEffect")}</span>
                                  <ol>
                                    {f.cause_effect_chain.map((step, i) => (
                                      <li key={`${f.id}-c-${i}`}>{step}</li>
                                    ))}
                                  </ol>
                                </div>
                              )}
                              <p>
                                <strong>{t(uiLang, "recommendation")}:</strong> {f.recommendation}
                              </p>
                              {f.estimated_impact && (
                                <p className="muted">
                                  <strong>{t(uiLang, "estimatedImpact")}:</strong>{" "}
                                  {displayImpact(f.estimated_impact, uiLang)}
                                </p>
                              )}
                              {f.data_completeness_caveat && (
                                <p className="caveat">{f.data_completeness_caveat}</p>
                              )}
                            </article>
                          ))}
                        </div>
                      )}

                      {methodology.length > 0 && (
                        <details className="methodology-footer">
                          <summary>{t(uiLang, "methodologyFooter")}</summary>
                          {methodology.map((f) => (
                            <div key={f.id} className="methodology-item">
                              <strong>{f.title}</strong>
                              <p>{f.description}</p>
                            </div>
                          ))}
                        </details>
                      )}
                    </>
                  );
                })()}
                <p className="disclaimer">{t(uiLang, "disclaimer")}</p>
              </div>
            )}
          </section>
        )}
      </main>
    </div>
  );
}

export default App;
