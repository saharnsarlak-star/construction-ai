import { useEffect, useId, useState } from "react";
import type { LanguageCode } from "./api";
import { t } from "./i18n";

type Props = {
  uiLang: LanguageCode;
  readiness: number;
  high: number;
  medium: number;
  low: number;
  avgRisk: number | null;
  docsLimited: number | null;
  summary: string;
  blocked?: boolean;
};

type HelpTopic = "readiness" | "riskMix" | "avgRisk";

const R = 38;
const CIRC = 2 * Math.PI * R;

function clampPct(n: number) {
  return Math.max(0, Math.min(100, Math.round(n)));
}

function paragraphs(raw: string): string[] {
  return raw
    .split(/\n+/)
    .map((x) => x.trim())
    .filter(Boolean);
}

function HelpButton({
  uiLang,
  onOpen,
  label,
}: {
  uiLang: LanguageCode;
  onOpen: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      className="donut-help-btn"
      onClick={onOpen}
      title={t(uiLang, "metricHelpHint")}
      aria-label={`${t(uiLang, "metricHelpHint")}: ${label}`}
    >
      {uiLang === "fa" ? "؟" : "?"}
    </button>
  );
}

function HelpModal({
  uiLang,
  topic,
  onClose,
}: {
  uiLang: LanguageCode;
  topic: HelpTopic;
  onClose: () => void;
}) {
  const titleId = useId();
  const title = t(uiLang, `help_${topic}_title`);
  const what = paragraphs(t(uiLang, `help_${topic}_what`));
  const how = paragraphs(t(uiLang, `help_${topic}_how`));
  const example = paragraphs(t(uiLang, `help_${topic}_example`));

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="help-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="help-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="help-modal-head">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="help-modal-close" onClick={onClose}>
            {t(uiLang, "helpClose")}
          </button>
        </div>
        <div className="help-modal-body">
          <section>
            <h3>{t(uiLang, "helpWhatIs")}</h3>
            {what.map((p) => (
              <p key={p}>{p}</p>
            ))}
          </section>
          <section>
            <h3>{t(uiLang, "helpHowCalculated")}</h3>
            {how.map((p) => (
              <p key={p}>{p}</p>
            ))}
          </section>
          <section>
            <h3>{t(uiLang, "helpExample")}</h3>
            {example.map((p) => (
              <p key={p}>{p}</p>
            ))}
          </section>
        </div>
      </div>
    </div>
  );
}

function SingleDonut({
  uiLang,
  percent,
  color,
  title,
  explain,
  onHelp,
}: {
  uiLang: LanguageCode;
  percent: number;
  color: string;
  title: string;
  explain: string;
  onHelp: () => void;
}) {
  const p = clampPct(percent);
  const offset = CIRC - (p / 100) * CIRC;
  return (
    <article className="donut-card">
      <HelpButton uiLang={uiLang} onOpen={onHelp} label={title} />
      <div className="donut-visual">
        <svg viewBox="0 0 100 100" aria-hidden="true">
          <circle className="donut-track" cx="50" cy="50" r={R} />
          <circle
            className="donut-value"
            cx="50"
            cy="50"
            r={R}
            stroke={color}
            strokeDasharray={CIRC}
            strokeDashoffset={offset}
          />
        </svg>
        <div className="donut-center">
          <strong>{p}%</strong>
        </div>
      </div>
      <h3>{title}</h3>
      <p>{explain}</p>
    </article>
  );
}

