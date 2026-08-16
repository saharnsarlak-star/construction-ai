import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type ImplementationStepOut,
  type LanguageCode,
  type ProjectRegistryGroupOut,
  type ProjectRegistryOut,
} from "./api";
import { t } from "./i18n";

const STATUS_OPTIONS = ["pending", "in_progress", "completed", "verified", "blocked"] as const;

const CATEGORY_COLORS = [
  "rgba(15, 92, 110, 0.14)",
  "rgba(46, 125, 50, 0.14)",
  "rgba(21, 101, 192, 0.14)",
  "rgba(230, 81, 0, 0.14)",
  "rgba(123, 31, 162, 0.14)",
  "rgba(0, 105, 92, 0.14)",
  "rgba(194, 24, 91, 0.14)",
  "rgba(69, 90, 100, 0.14)",
];

type Props = {
  uiLang: LanguageCode;
  busy: boolean;
  setBusy: (v: boolean) => void;
  onNotify: (text: string, kind: "success" | "error") => void;
  onError: (text: string) => void;
};

function statusLabel(uiLang: LanguageCode, status: string): string {
  const key = `implStatus_${status}` as const;
  const translated = t(uiLang, key);
  return translated !== key ? translated : status;
}

function categoryTitle(group: ProjectRegistryGroupOut, uiLang: LanguageCode): string {
  if (group.category) {
    return uiLang === "fa" ? group.category.title_fa : group.category.title_en || group.category.title_fa;
  }
  return group.category_code;
}

function categoryColor(group: ProjectRegistryGroupOut): string {
  const idx = group.category?.color_index ?? 7;
  return CATEGORY_COLORS[idx % CATEGORY_COLORS.length];
}

