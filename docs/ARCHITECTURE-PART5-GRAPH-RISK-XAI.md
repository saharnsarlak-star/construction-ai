# TenderRisk AI — Architecture Part 5  
## Knowledge Graph · Risk Knowledge Base · Explainable Findings · Multi-country check

**Depends on:** Parts [1](./ARCHITECTURE-PART1-FOUNDATION.md)–[4](./ARCHITECTURE-PART4-SCHEDULE-GEOTECH-ER-ADDENDA.md)  
**Status:** Design complete — **concludes architecture design session Parts 1–5**.  
**Role:** Global consolidation (Knowledge Graph · RKB · Explainable Finding · multi-country check).  
**Constraint:** No code / pseudocode. Extension of existing `Project` / `Document` / `Analysis` / `Finding` — not replacement.  
**Next step after this doc:** Joint review before any implementation.  
**Later (outside this Part):** Part 6 ontology authority refinement; seed rule batches.

---

## 0. Design stance

Parts 1–4 defined **what** each document contributes (CDM, ontology entities, tagged validations).  
Part 5 defines **how** those contributions connect into one project brain, how findings map to a durable risk taxonomy, and how every medium/high finding stays explainable.

```text
Documents (10 types)
    → CDM + Ontology entities (Part 1)
    → OntologyEdge / Knowledge Graph (Part 5 Task 1)
    → Rule Engine [PYTHON] + LLM [AI] + Hybrid (Parts 2–4)
    → Finding (canonical explainable schema — Task 3)
    → Risk ID (Risk Knowledge Base — Task 2)
    → Analysis report (existing Analysis row)
```

---

# TASK 1 — Construction Knowledge Graph

## 1.1 Purpose

A **project-scoped** graph of ontology entities and typed relationships so the Risk Engine can traverse evidence across Contract, BOQ, Drawings, Specs, Standards, Schedule, Geotech, ER, Tender docs, and Addenda — instead of treating each file as an isolated bag of text.

## 1.2 Node inventory (from Part 1 ontology + Parts 2–4)

Nodes are **not** new root aggregates replacing Project/Document. Each node carries:

- `node_type` (ontology class)  
- `node_id` (stable within project)  
- `project_id` → **Project**  
- optional `document_id` → **Document** (provenance)  
- optional links to StandardVersion / StandardClause (library, cross-project)  
- payload ref (CDM content_unit, BoqItem fields, etc.)

**Core node types:** Project, Party, ContractPackage, ExtractedClause, SpecSection, BoqItem, DrawingSheet / ModelRoot, Level, Grid, Room/Space, ScheduleActivity, Requirement, MaterialMention, EquipmentMention, Location / InvestigationPoint, StandardVersion, StandardClause, AddendumChange, Finding (published), Risk (KB id — see Task 2).

## 1.3 Edge (relationship) vocabulary

Stored as **OntologyEdge** (Part 1) — project-scoped:

| Predicate | Typical from → to | Built mainly by |
|-----------|-------------------|-----------------|
| `references` | BoqItem → DrawingSheet; Clause → SpecSection; Spec → StandardClause | **[PYTHON]** ID resolve + **[AI]** soft refs |
| `amends` / `supersedes` | Addendum → Document/Clause/Sheet; DrawingSheet rev → prior | **[PYTHON]** |
| `conflicts_with` | Clause ↔ Clause; SpecSection ↔ SpecSection; ER ↔ Contract | **[AI]** / **[HYBRID]** |
| `quantifies` | BoqItem → Material / work on Drawing | **[HYBRID]** |
| `precedes` / `lags` | ScheduleActivity → ScheduleActivity | **[PYTHON]** |
| `depends_on` | Activity → Procurement/Material; Foundation → Geotech recommendation; Structure → Level | **[HYBRID]** |
| `governed_by` | Requirement / SpecSection → StandardClause | **[PYTHON]** lookup |
| `implements` | Milestone → Contractual completion Requirement | **[HYBRID]** |
| `allocates_responsibility` | Clause / ER → Party | **[AI]** |
| `affects_payment` | Contract clause → payment Requirement / BoqItem | **[AI]** / **[HYBRID]** |
| `evidences` / `gaps` | Project entity → StandardClause | **[PYTHON]** presence + **[AI]** adequacy |
| `clarifies` | Q&A / Addendum → Requirement | **[HYBRID]** |
| `located_in` | Space / InvestigationPoint → Location / Site | **[PYTHON]** |

