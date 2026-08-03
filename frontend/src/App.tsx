import { useEffect, useMemo, useState } from "react";
import {
  api,
  FILE_ACCEPT,
  FILE_ACCEPT_BY_CATEGORY,
  UPLOAD_CHUNK_SIZE,
  getApiToken,
  setApiToken,
  type AnalysisOut,
  type CountryCode,
  type DocumentCategory,
  type LanguageCode,
  type ProjectOut,
  type ProjectStandardOut,
  type ProjectType,
  type UserRole,
} from "./api";
import { countryOptions, displayImpact, languageOptions, projectTypeOptions, t } from "./i18n";
import { BulkFileList } from "./BulkFileList";
import { ExperiencePanel } from "./ExperiencePanel";
import { ReportDashboard } from "./ReportDashboard";
import "./App.css";

const uploadCategories: { key: DocumentCategory; labelKey: string; optional?: boolean }[] = [
  { key: "tender", labelKey: "tenderDocs" },
  { key: "drawing", labelKey: "drawings", optional: true },
  { key: "schedule", labelKey: "schedule", optional: true },
  // standards has a dedicated selection panel + custom upload
];

function findingTier(
  f: { finding_category?: string | null; code?: string },
): "limitation" | "methodology" | "experience" | "risk" {
  const cat = f.finding_category || "risk";
  if (cat === "limitation" || cat === "methodology" || cat === "experience") return cat;
  const code = (f.code || "").toUpperCase();
  if (code.startsWith("EXTRACT-") || code.startsWith("OCR-")) return "limitation";
  if (code.startsWith("STD-SELECT")) return "methodology";
  if (code.startsWith("EXP-")) return "experience";
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
  const [standardsOpen, setStandardsOpen] = useState(false);
  const [analysisStale, setAnalysisStale] = useState(false);
  const [notice, setNotice] = useState<{ text: string; kind: "success" | "error" } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [apiRole, setApiRole] = useState<UserRole>("user");
  const [isAdmin, setIsAdmin] = useState(false);
  const [catalogCode, setCatalogCode] = useState("");
  const [catalogTitle, setCatalogTitle] = useState("");
  const [workspaceTab, setWorkspaceTab] = useState<"docs" | "standards" | "report" | "admin">(
    "docs",
  );
  /** Full-page file browser for one document category (null = overview cards). */
  const [docsDetailCat, setDocsDetailCat] = useState<DocumentCategory | null>(null);

  const [name, setName] = useState("");
  const [country, setCountry] = useState<CountryCode>("IR");
  const [projectType, setProjectType] = useState<ProjectType>("office");
  const [description, setDescription] = useState("");

  const dir = uiLang === "fa" ? "rtl" : "ltr";

  async function refreshAuth() {
    try {
      const me = await api.authMe();
      setApiRole(me.role);
      setIsAdmin(me.is_admin);
    } catch {
      setApiRole("user");
      setIsAdmin(false);
    }
  }

  function applyRolePreset(role: UserRole) {
    const token = role === "admin" ? "dev-admin-token" : "dev-user-token";
    setApiToken(token);
    void refreshAuth();
  }

  useEffect(() => {
    if (!getApiToken()) setApiToken("dev-user-token");
    void refreshAuth();
  }, []);

  useEffect(() => {
    if (isAdmin) setStandardsOpen(true);
  }, [isAdmin]);

  useEffect(() => {
    if (workspaceTab === "standards") setStandardsOpen(true);
    if (workspaceTab !== "docs") setDocsDetailCat(null);
  }, [workspaceTab]);

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
  // Only refresh documents — do NOT reload analysis (avoids overwriting a fresh run).
  useEffect(() => {
    if (!project) return;
    const busyDocs = project.documents.some((d) => {
      const phase = d.extraction_phase;
      return phase && phase !== "completed" && phase !== "failed";
    });
    if (!busyDocs) return;
    const timer = window.setInterval(() => {
      void refreshProjectDocs(project.id);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [project]);

  async function waitForExtractions(projectId: number, maxMs = 180_000) {
    const started = Date.now();
    let latest = await api.getProject(projectId);
    setProject(latest);
    while (Date.now() - started < maxMs) {
      const pending = latest.documents.some((d) => {
        const phase = d.extraction_phase;
        return phase != null && phase !== "completed" && phase !== "failed";
      });
      if (!pending) return latest;
      await new Promise((r) => window.setTimeout(r, 2000));
      latest = await api.getProject(projectId);
      setProject(latest);
    }
    return latest;
  }

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

  async function loadProject(id: number, opts?: { includeAnalysis?: boolean }) {
    const includeAnalysis = opts?.includeAnalysis !== false;
    setError(null);
    try {
      const p = await api.getProject(id);
      setProject(p);
      // One language drives both UI and analysis for this project.
      setAppLang(p.report_language || p.ui_language);
      void loadStandards(id);
      if (includeAnalysis) {
        try {
          const a = await api.latestAnalysis(id);
          setAnalysis(a);
          setAnalysisStale(false);
        } catch {
          setAnalysis(null);
          setAnalysisStale(false);
        }
      }
    } catch (e) {
      setError(String(e));
    }
  }

  async function refreshProjectDocs(id: number) {
    try {
      const p = await api.getProject(id);
      setProject(p);
    } catch {
      /* keep current project on poll errors */
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
      setWorkspaceTab("docs");
      setSelectedId(p.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onUpload(category: DocumentCategory, files: FileList | File[] | null) {
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
      await loadProject(project.id, { includeAnalysis: false });
      setAnalysisStale(true);
      if (failed.length) {
        const preview = failed.slice(0, 5).join("\n");
        const more = failed.length > 5 ? `\n… +${failed.length - 5}` : "";
        setError(`${t(uiLang, "uploadPartial")}\n${preview}${more}`);
      } else {
        setNotice({ text: t(uiLang, "docsChangedReanalyze"), kind: "success" });
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
      await loadProject(project.id, { includeAnalysis: false });
      setAnalysisStale(true);
      setNotice({ text: t(uiLang, "docsChangedReanalyze"), kind: "success" });
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
    await loadProject(project.id, { includeAnalysis: false });
    setAnalysisStale(true);
    return result;
  }

  async function onReextract(docId: number) {
    if (!project) return;
    setBusy(true);
    setError(null);
    try {
      await api.reextractDocument(project.id, docId);
      await loadProject(project.id, { includeAnalysis: false });
      setAnalysisStale(true);
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
    setNotice({ text: t(uiLang, "analyzingPreparing"), kind: "success" });
    try {
      await waitForExtractions(project.id);
      const a = await api.analyze(project.id, uiLang);
      setAnalysis(a);
      setAnalysisStale(false);
      setWorkspaceTab("report");
      const p = await api.getProject(project.id);
      setProject(p);
      setNotice({
        text: t(uiLang, "analyzeDone")
          .replace("{n}", String(p.documents.length))
          .replace("{findings}", String(a.findings?.length ?? 0)),
        kind: "success",
      });
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
    <div className={`app-shell${!selectedId ? " is-home" : ""}`} dir={dir}>
      <header className={`topbar${!selectedId ? " landing-topbar" : ""}`}>
        <div className="topbar-inner">
          <button
            type="button"
            className="brand"
            onClick={() => {
              setSelectedId(null);
              setWorkspaceTab("docs");
              setDocsDetailCat(null);
            }}
          >
            <span className="brand-mark" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="16" height="16">
                <path
                  fill="currentColor"
                  d="M12 2 3 7v10l9 5 9-5V7l-9-5zm0 2.2 6.5 3.6v1.7L12 13.1 5.5 9.5V7.8L12 4.2zm-6.5 7.3L12 15l6.5-3.5V17L12 20.5 5.5 17v-5.5z"
                />
              </svg>
            </span>
            {!selectedId ? null : (
              <span className="brand-text">
                <strong>TenderRisk</strong>
                <small>{t(uiLang, "appNameFull")}</small>
              </span>
            )}
          </button>

          {!selectedId ? (
            <nav className="landing-nav" aria-label="main">
              <button type="button" className="is-active">
                {t(uiLang, "homeNavHome")}
              </button>
              <button
                type="button"
                onClick={() => document.getElementById("home-start")?.scrollIntoView({ behavior: "smooth" })}
              >
                {t(uiLang, "homeNavFeatures")}
              </button>
              <button
                type="button"
                onClick={() => document.getElementById("home-start")?.scrollIntoView({ behavior: "smooth" })}
              >
                {t(uiLang, "homeNavPricing")}
              </button>
              <button
                type="button"
                onClick={() => document.getElementById("home-start")?.scrollIntoView({ behavior: "smooth" })}
              >
                {t(uiLang, "homeNavResources")}
              </button>
              <button
                type="button"
                onClick={() => document.getElementById("home-start")?.scrollIntoView({ behavior: "smooth" })}
              >
                {t(uiLang, "homeNavAbout")}
              </button>
            </nav>
          ) : null}

          <div className="topbar-actions">
            {!selectedId ? (
              <>
                <label className="chrome-control">
                  <span className="visually-hidden">{t(uiLang, "appLanguage")}</span>
                  <select
                    className="chrome-select"
                    value={uiLang}
                    onChange={(e) => setAppLang(e.target.value as LanguageCode)}
                    title={t(uiLang, "appLanguage")}
                  >
                    {languageOptions.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  className="landing-login"
                  onClick={() => document.getElementById("home-start")?.scrollIntoView({ behavior: "smooth" })}
                >
                  {t(uiLang, "homeNavLogin")}
                </button>
                <button
                  type="button"
                  className="landing-demo"
                  onClick={() => document.getElementById("home-start")?.scrollIntoView({ behavior: "smooth" })}
                >
                  {t(uiLang, "homeNavDemo")}
                </button>
              </>
            ) : null}
            <label className="chrome-control">
              <span className="visually-hidden">{t(uiLang, "roleLabel")}</span>
              <select
                className="chrome-select"
                value={apiRole}
                onChange={(e) => applyRolePreset(e.target.value as UserRole)}
                title={t(uiLang, "roleLabel")}
              >
                <option value="user">{t(uiLang, "roleUser")}</option>
                <option value="admin">{t(uiLang, "roleAdmin")}</option>
              </select>
            </label>
          </div>
        </div>
      </header>

      {!selectedId ? (
        <section className="hero home-hero">
          <div className="hero-inner home-hero-grid">
            <div className="home-hero-copy">
              <h1>{t(uiLang, "homeHeroTitle")}</h1>
              <p className="tagline">{t(uiLang, "tagline")}</p>
              <div className="home-cta-row">
                <button
                  type="button"
                  className="home-cta-primary"
                  onClick={() =>
                    document.getElementById("home-start")?.scrollIntoView({ behavior: "smooth", block: "start" })
                  }
                >
                  {t(uiLang, "homeCtaPrimary")}
                  <span aria-hidden="true">→</span>
                </button>
                <button
                  type="button"
                  className="home-cta-secondary"
                  onClick={() =>
                    document.getElementById("home-start")?.scrollIntoView({ behavior: "smooth", block: "start" })
                  }
                >
                  <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
                    <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.8" />
                    <path d="M10 8.5v7l6-3.5-6-3.5z" fill="currentColor" />
                  </svg>
                  {t(uiLang, "homeCtaSecondary")}
                </button>
              </div>
              <ul className="home-pillars">
                <li>
                  <span className="home-pillar-icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24" fill="none">
                      <path d="M7 4h7l3 3v13H7V4z" stroke="currentColor" strokeWidth="1.7" />
                      <path d="M14 4v3h3M9 11h6M9 15h5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
                    </svg>
                  </span>
                  <span>{t(uiLang, "homePillar1")}</span>
                </li>
                <li>
                  <span className="home-pillar-icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24" fill="none">
                      <path
                        d="M12 4l8 4v5c0 4.5-3.2 7.6-8 9-4.8-1.4-8-4.5-8-9V8l8-4z"
                        stroke="currentColor"
                        strokeWidth="1.7"
                      />
                      <path
                        d="M9.5 12.2l1.8 1.8 3.4-3.6"
                        stroke="currentColor"
                        strokeWidth="1.7"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </span>
                  <span>{t(uiLang, "homePillar2")}</span>
                </li>
                <li>
                  <span className="home-pillar-icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24" fill="none">
                      <path
                        d="M4 18V6M8 18V10M12 18V8M16 18v-5M20 18V9"
                        stroke="currentColor"
                        strokeWidth="1.7"
                        strokeLinecap="round"
                      />
                    </svg>
                  </span>
                  <span>{t(uiLang, "homePillar3")}</span>
                </li>
                <li>
                  <span className="home-pillar-icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24" fill="none">
                      <circle cx="9" cy="10" r="2.2" stroke="currentColor" strokeWidth="1.7" />
                      <circle cx="15" cy="10" r="2.2" stroke="currentColor" strokeWidth="1.7" />
                      <path
                        d="M5.5 17c.8-1.8 2.3-2.7 3.5-2.7S11 15.2 11.8 17M12.2 17c.8-1.8 2.3-2.7 3.5-2.7s2.7.9 3.5 2.7"
                        stroke="currentColor"
                        strokeWidth="1.7"
                        strokeLinecap="round"
                      />
                    </svg>
                  </span>
                  <span>{t(uiLang, "homePillar4")}</span>
                </li>
              </ul>
            </div>

            <div className="home-hero-visual">
              <img
                className="home-devices-img"
                src="/home-devices.png"
                alt=""
                width={1536}
                height={1024}
                decoding="async"
              />
            </div>
          </div>
        </section>
      ) : null}

      <main className={`layout${!selectedId ? " home-layout" : ""}`}>
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
          <section className="panel home-panel" id="home-start">
            <div className="home-panel-head">
              <h2>{t(uiLang, "homeCta")}</h2>
              <p className="muted">{t(uiLang, "homePanelHint")}</p>
            </div>
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

            <h2 className="mt">{t(uiLang, "projectsHeading")}</h2>
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
                    <button
                      type="button"
                      className="primary soft"
                      onClick={() => {
                        setWorkspaceTab("docs");
                        setSelectedId(p.id);
                      }}
                    >
                      {t(uiLang, "open")}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {selectedId && project && (
          <section className="workspace">
            <div className="workspace-bar">
              <button
                type="button"
                className="btn-back"
                  onClick={() => {
                    setSelectedId(null);
                    setWorkspaceTab("docs");
                    setDocsDetailCat(null);
                  }}
              >
                {dir === "rtl" ? "→" : "←"} {t(uiLang, "back")}
              </button>
              <div className="meta">
                <strong>{project.name}</strong>
                <span>
                  {project.country} · {project.project_type || "infrastructure"}
                  {project.country_profile_code ? ` · ${project.country_profile_code}` : ""}
                </span>
              </div>
              <button className="primary analyze-cta" disabled={busy} onClick={() => void runAnalysis()}>
                {busy ? t(uiLang, "analyzing") : t(uiLang, "analyze")}
              </button>
            </div>

            {analysisStale ? (
              <p className="muted upload-hint" role="status">
                {t(uiLang, "analysisStaleHint")}
              </p>
            ) : null}

            <nav className="workspace-tabs" aria-label={t(uiLang, "workspaceHint")}>
              {(
                [
                  { id: "docs" as const, label: t(uiLang, "tabDocs") },
                  { id: "standards" as const, label: t(uiLang, "tabStandards") },
                  { id: "report" as const, label: t(uiLang, "tabReport") },
                  ...(isAdmin ? [{ id: "admin" as const, label: t(uiLang, "tabAdmin") }] : []),
                ]
              ).map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  className={workspaceTab === tab.id ? "tab on" : "tab"}
                  onClick={() => setWorkspaceTab(tab.id)}
                >
                  {tab.label}
                </button>
              ))}
            </nav>

            {uploadProgress && workspaceTab === "docs" ? (
              <p className="upload-progress" role="status">
                {t(uiLang, "uploadingProgress")
                  .replace("{done}", String(uploadProgress.done))
                  .replace("{total}", String(uploadProgress.total))}
              </p>
            ) : null}

            {workspaceTab === "docs" && docsDetailCat ? (
              <section className={`docs-files-page doc-cat-${docsDetailCat}`}>
                <div className="docs-files-page-bar">
                  <button
                    type="button"
                    className="btn-back"
                    onClick={() => setDocsDetailCat(null)}
                  >
                    {dir === "rtl" ? "→" : "←"} {t(uiLang, "backToDocCategories")}
                  </button>
                  <div className="meta">
                    <strong>
                      {t(
                        uiLang,
                        uploadCategories.find((c) => c.key === docsDetailCat)?.labelKey ||
                          "tenderDocs",
                      )}
                    </strong>
                    <span>
                      {t(uiLang, "filesInCategory").replace(
                        "{n}",
                        String(docsByCategory[docsDetailCat].length),
                      )}
                    </span>
                  </div>
                  <label className={`file-btn${busy ? " disabled" : ""}`}>
                    {busy && uploadProgress?.category === docsDetailCat
                      ? t(uiLang, "uploading")
                      : t(uiLang, "upload")}
                    <input
                      type="file"
                      multiple
                      accept={FILE_ACCEPT_BY_CATEGORY[docsDetailCat] || FILE_ACCEPT}
                      disabled={busy}
                      onChange={(e) => {
                        const picked = e.target.files ? Array.from(e.target.files) : [];
                        e.target.value = "";
                        if (picked.length) void onUpload(docsDetailCat, picked);
                      }}
                    />
                  </label>
                </div>
                <BulkFileList
                  uiLang={uiLang}
                  category={docsDetailCat}
                  files={docsByCategory[docsDetailCat]}
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
              </section>
            ) : null}

            {workspaceTab === "docs" && !docsDetailCat ? (
            <div className="upload-grid docs-row">
              {uploadCategories.map((cat) => {
                const files = docsByCategory[cat.key];
                const ranks = t(
                  uiLang,
                  cat.key === "drawing"
                    ? "formatsDrawingRanks"
                    : cat.key === "schedule"
                      ? "formatsScheduleRanks"
                      : "formatsTenderRanks",
                )
                  .split("|")
                  .map((x) => x.trim())
                  .filter(Boolean);
                return (
                  <article
                    key={cat.key}
                    className={`upload-card doc-cat doc-cat-${cat.key}`}
                  >
                    <div className="doc-cat-head">
                      <h3>
                        {t(uiLang, cat.labelKey)}
                        {cat.optional ? (
                          <span className="optional-badge"> {t(uiLang, "optional")}</span>
                        ) : null}
                      </h3>
                      <span className="doc-file-count">
                        {t(uiLang, "filesInCategory").replace("{n}", String(files.length))}
                      </span>
                    </div>
                    <p className="muted upload-hint doc-cat-hint">
                      {cat.key === "schedule"
                        ? t(uiLang, "scheduleOptionalHintShort")
                        : cat.key === "drawing"
                          ? t(uiLang, "drawingsHintShort")
                          : t(uiLang, "tenderHintShort")}
                    </p>

                    <details className="format-guide collapsed-guide">
                      <summary>{t(uiLang, "formatGuideSummary")}</summary>
                      <p className="format-guide-hint">{t(uiLang, "formatGuideHint")}</p>
                      <ol className="format-ladder">
                        {ranks.map((item, idx) => {
                          const rank = idx + 1;
                          const labelKey =
                            rank === 1
                              ? "formatRank1"
                              : rank === 2
                                ? "formatRank2"
                                : rank === 3
                                  ? "formatRank3"
                                  : rank === ranks.length
                                    ? "formatRankLast"
                                    : "formatRank4";
                          return (
                            <li key={item} className={`ladder-r${Math.min(rank, 5)}`}>
                              <span className="ladder-badge">
                                {t(uiLang, labelKey)}
                              </span>
                              <span className="ladder-text">{item}</span>
                            </li>
                          );
                        })}
                      </ol>
                    </details>

                    <div className="doc-cat-actions">
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
                            const picked = e.target.files ? Array.from(e.target.files) : [];
                            e.target.value = "";
                            if (picked.length) void onUpload(cat.key, picked);
                          }}
                        />
                      </label>
                      <button
                        type="button"
                        className="exp-btn view-files-btn"
                        disabled={busy}
                        onClick={() => setDocsDetailCat(cat.key)}
                      >
                        {t(uiLang, "viewFiles").replace("{n}", String(files.length))}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
            ) : null}

            {workspaceTab === "docs" && staging ? (
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
            ) : null}

            {workspaceTab === "standards" ? (
            <article className="upload-card standards-panel">
              <div className="row-between standards-header">
                <h3>
                  {t(uiLang, "standards")}
                  <span className="optional-badge"> {t(uiLang, "optional")}</span>
                </h3>
              </div>
              <p className="muted upload-hint">{t(uiLang, "standardsSelectHint")}</p>
              <>
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
                <p className="muted">{t(uiLang, "standardsEmpty")}</p>
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
                            {s.standard_code}
                            {" · "}
                            {s.standard_class}
                            {s.selected_by === "user_override" ? ` · ${t(uiLang, "userOverride")}` : ""}
                          </small>
                        </span>
                      </label>
                      {s.has_pdf ? (
                        <button
                          type="button"
                          className="linkish std-download"
                          disabled={busy}
                          onClick={() => {
                            if (!project) return;
                            void api
                              .downloadProjectStandardPdf(project.id, s.standard_code)
                              .then(() =>
                                setNotice({ text: t(uiLang, "downloadPdfOk"), kind: "success" }),
                              )
                              .catch((err: Error) => setError(err.message || String(err)));
                          }}
                        >
                          {t(uiLang, "downloadPdf")}
                        </button>
                      ) : (
                        <span className="muted">{t(uiLang, "downloadUnavailable")}</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {isAdmin ? (
                <>
                  <p className="muted upload-hint">{t(uiLang, "standardsCustomHint")}</p>
                  <div className="standards-admin-form">
                    <label>
                      {t(uiLang, "standardCodeLabel")}
                      <input
                        type="text"
                        value={catalogCode}
                        placeholder="NBC-03"
                        disabled={busy}
                        onChange={(e) => setCatalogCode(e.target.value)}
                      />
                    </label>
                    <label>
                      {t(uiLang, "standardTitleLabel")}
                      <input
                        type="text"
                        value={catalogTitle}
                        placeholder=""
                        disabled={busy}
                        onChange={(e) => setCatalogTitle(e.target.value)}
                      />
                    </label>
                  </div>
                  <p className="format-line">{t(uiLang, "formatsStandard")}</p>
                  <label className={`file-btn${busy || !project ? " disabled" : ""}`}>
                    {busy ? t(uiLang, "uploading") : t(uiLang, "uploadCatalogStandard")}
                    <input
                      type="file"
                      accept=".pdf,.docx,application/pdf"
                      disabled={busy || !project}
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        e.target.value = "";
                        if (!file || !project) return;
                        const fromName = file.name
                          .replace(/\.[^.]+$/, "")
                          .toUpperCase()
                          .replace(/[^A-Z0-9._-]+/g, "_")
                          .replace(/^_+|_+$/g, "")
                          .slice(0, 64);
                        const code = (
                          catalogCode.trim() ||
                          fromName ||
                          `STD_${Date.now().toString(36).toUpperCase()}`
                        )
                          .toUpperCase()
                          .replace(/[^A-Z0-9._-]+/g, "_")
                          .slice(0, 64);
                        const title =
                          catalogTitle.trim() ||
                          file.name.replace(/\.[^.]+$/, "") ||
                          code;
                        setBusy(true);
                        setError(null);
                        void api
                          .uploadCatalogStandard({
                            file,
                            standard_code: code,
                            title,
                            project_id: project.id,
                          })
                          .then(async () => {
                            setNotice({ text: t(uiLang, "catalogUploadOk"), kind: "success" });
                            setCatalogCode("");
                            setCatalogTitle("");
                            setStandardsOpen(true);
                            await loadStandards(project.id);
                          })
                          .catch((err: Error) => {
                            const msg = err.message || String(err);
                            if (/403|Admin role/i.test(msg)) {
                              setError(t(uiLang, "standardsNeedAdmin"));
                            } else {
                              setError(msg);
                            }
                          })
                          .finally(() => setBusy(false));
                      }}
                    />
                  </label>
                </>
              ) : (
                <p className="muted upload-hint">{t(uiLang, "standardsNeedAdmin")}</p>
              )}
              {docsByCategory.standard.length > 0 ? (
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
              ) : null}
              </>
            </article>
            ) : null}

            {workspaceTab === "admin" && isAdmin ? (
              <ExperiencePanel
                uiLang={uiLang}
                busy={busy}
                setBusy={setBusy}
                onNotify={(text, kind) => {
                  setNotice({ text, kind });
                  if (kind === "error") setError(text);
                }}
                onError={(text) => setError(text)}
              />
            ) : null}

            {workspaceTab === "report" ? (
              analysis ? (
              <div className="report panel">
                <ReportDashboard
                  uiLang={uiLang}
                  readiness={analysis.readiness_score}
                  high={(analysis.counts_risk || analysis.counts).high || 0}
                  medium={(analysis.counts_risk || analysis.counts).medium || 0}
                  low={(analysis.counts_risk || analysis.counts).low || 0}
                  avgRisk={analysis.aggregate_risk_score ?? null}
                  docsLimited={analysis.documents_with_limitations ?? null}
                  summary={analysis.summary}
                  blocked={analysis.status === "blocked"}
                />

                {(() => {
                  const unique = new Map<number, (typeof analysis.findings)[0]>();
                  for (const f of analysis.findings) unique.set(f.id, f);
                  const all = [...unique.values()];
                  const limitations = all.filter((f) => findingTier(f) === "limitation");
                  const risks = all.filter((f) => findingTier(f) === "risk");
                  const experiences = all.filter((f) => findingTier(f) === "experience");
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
                      <p className="muted finding-metrics-hint">{t(uiLang, "findingMetricsHint")}</p>
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

                      {experiences.length > 0 && (
                        <>
                          <h2>{t(uiLang, "experienceFindings")}</h2>
                          <div className="findings experience-findings">
                            {experiences.map((f) => (
                              <article key={f.id} className="finding finding-experience">
                                <h3>{f.title}</h3>
                                <p>{f.description}</p>
                                <p>
                                  <strong>{t(uiLang, "recommendation")}:</strong> {f.recommendation}
                                </p>
                              </article>
                            ))}
                          </div>
                        </>
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
              ) : (
                <div className="panel empty-report">
                  <h2>{t(uiLang, "tabReport")}</h2>
                  <p className="muted">{t(uiLang, "empty")}</p>
                  <button className="primary" disabled={busy} onClick={() => void runAnalysis()}>
                    {busy ? t(uiLang, "analyzing") : t(uiLang, "analyze")}
                  </button>
                </div>
              )
            ) : null}
          </section>
        )}
      </main>
    </div>
  );
}

export default App;