function RiskMixDonut({
  uiLang,
  high,
  medium,
  low,
  onHelp,
}: {
  uiLang: LanguageCode;
  high: number;
  medium: number;
  low: number;
  onHelp: () => void;
}) {
  const total = high + medium + low;
  const segments =
    total === 0
      ? [{ value: 1, color: "#d1d5db", key: "empty" }]
      : [
          { value: high, color: "#b42318", key: "high" },
          { value: medium, color: "#d97706", key: "medium" },
          { value: low, color: "#15803d", key: "low" },
        ].filter((s) => s.value > 0);

  let angle = -90;
  const arcs = segments.map((s) => {
    const share = s.value / (total || 1);
    const sweep = share * 360;
    const start = angle;
    angle += sweep;
    return { ...s, start, sweep, share };
  });

  function polar(cx: number, cy: number, r: number, deg: number) {
    const rad = (deg * Math.PI) / 180;
    return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
  }

  function arcPath(startDeg: number, sweepDeg: number) {
    const r = R;
    const large = sweepDeg > 180 ? 1 : 0;
    const a0 = polar(50, 50, r, startDeg);
    const a1 = polar(50, 50, r, startDeg + sweepDeg);
    if (sweepDeg >= 359.9) {
      return `M ${50 - r} 50 A ${r} ${r} 0 1 1 ${50 + r} 50 A ${r} ${r} 0 1 1 ${50 - r} 50`;
    }
    return `M ${a0.x} ${a0.y} A ${r} ${r} 0 ${large} 1 ${a1.x} ${a1.y}`;
  }

  const highPct = total ? Math.round((high / total) * 100) : 0;
  const medPct = total ? Math.round((medium / total) * 100) : 0;
  const lowPct = total ? Math.round((low / total) * 100) : 0;

  return (
    <article className="donut-card donut-mix">
      <HelpButton uiLang={uiLang} onOpen={onHelp} label={t(uiLang, "riskMixTitle")} />
      <div className="donut-visual">
        <svg viewBox="0 0 100 100" aria-hidden="true">
          <circle className="donut-track" cx="50" cy="50" r={R} />
          {arcs.map((a) => (
            <path
              key={a.key}
              className="donut-arc"
              d={arcPath(a.start, a.sweep)}
              stroke={a.color}
              fill="none"
              strokeWidth="12"
              strokeLinecap="butt"
            />
          ))}
        </svg>
        <div className="donut-center">
          <strong>{total}</strong>
          <small>{t(uiLang, "riskFindingsCount")}</small>
        </div>
      </div>
      <h3>{t(uiLang, "riskMixTitle")}</h3>
      <p>{t(uiLang, "riskMixExplain")}</p>
      <ul className="donut-legend">
        <li>
          <span className="dot high" />
          {t(uiLang, "high")}: {high} ({highPct}%)
        </li>
        <li>
          <span className="dot medium" />
          {t(uiLang, "medium")}: {medium} ({medPct}%)
        </li>
        <li>
          <span className="dot low" />
          {t(uiLang, "low")}: {low} ({lowPct}%)
        </li>
      </ul>
    </article>
  );
}

export function ReportDashboard({
  uiLang,
  readiness,
  high,
  medium,
  low,
  avgRisk,
  docsLimited,
  summary,
  blocked,
}: Props) {
  const riskPct = avgRisk != null ? clampPct(avgRisk) : 0;
  const [helpTopic, setHelpTopic] = useState<HelpTopic | null>(null);

  return (
    <section className="report-dashboard">
      <header className="report-dash-head">
        <h2>{t(uiLang, "summary")}</h2>
        <p className="report-plain-summary">{summary}</p>
        {blocked ? <p className="blocked-note">{t(uiLang, "analysisBlocked")}</p> : null}
      </header>

      <div className="donut-grid">
        <SingleDonut
          uiLang={uiLang}
          percent={readiness}
          color="#0f5c6e"
          title={t(uiLang, "readiness")}
          explain={t(uiLang, "readinessExplain")}
          onHelp={() => setHelpTopic("readiness")}
        />
        <RiskMixDonut
          uiLang={uiLang}
          high={high}
          medium={medium}
          low={low}
          onHelp={() => setHelpTopic("riskMix")}
        />
        <SingleDonut
          uiLang={uiLang}
          percent={riskPct}
          color={riskPct >= 70 ? "#b42318" : riskPct >= 40 ? "#d97706" : "#15803d"}
          title={t(uiLang, "avgRiskScore")}
          explain={t(uiLang, "avgRiskExplain")}
          onHelp={() => setHelpTopic("avgRisk")}
        />
      </div>

      <div className="report-fact-row">
        <div className="report-fact">
          <strong>{docsLimited ?? 0}</strong>
          <span>{t(uiLang, "docsLimited")}</span>
          <small>{t(uiLang, "docsLimitedExplain")}</small>
        </div>
        <div className="report-fact">
          <strong>{high + medium + low}</strong>
          <span>{t(uiLang, "realRisks")}</span>
          <small>{t(uiLang, "realRisksExplain")}</small>
        </div>
      </div>

      {helpTopic ? (
        <HelpModal uiLang={uiLang} topic={helpTopic} onClose={() => setHelpTopic(null)} />
      ) : null}
    </section>
  );
}