**Examples requested in the prompt (normalized):**

- BoqItem —`references`→ DrawingSheet —`references`→ SpecSection —`governed_by`→ StandardClause  
- ScheduleActivity —`depends_on`→ Procurement / long-lead MaterialMention  
- ExtractedClause —`affects_payment`→ payment Requirement / BoqItem  
- Foundation recommendation / Structure —`depends_on`→ Geotech Document / InvestigationPoint  

## 1.4 Incremental build lifecycle

Graph is **append/merge**, never a full rebuild unless forced re-extract.

| Moment | Graph action |
|--------|----------------|
| **Upload + extraction complete** | Create/update Document node; emit CDM; create type-specific entities (items, sheets, activities, clauses…) with `document_id` |
| **Relationship Extraction stage** | Add edges resolvable by **[PYTHON]** (IDs, OZ, sheet numbers, dates) |
| **Semantic Parsing / LLM stage** | Propose soft edges (`conflicts_with`, `allocates_responsibility`) with confidence + evidence pointers; mark `source=ai` |
| **Addendum ingest** | `supersedes`/`amends` edges; deprecate or version prior node payloads |
| **Standard binding change** | Rewire `governed_by` / `gaps` using StandardClause **lookup** (no re-parse of codes) |
| **Analyze / Risk Engine** | Traverse neighborhoods for cross-doc rules; attach Finding nodes via `evidences` edges to supporting nodes |
| **Document delete** | Soft-delete nodes/edges with that `document_id` or mark orphaned |

Confidence of an edge ≤ min(endpoint extraction bands, resolver confidence).

## 1.5 Storage relative to existing schema

| Layer | Storage | Relation to MVP |
|-------|---------|-----------------|
| Project / Document / Analysis / Finding | **Existing tables** | Unchanged roles |
| CDM | `Document.meta_json.canonical` | Extension |
| Entity tables (BoqItem, ExtractedClause, …) | **New child tables** FK → `project_id` / `document_id` | Extension |
| Graph edges | **OntologyEdge** table (or JSONB edge list on Project for MVP scale) FK → `project_id` | Extension |
| StandardClause / StandardVersion | **Library tables** (prior design) | Shared across projects; edges point by ID |

**Not a parallel Project graph DB as source of truth** — Project row remains the root; graph is indexed evidence under it.

**BREAKING CHANGE:** None if edges/entities are additive.

---

# TASK 2 — Construction Risk Knowledge Base (RKB)

## 2.1 Purpose

Every published **Finding** maps to a predefined **Risk ID** in a curated taxonomy so:

- Risks are comparable across projects/countries  
- Mitigation and lessons can accumulate  
- Reporting is stable even when wording of findings differs  

Mapping must be **traceable** (why this Risk ID) — never a silent classifier label.

## 2.2 Risk record schema

| Field | Meaning |
|-------|---------|
| **Risk ID** | Stable code e.g. `RISK-CLAIM-NOTICE-001`, `RISK-GEO-GW-001` |
| **Category** | claim · cost · delay · quality · safety · compliance · commercial · constructability · procurement · … |
| **Description** | Neutral definition of the risk class (not project-specific) |
| **Probability** | Default prior (Low/Med/High or 1–5); overridable per finding |
| **Cost Impact** | Default ordinal / guidance band |
| **Schedule Impact** | Default ordinal / guidance band |
| **Quality Impact** | Default ordinal / guidance band |
| **Safety Impact** | Default ordinal / guidance band |
| **Mitigation** | Employer-side mitigation patterns before award / after |
| **Lessons Learned** | Curated summaries linked from outcome feedback (see 2.4) |
| **Related Standards** | StandardClause / StandardVersion refs (library) |
| **Related Documents** | Typical document types / subtypes that evidence this risk |

RKB is **platform-level** (versioned). Project findings **reference** Risk IDs; they do not fork the taxonomy per project (optional project overrides only for probability/impact scoring).

## 2.3 Finding → Risk ID assignment