export function ProjectRegistryPanel({ uiLang, busy, setBusy, onNotify, onError }: Props) {
  const [registry, setRegistry] = useState<ProjectRegistryOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [drag, setDrag] = useState<{ categoryCode: string; id: number } | null>(null);
  const groupsRef = useRef<ProjectRegistryGroupOut[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getProjectRegistry();
      setRegistry(data);
      setExpanded((prev) => {
        const next = { ...prev };
        for (const g of data.groups) {
          if (next[g.category_code] == null) next[g.category_code] = true;
        }
        return next;
      });
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [onError]);

  useEffect(() => {
    void load();
  }, [load]);

  const groups = registry?.groups ?? [];
  groupsRef.current = groups;

  const filteredGroups = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return groups;
    return groups
      .map((g) => ({
        ...g,
        items: g.items.filter((item) => {
          const hay = [
            item.step_code,
            item.phase,
            item.title_fa,
            item.title_en,
            item.description_fa,
            item.deliverables_fa,
            item.related_paths,
            item.notes,
          ]
            .filter(Boolean)
            .join(" ")
            .toLowerCase();
          return hay.includes(q);
        }),
      }))
      .filter((g) => g.items.length > 0 || categoryTitle(g, uiLang).toLowerCase().includes(q));
  }, [groups, query, uiLang]);

  async function saveRow(id: number, patch: Partial<ImplementationStepOut>) {
    setBusy(true);
    try {
      const updated = await api.patchImplementationStep(id, patch);
      setRegistry((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          groups: prev.groups.map((g) => ({
            ...g,
            items: g.items.map((r) => (r.id === id ? updated : r)),
          })),
        };
      });
      onNotify(t(uiLang, "registrySaved"), "success");
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function persistCategoryOrder(categoryCode: string, items: ImplementationStepOut[]) {
    setBusy(true);
    try {
      const payload = items.map((r, idx) => ({ id: r.id, sort_order: (idx + 1) * 10 }));
      const updated = await api.reorderRegistryItems(categoryCode, payload);
      const byId = new Map(updated.map((r) => [r.id, r]));
      setRegistry((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          groups: prev.groups.map((g) =>
            g.category_code === categoryCode
              ? { ...g, items: g.items.map((r) => byId.get(r.id) ?? r).sort((a, b) => a.sort_order - b.sort_order) }
              : g,
          ),
        };
      });
      onNotify(t(uiLang, "registryReordered"), "success");
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
      await load();
    } finally {
      setBusy(false);
    }
  }

  function reorderLocal(categoryCode: string, dragId: number, overId: number) {
    setRegistry((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        groups: prev.groups.map((g) => {
          if (g.category_code !== categoryCode) return g;
          const from = g.items.findIndex((r) => r.id === dragId);
          const to = g.items.findIndex((r) => r.id === overId);
          if (from < 0 || to < 0) return g;
          const copy = [...g.items];
          const [item] = copy.splice(from, 1);
          copy.splice(to, 0, item);
          return { ...g, items: copy };
        }),
      };
    });
  }

  async function onDragEnd(categoryCode: string) {
    if (!drag || drag.categoryCode !== categoryCode) {
      setDrag(null);
      return;
    }
    setDrag(null);
    const group = groupsRef.current.find((g) => g.category_code === categoryCode);
    if (group) await persistCategoryOrder(categoryCode, group.items);
  }

  function toggleCategory(code: string) {
    setExpanded((prev) => ({ ...prev, [code]: !prev[code] }));
  }

  return (
    <section className="registry-panel panel">
      <div className="row-between registry-head">
        <div>
          <h3>{t(uiLang, "registryTitle")}</h3>
          <p className="muted upload-hint">{t(uiLang, "registryHint")}</p>
          {registry ? (
            <p className="muted registry-stats">
              {t(uiLang, "registryStats")
                .replace("{cats}", String(registry.groups.length))
                .replace("{items}", String(registry.total_items))}
            </p>
          ) : null}
        </div>
        <button type="button" className="linkish" disabled={busy || loading} onClick={() => void load()}>
          {t(uiLang, "standardsRetry")}
        </button>
      </div>

      <div className="registry-toolbar">
        <input
          className="registry-search"
          type="search"
          value={query}
          disabled={busy}
          placeholder={t(uiLang, "registrySearchPlaceholder")}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {loading ? <p className="muted">{t(uiLang, "registryLoading")}</p> : null}

      {!loading ? (
        <div className="registry-groups">
          {filteredGroups.map((group) => {
            const code = group.category_code;
            const open = expanded[code] !== false;
            const title = categoryTitle(group, uiLang);
            const bg = categoryColor(group);
            return (
              <article key={code} className="registry-group" style={{ ["--registry-accent" as string]: bg }}>
                <header className="registry-group-head">
                  <button type="button" className="registry-toggle" onClick={() => toggleCategory(code)}>
                    {open ? "▾" : "▸"}
                  </button>
                  <div className="registry-group-meta">
                    <strong>{title}</strong>
                    <span className="muted">
                      {group.category?.code ?? code} · {group.items.length} {t(uiLang, "registryItemCount")}
                    </span>
                    {group.category?.description_fa ? (
                      <small className="muted">{group.category.description_fa}</small>
                    ) : null}
                  </div>
                </header>

                {open ? (
                  <div className="impl-steps-table-wrap">
                    <table className="impl-steps-table registry-table">
                      <thead>
                        <tr>
                          <th aria-label="drag" />
                          <th>#</th>
                          <th>{t(uiLang, "implStepsColPhase")}</th>
                          <th>{t(uiLang, "implStepsColCode")}</th>
                          <th>{t(uiLang, "implStepsColTitle")}</th>
                          <th>{t(uiLang, "registryColDeliverables")}</th>
                          <th>{t(uiLang, "registryColPaths")}</th>
                          <th>{t(uiLang, "implStepsColStatus")}</th>
                          <th>{t(uiLang, "registryColVerified")}</th>
                          <th>{t(uiLang, "implStepsColNotes")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {group.items.map((row, idx) => (
                          <tr
                            key={row.id}
                            draggable={!busy}
                            onDragStart={() => setDrag({ categoryCode: code, id: row.id })}
                            onDragOver={(e) => {
                              e.preventDefault();
                              if (drag?.categoryCode === code && drag.id !== row.id) {
                                reorderLocal(code, drag.id, row.id);
                                setDrag({ categoryCode: code, id: drag.id });
                              }
                            }}
                            onDragEnd={() => void onDragEnd(code)}
                            className={drag?.id === row.id ? "dragging" : ""}
                          >
                            <td className="impl-drag" title={t(uiLang, "implStepsDragHint")}>
                              ⠿
                            </td>
                            <td>{idx + 1}</td>
                            <td>
                              <input
                                className="impl-inline-input narrow"
                                defaultValue={row.phase}
                                disabled={busy}
                                onBlur={(e) => {
                                  const v = e.target.value.trim();
                                  if (v && v !== row.phase) void saveRow(row.id, { phase: v });
                                }}
                              />
                            </td>
                            <td>
                              <code>{row.step_code}</code>
                            </td>
                            <td>
                              <input
                                className="impl-inline-input"
                                defaultValue={row.title_fa}
                                disabled={busy}
                                onBlur={(e) => {
                                  const v = e.target.value.trim();
                                  if (v && v !== row.title_fa) void saveRow(row.id, { title_fa: v });
                                }}
                              />
                              <textarea
                                className="impl-inline-textarea"
                                defaultValue={row.description_fa || ""}
                                disabled={busy}
                                rows={2}
                                placeholder={t(uiLang, "registryDescPlaceholder")}
                                onBlur={(e) => {
                                  const v = e.target.value.trim();
                                  if (v !== (row.description_fa || ""))
                                    void saveRow(row.id, { description_fa: v || null });
                                }}
                              />
                            </td>
                            <td>
                              <textarea
                                className="impl-inline-textarea"
                                defaultValue={row.deliverables_fa || ""}
                                disabled={busy}
                                rows={2}
                                placeholder={t(uiLang, "registryDeliverablesPlaceholder")}
                                onBlur={(e) => {
                                  const v = e.target.value.trim();
                                  if (v !== (row.deliverables_fa || ""))
                                    void saveRow(row.id, { deliverables_fa: v || null });
                                }}
                              />
                            </td>
                            <td>
                              <textarea
                                className="impl-inline-textarea registry-paths"
                                defaultValue={row.related_paths || ""}
                                disabled={busy}
                                rows={2}
                                placeholder={t(uiLang, "registryPathsPlaceholder")}
                                onBlur={(e) => {
                                  const v = e.target.value.trim();
                                  if (v !== (row.related_paths || ""))
                                    void saveRow(row.id, { related_paths: v || null });
                                }}
                              />
                            </td>
                            <td>
                              <select
                                className="impl-inline-select"
                                value={row.status}
                                disabled={busy}
                                onChange={(e) => void saveRow(row.id, { status: e.target.value })}
                              >
                                {STATUS_OPTIONS.map((s) => (
                                  <option key={s} value={s}>
                                    {statusLabel(uiLang, s)}
                                  </option>
                                ))}
                              </select>
                            </td>
                            <td className="registry-verified-cell">
                              <input
                                type="checkbox"
                                checked={row.is_verified}
                                disabled={busy}
                                title={t(uiLang, "registryVerifiedHint")}
                                onChange={(e) => void saveRow(row.id, { is_verified: e.target.checked })}
                              />
                            </td>
                            <td>
                              <textarea
                                className="impl-inline-textarea"
                                defaultValue={row.notes || ""}
                                disabled={busy}
                                rows={2}
                                placeholder={t(uiLang, "implStepsNotesPlaceholder")}
                                onBlur={(e) => {
                                  const v = e.target.value.trim();
                                  if (v !== (row.notes || "")) void saveRow(row.id, { notes: v || null });
                                }}
                              />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}
