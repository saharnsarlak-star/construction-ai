import { useEffect, useState } from "react";
import {
  api,
  parseApiError,
  type LanguageCode,
  type TaxonomyNodeOut,
  type TaxonomySearchHitOut,
} from "./api";
import { t } from "./i18n";

type Props = {
  uiLang: LanguageCode;
};

function legacyLabel(uiLang: LanguageCode, legacy: string): string {
  switch (legacy) {
    case "drawing":
      return t(uiLang, "drawings");
    case "schedule":
      return t(uiLang, "schedule");
    case "standard":
      return t(uiLang, "standards");
    default:
      return t(uiLang, "tenderDocs");
  }
}

function collectCodes(_nodes: TaxonomyNodeOut[]): string[] {
  return [];
}

function TaxonomyNodeCard({
  node,
  uiLang,
  depth,
  open,
  onToggle,
  forceOpen,
}: {
  node: TaxonomyNodeOut;
  uiLang: LanguageCode;
  depth: number;
  open: boolean;
  onToggle: () => void;
  forceOpen?: boolean;
}) {
  const hasChildren = node.subcategories.length > 0 || (node.topics?.length ?? 0) > 0;
  const title = uiLang === "fa" ? node.title_fa : node.title_en || node.title_fa;
  const subtitle = uiLang === "fa" ? node.title_en : node.title_fa;

  return (
    <article className={`taxonomy-node depth-${Math.min(depth, 3)}`}>
      <div className="taxonomy-node-head">
        {hasChildren ? (
          <button
            type="button"
            className="taxonomy-toggle"
            aria-expanded={open}
            onClick={onToggle}
          >
            {open ? "▾" : "▸"}
          </button>
        ) : (
          <span className="taxonomy-toggle spacer" aria-hidden />
        )}
        <div className="taxonomy-node-titles">
          <strong>{title}</strong>
          {subtitle ? <span className="muted taxonomy-subtitle">{subtitle}</span> : null}
        </div>
        <span className="taxonomy-code">{node.code}</span>
        <span className={`taxonomy-legacy legacy-${node.legacy_category}`}>
          {legacyLabel(uiLang, node.legacy_category)}
        </span>
      </div>

      {open ? (
        <div className="taxonomy-node-body">
          {(node.topics?.length ?? 0) > 0 ? (
            <div className="taxonomy-items">
              <span className="taxonomy-items-label">{t(uiLang, "taxonomyItemsLabel")}</span>
              <ul className="taxonomy-topic-list">
                {(node.topics || []).map((topic) => {
                  const label = uiLang === "fa" ? topic.title_fa : topic.title_en || topic.title_fa;
                  return (
                    <li key={topic.code}>
                      <span className="taxonomy-code">{topic.code}</span>
                      <span>{label}</span>
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}
          {node.subcategories.length ? (
            <div className="taxonomy-children">
              {node.subcategories.map((child) => (
                <TaxonomyNodeCardWrap
                  key={child.code}
                  node={child}
                  uiLang={uiLang}
                  depth={depth + 1}
                  forceOpen={forceOpen}
                />
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function TaxonomyNodeCardWrap({
  node,
  uiLang,
  depth,
  forceOpen,
}: {
  node: TaxonomyNodeOut;
  uiLang: LanguageCode;
  depth: number;
  forceOpen?: boolean;
}) {
  const [open, setOpen] = useState(depth === 0);
  const isOpen = forceOpen ?? open;
  return (
    <TaxonomyNodeCard
      node={node}
      uiLang={uiLang}
      depth={depth}
      open={isOpen}
      onToggle={() => setOpen((v) => !v)}
      forceOpen={forceOpen}
    />
  );
}

export function TaxonomyBrowser({ uiLang }: Props) {
  const [categories, setCategories] = useState<TaxonomyNodeOut[]>([]);
  const [taxonomyName, setTaxonomyName] = useState("");
  const [metaStats, setMetaStats] = useState({
    total_codes: 0,
    topic_count: 0,
    subcategory_count: 0,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [query, setQuery] = useState("");
  const [searchHits, setSearchHits] = useState<TaxonomySearchHitOut[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [expandAll, setExpandAll] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    async function load(attempt: number) {
      try {
        const res = await api.getTaxonomy();
        if (cancelled) return;
        setCategories(res.categories);
        setTaxonomyName(res.meta.taxonomy_name);
        setMetaStats({
          total_codes: res.meta.total_codes,
          topic_count: res.meta.topic_count,
          subcategory_count: res.meta.subcategory_count,
        });
      } catch (err) {
        if (cancelled) return;
        if (attempt < 2) {
          await new Promise((r) => window.setTimeout(r, 1500));
          if (!cancelled) await load(attempt + 1);
          return;
        }
        setError(parseApiError(err) || t(uiLang, "taxonomyLoadError"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load(0);
    return () => {
      cancelled = true;
    };
  }, [uiLang, reloadKey]);

  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setSearchHits(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    const timer = window.setTimeout(() => {
      api
        .searchTaxonomy(q)
        .then((res) => setSearchHits(res.results))
        .catch(() => setSearchHits([]))
        .finally(() => setSearching(false));
    }, 280);
    return () => window.clearTimeout(timer);
  }, [query]);

  if (loading) {
    return <p className="muted taxonomy-status">{t(uiLang, "taxonomyLoading")}</p>;
  }
  if (error) {
    return (
      <section className="taxonomy-browser upload-card wide">
        <p className="error taxonomy-status">{error}</p>
        <button type="button" className="linkish" onClick={() => setReloadKey((k) => k + 1)}>
          {t(uiLang, "taxonomyRetry")}
        </button>
      </section>
    );
  }

  return (
    <section className="taxonomy-browser upload-card wide">
      <header className="taxonomy-header">
        <div>
          <h3>{t(uiLang, "taxonomyPanelTitle")}</h3>
          {taxonomyName ? <p className="muted taxonomy-intro">{taxonomyName}</p> : null}
          <p className="muted taxonomy-intro">{t(uiLang, "taxonomyCodeFormat")}</p>
        </div>
        <div className="taxonomy-stats muted">
          {t(uiLang, "taxonomyRootCount").replace("{n}", String(categories.length))}
          {" · "}
          {t(uiLang, "taxonomySubCount").replace("{n}", String(metaStats.subcategory_count))}
          {" · "}
          {t(uiLang, "taxonomyTopicCount").replace("{n}", String(metaStats.topic_count))}
          {" · "}
          {t(uiLang, "taxonomyTotalCodes").replace("{n}", String(metaStats.total_codes))}
        </div>
      </header>

      <div className="taxonomy-toolbar">
        <input
          type="search"
          className="taxonomy-search"
          value={query}
          placeholder={t(uiLang, "taxonomySearchPlaceholder")}
          onChange={(e) => setQuery(e.target.value)}
        />
        {!query.trim() ? (
          <button
            type="button"
            className="linkish"
            onClick={() => setExpandAll((v) => !v)}
          >
            {expandAll ? t(uiLang, "taxonomyCollapseAll") : t(uiLang, "taxonomyExpandAll")}
          </button>
        ) : null}
      </div>

      {query.trim() ? (
        <div className="taxonomy-search-results">
          {searching ? (
            <p className="muted">{t(uiLang, "taxonomySearching")}</p>
          ) : searchHits && searchHits.length === 0 ? (
            <p className="muted">{t(uiLang, "taxonomyNoResults")}</p>
          ) : (
            <ul className="taxonomy-hit-list">
              {(searchHits || []).map((hit) => {
                const title = uiLang === "fa" ? hit.title_fa : hit.title_en || hit.title_fa;
                return (
                  <li key={hit.code}>
                    <span className="taxonomy-code">{hit.code}</span>
                    <div className="taxonomy-hit-text">
                      <strong>{title}</strong>
                      {hit.path_fa ? <span className="muted taxonomy-path">{hit.path_fa}</span> : null}
                    </div>
                    <span className={`taxonomy-legacy legacy-${hit.legacy_category}`}>
                      {legacyLabel(uiLang, hit.legacy_category)}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ) : (
        <div className={`taxonomy-tree${expandAll ? " all-open" : ""}`}>
          {categories.map((cat) => (
            <TaxonomyNodeCardWrap
              key={cat.code}
              node={cat}
              uiLang={uiLang}
              depth={0}
              forceOpen={expandAll ? true : undefined}
            />
          ))}
        </div>
      )}
    </section>
  );
}