```text
Validation hit (Parts 2–4 rule IDs e.g. C-H01, GEO-P02)
    → candidate Risk IDs (many-to-one or one-to-many allowed, primary + secondary)
    → Reasoning field MUST state mapping rationale
    → Validation Evidence + graph neighborhood support the choice
```

- **[PYTHON]** rules often have a **fixed** Risk ID map (deterministic).  
- **[AI]** findings propose Risk ID with explicit rationale; optional **[PYTHON]** allow-list check that proposed ID exists and category fits.  
- **[HYBRID]** Python selects candidate set; AI chooses primary ID + explains.

Unsupported mapping (no evidence) → **forbidden**; emit limitation Finding or drop.

## 2.4 Three knowledge sources — how they differ and feed Risk IDs

| Source | What it is | When it updates | Feeds Risk IDs how |
|--------|------------|-----------------|-------------------|
| **Risk Knowledge Base (RKB)** | Canonical taxonomy of risk classes + default impacts/mitigations | Curated product releases; rare admin edits | **Target** of Finding.risk_id; defaults for impact fields |
| **ExtractedInsight** *(external / prior session)* | Insights mined from **external** knowledge (guides, case law summaries, published claim patterns, standards commentaries) — not from this project’s files | Ingestion of external corpora; linked to Risk IDs / StandardClauses | Suggests new Risk IDs, enriches Description/Mitigation, biases AI prompts with cited external insight IDs (still must attach project evidence for the Finding itself) |
| **LessonsLearned** *(project outcome feedback)* | Post-award / post-project outcomes: which findings materialized, actual cost/time, what mitigation worked | Project closeout / user feedback loop | Adjusts empirical Probability/Impact priors per Risk ID; appends Lessons Learned text on Risk record; may spawn ExtractedInsight candidates after review |

**Flow over time:**

1. **RKB** defines the ID space.  
2. **ExtractedInsight** enriches definitions and AI priors (external).  
3. Project **Findings** instantiate risks with project evidence.  
4. **LessonsLearned** updates real-world priors and mitigation quality on the same Risk IDs.  

None of the three replaces Finding explainability: external insight may inform wording; **quotation/evidence must still come from this Project’s graph/CDM**.

## 2.5 Relation to Analysis / Finding tables

- `Finding` gains additive fields: `risk_id`, `risk_mapping_rationale`, optional `secondary_risk_ids[]`.  
- `Analysis` aggregates counts by Risk Category / Risk ID.  
- No replacement of Finding by Risk record — Risk is the **class**, Finding is the **instance**.

---

# TASK 3 — Explainable AI / Canonical Finding Output Model

## 3.1 Principle

**Never produce an unsupported conclusion.**  
Every medium/high Finding’s Recommendation, Cause, Effect, and Business Impact must trace to:

- a tagged validation (**[PYTHON]/[AI]/[HYBRID]**), and  
- concrete evidence nodes (clause text, BoqItem, sheet ID, activity ID, StandardClause ID, graph edge), and  
- extraction confidence honesty (band + Missing Evidence).

If evidence is insufficient → Finding Type = limitation / data gap (`source_layer` usually `rule_based`), **not** a fabricated commercial risk.

## 3.2 Canonical Finding schema (consolidation of Parts 2–4)

| Field | Required (Med/High) | Notes |
|-------|---------------------|-------|
| **Finding Type** | Yes | Taxonomy aligned to risk categories |
| **Severity** | Yes | high / medium / low (existing) |
| **Confidence** | Yes | 0–100; derived from evidence + extraction bands |
| **Source Layer** | Yes | `rule_based` \| `llm_based` \| `hybrid` (maps from PYTHON/AI/HYBRID) |
| **Source Document** | Yes | Primary Document id/name |
| **Page** | If applicable | Page/sheet index |
| **Paragraph** | If applicable | content_unit / clause / OZ / activity id |
| **Exact Quotation** | Yes for Med/High when text exists | Verbatim; empty only if purely structural **[PYTHON]** count with Validation Evidence substituting |
| **Reasoning** | Yes | Why this is a tender risk *and* why this Risk ID |
| **Cause** | Yes | Condition in the pack |
| **Effect** | Yes | Likely project outcome |
| **Business Impact** | Yes | Cost / time / claim / quality / safety narrative |
| **Recommendation** | Yes | Employer-actionable, pre-award oriented |
| **Cross References** | Yes when cross-doc | Other docs / graph node IDs |
| **Related Standards** | When relevant | StandardVersion + StandardClause IDs |
| **Validation Evidence** | Yes | Deterministic artifacts, rule IDs, edge IDs, totals |
| **Confidence Explanation** | Yes | Band + what limits certainty |
| **Missing Evidence** | Yes if confidence < threshold or gap | What would improve certainty |
| **Risk ID** | Yes for Med/High risk findings | From RKB + mapping rationale |
| **Graph Neighborhood** *(optional field)* | Recommended | Short list of traversed node IDs |

