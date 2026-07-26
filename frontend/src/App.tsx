import { useEffect, useMemo, useState } from "react";
import {
  api,
  FILE_ACCEPT,
  UPLOAD_CHUNK_SIZE,
  type AnalysisOut,
  type CountryCode,
  type DocumentCategory,
  type LanguageCode,
  type ProjectOut,
  type ProjectStandardOut,
  type ProjectType,
} from "./api";
import { countryOptions, languageOptions, projectTypeOptions, t } from "./i18n";
import "./App.css";

const uploadCategories: { key: DocumentCategory; labelKey: string; optional?: boolean }[] = [
  { key: "tender", labelKey: "tenderDocs" },
  { key: "drawing", labelKey: "drawings", optional: true },
  { key: "schedule", labelKey: "schedule", optional: true },
  // standards has a dedicated selection panel + custom upload
];

function App() {
  const [uiLang, setUiLang] = useState<LanguageCode>(() => {
    return (localStorage.getItem("ui_lang") as LanguageCode) || "fa";
  });
  const [projects, setProjects] = useState<ProjectOut[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [project, setProject] = useState<ProjectOut | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisOut | null>(null);
  const [projectStandards, setProjectStandards] = useState<ProjectStandardOut[]>([]);
  const [busy, setBusy] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{
    done: number;
    total: number;
    category: DocumentCategory;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [country, setCountry] = useState<CountryCode>("IR");
  const [projectType, setProjectType] = useState<ProjectType>("office");
  const [reportLang, setReportLang] = useState<LanguageCode>("fa");
  const [description, setDescription] = useState("");

  const dir = uiLang === "fa" ? "rtl" : "ltr";

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
      return;
    }
    void loadProject(selectedId);
  }, [selectedId]);

  async function refreshProjects() {
    try {
      const list = await api.listProjects();
      setProjects(list);
    } catch (e) {
      setError(String(e));
    }
  }

  async function loadProject(id: number) {
    setError(null);
    try {
      const p = await api.getProject(id);
      setProject(p);
      setReportLang(p.report_language);
      try {
        const standards = await api.listProjectStandards(id);
        setProjectStandards(standards);
      } catch {
        setProjectStandards([]);
      }
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
    // Optimistic UI — do not freeze the whole page with global busy.
    const previous = projectStandards;
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
      setProjectStandards(updated);
    } catch (e) {
      setProjectStandards(previous);
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
        report_language: reportLang,
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

  async function saveLanguages() {
    if (!project) return;
    setBusy(true);
    try {
      const updated = await api.updateProject(project.id, {
        ui_language: uiLang,
        report_language: reportLang,
      });
      setProject(updated);
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

  async function onDeleteDoc(docId: number) {
    if (!project) return;
    setBusy(true);
    try {
      await api.deleteDocument(project.id, docId);
      await loadProject(project.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
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
      const a = await api.analyze(project.id, reportLang);
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
              {t(uiLang, "uiLanguage")}
              <select
                value={uiLang}
                onChange={(e) => setUiLang(e.target.value as LanguageCode)}
              >
                {languageOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
      </header>

      <main className="layout">
        {error && <div className="error-banner">{error}</div>}

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
              <label>
                {t(uiLang, "reportLanguage")}
                <select
                  value={reportLang}
                  onChange={(e) => setReportLang(e.target.value as LanguageCode)}
                >
                  {languageOptions.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
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
                {t(uiLang, "reportLanguage")}
                <select
                  value={reportLang}
                  onChange={(e) => setReportLang(e.target.value as LanguageCode)}
                >
                  {languageOptions.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>
              <div className="actions">
                <button disabled={busy} onClick={() => void saveLanguages()}>
                  {t(uiLang, "saveLanguages")}
                </button>
                <button className="primary" disabled={busy} onClick={() => void runAnalysis()}>
                  {busy ? t(uiLang, "analyzing") : t(uiLang, "analyze")}
                </button>
              </div>
            </div>

            {uploadProgress && (
              <p className="upload-progress" role="status">
                {t(uiLang, "uploadingProgress")
                  .replace("{done}", String(uploadProgress.done))
                  .replace("{total}", String(uploadProgress.total))}
              </p>
            )}

            <div className="upload-grid">
              {uploadCategories.map((cat) => (
                <article key={cat.key} className="upload-card">
                  <h3>
                    {t(uiLang, cat.labelKey)}
                    {cat.optional ? (
                      <span className="optional-badge"> {t(uiLang, "optional")}</span>
                    ) : null}
                  </h3>
                  <p className="muted upload-hint">
                    {cat.key === "schedule" ? t(uiLang, "scheduleOptionalHint") : t(uiLang, "uploadHint")}
                  </p>
                  <label className={`file-btn${busy ? " disabled" : ""}`}>
                    {busy && uploadProgress?.category === cat.key
                      ? t(uiLang, "uploading")
                      : t(uiLang, "upload")}
                    <input
                      type="file"
                      multiple
                      accept={FILE_ACCEPT}
                      disabled={busy}
                      onChange={(e) => {
                        void onUpload(cat.key, e.target.files);
                        e.target.value = "";
                      }}
                    />
                  </label>
                  {docsByCategory[cat.key].length === 0 ? (
                    <p className="muted">{t(uiLang, "noFiles")}</p>
                  ) : (
                    <ul className="file-list">
                      {docsByCategory[cat.key].map((d) => (
                        <li key={d.id}>
                          <div className="file-meta">
                            <span title={d.original_name}>{d.original_name}</span>
                            <small className={d.has_text ? "tag ok" : "tag warn"}>
                              {d.has_text ? t(uiLang, "textOk") : t(uiLang, "textMissing")}
                              {d.ocr_applied ? ` · ${t(uiLang, "ocrUsed")}` : ""}
                            </small>
                          </div>
                          <div className="file-actions">
                            {!d.has_text && (
                              <button
                                className="linkish"
                                disabled={busy}
                                onClick={() => void onReextract(d.id)}
                              >
                                {t(uiLang, "reextract")}
                              </button>
                            )}
                            <button
                              className="linkish"
                              disabled={busy}
                              onClick={() => void onDeleteDoc(d.id)}
                            >
                              {t(uiLang, "delete")}
                            </button>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </article>
              ))}
            </div>

            <article className="upload-card standards-panel">
              <h3>
                {t(uiLang, "standards")}
                <span className="optional-badge"> {t(uiLang, "optional")}</span>
              </h3>
              <p className="muted upload-hint">{t(uiLang, "standardsSelectHint")}</p>
              {projectStandards.length === 0 ? (
                <p className="muted">{t(uiLang, "standardsLoading")}</p>
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
              <label className={`file-btn${busy ? " disabled" : ""}`}>
                {busy && uploadProgress?.category === "standard"
                  ? t(uiLang, "uploading")
                  : t(uiLang, "uploadCustomStandard")}
                <input
                  type="file"
                  multiple
                  accept={FILE_ACCEPT}
                  disabled={busy}
                  onChange={(e) => {
                    void onUpload("standard", e.target.files);
                    e.target.value = "";
                  }}
                />
              </label>
              {docsByCategory.standard.length === 0 ? (
                <p className="muted">{t(uiLang, "noCustomStandards")}</p>
              ) : (
                <ul className="file-list">
                  {docsByCategory.standard.map((d) => (
                    <li key={d.id}>
                      <div className="file-meta">
                        <span title={d.original_name}>{d.original_name}</span>
                        <small className={d.has_text ? "tag ok" : "tag warn"}>
                          {d.has_text ? t(uiLang, "textOk") : t(uiLang, "textMissing")}
                        </small>
                      </div>
                      <div className="file-actions">
                        <button
                          className="linkish"
                          disabled={busy}
                          onClick={() => void onDeleteDoc(d.id)}
                        >
                          {t(uiLang, "delete")}
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </article>

            {analysis && (
              <div className="report">
                <div className="score-row">
                  <div>
                    <h2>{t(uiLang, "summary")}</h2>
                    <p>{analysis.summary}</p>
                  </div>
                  <div className="score">
                    <span>{t(uiLang, "readiness")}</span>
                    <strong>{analysis.readiness_score}%</strong>
                    <small>
                      {t(uiLang, "high")}: {analysis.counts.high || 0} · {t(uiLang, "medium")}:{" "}
                      {analysis.counts.medium || 0} · {t(uiLang, "low")}: {analysis.counts.low || 0}
                    </small>
                  </div>
                </div>

                <h2>{t(uiLang, "findings")}</h2>
                <div className="findings">
                  {analysis.findings.map((f) => (
                    <article key={f.id} className={`finding sev-${f.severity}`}>
                      <header>
                        <span className="badge">{t(uiLang, f.severity)}</span>
                        <code>{f.code}</code>
                      </header>
                      <h3>{f.title}</h3>
                      <p>{f.description}</p>
                      <p>
                        <strong>{t(uiLang, "recommendation")}:</strong> {f.recommendation}
                      </p>
                      {f.evidence && (
                        <p className="evidence">
                          <strong>{t(uiLang, "evidence")}:</strong> {f.evidence}
                        </p>
                      )}
                    </article>
                  ))}
                </div>
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
