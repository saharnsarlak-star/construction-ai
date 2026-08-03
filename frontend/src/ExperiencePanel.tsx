import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type ExperienceOut,
  type LanguageCode,
  type ProjectType,
} from "./api";
import { projectTypeOptions, t } from "./i18n";

const CATEGORY_CODES = [
  "schedule",
  "boq_cost",
  "drawing_technical",
  "contract_claims",
  "standards_compliance",
  "safety_hse",
  "geotech_foundation",
  "procurement_tender",
  "lesson",
] as const;

type Props = {
  uiLang: LanguageCode;
  busy: boolean;
  setBusy: (v: boolean) => void;
  onNotify: (text: string, kind: "success" | "error") => void;
  onError: (text: string) => void;
};

export function ExperiencePanel({ uiLang, busy, setBusy, onNotify, onError }: Props) {
  const [items, setItems] = useState<ExperienceOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [filterCat, setFilterCat] = useState("");
  const [query, setQuery] = useState("");
  const [showInactive, setShowInactive] = useState(true);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [prevention, setPrevention] = useState("");
  const [category, setCategory] = useState("lesson");
  const [keywords, setKeywords] = useState("");
  const [projectTypes, setProjectTypes] = useState<string[]>([]);

  const [bulkText, setBulkText] = useState("");
  const [editing, setEditing] = useState<ExperienceOut | null>(null);
  const [viewing, setViewing] = useState<ExperienceOut | null>(null);
  const formRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await api.listExperience({
        active_only: !showInactive,
        category: filterCat || undefined,
        q: query.trim() || undefined,
      });
      setItems(rows);
      setViewing((prev) => {
        if (!prev) return null;
        return rows.find((r) => r.experience_id === prev.experience_id) ?? null;
      });
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [filterCat, onError, query, showInactive]);

  useEffect(() => {
    void load();
  }, [load]);

  const grouped = useMemo(() => {
    const map = new Map<string, ExperienceOut[]>();
    for (const it of items) {
      const key = it.category || "lesson";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(it);
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [items]);

  const itemNumbers = useMemo(() => {
    const map = new Map<string, number>();
    let n = 0;
    for (const [, rows] of grouped) {
      for (const it of rows) {
        n += 1;
        map.set(it.experience_id, n);
      }
    }
    return map;
  }, [grouped]);

  function formatExpNo(n: number): string {
    const raw = String(n);
    if (uiLang !== "fa") return raw;
    return raw.replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]!);
  }

  function resetForm() {
    setTitle("");
    setDescription("");
    setPrevention("");
    setCategory("lesson");
    setKeywords("");
    setProjectTypes([]);
    setEditing(null);
  }

  async function onSuggest() {
    const text = `${title}\n${description}`.trim();
    if (!text) return;
    setBusy(true);
    try {
      const s = await api.suggestExperience(text);
      setCategory(s.category || "lesson");
      if (s.title_suggestion && !title.trim()) setTitle(s.title_suggestion);
      if (s.match_keywords?.length) setKeywords(s.match_keywords.join(", "));
      onNotify(t(uiLang, "experienceSuggestOk"), "success");
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onSaveOne() {
    if (title.trim().length < 3) {
      onError(t(uiLang, "experienceTitleRequired"));
      return;
    }
    setBusy(true);
    try {
      const kws = keywords
        .split(/[,،\n]/)
        .map((x) => x.trim())
        .filter(Boolean);
      if (editing) {
        await api.patchExperience(editing.experience_id, {
          title: title.trim(),
          description: description.trim(),
          category,
          recommended_prevention: prevention.trim() || undefined,
          match_keywords: kws,
          related_project_types: projectTypes,
        });
        onNotify(t(uiLang, "experienceUpdated"), "success");
      } else {
        await api.createExperience({
          title: title.trim(),
          description: description.trim(),
          category,
          recommended_prevention: prevention.trim() || undefined,
          match_keywords: kws,
          related_project_types: projectTypes,
        });
        onNotify(t(uiLang, "experienceCreated"), "success");
      }
      resetForm();
      await load();
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onBulk() {
    if (!bulkText.trim()) {
      onError(t(uiLang, "experienceBulkEmpty"));
      return;
    }
    setBusy(true);
    try {
      const res = await api.bulkCreateExperience({
        raw_text: bulkText,
        default_category: category !== "lesson" ? category : undefined,
        default_project_types: projectTypes,
        auto_categorize: true,
      });
      onNotify(
        t(uiLang, "experienceBulkOk")
          .replace("{n}", String(res.created_count))
          .replace("{s}", String(res.skipped)),
        "success",
      );
      setBulkText("");
      await load();
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function startEdit(item: ExperienceOut) {
    setEditing(item);
    setViewing(null);
    setTitle(item.title);
    setDescription(item.description || "");
    setPrevention(item.recommended_prevention || "");
    setCategory(item.category || "lesson");
    setKeywords((item.match_keywords || []).join(", "));
    setProjectTypes(item.related_project_types || []);
    window.setTimeout(() => {
      formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 50);
  }

  function openView(item: ExperienceOut) {
    setViewing((prev) => (prev?.experience_id === item.experience_id ? null : item));
    setEditing(null);
  }

  async function toggleActive(item: ExperienceOut) {
    setBusy(true);
    try {
      await api.patchExperience(item.experience_id, { is_active: !item.is_active });
      await load();
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(item: ExperienceOut) {
    if (!window.confirm(t(uiLang, "experienceDeleteConfirm"))) return;
    setBusy(true);
    try {
      await api.deleteExperience(item.experience_id);
      if (editing?.experience_id === item.experience_id) resetForm();
      if (viewing?.experience_id === item.experience_id) setViewing(null);
      onNotify(t(uiLang, "experienceDeleted"), "success");
      await load();
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function toggleType(pt: ProjectType) {
    setProjectTypes((prev) =>
      prev.includes(pt) ? prev.filter((x) => x !== pt) : [...prev, pt],
    );
  }

  return (
    <article className="upload-card experience-panel">
      <h3>{t(uiLang, "experienceAdminTitle")}</h3>
      <p className="muted upload-hint">{t(uiLang, "experienceAdminHint")}</p>

      <div className={`experience-form${editing ? " is-editing" : ""}`} ref={formRef}>
        {editing ? (
          <p className="editing-banner" role="status">
            {t(uiLang, "experienceSaveEdit")}: <strong>{editing.title}</strong>
          </p>
        ) : null}
        <label>
          {t(uiLang, "experienceTitle")}
          <input value={title} disabled={busy} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label>
          {t(uiLang, "experienceBody")}
          <textarea
            rows={4}
            value={description}
            disabled={busy}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>
        <label>
          {t(uiLang, "experiencePrevention")}
          <textarea
            rows={2}
            value={prevention}
            disabled={busy}
            onChange={(e) => setPrevention(e.target.value)}
          />
        </label>
        <div className="experience-row">
          <label>
            {t(uiLang, "experienceCategory")}
            <select value={category} disabled={busy} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORY_CODES.map((c) => (
                <option key={c} value={c}>
                  {t(uiLang, `expCat_${c}` as "experienceCategory")}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t(uiLang, "experienceKeywords")}
            <input
              value={keywords}
              disabled={busy}
              placeholder="delay, برنامه, claim"
              onChange={(e) => setKeywords(e.target.value)}
            />
          </label>
        </div>
        <div className="experience-types">
          <span>{t(uiLang, "experienceProjectTypes")}</span>
          <div className="chip-row">
            {projectTypeOptions.slice(0, 12).map((o) => (
              <button
                key={o.value}
                type="button"
                className={projectTypes.includes(o.value) ? "chip on" : "chip"}
                disabled={busy}
                onClick={() => toggleType(o.value)}
              >
                {t(uiLang, o.labelKey)}
              </button>
            ))}
          </div>
        </div>
        <div className="row-actions">
          <button type="button" className="ghost" disabled={busy} onClick={() => void onSuggest()}>
            {t(uiLang, "experienceSuggest")}
          </button>
          <button type="button" className="primary" disabled={busy} onClick={() => void onSaveOne()}>
            {editing ? t(uiLang, "experienceSaveEdit") : t(uiLang, "experienceSave")}
          </button>
          {editing ? (
            <button type="button" className="ghost" disabled={busy} onClick={resetForm}>
              {t(uiLang, "experienceCancelEdit")}
            </button>
          ) : null}
        </div>
      </div>

      <div className="experience-bulk">
        <h4>{t(uiLang, "experienceBulkTitle")}</h4>
        <p className="muted upload-hint">{t(uiLang, "experienceBulkHint")}</p>
        <textarea
          rows={8}
          value={bulkText}
          disabled={busy}
          placeholder={t(uiLang, "experienceBulkPlaceholder")}
          onChange={(e) => setBulkText(e.target.value)}
        />
        <button type="button" className="primary" disabled={busy} onClick={() => void onBulk()}>
          {t(uiLang, "experienceBulkSubmit")}
        </button>
      </div>

      <div className="experience-toolbar">
        <div className="exp-filters">
          <label className="exp-filter-field">
            <span>{t(uiLang, "experienceSearch")}</span>
            <input
              value={query}
              placeholder={t(uiLang, "experienceSearch")}
              disabled={busy || loading}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <label className="exp-filter-field">
            <span>{t(uiLang, "experienceCategory")}</span>
            <select
              value={filterCat}
              disabled={busy || loading}
              onChange={(e) => setFilterCat(e.target.value)}
            >
              <option value="">{t(uiLang, "experienceAllCategories")}</option>
              {CATEGORY_CODES.map((c) => (
                <option key={c} value={c}>
                  {t(uiLang, `expCat_${c}` as "experienceCategory")}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="ghost exp-refresh"
            disabled={busy || loading}
            onClick={() => void load()}
          >
            {t(uiLang, "experienceRefresh")}
          </button>
        </div>

        <div className="exp-switch-box">
          <span className="exp-switch-label">{t(uiLang, "experienceShowInactive")}</span>
          <button
            type="button"
            className={`exp-switch${showInactive ? " on" : ""}`}
            role="switch"
            aria-checked={showInactive}
            disabled={busy || loading}
            onClick={() => setShowInactive((v) => !v)}
          >
            <span className="exp-switch-track" aria-hidden="true">
              <span className="exp-switch-knob" />
            </span>
            <span className="exp-switch-state">
              {showInactive ? t(uiLang, "experienceToggleOn") : t(uiLang, "experienceToggleOff")}
            </span>
          </button>
        </div>
      </div>

      <h4 className="experience-library-title">
        {t(uiLang, "experienceLibrary")}{" "}
        <small>({items.length})</small>
      </h4>

      {loading ? (
        <p className="muted">{t(uiLang, "experienceLoading")}</p>
      ) : items.length === 0 ? (
        <p className="muted">{t(uiLang, "experienceEmpty")}</p>
      ) : (
        <div className="experience-groups">
          {grouped.map(([cat, rows]) => (
            <section key={cat}>
              <h4>
                {t(uiLang, `expCat_${cat}` as "experienceCategory")}{" "}
                <small>({rows.length})</small>
              </h4>
              <ul className="experience-list">
                {rows.map((it) => {
                  const isOpen = viewing?.experience_id === it.experience_id;
                  const isEditing = editing?.experience_id === it.experience_id;
                  const num = itemNumbers.get(it.experience_id) ?? 0;
                  const catClass = `cat-${it.category || "lesson"}`;
                  return (
                    <li
                      key={it.experience_id}
                      className={`exp-card ${catClass} ${it.is_active ? "" : "inactive"} ${
                        isOpen ? "selected" : ""
                      } ${isEditing ? "is-editing-row" : ""}`.trim()}
                    >
                      <div className="exp-card-top">
                        <span className="exp-num" aria-hidden="true">
                          {formatExpNo(num)}
                        </span>
                        <div className="exp-body">
                          <div className="exp-title-row">
                            <strong>{it.title}</strong>
                            <span className="exp-cat-chip">
                              {t(uiLang, `expCat_${it.category || "lesson"}` as "experienceCategory")}
                            </span>
                          </div>
                          <small>
                            #{formatExpNo(num)} · {it.experience_id}
                            {!it.is_active ? ` · ${t(uiLang, "experienceInactive")}` : ""}
                          </small>
                          {isOpen ? (
                            <div className="experience-detail inline">
                              <p>
                                <strong>{t(uiLang, "experienceBody")}:</strong>{" "}
                                {it.description || "—"}
                              </p>
                              {it.recommended_prevention ? (
                                <p>
                                  <strong>{t(uiLang, "experiencePrevention")}:</strong>{" "}
                                  {it.recommended_prevention}
                                </p>
                              ) : null}
                              {(it.match_keywords || []).length > 0 ? (
                                <p className="muted">
                                  <strong>{t(uiLang, "experienceKeywordsLabel")}:</strong>{" "}
                                  {it.match_keywords.join("، ")}
                                </p>
                              ) : null}
                            </div>
                          ) : null}
                        </div>
                      </div>
                      <div className="exp-actions horizontal">
                        <button
                          type="button"
                          className="exp-btn"
                          disabled={busy}
                          onClick={() => openView(it)}
                        >
                          {isOpen ? t(uiLang, "experienceCloseView") : t(uiLang, "experienceView")}
                        </button>
                        <button
                          type="button"
                          className="exp-btn"
                          disabled={busy}
                          onClick={() => startEdit(it)}
                        >
                          {t(uiLang, "experienceEdit")}
                        </button>
                        <button
                          type="button"
                          className="exp-btn"
                          disabled={busy}
                          onClick={() => void toggleActive(it)}
                        >
                          {it.is_active
                            ? t(uiLang, "experienceDeactivate")
                            : t(uiLang, "experienceActivate")}
                        </button>
                        <button
                          type="button"
                          className="exp-btn danger"
                          disabled={busy}
                          onClick={() => void onDelete(it)}
                        >
                          {t(uiLang, "experienceDelete")}
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      )}
    </article>
  );
}