Maps onto existing **Finding** row + additive JSON/columns (Part 1). Low severity / methodology/limitation may omit quotation if purely procedural, but still need Validation Evidence.

## 3.3 Explainability pipeline

1. **Emit** candidate from Rule / AI / Hybrid with evidence pointers.  
2. **Guardrail [PYTHON]:** reject if Med/High and (no evidence pointers OR Risk ID missing OR recommendation empty).  
3. **Enrich:** Cause→Effect chain; Business Impact; Mitigation from RKB defaults refined by AI only with citations.  
4. **Persist** Finding under Analysis; link graph `evidences` edges.  
5. **UI:** show quotation + rule ID + Risk ID + confidence explanation (never only a score).

## 3.4 Source Layer semantics

| source_layer | Origin | Evidence expectation |
|--------------|--------|----------------------|
| `rule_based` | **[PYTHON]** | Counts, IDs, dates, totals, clause presence |
| `llm_based` | **[AI]** | Quotations + semantic rationale; no invented numbers that contradict parsers |
| `hybrid` | **[HYBRID]** | Python artifact + AI narrative bound to that artifact |

---

# TASK 4 — Multi-country & scalability compatibility (confirmation only)

## 4.1 Existing mechanisms (unchanged)

- Country profiles: IR / DE / CA (+ EU)  
- Per-country Standard catalog applicability + **ProjectStandard** selection  
- Per-country **RuleSet** overrides in `rules_registry` / profiles  
- GAEB path for DE BOQ; Fehrest-oriented IR; IFC universal  
- Multilingual Finding text via report language  

## 4.2 Compatibility of Parts 1–5

| Design element | Compatible? | Note |
|----------------|-------------|------|
| CDM / ontology / graph | **Yes** | Country-agnostic structure; payloads localize |
| RKB Risk IDs | **Yes** | Global IDs; optional `jurisdiction_tags` / RuleSet filters which risks are activated — **not** separate RKB forks required |
| StandardClause library | **Yes** | Already edition- and jurisdiction-aware via StandardVersion |
| Cross-doc rules Parts 2–4 | **Yes** | Enable/disable via country RuleSet; same tags PYTHON/AI/HYBRID |
| Explainable Finding schema | **Yes** | Language field already on Analysis/Finding |

## 4.3 Genuine conflicts flagged

**None that require redesign.**  

**Watch-outs (non-blocking):**  
- RKB impact priors may need country-specific calibration via LessonsLearned (data), not schema split.  
- Some Risk IDs are jurisdiction-specific (e.g. VOB/GAEB procedural); activate through RuleSet, keep one RKB.  
- Legal citations in ExtractedInsight must remain labeled non-authoritative for Employer decisions.

---

## End-to-end picture (Parts 1–5)

```text
Upload → Extract/CDM → Ontology entities → Knowledge Graph edges
                              ↓
              Country RuleSet + StandardClause lookup
                              ↓
         [PYTHON] / [AI] / [HYBRID] validations (10 doc types)
                              ↓
         Explainable Finding → Risk ID (RKB) → Analysis
                              ↓
         LessonsLearned / ExtractedInsight refine RKB over time
```

---

## Session complete — artifact index

| Part | Document |
|------|----------|
| 1 | Foundation: pipeline, normalization, ontology |
| 2 | Contract, BOQ, Drawings |
| 3 | Tender docs, Specs, Standards |
| 4 | Schedule, Geotech, ER, Addenda |
| 5 | **This file** — Graph, RKB, Explainable Finding, country check |

**Recommended next step:** Human review of Parts 1–5 before implementation sequencing (CDM writer → entity tables → edges → Finding schema → RKB seed → LLM stage behind flag).
