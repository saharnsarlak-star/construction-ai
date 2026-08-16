import { useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  CATALOG_STANDARD_ACCEPT,
  FILE_ACCEPT,
  FILE_ACCEPT_BY_CATEGORY,
  UPLOAD_CHUNK_SIZE,
  getApiToken,
  parseApiError,
  setApiToken,
  type AnalysisOut,
  type CountryCode,
  type DemoLimitsOut,
  type DemoRequestOut,
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
import { ProjectRegistryPanel } from "./ProjectRegistryPanel";
import { ReportDashboard } from "./ReportDashboard";
import { TaxonomyBrowser } from "./TaxonomyBrowser";
import { StandardSectionBrowser } from "./StandardSectionBrowser";
import "./App.css";

function codeFromStandardFileName(fileName: string): string {
  return fileName
    .replace(/\.[^.]+$/, "")
    .toUpperCase()
    .replace(/[^A-Z0-9._-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 64);
}

function titleFromStandardFileName(fileName: string): string {
  return fileName.replace(/\.[^.]+$/, "").trim() || fileName;
}

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

/** Visual severity — aligned with backend compose_finding_risk (≥70 high, ≥40 medium). */
function severityFromRiskScore(
  score: number | null | undefined,
  fallback?: string | null,
  opts?: { capAtMedium?: boolean },
): "high" | "medium" | "low" {
  let band: "high" | "medium" | "low" = "medium";
  if (score != null && Number.isFinite(score)) {
    const n = Math.round(Number(score));
    if (n >= 70) band = "high";
    else if (n >= 40) band = "medium";
    else band = "low";
  } else {
    const fb = (fallback || "").toLowerCase();
    if (fb === "high" || fb === "medium" || fb === "low") band = fb;
  }
  if (opts?.capAtMedium && band === "high") return "medium";
  return band;
}

function countSeverityMix(
  findings: {
    risk_score?: number | null;
    severity?: string | null;
    finding_category?: string | null;
    code?: string;
  }[],
): { high: number; medium: number; low: number } {
  let high = 0;
  let medium = 0;
  let low = 0;
  for (const f of findings) {
    const tier = findingTier(f);
    if (tier !== "risk" && tier !== "experience") continue;
    const sev = severityFromRiskScore(f.risk_score, f.severity, {
      capAtMedium: tier === "experience",
    });
    if (sev === "high") high += 1;
    else if (sev === "medium") medium += 1;
    else low += 1;
  }
  return { high, medium, low };
}

function shortenText(text: string, max = 280): string {
  const t = (text || "").trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max)}…`;
}

/** Strip OCR/page chrome only — never rewrite document wording. */
function cleanQuoteForDisplay(raw: string | null | undefined): string | null {
  if (!raw) return null;
  let s = raw
    .replace(/---\s*page\s+\d+\s*\([^)]*\)\s*---(?:\s*\[[^\]]*\])?/gi, "")
    .replace(/---\s*(?:page|sheet|ocr|cad|ifc|gaeb)[^\n-]*---/gi, "")
    .replace(/\[(?:OCR_TRUNCATED|OCR_APPLIED|NEEDS_MANUAL_REVIEW|STAMP|SIGNATURE|DRAWING)[^\]]*\]/gi, "")
    .replace(/\[(?:DWG|DXF|Revit|DXF-fallback)[^\]]*\]/gi, "")
    .replace(/^\s+|\s+$/g, "");
  return s || null;
}

function humanCauseSteps(chain: string[] | undefined): string[] {
  if (!chain?.length) return [];
  return chain.filter((s) => {
    const t = s.trim();
    if (!t) return false;
    if (t.includes("=") && /^(risk_id|check|source_layer|rkb_|confidence|document|location|score_)/i.test(t)) {
      return false;
    }
    return true;
  });
}

function looksLikeStandardCodeList(text: string): boolean {
  const t = (text || "").trim();
  if (!t) return false;
  // e.g. 102-1321-56-4437؛ 105-735-54-201؛ ...
  const parts = t.split(/[؛;|]/).map((p) => p.trim()).filter(Boolean);
  if (parts.length < 2) return false;
  const codeish = parts.filter((p) => /^[\w.\-]{6,}$/i.test(p) || /\d{2,}[-_]\d+/i.test(p));
  return codeish.length >= Math.max(2, Math.floor(parts.length * 0.6));
}

function resolveFindingSource(
  f: {
    code?: string;
    title?: string;
    description?: string;
    source_document_name?: string | null;
    source_page?: number | null;
    source_excerpt?: string | null;
    evidence?: string | null;
    cause_effect_chain?: string[];
  },
  projectDocs?: { original_name: string; category: string }[],
): {
  fileName: string | null;
  page: number | null;
  quote: string | null;
  isMissingCategory: boolean;
  quoteKind: "sentence" | "explanation" | "standards_list";
} {
  let quote = (f.source_excerpt || "").trim() || null;
  let page = typeof f.source_page === "number" && f.source_page > 0 ? f.source_page : null;
  let fileName = (f.source_document_name || "").trim() || null;
  let isMissingCategory = false;
  let quoteKind: "sentence" | "explanation" | "standards_list" = "sentence";
  const code = (f.code || "").toUpperCase();
  const isStandardsGap =
    code.startsWith("STD-TOPIC-") || code.startsWith("STD-CITE-") || code.startsWith("STD-CONTENT-");

  for (const step of f.cause_effect_chain || []) {
    if (!fileName && step.startsWith("document=")) {
      fileName = step.slice("document=".length).trim() || null;
    }
    if (page == null && step.startsWith("location=")) {
      const loc = step.slice("location=".length);
      const m = loc.match(/(?:page|صفحه|p\.?|pg\.?)\s*[:=\-]?\s*(\d+)/i) || loc.match(/^\s*(\d+)\s*$/);
      if (m) page = Number(m[1]);
    }
    if (/موجود نیست|missing|fehlt|manquant/i.test(step)) {
      isMissingCategory = true;
    }
  }

  const evidence = (f.evidence || "").trim();
  if (!fileName && evidence && !looksLikeStandardCodeList(evidence) && !isStandardsGap) {
    const m =
      evidence.match(/^\s*\(([^)]+)\)/) ||
      evidence.match(/\b([\w.\-]+\.(?:pdf|docx?|xlsx?|txt|dwg|dxf|ifc))\b/i);
    if (m) fileName = (m[1] || "").trim() || null;
  }
  if (quote && looksLikeStandardCodeList(quote)) {
    quoteKind = "standards_list";
  } else if (isStandardsGap && quote) {
    quoteKind = "explanation";
    page = null;
    if (fileName && /شرایط|خصوص|اختصاص|special|particular|tender|مناقصه/i.test(fileName)) {
      // keep optional file context without pretending a page quote
    }
  } else if (!quote && evidence) {
    if (looksLikeStandardCodeList(evidence) || isStandardsGap) {
      quote = null;
      quoteKind = "standards_list";
    } else {
      const stripped = evidence
        .replace(/^\s*\([^)]+\)\s*/, "")
        .replace(/\s*\[[^\]]*\]\s*:?\s*/, "")
        .trim();
      quote = stripped || evidence;
    }
  }

  const blob = `${f.code || ""} ${f.title || ""} ${f.description || ""} ${fileName || ""}`.toLowerCase();
  if (
    /بارگذاری نشده|موجود نیست|no .*uploaded|missing|fehlt|aucun fichier|استاندارد مرجعی/.test(blob) ||
    isMissingCategory
  ) {
    isMissingCategory = true;
  }

  // Fallback for older analyses: derive actionable file list from project documents
  if (projectDocs && projectDocs.length > 0) {
    const byCat = (cat: string) =>
      projectDocs.filter((d) => d.category === cat).map((d) => d.original_name).filter(Boolean);
    const allNames = projectDocs.map((d) => d.original_name).filter(Boolean);
    let missingLabel: string | null = null;
    if (/standard|استاندارد|std-001/i.test(blob) && byCat("standard").length === 0) {
      missingLabel = "standard";
    } else if (/schedule|زمان|sched/i.test(blob) && byCat("schedule").length === 0) {
      missingLabel = "schedule";
    } else if (/drawing|نقشه|draw/i.test(blob) && byCat("drawing").length === 0) {
      missingLabel = "drawing";
    }

    if (missingLabel) {
      isMissingCategory = true;
      const present = allNames.slice(0, 6).join("، ") || "—";
      if (!fileName || fileName === "—" || /نامشخص|unknown|اسناد فعلی/i.test(fileName)) {
        fileName = `— (فایل «${missingLabel}» بارگذاری نشده)`;
      }
      if (!quote) {
        quote = `در بین اسناد پروژه، فایلی در دسته «${missingLabel}» نیست. اسناد فعلی: ${present}`;
      }
    } else if (!isStandardsGap && (!fileName || /[،,]/.test(fileName))) {
      // Exactly one file — prefer tender file whose name matches the finding topic
      const tender = byCat("tender");
      const pool = tender.length ? tender : allNames;
      const titleBits = `${f.title || ""} ${f.description || ""}`.toLowerCase();
      const scored = pool
        .map((n) => {
          const nl = n.toLowerCase();
          let s = 0;
          for (const hint of ["شرح", "محدوده", "خصوص", "اختصاص", "scope", "شرایط", "فنی", "ایمنی", "پیمان"]) {
            if (nl.includes(hint)) s += 5;
            if (titleBits.includes(hint) && nl.includes(hint)) s += 3;
          }
          return { n, s };
        })
        .sort((a, b) => b.s - a.s);
      fileName = scored[0]?.n || pool[0] || null;
    }
  }

  // Never show a comma-separated list in the file badge
  if (fileName && /[،,]/.test(fileName) && !/بارگذاری نشده|uploaded|aucun|keine/i.test(fileName)) {
    fileName = fileName.split(/\s*[،,]\s*/)[0]?.trim() || fileName;
  }

  if (isStandardsGap) {
    page = null;
    if (!fileName) fileName = null;
    if (quote && looksLikeStandardCodeList(quote)) {
      quoteKind = "standards_list";
    } else if (quote) {
      quoteKind = "explanation";
    }
  }

  // Sentence quotes: keep wording exact (strip only OCR/page chrome markers).
  if (quoteKind === "sentence") {
    quote = cleanQuoteForDisplay(quote);
  } else {
    quote = (quote || "").trim() || null;
  }

  return { fileName, page, quote: quote || null, isMissingCategory, quoteKind };
}

function cleanFindingTitle(title: string): string {
  return (title || "")
    .replace(/^\s*\[(تجربه|Experience|Erfahrung|Expérience)\]\s*/i, "")
    .trim();
}

function cleanFindingDescription(description: string): string {
  return (description || "")
    .replace(/^\s*(مبتنی بر تجربه \(قاعده اجباری نیست\)\.|EXPERIENCE-BASED \(not a mandatory rule\)\.|ERFAHRUNGSBASIERT \(keine Pflichtregel\)\.|BASÉ SUR L'EXPÉRIENCE \(pas une règle obligatoire\)\.)\s*/i, "")
    .replace(/\s*\[[^\]]*(validation_status|origin_kind|confidence)[^\]]*\]\s*$/i, "")
    .trim();
}

function analysisReferenceLabel(
  f: { source_layer?: string | null; finding_category?: string | null; code?: string },
  lang: LanguageCode,
): string {
  const layer = (f.source_layer || "").toLowerCase();
  const cat = (f.finding_category || "").toLowerCase();
  const code = (f.code || "").toUpperCase();
  if (cat === "experience" || layer === "experience_based" || code.startsWith("EXP-")) {
    return t(lang, "refExperience");
  }
  if (layer === "llm_based" || layer === "ai") return t(lang, "refAi");
  if (layer === "hybrid") return t(lang, "refHybrid");
  if (layer === "rule_based" || layer === "vision_based") return t(lang, "refRules");
  if (cat === "methodology") return t(lang, "refMethodology");
  if (cat === "limitation") return t(lang, "refExtraction");
  return t(lang, "refRules");
}

function formatEngineChip(engine: string, lang: LanguageCode): string {
  const labels: Record<string, string> = {
    keyword: t(lang, "engineKeyword"),
    python_seed_rules: t(lang, "enginePython"),
    ai_hybrid_seed_rules: t(lang, "engineAi"),
    tender_intelligence: t(lang, "engineTi"),
    experience_layer: t(lang, "engineExperience"),
    vision_drawing: t(lang, "engineVision"),
  };
  return labels[engine] || engine;
}

function AnalysisEngineSummary({
  analysis,
  uiLang,
}: {
  analysis: AnalysisOut;
  uiLang: LanguageCode;
}) {
  const engines = (analysis.engine || "keyword").split("+").filter(Boolean);
  const aiCalls =
    typeof analysis.ai_metrics?.calls === "number" ? analysis.ai_metrics.calls : null;
  const tiChecks =
    typeof analysis.tender_intelligence_metrics?.checks_run === "number"
      ? analysis.tender_intelligence_metrics.checks_run
      : null;
  const counts = [
    analysis.python_rule_findings
      ? `${t(uiLang, "enginePython")}: ${analysis.python_rule_findings}`
      : null,
    analysis.ai_rule_findings ? `${t(uiLang, "engineAi")}: ${analysis.ai_rule_findings}` : null,
    analysis.tender_intelligence_findings
      ? `${t(uiLang, "engineTi")}: ${analysis.tender_intelligence_findings}`
      : null,
    aiCalls != null ? `${t(uiLang, "engineCalls")}: ${aiCalls}` : null,
    tiChecks != null ? `${t(uiLang, "engineTiChecks")}: ${tiChecks}` : null,
  ].filter(Boolean);

  return (
    <div className="engine-summary">
      <strong>{t(uiLang, "engineLabel")}:</strong>{" "}
      {engines.map((e) => formatEngineChip(e, uiLang)).join(" · ")}
      {counts.length > 0 && <span className="muted engine-summary-metrics"> — {counts.join(" · ")}</span>}
    </div>
  );
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
  const [expandedStandardCode, setExpandedStandardCode] = useState<string | null>(null);
  const [analysisStale, setAnalysisStale] = useState(false);
  const [notice, setNotice] = useState<{ text: string; kind: "success" | "error" } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [projectLoading, setProjectLoading] = useState(false);
  const [apiRole, setApiRole] = useState<UserRole>("user");
  const [isAdmin, setIsAdmin] = useState(false);
  /** Landing gate: create-project / list only after explicit login. */
  const [homeLoggedIn, setHomeLoggedIn] = useState(false);
  /** home = marketing; features = capabilities page; login = sign-in; demo = demo registration */
  const [landingPage, setLandingPage] = useState<"home" | "features" | "login" | "demo">("home");
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [authUsername, setAuthUsername] = useState("");
  const [demoFullName, setDemoFullName] = useState("");
  const [demoEmail, setDemoEmail] = useState("");
  const [demoPassword, setDemoPassword] = useState("");
  const [demoCompany, setDemoCompany] = useState("");
  const [demoPhone, setDemoPhone] = useState("");
  const [demoMessage, setDemoMessage] = useState("");
  const [demoBusy, setDemoBusy] = useState(false);
  const [demoError, setDemoError] = useState<string | null>(null);
  const [demoDone, setDemoDone] = useState(false);
  const [demoRequests, setDemoRequests] = useState<DemoRequestOut[]>([]);
  const [demoAdminBusyId, setDemoAdminBusyId] = useState<number | null>(null);
  const [demoSelectedIds, setDemoSelectedIds] = useState<number[]>([]);
  const [demoDeleteBusy, setDemoDeleteBusy] = useState(false);
  const [demoLimits, setDemoLimits] = useState<DemoLimitsOut | null>(null);
  const [demoProjectId, setDemoProjectId] = useState<number | null>(null);
  const [catalogCode, setCatalogCode] = useState("");
  const [catalogTitle, setCatalogTitle] = useState("");
  const catalogSingleInputRef = useRef<HTMLInputElement>(null);
  const [workspaceTab, setWorkspaceTab] = useState<"docs" | "standards" | "report" | "admin">(
    "docs",
  );
  /** Full-page file browser for one document category (null = overview cards). */
  const [docsDetailCat, setDocsDetailCat] = useState<DocumentCategory | null>(null);
  const [docsPanelMode, setDocsPanelMode] = useState<"upload" | "taxonomy">("upload");

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
      setAuthUsername(me.username);
      setDemoLimits(me.demo?.is_demo ? me.demo : null);
      setDemoProjectId(me.demo_project_id ?? null);
      return true;
    } catch {
      setApiRole("user");
      setIsAdmin(false);
      setAuthUsername("");
      setDemoLimits(null);
      setDemoProjectId(null);
      return false;
    }
  }

  function openLoginPage(kind: "user" | "admin" | "demo" = "user") {
    if (kind === "demo") {
      setDemoError(null);
      setDemoDone(false);
      setLandingPage("demo");
      window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    if (kind === "admin") {
      setLoginEmail("admin@tenderrisk.local");
      setLoginPassword("Admin123!");
    } else {
      setLoginEmail("user@tenderrisk.local");
      setLoginPassword("User123!");
    }
    setLoginError(null);
    setLandingPage("login");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function refreshDemoRequests() {
    try {
      const list = await api.listDemoRequests();
      setDemoRequests(list);
      setDemoSelectedIds((prev) => prev.filter((id) => list.some((r) => r.id === id)));
    } catch {
      setDemoRequests([]);
      setDemoSelectedIds([]);
    }
  }

  function toggleDemoSelected(id: number) {
    setDemoSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  function toggleDemoSelectAll() {
    if (demoSelectedIds.length === demoRequests.length) {
      setDemoSelectedIds([]);
    } else {
      setDemoSelectedIds(demoRequests.map((r) => r.id));
    }
  }

  async function deleteSelectedDemos(ids?: number[]) {
    const target = ids && ids.length ? ids : demoSelectedIds;
    if (!target.length) return;
    if (!window.confirm(t(uiLang, "demoAdminDeleteConfirm"))) return;
    setDemoDeleteBusy(true);
    try {
      const res = await api.deleteDemoRequests(target);
      setNotice({
        text: `${t(uiLang, "demoAdminDeleted")} (${res.deleted_count})`,
        kind: "success",
      });
      setDemoSelectedIds([]);
      await refreshDemoRequests();
      await refreshProjects();
    } catch (err) {
      setNotice({ text: parseApiError(err), kind: "error" });
    } finally {
      setDemoDeleteBusy(false);
    }
  }

  async function submitDemoRequest(e: React.FormEvent) {
    e.preventDefault();
    setDemoBusy(true);
    setDemoError(null);
    setDemoDone(false);
    try {
      await api.requestDemo({
        full_name: demoFullName.trim(),
        email: demoEmail.trim(),
        password: demoPassword,
        company: demoCompany.trim() || undefined,
        phone: demoPhone.trim() || undefined,
        message: demoMessage.trim() || undefined,
      });
      setDemoDone(true);
      setDemoPassword("");
    } catch (err) {
      const msg = parseApiError(err);
      setDemoError(msg || t(uiLang, "homeLoginError"));
    } finally {
      setDemoBusy(false);
    }
  }

  async function approveDemo(userId: number) {
    setDemoAdminBusyId(userId);
    try {
      await api.approveDemoRequest(userId);
      await refreshDemoRequests();
      setNotice({ text: t(uiLang, "demoAdminApproved"), kind: "success" });
      await refreshProjects();
    } catch (err) {
      setNotice({ text: parseApiError(err), kind: "error" });
    } finally {
      setDemoAdminBusyId(null);
    }
  }

  async function rejectDemo(userId: number) {
    setDemoAdminBusyId(userId);
    try {
      await api.rejectDemoRequest(userId);
      await refreshDemoRequests();
      setNotice({ text: t(uiLang, "demoAdminRejected"), kind: "success" });
    } catch (err) {
      setNotice({ text: parseApiError(err), kind: "error" });
    } finally {
      setDemoAdminBusyId(null);
    }
  }

  async function submitLogin(e: React.FormEvent) {
    e.preventDefault();
    setLoginBusy(true);
    setLoginError(null);
    setError(null);
    try {
      const res = await api.login(loginEmail.trim(), loginPassword);
      setApiToken(res.api_token);
      setApiRole(res.role);
      setIsAdmin(res.is_admin);
      setAuthUsername(res.username);
      setHomeLoggedIn(true);
      setLoginPassword("");
      setLandingPage("home");
      setDemoLimits(res.demo?.is_demo ? res.demo : null);
      setDemoProjectId(res.demo_project_id ?? null);
      await refreshProjects();
      if (res.is_admin) await refreshDemoRequests();
      if (res.demo_project_id) {
        setSelectedId(res.demo_project_id);
      } else {
        window.setTimeout(() => {
          document.getElementById("home-start")?.scrollIntoView({ behavior: "smooth", block: "start" });
        }, 80);
      }
    } catch (err) {
      const raw = parseApiError(err);
      if (/pending/i.test(raw)) setLoginError(t(uiLang, "demoPendingLogin"));
      else if (/rejected/i.test(raw)) setLoginError(t(uiLang, "demoRejectedLogin"));
      else setLoginError(raw || t(uiLang, "homeLoginError"));
    } finally {
      setLoginBusy(false);
    }
  }

  function logoutHome() {
    setHomeLoggedIn(false);
    setSelectedId(null);
    setProjects([]);
    setApiToken("");
    setApiRole("user");
    setIsAdmin(false);
    setAuthUsername("");
    setLoginEmail("");
    setLoginPassword("");
    setLoginError(null);
    setDemoRequests([]);
    setDemoSelectedIds([]);
    setDemoLimits(null);
    setDemoProjectId(null);
    setLandingPage("home");
  }

  useEffect(() => {
    const token = getApiToken();
    if (!token) return;
    void (async () => {
      const ok = await refreshAuth();
      if (ok) {
        setHomeLoggedIn(true);
        await refreshProjects();
      } else setApiToken("");
    })();
  }, []);

  useEffect(() => {
    if (homeLoggedIn && isAdmin) void refreshDemoRequests();
  }, [homeLoggedIn, isAdmin]);

  useEffect(() => {
    if (isAdmin) setStandardsOpen(true);
  }, [isAdmin]);

  useEffect(() => {
    if (workspaceTab === "standards") setStandardsOpen(true);
    if (workspaceTab !== "docs") {
      setDocsDetailCat(null);
      setDocsPanelMode("upload");
    }
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
    if (!homeLoggedIn) return;
    void refreshProjects();
  }, [homeLoggedIn]);

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
    setProjectLoading(true);
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
      setProject(null);
      setError(parseApiError(e) || t(uiLang, "projectLoadError"));
    } finally {
      setProjectLoading(false);
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
    if (demoLimits?.is_demo && !demoLimits.can_create_project) {
      setError(t(uiLang, "demoLockedCreate"));
      return;
    }
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
      setError(parseApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function uploadCatalogStandards(files: FileList | File[] | null) {
    if (!project || !files?.length) return;
    const list = Array.from(files);
    const singleCode = catalogCode.trim();
    const singleTitle = catalogTitle.trim();
    const usedCodes = new Set<string>();

    setBusy(true);
    setError(null);
    setNotice({
      text: t(uiLang, "catalogUploadStarted").replace("{name}", list[0]?.name || ""),
      kind: "success",
    });
    setUploadProgress({ done: 0, total: list.length, category: "standard" });
    const failed: string[] = [];
    let ok = 0;

    try {
      for (let i = 0; i < list.length; i += 1) {
        const file = list[i];
        const fromName = codeFromStandardFileName(file.name);
        let code =
          list.length === 1 && singleCode
            ? singleCode
            : fromName || `STD_${Date.now().toString(36).toUpperCase()}_${i + 1}`;
        code = code
          .toUpperCase()
          .replace(/[^A-Z0-9._-]+/g, "_")
          .replace(/^_+|_+$/g, "")
          .slice(0, 64);
        if (!code) code = `STD_${Date.now().toString(36).toUpperCase()}_${i + 1}`;
        if (usedCodes.has(code)) {
          code = `${code}_${i + 1}`.slice(0, 64);
        }
        usedCodes.add(code);
        const title =
          list.length === 1 && singleTitle
            ? singleTitle
            : titleFromStandardFileName(file.name) || code;

        try {
          await api.uploadCatalogStandard({
            file,
            standard_code: code,
            title,
            project_id: project.id,
          });
          ok += 1;
        } catch (err) {
          failed.push(`${file.name}: ${parseApiError(err)}`);
        }
        setUploadProgress({
          done: i + 1,
          total: list.length,
          category: "standard",
        });
      }

      if (singleCode) setCatalogCode(singleCode);
      else setCatalogCode("");
      if (singleTitle) setCatalogTitle(singleTitle);
      else setCatalogTitle("");
      setStandardsOpen(true);
      try {
        await loadStandards(project.id);
      } catch (err) {
        failed.push(parseApiError(err));
      }

      if (ok && !failed.length) {
        setNotice({
          text:
            ok === 1
              ? t(uiLang, "catalogUploadOk")
              : t(uiLang, "catalogUploadBulkOk").replace("{n}", String(ok)),
          kind: "success",
        });
      } else if (ok && failed.length) {
        setNotice({
          text: t(uiLang, "catalogUploadPartial")
            .replace("{ok}", String(ok))
            .replace("{fail}", String(failed.length)),
          kind: "success",
        });
        setError(failed.slice(0, 5).join("\n"));
      } else if (failed.length) {
        const msg = failed[0] || t(uiLang, "catalogUploadFailed");
        if (/403|Admin role/i.test(msg)) {
          setError(t(uiLang, "standardsNeedAdmin"));
        } else {
          setError(failed.slice(0, 5).join("\n"));
        }
        setNotice(null);
      }
    } catch (err) {
      setError(parseApiError(err) || t(uiLang, "catalogUploadFailed"));
      setNotice(null);
    } finally {
      setBusy(false);
      setUploadProgress(null);
    }
  }

  function openCatalogUploadForStandard(code: string, title: string) {
    if (!project || busy) return;
    setCatalogCode(code);
    setCatalogTitle(title);
    window.setTimeout(() => catalogSingleInputRef.current?.click(), 0);
  }

  async function onUpload(category: DocumentCategory, files: FileList | File[] | null) {
    if (!project || !files?.length) return;
    if (demoLimits?.is_demo && !demoLimits.can_upload) {
      setError(t(uiLang, "demoLockedUpload"));
      return;
    }
    const list = Array.from(files);
    setBusy(true);
    setError(null);
    setUploadProgress({ done: 0, total: list.length, category });
    const failed: string[] = [];
    try {
      for (let i = 0; i < list.length; i += UPLOAD_CHUNK_SIZE) {
        const chunk = list.slice(i, i + UPLOAD_CHUNK_SIZE);
        const uploadChunk = async (files: File[]) => {
          const result = await api.uploadDocuments(project.id, category, files);
          for (const err of result.errors) {
            failed.push(`${err.filename}: ${err.detail}`);
          }
        };
        try {
          await uploadChunk(chunk);
        } catch {
          for (const file of chunk) {
            try {
              await uploadChunk([file]);
            } catch (e) {
              failed.push(`${file.name}: ${parseApiError(e)}`);
            }
          }
        }
        setUploadProgress({
          done: Math.min(i + chunk.length, list.length),
          total: list.length,
          category,
        });
      }
      await loadProject(project.id, { includeAnalysis: false });
      setAnalysisStale(true);
      await refreshAuth();
      if (failed.length) {
        const preview = failed.slice(0, 5).join("\n");
        const more = failed.length > 5 ? `\n… +${failed.length - 5}` : "";
        setError(`${t(uiLang, "uploadPartial")}\n${preview}${more}`);
      } else {
        setNotice({ text: t(uiLang, "docsChangedReanalyze"), kind: "success" });
      }
    } catch (e) {
      setError(parseApiError(e));
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
    if (demoLimits?.is_demo && !demoLimits.can_analyze) {
      setError(t(uiLang, "demoLockedAnalyze"));
      return;
    }
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
      await refreshAuth();
      setNotice({
        text: t(uiLang, "analyzeDone")
          .replace("{n}", String(p.documents.length))
          .replace("{findings}", String(a.findings?.length ?? 0)),
        kind: "success",
      });
    } catch (e) {
      setError(parseApiError(e));
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
              setLandingPage("home");
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
              <button
                type="button"
                className={landingPage === "home" ? "is-active" : undefined}
                onClick={() => setLandingPage("home")}
              >
                {t(uiLang, "homeNavHome")}
              </button>
              <button
                type="button"
                className={landingPage === "features" ? "is-active" : undefined}
                onClick={() => {
                  setLandingPage("features");
                  window.scrollTo({ top: 0, behavior: "smooth" });
                }}
              >
                {t(uiLang, "homeNavFeatures")}
              </button>
              <button type="button" onClick={() => setLandingPage("home")}>
                {t(uiLang, "homeNavPricing")}
              </button>
              <button type="button" onClick={() => setLandingPage("home")}>
                {t(uiLang, "homeNavResources")}
              </button>
              <button type="button" onClick={() => setLandingPage("home")}>
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
                {homeLoggedIn ? (
                  <>
                    <span className="landing-user" title={authUsername}>
                      {authUsername}
                      {isAdmin ? ` · ${t(uiLang, "roleAdmin")}` : ""}
                    </span>
                    <button type="button" className="landing-login" onClick={logoutHome}>
                      {t(uiLang, "homeLogout")}
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      className="landing-login"
                      onClick={() => openLoginPage("user")}
                    >
                      {t(uiLang, "homeLoginAsUser")}
                    </button>
                    <button
                      type="button"
                      className="landing-login landing-login-admin"
                      onClick={() => openLoginPage("admin")}
                    >
                      {t(uiLang, "homeLoginAsAdmin")}
                    </button>
                  </>
                )}
                <button type="button" className="landing-demo" onClick={() => openLoginPage("demo")}>
                  {t(uiLang, "homeNavDemo")}
                </button>
              </>
            ) : null}
          </div>
        </div>
      </header>

      {!selectedId && landingPage === "home" ? (
        <section className="hero-section">
          <div className="hero-container">
            <div className="hero-image-wrapper">
              <img
                className="hero-image"
                src="/home-hero-bim.png"
                alt="پروژه ساختمانی"
                width={1024}
                height={772}
                decoding="async"
                fetchPriority="high"
                sizes="(max-width: 1280px) 100vw, 1280px"
              />
            </div>
            <div className="hero-text-block">
              <h1>{t(uiLang, "homeHeroTitle")}</h1>
              <p className="tagline">{t(uiLang, "tagline")}</p>
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
              {homeLoggedIn ? (
                <div className="home-cta-row home-hero-auth-row">
                  <button
                    type="button"
                    className="home-cta-primary"
                    onClick={() =>
                      document.getElementById("home-start")?.scrollIntoView({ behavior: "smooth", block: "start" })
                    }
                  >
                    {t(uiLang, "homeCta")}
                    <span aria-hidden="true">→</span>
                  </button>
                </div>
              ) : (
                <div className="home-cta-row home-hero-auth-row">
                  <button
                    type="button"
                    className="home-cta-primary"
                    onClick={() => openLoginPage("user")}
                  >
                    {t(uiLang, "homeLoginAsUser")}
                  </button>
                  <button
                    type="button"
                    className="home-cta-secondary"
                    onClick={() => openLoginPage("admin")}
                  >
                    {t(uiLang, "homeLoginAsAdmin")}
                  </button>
                </div>
              )}
            </div>
          </div>
        </section>
      ) : null}

      {!selectedId && landingPage === "features" ? (
        <section className="home-features home-features-page" id="home-features">
          <div className="home-features-inner">
            <button type="button" className="login-page-back linkish" onClick={() => setLandingPage("home")}>
              ← {t(uiLang, "homeNavHome")}
            </button>
            <header className="home-features-head">
              <h2>{t(uiLang, "homeFeaturesTitle")}</h2>
              <p>{t(uiLang, "homeFeaturesLead")}</p>
            </header>
            <ul className="home-features-grid">
              {(
                [
                  ["homeFeature1Title", "homeFeature1En", "homeFeature1Text"],
                  ["homeFeature2Title", "homeFeature2En", "homeFeature2Text"],
                  ["homeFeature3Title", "homeFeature3En", "homeFeature3Text"],
                  ["homeFeature4Title", "homeFeature4En", "homeFeature4Text"],
                  ["homeFeature5Title", "homeFeature5En", "homeFeature5Text"],
                  ["homeFeature6Title", "homeFeature6En", "homeFeature6Text"],
                ] as const
              ).map(([titleKey, enKey, textKey], idx) => (
                <li key={titleKey}>
                  <span className="home-feature-index" aria-hidden="true">
                    {String(idx + 1).padStart(2, "0")}
                  </span>
                  <div>
                    <h3>{t(uiLang, titleKey)}</h3>
                    <p className="home-feature-en">{t(uiLang, enKey)}</p>
                    <p>{t(uiLang, textKey)}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </section>
      ) : null}

      {!selectedId && landingPage === "login" ? (
        <section className="login-page" id="home-login">
          <div className="login-page-card panel">
            <button type="button" className="login-page-back linkish" onClick={() => setLandingPage("home")}>
              ← {t(uiLang, "homeNavHome")}
            </button>
            <h1>{t(uiLang, "homeLoginTitle")}</h1>
            <p className="muted">{t(uiLang, "homeLoginHint")}</p>
            <div className="home-login-role-row">
              <button type="button" className="home-login-role" onClick={() => openLoginPage("user")}>
                {t(uiLang, "homeLoginAsUser")}
              </button>
              <button
                type="button"
                className="home-login-role home-login-role-admin"
                onClick={() => openLoginPage("admin")}
              >
                {t(uiLang, "homeLoginAsAdmin")}
              </button>
            </div>
            <form className="home-login-form" onSubmit={(e) => void submitLogin(e)}>
              <label>
                {t(uiLang, "homeLoginEmail")}
                <input
                  type="email"
                  autoComplete="email"
                  value={loginEmail}
                  onChange={(e) => setLoginEmail(e.target.value)}
                  required
                  placeholder="user@tenderrisk.local"
                />
              </label>
              <label>
                {t(uiLang, "homeLoginPassword")}
                <input
                  type="password"
                  autoComplete="current-password"
                  value={loginPassword}
                  onChange={(e) => setLoginPassword(e.target.value)}
                  required
                  placeholder="••••••••"
                />
              </label>
              {loginError ? (
                <p className="home-login-error" role="alert">
                  {loginError}
                </p>
              ) : null}
              <button type="submit" className="home-cta-primary home-login-submit" disabled={loginBusy}>
                {loginBusy ? "…" : t(uiLang, "homeLoginSubmit")}
                <span aria-hidden="true">→</span>
              </button>
            </form>
            <p className="home-login-accounts">{t(uiLang, "homeLoginAccounts")}</p>
          </div>
        </section>
      ) : null}

      {!selectedId && landingPage === "demo" ? (
        <section className="login-page demo-page" id="home-demo">
          <div className="login-page-card panel">
            <button type="button" className="login-page-back linkish" onClick={() => setLandingPage("home")}>
              ← {t(uiLang, "homeNavHome")}
            </button>
            <h1>{t(uiLang, "demoTitle")}</h1>
            <p className="muted">{t(uiLang, "demoHint")}</p>
            <p className="muted demo-limits-hint">{t(uiLang, "demoHintLimits")}</p>
            {demoDone ? (
              <div className="demo-success" role="status">
                <p>{t(uiLang, "demoSuccess")}</p>
                <button
                  type="button"
                  className="home-cta-primary"
                  onClick={() => {
                    setLoginEmail(demoEmail);
                    setLoginPassword("");
                    setLoginError(null);
                    setLandingPage("login");
                  }}
                >
                  {t(uiLang, "homeLoginSubmit")}
                </button>
              </div>
            ) : (
              <form className="home-login-form" onSubmit={(e) => void submitDemoRequest(e)}>
                <label>
                  {t(uiLang, "demoFullName")}
                  <input
                    value={demoFullName}
                    onChange={(e) => setDemoFullName(e.target.value)}
                    required
                    minLength={2}
                    autoComplete="name"
                  />
                </label>
                <label>
                  {t(uiLang, "homeLoginEmail")}
                  <input
                    type="email"
                    value={demoEmail}
                    onChange={(e) => setDemoEmail(e.target.value)}
                    required
                    autoComplete="email"
                  />
                </label>
                <label>
                  {t(uiLang, "demoPassword")}
                  <input
                    type="password"
                    value={demoPassword}
                    onChange={(e) => setDemoPassword(e.target.value)}
                    required
                    minLength={8}
                    autoComplete="new-password"
                  />
                </label>
                <label>
                  {t(uiLang, "demoCompany")}
                  <input value={demoCompany} onChange={(e) => setDemoCompany(e.target.value)} />
                </label>
                <label>
                  {t(uiLang, "demoPhone")}
                  <input value={demoPhone} onChange={(e) => setDemoPhone(e.target.value)} autoComplete="tel" />
                </label>
                <label>
                  {t(uiLang, "demoMessage")}
                  <textarea
                    value={demoMessage}
                    onChange={(e) => setDemoMessage(e.target.value)}
                    rows={3}
                  />
                </label>
                {demoError ? (
                  <p className="home-login-error" role="alert">
                    {demoError}
                  </p>
                ) : null}
                <button type="submit" className="home-cta-primary home-login-submit" disabled={demoBusy}>
                  {demoBusy ? "…" : t(uiLang, "demoSubmit")}
                </button>
              </form>
            )}
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

        {homeLoggedIn && demoLimits?.is_demo ? (
          <aside className={`demo-banner${demoLimits.expired ? " is-expired" : ""}`} role="status">
            <strong>{t(uiLang, "demoBadge")}</strong>
            <span>{t(uiLang, "demoBannerTitle")}</span>
            <span>
              {t(uiLang, "demoBannerQuota")
                .replace("{docs}", String(demoLimits.documents_used))
                .replace("{maxDocs}", String(demoLimits.max_documents))
                .replace("{runs}", String(demoLimits.analyses_used))
                .replace("{maxRuns}", String(demoLimits.max_analyses))}
            </span>
            {demoLimits.expired ? (
              <span>{t(uiLang, "demoBannerExpired")}</span>
            ) : (
              <span>
                {t(uiLang, "demoBannerExpiry")
                  .replace(
                    "{date}",
                    demoLimits.expires_at
                      ? new Date(demoLimits.expires_at).toLocaleDateString(uiLang === "fa" ? "fa-IR" : uiLang)
                      : "—",
                  )
                  .replace("{days}", String(demoLimits.days_left ?? 0))}
              </span>
            )}
          </aside>
        ) : null}

        {!selectedId && homeLoggedIn && (
          <section className="panel home-panel" id="home-start">
            {demoLimits?.is_demo ? (
              <>
                <div className="home-panel-head">
                  <h2>{t(uiLang, "demoBadge")}</h2>
                  <p className="muted">{t(uiLang, "demoHowToTest")}</p>
                </div>
                <button
                  type="button"
                  className="primary"
                  disabled={busy || (!demoProjectId && projects.length === 0)}
                  onClick={() => {
                    const id = demoProjectId || projects.find((p) => p.is_demo)?.id || projects[0]?.id;
                    if (id == null) return;
                    setWorkspaceTab("docs");
                    setSelectedId(id);
                  }}
                >
                  {t(uiLang, "demoOpenWorkspace")}
                  <span aria-hidden="true">→</span>
                </button>
              </>
            ) : (
              <>
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
              </>
            )}

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

        {!selectedId && homeLoggedIn && isAdmin ? (
          <section className="panel home-panel demo-admin-panel" id="demo-requests">
            <div className="home-panel-head">
              <h2>{t(uiLang, "demoAdminTitle")}</h2>
              <button type="button" className="linkish" onClick={() => void refreshDemoRequests()}>
                ↻
              </button>
            </div>
            {demoRequests.length === 0 ? (
              <p className="muted">{t(uiLang, "demoAdminEmpty")}</p>
            ) : (
              <>
                <div className="demo-admin-toolbar">
                  <label className="demo-select-all">
                    <input
                      type="checkbox"
                      checked={demoSelectedIds.length === demoRequests.length && demoRequests.length > 0}
                      onChange={toggleDemoSelectAll}
                    />
                    <span>
                      {t(uiLang, "demoAdminSelectAll")}
                      {demoSelectedIds.length ? ` (${demoSelectedIds.length})` : ""}
                    </span>
                  </label>
                  <button
                    type="button"
                    className="demo-delete-btn"
                    disabled={demoDeleteBusy || demoSelectedIds.length === 0}
                    onClick={() => void deleteSelectedDemos()}
                  >
                    {t(uiLang, "demoAdminDelete")}
                  </button>
                </div>
                <ul className="demo-request-list">
                  {demoRequests.map((req) => (
                    <li
                      key={req.id}
                      className={`demo-request-item is-${req.status}${
                        demoSelectedIds.includes(req.id) ? " is-selected" : ""
                      }`}
                    >
                      <label className="demo-request-check">
                        <input
                          type="checkbox"
                          checked={demoSelectedIds.includes(req.id)}
                          onChange={() => toggleDemoSelected(req.id)}
                        />
                      </label>
                      <div>
                        <strong>{req.full_name || req.username}</strong>
                        <span>
                          {req.email}
                          {req.company ? ` · ${req.company}` : ""}
                          {req.phone ? ` · ${req.phone}` : ""}
                        </span>
                        {req.message ? <p className="muted">{req.message}</p> : null}
                        <span className="demo-status-badge">
                          {t(uiLang, "demoStatus")}:{" "}
                          {req.status === "pending"
                            ? t(uiLang, "demoAdminPending")
                            : req.status === "approved"
                              ? t(uiLang, "demoAdminApproved")
                              : t(uiLang, "demoAdminRejected")}
                          {req.demo_project_id ? ` · #${req.demo_project_id}` : ""}
                        </span>
                      </div>
                      <div className="demo-request-actions">
                        {req.status === "pending" ? (
                          <>
                            <button
                              type="button"
                              className="primary soft"
                              disabled={demoAdminBusyId === req.id || demoDeleteBusy}
                              onClick={() => void approveDemo(req.id)}
                            >
                              {t(uiLang, "demoAdminApprove")}
                            </button>
                            <button
                              type="button"
                              className="linkish"
                              disabled={demoAdminBusyId === req.id || demoDeleteBusy}
                              onClick={() => void rejectDemo(req.id)}
                            >
                              {t(uiLang, "demoAdminReject")}
                            </button>
                          </>
                        ) : null}
                        <button
                          type="button"
                          className="linkish demo-delete-one"
                          disabled={demoDeleteBusy}
                          onClick={() => void deleteSelectedDemos([req.id])}
                        >
                          {t(uiLang, "demoAdminDeleteOne")}
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
        ) : null}

        {selectedId && !project && projectLoading ? (
          <section className="panel home-panel">
            <p className="muted" role="status">
              {t(uiLang, "projectLoading")}
            </p>
          </section>
        ) : null}

        {selectedId && !project && !projectLoading ? (
          <section className="panel home-panel">
            <p className="home-login-error" role="alert">
              {error || t(uiLang, "projectLoadError")}
            </p>
            <button
              type="button"
              className="primary soft"
              onClick={() => {
                setSelectedId(null);
                setError(null);
              }}
            >
              {t(uiLang, "back")}
            </button>
          </section>
        ) : null}

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
                <strong>
                  {project.name}
                  {project.is_demo || demoLimits?.is_demo ? (
                    <span className="demo-chip">{t(uiLang, "demoBadge")}</span>
                  ) : null}
                </strong>
                <span>
                  {project.country} · {project.project_type || "infrastructure"}
                  {project.country_profile_code ? ` · ${project.country_profile_code}` : ""}
                </span>
              </div>
              <button
                className="primary analyze-cta"
                disabled={busy || (demoLimits?.is_demo === true && !demoLimits.can_analyze)}
                onClick={() => void runAnalysis()}
                title={
                  demoLimits?.is_demo && !demoLimits.can_analyze ? t(uiLang, "demoLockedAnalyze") : undefined
                }
              >
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

            {workspaceTab === "docs" && !docsDetailCat ? (
              <nav className="docs-subtabs" aria-label={t(uiLang, "docsSubNavLabel")}>
                <button
                  type="button"
                  className={docsPanelMode === "upload" ? "docs-subtab on" : "docs-subtab"}
                  onClick={() => setDocsPanelMode("upload")}
                >
                  {t(uiLang, "docsSubUpload")}
                </button>
                <button
                  type="button"
                  className={docsPanelMode === "taxonomy" ? "docs-subtab on" : "docs-subtab"}
                  onClick={() => setDocsPanelMode("taxonomy")}
                >
                  {t(uiLang, "docsSubTaxonomy")}
                </button>
              </nav>
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

            {workspaceTab === "docs" && !docsDetailCat && docsPanelMode === "taxonomy" ? (
              <TaxonomyBrowser uiLang={uiLang} />
            ) : null}

            {workspaceTab === "docs" && !docsDetailCat && docsPanelMode === "upload" ? (
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
                            setNotice({ text: t(uiLang, "downloadPdfStarting"), kind: "success" });
                            void api
                              .downloadProjectStandardPdf(project.id, s.standard_code)
                              .then((name) =>
                                setNotice({
                                  text: t(uiLang, "downloadPdfOk").replace("{name}", name),
                                  kind: "success",
                                }),
                              )
                              .catch((err: Error) => {
                                const msg = parseApiError(err) || t(uiLang, "downloadPdfFailed");
                                setError(msg);
                                setNotice({ text: msg, kind: "error" });
                              });
                          }}
                        >
                          {t(uiLang, "downloadPdf")}
                        </button>
                      ) : isAdmin ? (
                        <button
                          type="button"
                          className="linkish std-upload"
                          disabled={busy}
                          onClick={() => openCatalogUploadForStandard(s.standard_code, s.title)}
                        >
                          {t(uiLang, "uploadStandardFile")}
                        </button>
                      ) : (
                        <span className="muted">{t(uiLang, "downloadUnavailable")}</span>
                      )}
                      <button
                        type="button"
                        className="linkish std-sections-btn"
                        disabled={busy}
                        onClick={() =>
                          setExpandedStandardCode((prev) =>
                            prev === s.standard_code ? null : s.standard_code,
                          )
                        }
                      >
                        {expandedStandardCode === s.standard_code
                          ? t(uiLang, "stdSectionsHide")
                          : t(uiLang, "stdSectionsShow")}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {expandedStandardCode && project ? (
                <StandardSectionBrowser
                  projectId={project.id}
                  standardCode={expandedStandardCode}
                  standardTitle={
                    projectStandards.find((x) => x.standard_code === expandedStandardCode)?.title ||
                    expandedStandardCode
                  }
                  uiLang={uiLang}
                  onClose={() => setExpandedStandardCode(null)}
                />
              ) : null}
              {isAdmin ? (
                <>
                  <h4 className="standards-admin-title">{t(uiLang, "standardsAdminUploadTitle")}</h4>
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
                  <p className="muted upload-hint">{t(uiLang, "standardsBulkHint")}</p>
                  <p className="format-line">{t(uiLang, "formatsStandard")}</p>
                  {busy && uploadProgress?.category === "standard" ? (
                    <p className="upload-progress" role="status">
                      {uploadProgress.done === 0
                        ? t(uiLang, "catalogUploadSending")
                        : t(uiLang, "uploadingProgress")
                            .replace("{done}", String(uploadProgress.done))
                            .replace("{total}", String(uploadProgress.total))}
                    </p>
                  ) : null}
                  <div className="standards-upload-actions">
                    <label className={`file-btn${busy || !project ? " disabled" : ""}`}>
                      {busy && uploadProgress?.category === "standard"
                        ? t(uiLang, "uploading")
                        : t(uiLang, "uploadCatalogStandard")}
                      <input
                        ref={catalogSingleInputRef}
                        type="file"
                        accept={CATALOG_STANDARD_ACCEPT}
                        disabled={busy || !project}
                        onChange={(e) => {
                          const picked = e.target.files ? Array.from(e.target.files) : [];
                          e.target.value = "";
                          if (picked.length) void uploadCatalogStandards(picked);
                        }}
                      />
                    </label>
                    <label className={`file-btn secondary${busy || !project ? " disabled" : ""}`}>
                      {busy && uploadProgress?.category === "standard"
                        ? t(uiLang, "uploading")
                        : t(uiLang, "uploadCatalogStandardBulk")}
                      <input
                        type="file"
                        accept={CATALOG_STANDARD_ACCEPT}
                        multiple
                        disabled={busy || !project}
                        onChange={(e) => {
                          const picked = e.target.files ? Array.from(e.target.files) : [];
                          e.target.value = "";
                          if (picked.length) void uploadCatalogStandards(picked);
                        }}
                      />
                    </label>
                  </div>
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
              <>
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
              <ProjectRegistryPanel
                uiLang={uiLang}
                busy={busy}
                setBusy={setBusy}
                onNotify={(text, kind) => {
                  setNotice({ text, kind });
                  if (kind === "error") setError(text);
                }}
                onError={(text) => setError(text)}
              />
              </>
            ) : null}

            {workspaceTab === "report" ? (
              analysis ? (
              <div className="report panel">
                {(() => {
                  const unique = new Map<number, (typeof analysis.findings)[0]>();
                  for (const f of analysis.findings) unique.set(f.id, f);
                  const all = [...unique.values()];
                  const limitations = all.filter((f) => findingTier(f) === "limitation");
                  const risks = all.filter((f) => findingTier(f) === "risk");
                  const experiences = all.filter((f) => findingTier(f) === "experience");
                  const methodology = all.filter((f) => findingTier(f) === "methodology");
                  const mix = countSeverityMix([...risks, ...experiences]);
                  return (
                    <>
                      <ReportDashboard
                        uiLang={uiLang}
                        readiness={analysis.readiness_score}
                        high={mix.high}
                        medium={mix.medium}
                        low={mix.low}
                        avgRisk={analysis.aggregate_risk_score ?? null}
                        docsLimited={analysis.documents_with_limitations ?? null}
                        summary={analysis.summary || ""}
                        blocked={analysis.status === "blocked"}
                      />

                      <AnalysisEngineSummary analysis={analysis} uiLang={uiLang} />

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
                          {risks.map((f, idx) => {
                            const src = resolveFindingSource(
                              f,
                              project?.documents.map((d) => ({
                                original_name: d.original_name,
                                category: d.category,
                              })),
                            );
                            const steps = humanCauseSteps(f.cause_effect_chain);
                            const scorePct =
                              f.risk_score != null && Number.isFinite(f.risk_score)
                                ? `${Math.round(f.risk_score)}%`
                                : "—";
                            const sev = severityFromRiskScore(f.risk_score, f.severity);
                            const findingNo = idx + 1;
                            return (
                              <article key={f.id} className={`finding sev-${sev} finding-risk`}>
                                <header className="finding-topbar">
                                  <div className="finding-metrics">
                                    <span className="badge">
                                      <span className="metric-label">{t(uiLang, "riskSeverityLabel")}</span>
                                      <strong>{t(uiLang, sev)}</strong>
                                    </span>
                                    <span className="badge score-badge">
                                      <span className="metric-label">{t(uiLang, "riskScorePercent")}</span>
                                      <strong>{scorePct}</strong>
                                    </span>
                                  </div>
                                  <span className="finding-ref">{analysisReferenceLabel(f, uiLang)}</span>
                                </header>

                                <div
                                  className={`finding-source-file${src.isMissingCategory ? " is-missing" : ""}`}
                                >
                                  <span className="source-file-label">{t(uiLang, "sourceFileLabel")}</span>
                                  <strong className="source-file-name" title={src.fileName || undefined}>
                                    {src.fileName ||
                                      (src.quoteKind !== "sentence"
                                        ? t(uiLang, "sourceFileCorpus")
                                        : t(uiLang, "sourceFileUnknown"))}
                                  </strong>
                                  {!src.isMissingCategory && src.quoteKind === "sentence" ? (
                                    <span className="source-page-pill">
                                      {t(uiLang, "sourcePageLabel")}:{" "}
                                      {src.page != null ? src.page : t(uiLang, "sourcePageUnknown")}
                                    </span>
                                  ) : src.isMissingCategory ? (
                                    <span className="source-page-pill source-missing-pill">
                                      {t(uiLang, "sourceFileActionUpload")}
                                    </span>
                                  ) : null}
                                </div>

                                <h3>
                                  {findingNo}. {cleanFindingTitle(f.title)}
                                </h3>
                                <p>{cleanFindingDescription(f.description)}</p>

                                {src.quote ? (
                                  <div className="source-quote-block">
                                    <div className="source-quote-head">
                                      <span>
                                        {src.quoteKind === "explanation"
                                          ? t(uiLang, "sourceGapExplainLabel")
                                          : src.quoteKind === "standards_list"
                                            ? t(uiLang, "standardsGapListLabel")
                                            : t(uiLang, "sourceQuoteLabel")}
                                      </span>
                                      {src.quoteKind === "sentence" ? (
                                        <span className="source-quote-page">
                                          {t(uiLang, "sourcePageLabel")}{" "}
                                          {src.page != null ? src.page : t(uiLang, "sourcePageUnknown")}
                                        </span>
                                      ) : null}
                                    </div>
                                    <blockquote className="source-excerpt" dir="auto">
                                      {src.quoteKind === "sentence" ? "«" : ""}
                                      {src.quoteKind === "sentence"
                                        ? src.quote
                                        : shortenText(src.quote, 420)}
                                      {src.quoteKind === "sentence" ? "»" : ""}
                                    </blockquote>
                                  </div>
                                ) : null}
                                {f.evidence &&
                                looksLikeStandardCodeList(f.evidence) &&
                                src.quoteKind !== "standards_list" ? (
                                  <div className="source-quote-block">
                                    <div className="source-quote-head">
                                      <span>{t(uiLang, "standardsGapListLabel")}</span>
                                    </div>
                                    <blockquote className="source-excerpt" dir="auto">
                                      {shortenText(f.evidence, 420)}
                                    </blockquote>
                                  </div>
                                ) : null}

                                {steps.length > 0 && (
                                  <div className="cause-chain">
                                    <span className="chain-label">{t(uiLang, "causeEffect")}</span>
                                    <ol>
                                      {steps.map((step, i) => (
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
                            );
                          })}
                        </div>
                      )}

                      {experiences.length > 0 && (
                        <>
                          <h2>{t(uiLang, "experienceFindings")}</h2>
                          <div className="findings experience-findings">
                            {experiences.map((f, idx) => {
                              const src = resolveFindingSource(
                                f,
                                project?.documents.map((d) => ({
                                  original_name: d.original_name,
                                  category: d.category,
                                })),
                              );
                              const scorePct =
                                f.risk_score != null && Number.isFinite(f.risk_score)
                                  ? `${Math.round(f.risk_score)}%`
                                  : "—";
                              const sev = severityFromRiskScore(f.risk_score, f.severity, {
                                capAtMedium: true,
                              });
                              const findingNo = risks.length + idx + 1;
                              return (
                                <article
                                  key={f.id}
                                  className={`finding sev-${sev} finding-experience`}
                                >
                                  <header className="finding-topbar">
                                    <div className="finding-metrics">
                                      <span className="badge">
                                        <span className="metric-label">{t(uiLang, "riskSeverityLabel")}</span>
                                        <strong>{t(uiLang, sev)}</strong>
                                      </span>
                                      <span className="badge score-badge">
                                        <span className="metric-label">{t(uiLang, "riskScorePercent")}</span>
                                        <strong>{scorePct}</strong>
                                      </span>
                                    </div>
                                    <span className="finding-ref">{analysisReferenceLabel(f, uiLang)}</span>
                                  </header>
                                  <div className="finding-source-file">
                                    <span className="source-file-label">{t(uiLang, "sourceFileLabel")}</span>
                                    <strong className="source-file-name" title={src.fileName || undefined}>
                                      {src.fileName || t(uiLang, "sourceFileUnknown")}
                                    </strong>
                                    <span className="source-page-pill">
                                      {t(uiLang, "sourcePageLabel")}:{" "}
                                      {src.page != null ? src.page : t(uiLang, "sourcePageUnknown")}
                                    </span>
                                  </div>
                                  <h3>
                                    {findingNo}. {cleanFindingTitle(f.title)}
                                  </h3>
                                  <p>{cleanFindingDescription(f.description)}</p>
                                  {src.quote ? (
                                    <div className="source-quote-block">
                                      <div className="source-quote-head">
                                        <span>{t(uiLang, "sourceQuoteLabel")}</span>
                                        <span className="source-quote-page">
                                          {t(uiLang, "sourcePageLabel")}{" "}
                                          {src.page != null ? src.page : t(uiLang, "sourcePageUnknown")}
                                        </span>
                                      </div>
                                      <blockquote className="source-excerpt" dir="auto">
                                        «{src.quote}»
                                      </blockquote>
                                    </div>
                                  ) : null}
                                  <p>
                                    <strong>{t(uiLang, "recommendation")}:</strong> {f.recommendation}
                                  </p>
                                  {f.data_completeness_caveat && (
                                    <p className="caveat">{f.data_completeness_caveat}</p>
                                  )}
                                </article>
                              );
                            })}
                          </div>
                        </>
                      )}

                      {methodology.length > 0 && (
                        <details className="methodology-footer">
                          <summary>{t(uiLang, "methodologyFooter")}</summary>
                          {methodology.map((f, idx) => (
                            <div key={f.id} className="methodology-item">
                              <strong>
                                #{risks.length + experiences.length + idx + 1}{" "}
                                {cleanFindingTitle(f.title)}
                              </strong>
                              <p>{cleanFindingDescription(f.description)}</p>
                              <span className="finding-ref muted">{analysisReferenceLabel(f, uiLang)}</span>
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
