import { useEffect, useMemo, useState } from "react";
import type { DocumentCategory, LanguageCode, ProjectOut } from "./api";
import { t } from "./i18n";

export type BulkFileItem = ProjectOut["documents"][number];

export type BulkDeleteResult = {
  deleted_count: number;
  failed_count: number;
  results: Array<{
    document_id: number;
    original_name: string | null;
    status: "deleted" | "not_found" | "blocked_referenced" | "error";
    detail: string | null;
  }>;
};

type Props = {
  uiLang: LanguageCode;
  category: DocumentCategory;
  files: BulkFileItem[];
  emptyLabel: string;
  busy?: boolean;
  showReextract?: boolean;
  onDeleteOne: (id: number) => Promise<void> | void;
  onBulkDelete: (ids: number[], opts: { force: boolean }) => Promise<BulkDeleteResult>;
  onReextract?: (id: number) => void;
  onNotify?: (message: string, kind: "success" | "error") => void;
};

/**
 * Shared file list: select-all, multi-select, one-click delete-all, bulk delete.
 * Selection is local UI state only.
 */
export function BulkFileList({
  uiLang,
  category,
  files,
  emptyLabel,
  busy = false,
  showReextract = false,
  onDeleteOne,
  onBulkDelete,
  onReextract,
  onNotify,
}: Props) {
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [working, setWorking] = useState(false);

  useEffect(() => {
    const alive = new Set(files.map((f) => f.id));
    setSelectedIds((prev) => prev.filter((id) => alive.has(id)));
  }, [files]);

  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const selectedCount = files.filter((f) => selectedSet.has(f.id)).length;
  const allSelected = files.length > 0 && selectedCount === files.length;
  const someSelected = selectedCount > 0 && !allSelected;
  const disabled = busy || working;

  if (files.length === 0) {
    return <p className="muted">{emptyLabel}</p>;
  }

  function toggleOne(id: number, checked: boolean) {
    setSelectedIds((prev) => {
      if (checked) return prev.includes(id) ? prev : [...prev, id];
      return prev.filter((x) => x !== id);
    });
  }

  function selectAll() {
    setSelectedIds(files.map((f) => f.id));
  }

  function deselectAll() {
    setSelectedIds([]);
  }

  async function executeDelete(ids: number[], force: boolean) {
    setWorking(true);
    try {
      let result = await onBulkDelete(ids, { force });

      // If referenced by old analysis text and not forced, offer one more confirm then force.
      const blocked = result.results.filter((r) => r.status === "blocked_referenced");
      if (!force && blocked.length > 0) {
        const names = blocked
          .map((r) => r.original_name || `#${r.document_id}`)
          .slice(0, 6)
          .join("، ");
        const ok = window.confirm(
          t(uiLang, "confirmDeleteReferenced")
            .replace("{n}", String(blocked.length))
            .replace("{names}", names),
        );
        if (ok) {
          const forced = await onBulkDelete(
            blocked.map((r) => r.document_id),
            { force: true },
          );
          result = {
            deleted_count: result.deleted_count + forced.deleted_count,
            failed_count: forced.failed_count,
            results: [
              ...result.results.filter((r) => r.status === "deleted"),
              ...forced.results,
            ],
          };
        }
      }

      const deletedIds = new Set(
        result.results.filter((r) => r.status === "deleted").map((r) => r.document_id),
      );
      setSelectedIds((prev) => prev.filter((id) => !deletedIds.has(id)));

      const failed = result.results.filter(
        (r) => r.status === "error" || r.status === "not_found",
      );

      if (result.deleted_count > 0) {
        onNotify?.(
          t(uiLang, "bulkDeleteSuccess").replace("{n}", String(result.deleted_count)),
          "success",
        );
      }
      if (failed.length > 0) {
        const lines = failed
          .slice(0, 5)
          .map((r) => `${r.original_name || r.document_id}: ${r.detail || r.status}`)
          .join("\n");
        onNotify?.(
          `${t(uiLang, "bulkDeletePartial").replace("{n}", String(failed.length))}\n${lines}`,
          "error",
        );
      }
    } catch (e) {
      onNotify?.(String(e), "error");
    } finally {
      setWorking(false);
    }
  }

  /** One-click: delete every file in this section. */
  function deleteAllInSection() {
    const ids = files.map((f) => f.id);
    const ok = window.confirm(
      t(uiLang, "confirmDeleteAllCount").replace("{n}", String(ids.length)),
    );
    if (!ok) return;
    // User already confirmed wiping the whole section — force past analysis-name warnings.
    void executeDelete(ids, true);
  }

  function deleteSelected() {
    const ids = files.filter((f) => selectedSet.has(f.id)).map((f) => f.id);
    if (!ids.length) return;
    const ok = window.confirm(
      t(uiLang, "confirmBulkDelete").replace("{n}", String(ids.length)),
    );
    if (!ok) return;
    void executeDelete(ids, true);
  }

  return (
    <div className="docs-panel bulk-file-list">
      <div className="bulk-primary-bar">
        <div className="bulk-primary-info">
          <label className="docs-master-check">
            <input
              type="checkbox"
              checked={allSelected}
              ref={(el) => {
                if (el) el.indeterminate = someSelected;
              }}
              disabled={disabled}
              onChange={(e) => {
                if (e.target.checked) selectAll();
                else deselectAll();
              }}
            />
            <strong>
              {t(uiLang, "filesInCategory").replace("{n}", String(files.length))}
            </strong>
          </label>
          {selectedCount > 0 ? (
            <span className="docs-selected-count">
              {t(uiLang, "filesSelectedBanner").replace("{n}", String(selectedCount))}
            </span>
          ) : null}
        </div>

        <div className="bulk-primary-actions">
          {!allSelected ? (
            <button type="button" className="linkish" disabled={disabled} onClick={selectAll}>
              {t(uiLang, "stagingSelectAll")}
            </button>
          ) : (
            <button type="button" className="linkish" disabled={disabled} onClick={deselectAll}>
              {t(uiLang, "stagingDeselectAll")}
            </button>
          )}
          {selectedCount > 0 ? (
            <button
              type="button"
              className="btn-danger-quiet"
              disabled={disabled}
              onClick={deleteSelected}
            >
              {t(uiLang, "deleteSelected")}
              {` (${selectedCount})`}
            </button>
          ) : null}
          <button
            type="button"
            className="linkish danger"
            disabled={disabled}
            onClick={deleteAllInSection}
          >
            {t(uiLang, "deleteAllFiles").replace("{n}", String(files.length))}
          </button>
        </div>
      </div>

      <ul className="file-list docs-file-list">
        {files.map((d) => {
          const checked = selectedSet.has(d.id);
          const textOk = d.has_text || category === "drawing";
          return (
            <li key={d.id} className={checked ? "is-selected" : ""}>
              <label className="file-check">
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={disabled}
                  onChange={(e) => toggleOne(d.id, e.target.checked)}
                  aria-label={d.original_name}
                />
                <div className="file-meta">
                  <span title={d.original_name}>{d.original_name}</span>
                  {d.taxonomy_code || d.taxonomy_title_fa ? (
                    <small className="tag taxonomy-tag">
                      {t(uiLang, "docTaxonomyLabel")}
                      {d.taxonomy_code ? ` ${d.taxonomy_code}` : ""}
                      {d.taxonomy_title_fa ? ` · ${d.taxonomy_title_fa}` : ""}
                    </small>
                  ) : null}
                  <small className={textOk ? "tag ok" : "tag warn"}>
                    {d.extraction_phase &&
                    d.extraction_phase !== "completed" &&
                    d.extraction_phase !== "failed"
                      ? `${t(uiLang, "extracting")} ${d.extraction_progress ?? 0}%`
                      : d.needs_manual_review
                        ? t(uiLang, "needsReview")
                        : d.has_text
                          ? t(uiLang, "textOk")
                          : t(uiLang, "textMissing")}
                    {d.ocr_applied ? ` · ${t(uiLang, "ocrUsed")}` : ""}
                  </small>
                </div>
              </label>
              <div className="file-actions">
                {showReextract && !d.has_text && onReextract && (
                  <button
                    type="button"
                    className="linkish"
                    disabled={disabled}
                    onClick={() => onReextract(d.id)}
                  >
                    {t(uiLang, "reextract")}
                  </button>
                )}
                <button
                  type="button"
                  className="linkish danger"
                  disabled={disabled}
                  onClick={() => void onDeleteOne(d.id)}
                >
                  {t(uiLang, "delete")}
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
