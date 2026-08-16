import { useCallback, useEffect, useRef, useState } from "react";
import { api, type ImplementationStepOut, type LanguageCode } from "./api";
import { t } from "./i18n";

const STATUS_OPTIONS = ["pending", "in_progress", "completed", "verified", "blocked"] as const;

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

export function ImplementationStepsPanel({ uiLang, busy, setBusy, onNotify, onError }: Props) {
  const [rows, setRows] = useState<ImplementationStepOut[]>([]);
  const rowsRef = useRef(rows);
  const [loading, setLoading] = useState(false);
  const [dragId, setDragId] = useState<number | null>(null);

  useEffect(() => {
    rowsRef.current = rows;
  }, [rows]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.listImplementationSteps();
      setRows(data);
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [onError]);

  useEffect(() => {
    void load();
  }, [load]);

  async function saveRow(id: number, patch: Partial<ImplementationStepOut>) {
    setBusy(true);
    try {
      const updated = await api.patchImplementationStep(id, patch);
      setRows((prev) => prev.map((r) => (r.id === id ? updated : r)));
      onNotify(t(uiLang, "implStepsSaved"), "success");
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function persistOrder(next: ImplementationStepOut[]) {
    setBusy(true);
    try {
      const items = next.map((r, idx) => ({ id: r.id, sort_order: (idx + 1) * 10 }));
      const data = await api.reorderImplementationSteps(items);
      setRows(data);
      onNotify(t(uiLang, "implStepsReordered"), "success");
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
      await load();
    } finally {
      setBusy(false);
    }
  }

  function onDragStart(id: number) {
    setDragId(id);
  }

  function onDragOver(e: React.DragEvent, overId: number) {
    e.preventDefault();
    if (dragId == null || dragId === overId) return;
    setRows((prev) => {
      const from = prev.findIndex((r) => r.id === dragId);
      const to = prev.findIndex((r) => r.id === overId);
      if (from < 0 || to < 0) return prev;
      const copy = [...prev];
      const [item] = copy.splice(from, 1);
      copy.splice(to, 0, item);
      return copy;
    });
  }

  async function onDragEnd() {
    if (dragId == null) return;
    setDragId(null);
    await persistOrder(rowsRef.current);
  }

  return (
    <section className="impl-steps-panel panel">
      <div className="row-between">
        <div>
          <h3>{t(uiLang, "implStepsTitle")}</h3>
          <p className="muted upload-hint">{t(uiLang, "implStepsHint")}</p>
        </div>
        <button type="button" className="linkish" disabled={busy || loading} onClick={() => void load()}>
          {t(uiLang, "standardsRetry")}
        </button>
      </div>

      {loading ? <p className="muted">{t(uiLang, "implStepsLoading")}</p> : null}

      {!loading ? (
        <div className="impl-steps-table-wrap">
          <table className="impl-steps-table">
            <thead>
              <tr>
                <th aria-label="drag" />
                <th>#</th>
                <th>{t(uiLang, "implStepsColPhase")}</th>
                <th>{t(uiLang, "implStepsColCode")}</th>
                <th>{t(uiLang, "implStepsColTitle")}</th>
                <th>{t(uiLang, "implStepsColStatus")}</th>
                <th>{t(uiLang, "implStepsColCategory")}</th>
                <th>{t(uiLang, "implStepsColNotes")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, idx) => (
                <tr
                  key={row.id}
                  draggable={!busy}
                  onDragStart={() => onDragStart(row.id)}
                  onDragOver={(e) => onDragOver(e, row.id)}
                  onDragEnd={() => void onDragEnd()}
                  className={dragId === row.id ? "dragging" : ""}
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
                    {row.description_fa ? (
                      <small className="muted impl-desc">{row.description_fa}</small>
                    ) : null}
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
                  <td>
                    <input
                      className="impl-inline-input narrow"
                      defaultValue={row.category}
                      disabled={busy}
                      onBlur={(e) => {
                        const v = e.target.value.trim();
                        if (v && v !== row.category) void saveRow(row.id, { category: v });
                      }}
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
    </section>
  );
}
