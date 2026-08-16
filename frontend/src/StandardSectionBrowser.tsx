import { useEffect, useState } from "react";
import {
  api,
  parseApiError,
  type LanguageCode,
  type StandardCategoryGroupOut,
  type StandardChapterOut,
  type StandardClauseSectionOut,
  type StandardSectionsOut,
  type StandardSubcategoryGroupOut,
  type StandardTopicGroupOut,
} from "./api";
import { t } from "./i18n";

type Props = {
  projectId: number;
  standardCode: string;
  standardTitle: string;
  uiLang: LanguageCode;
  onClose: () => void;
};

function nodeTitle(
  node: { title_fa?: string | null; title_en?: string | null; code: string },
  uiLang: LanguageCode,
): string {
  if (uiLang === "fa") return node.title_fa || node.code;
  return node.title_en || node.title_fa || node.code;
}

function TaxonomyLevelHead({
  node,
  uiLang,
  depth,
  colorIndex,
  open,
  onToggle,
  count,
}: {
  node: { code: string; title_fa?: string | null; title_en?: string | null; path_fa?: string | null; kind?: string };
  uiLang: LanguageCode;
  depth: number;
  colorIndex?: number;
  open: boolean;
  onToggle: () => void;
  count?: number;
}) {
  const title = nodeTitle(node, uiLang);
  const subtitle = uiLang === "fa" ? node.title_en : node.title_fa;
  const kindLabel =
    node.kind === "category"
      ? t(uiLang, "stdTaxKindCategory")
      : node.kind === "subcategory"
        ? t(uiLang, "stdTaxKindSubcategory")
        : t(uiLang, "stdTaxKindTopic");

  return (
    <button
      type="button"
      className={`taxonomy-node-head std-tax-head depth-${Math.min(depth, 3)}`}
      data-color={colorIndex != null ? String(colorIndex % 12) : undefined}
      aria-expanded={open}
      onClick={onToggle}
    >
      <span className="taxonomy-toggle">{open ? "▾" : "▸"}</span>
      <div className="taxonomy-node-titles">
        <strong>{title}</strong>
        {subtitle ? <span className="muted taxonomy-subtitle">{subtitle}</span> : null}
        <span className="std-tax-kind">{kindLabel}</span>
      </div>
      <span className="taxonomy-code">{node.code}</span>
      {count != null ? <span className="std-clause-count">{count}</span> : null}
    </button>
  );
}

function ClauseList({ clauses }: { clauses: StandardClauseSectionOut[] }) {
  return (
    <ul className="std-clause-list">
      {clauses.map((clause) => (
        <li key={clause.slot_code}>
          <div className="std-clause-head">
            <span className="std-clause-number">{clause.clause_number}</span>
            <span className="std-slot-code">{clause.slot_code}</span>
          </div>
          <p className="std-clause-title">{clause.title || clause.text_preview || "—"}</p>
        </li>
      ))}
    </ul>
  );
}

function ChapterBlock({
  chapter,
  uiLang,
}: {
  chapter: StandardChapterOut;
  uiLang: LanguageCode;
}) {
  return (
    <div className="std-chapter-block">
      <div className="std-chapter-head">
        <span className="std-chapter-label">
          {t(uiLang, "stdChapterLabel").replace("{section}", chapter.section)}
        </span>
        <span className="std-chapter-kind">{t(uiLang, "stdChapterKind")}</span>
        <span className="std-slot-code">{chapter.slot_code}</span>
      </div>
      <ClauseList clauses={chapter.clauses} />
    </div>
  );
}

function TopicBlock({
  topic,
  uiLang,
  depth,
  colorIndex,
}: {
  topic: StandardTopicGroupOut;
  uiLang: LanguageCode;
  depth: number;
  colorIndex: number;
}) {
  const [open, setOpen] = useState(false);
  return (
    <article className={`taxonomy-node std-topic-node depth-${Math.min(depth, 3)}`}>
      <TaxonomyLevelHead
        node={{ ...topic, kind: "topic" }}
        uiLang={uiLang}
        depth={depth}
        colorIndex={colorIndex}
        open={open}
        onToggle={() => setOpen((v) => !v)}
        count={topic.clause_count}
      />
      {open ? (
        <div className="taxonomy-node-body">
          {topic.chapters.map((chapter) => (
            <ChapterBlock key={chapter.slot_code} chapter={chapter} uiLang={uiLang} />
          ))}
        </div>
      ) : null}
    </article>
  );
}

function SubcategoryBlock({
  sub,
  uiLang,
  depth,
  colorIndex,
}: {
  sub: StandardSubcategoryGroupOut;
  uiLang: LanguageCode;
  depth: number;
  colorIndex: number;
}) {
  const [open, setOpen] = useState(true);
  const hasTopics = (sub.topics?.length ?? 0) > 0;
  const hasChapters = (sub.chapters?.length ?? 0) > 0;

  return (
    <article className={`taxonomy-node std-sub-node depth-${Math.min(depth, 3)}`}>
      <TaxonomyLevelHead
        node={{ ...sub, kind: "subcategory" }}
        uiLang={uiLang}
        depth={depth}
        colorIndex={colorIndex}
        open={open}
        onToggle={() => setOpen((v) => !v)}
        count={sub.clause_count}
      />
      {open ? (
        <div className="taxonomy-node-body">
          {hasTopics
            ? sub.topics!.map((topic) => (
                <TopicBlock
                  key={topic.code}
                  topic={topic}
                  uiLang={uiLang}
                  depth={depth + 1}
                  colorIndex={colorIndex}
                />
              ))
            : null}
          {hasChapters
            ? sub.chapters!.map((chapter) => (
                <ChapterBlock key={chapter.slot_code} chapter={chapter} uiLang={uiLang} />
              ))
            : null}
        </div>
      ) : null}
    </article>
  );
}

function CategoryBlock({
  cat,
  uiLang,
}: {
  cat: StandardCategoryGroupOut;
  uiLang: LanguageCode;
}) {
  const [open, setOpen] = useState(true);
  return (
    <article
      className="std-tax-group taxonomy-node depth-0"
      data-color={String(cat.color_index % 12)}
    >
      <TaxonomyLevelHead
        node={{ ...cat, kind: "category" }}
        uiLang={uiLang}
        depth={0}
        colorIndex={cat.color_index}
        open={open}
        onToggle={() => setOpen((v) => !v)}
        count={cat.clause_count}
      />
      {open ? (
        <div className="taxonomy-node-body">
          {cat.subcategories.map((sub) => (
            <SubcategoryBlock
              key={sub.code}
              sub={sub}
              uiLang={uiLang}
              depth={1}
              colorIndex={cat.color_index}
            />
          ))}
          {(cat.topics ?? []).map((topic) => (
            <TopicBlock
              key={topic.code}
              topic={topic}
              uiLang={uiLang}
              depth={1}
              colorIndex={cat.color_index}
            />
          ))}
        </div>
      ) : null}
    </article>
  );
}

export function StandardSectionBrowser({
  projectId,
  standardCode,
  standardTitle,
  uiLang,
  onClose,
}: Props) {
  const [data, setData] = useState<StandardSectionsOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void api
      .getProjectStandardSections(projectId, standardCode)
      .then((payload) => {
        if (cancelled) return;
        setData(payload);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        const msg = parseApiError(err);
        const isNetwork = /failed to fetch|network|abort/i.test(msg || err.message);
        setError(
          isNetwork ? t(uiLang, "stdSectionsNetworkError") : msg || t(uiLang, "stdSectionsLoadError"),
        );
        setData(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, standardCode, uiLang]);

  return (
    <section className="std-sections-panel">
      <div className="row-between std-sections-head">
        <div>
          <h4>{t(uiLang, "stdSectionsTitle")}</h4>
          <p className="muted std-sections-meta">
            {standardTitle}
            {" · "}
            <span className="std-family-code">{data?.family_code || "IR-STD-55"}</span>
            {data?.standard_version ? ` · v${data.standard_version}` : null}
            {data?.source === "database" ? ` · ${t(uiLang, "stdSectionsCached")}` : null}
          </p>
        </div>
        <button type="button" className="linkish" onClick={onClose}>
          {t(uiLang, "stdSectionsClose")}
        </button>
      </div>

      <p className="muted upload-hint">{t(uiLang, "stdSectionsHint")}</p>

      {loading ? <p className="muted">{t(uiLang, "stdSectionsLoading")}</p> : null}
      {error ? (
        <div className="file-list-meta">
          <span>{error}</span>
          <button
            type="button"
            className="linkish"
            onClick={() => {
              setLoading(true);
              setError(null);
              void api
                .getProjectStandardSections(projectId, standardCode)
                .then(setData)
                .catch((err: Error) => setError(parseApiError(err) || t(uiLang, "stdSectionsLoadError")))
                .finally(() => setLoading(false));
            }}
          >
            {t(uiLang, "standardsRetry")}
          </button>
        </div>
      ) : null}

      {!loading && !error && data ? (
        <>
          <p className="muted std-sections-stats">
            {t(uiLang, "stdSectionsStatsTree")
              .replace("{categories}", String(data.category_count))
              .replace("{topics}", String(data.topic_count))
              .replace("{clauses}", String(data.clause_count))}
          </p>
          <div className="std-tax-groups">
            {data.categories.map((cat) => (
              <CategoryBlock key={cat.code} cat={cat} uiLang={uiLang} />
            ))}
          </div>
        </>
      ) : null}
    </section>
  );
}
