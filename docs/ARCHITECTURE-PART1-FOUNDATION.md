# TenderRisk AI — Architecture Part 1  
## Foundation: Principles, Ingestion Pipeline, Normalization, Ontology

**Status:** Design complete (extend existing system — do not replace)  
**Checkpoint:** This Part 1 document is the authoritative foundation for the multi-part architecture session. Document-type-specific analysis remains **out of scope** here.

**Honesty note on current MVP:** Today’s `analyzer.py` still uses topic/keyword heuristics for several checks. This Part 1 designs the foundation so future validations can be tagged **[PYTHON] / [AI] / [HYBRID]** and stop treating keyword matching as the primary intelligence layer.

**Current parsers (as of post–seed session):** `ifc_extractor` and `gaeb_extractor` are **implemented** (not merely in progress) and feed `NormalizedExtractionResult` into `Document.meta_json.extraction`. Full CDM (`meta_json.canonical`) and ontology sub-tables remain **designed, not yet built**.

---

## 0. Non-negotiable principles

### 0.1 Product identity
TenderRisk AI is a **Construction Tender Intelligence Platform** (employer-side risk before contract signing), not a document management system and not a BIM viewer.

### 0.2 Two complementary layers (always both)

| Layer | Role | Must do | Must not do |
|-------|------|---------|-------------|
| **Layer 1 — Deterministic [PYTHON]** | Countable checks, exact comparisons, native-parser facts, revision/ID matching, quantity arithmetic, schedule logic, metadata completeness | Produce auditable pass/fail + evidence pointers | Invent meaning or claim intent |
| **Layer 2 — Semantic [AI]** | Ambiguity, intent, claim/responsibility interpretation, constructability reasoning, cross-document meaning | Explain risks in engineering language with citations | Invent numbers that parsers already measured; override hard gate facts |

**[HYBRID]** = Python detects a measurable condition → AI explains impact, cause–effect, and recommendation.

Every validation designed in later parts **must** be tagged `[PYTHON]`, `[AI]`, or `[HYBRID]`. Unclassified rules are rejected.

### 0.3 Reuse over redesign
Extend: `extractor.py` facade, OCR package, `cad_extractor` / `ifc_extractor` / `gaeb_extractor`, `NormalizedExtractionResult` envelope in `Document.meta_json`, existing `Project` / `Document` / `ProjectStandard` / `Analysis` / `Finding`, country profiles & rules registry.

**Already designed elsewhere (do not recreate in this part):**
- Persistent **StandardClause** store (parse once per standard edition, reuse across projects)
- **StandardVersion** / **StandardVersionDiff** / per-project binding to a specific edition  

When Part N covers “Standards and Codes”, integrate against those models.

### 0.4 Breaking changes in this part
**None required.** All additions are additive tables / JSON envelopes / pipeline stages. No drop or rename of existing MVP tables.

---

## 1. Document ingestion pipeline (high level)

End-to-end stages. Each stage: purpose · reuse vs new · layer tag.

```text
Upload
  → Document Classification
  → Language Detection
  → OCR Decision
  → OCR (if required)
  → Layout Analysis
  → Table Extraction
  → Drawing / Model Text Extraction
  → Document Normalization
  → Metadata Extraction
  → Entity Extraction
  → Relationship Extraction
  → Semantic Parsing
  → Knowledge Graph Mapping
  → Rule Engine
  → LLM Reasoning
  → Risk Engine
  → Report Generation
```

| # | Stage | What it does | Existing module / NEW | Tag |
|---|--------|--------------|------------------------|-----|
| 1 | **Upload** | Persist bytes; create `Document` row; queue async job; category chosen by UI (`tender` / `drawing` / `schedule` / `standard`) | **EXISTING** — `routers/projects.py`, `storage.py`, `extraction_jobs.queued_meta` | **[PYTHON]** |
| 2 | **Document Classification** | Confirm or refine *document subtype* (e.g. contract vs BOQ vs specs inside `tender`; sheet type inside drawings). Category stays the coarse UI bucket; subtype is finer | **PARTIAL** — category exists; subtype classifier **NEW** (rules on extension + native parse + optional AI) | **[HYBRID]** — Python: extension/native signature; AI: ambiguous PDF packs |
| 3 | **Language Detection** | Detect primary language(s) of extractable text; align with project app language for reporting | **PARTIAL** — project `ui_language` / `report_language` exist; per-document lang detect **NEW** (fastText/lingua or heuristic) | **[PYTHON]** (+ optional **[AI]** only if mixed/uncertain) |
| 4 | **OCR Decision** | Decide whether OCR is needed (searchable PDF vs scan vs CAD-native) | **EXISTING** — `ocr/classifier.py`, pipeline page kinds | **[PYTHON]** |
| 5 | **OCR (if required)** | Raster → text with confidence; fa/de/en | **EXISTING** — `ocr/pipeline.py`, Tesseract / RapidOCR | **[PYTHON]** |
| 6 | **Layout Analysis** | Blocks, reading order, headers/footers, title blocks, sheet frames | **NEW** for general PDF (beyond page kind); title-block harvest partially exists in CAD string paths | **[PYTHON]** (vision models optional later = **[AI]** assist) |
| 7 | **Table Extraction** | Recover tables (BOQ-like, schedule grids) into cells | **PARTIAL** — Excel native; PDF tables **NEW** | **[PYTHON]** |
| 8 | **Drawing / Model Text Extraction** | Layers, TEXT, IFC entities/Psets, harvested DWG/RVT strings | **EXISTING** — `cad_extractor`, `ifc_extractor` (implemented), DWG/RVT harvest | **[PYTHON]** |
| 9 | **Document Normalization** | Map all sources into one **Canonical Document Model** (see §2) | **PARTIAL** — `NormalizedExtractionResult` + `meta_json.extraction`; full canonical model **NEW** | **[PYTHON]** |
| 10 | **Metadata Extraction** | Project name, revision, date, discipline, sheet ID, GAEB phase, IFC schema, file hash | **PARTIAL** — IFC/GAEB structured; general PDF metadata **NEW** | **[PYTHON]** |
| 11 | **Entity Extraction** | Instantiate ontology entities (Clause, BOQ Item, Activity, …) linked to `Document` | **NEW** (writers into new sub-tables / JSON graph — see §3) | **[HYBRID]** — Python for structured natives; AI for prose entities |
| 12 | **Relationship Extraction** | Links: clause↔drawing ref, BOQ↔spec item, activity↔milestone, document↔revision | **NEW** | **[HYBRID]** |
| 13 | **Semantic Parsing** | Meaning units: obligations, ambiguities, soft requirements, exclusions | **NEW** (LLM + structured prompts); not keyword lists | **[AI]** |
| 14 | **Knowledge Graph Mapping** | Attach entities/relations to project graph under `Project` | **NEW** (graph store or JSONB adjacency on project — prefer JSONB first) | **[PYTHON]** orchestration + **[AI]** edge typing when ambiguous |
| 15 | **Rule Engine** | Deterministic validations from registry + countable facts | **EXISTING** — `rules_registry.py`, `analyzer.py` (to be evolved; drop keyword-as-primary) | **[PYTHON]** |
| 16 | **LLM Reasoning** | Interpret hybrid findings; cross-doc narrative; claim/delay/cost reasoning | **NEW** as first-class stage (today only prompt templates exist) | **[AI]** |
| 17 | **Risk Engine** | Merge Python outcomes + AI outcomes → scored `Finding`s with evidence, layer tag, confidence | **PARTIAL** — `analyzer.py` findings; merge semantics **NEW** | **[HYBRID]** |
| 18 | **Report Generation** | Multilingual summary + readiness + findings for UI/export | **EXISTING** — `Analysis` / `Finding` + frontend; export formats **NEW** later | **[PYTHON]** (+ **[AI]** for executive narrative polish) |

### Pipeline orchestration note
- Keep **async job** pattern (`extraction_jobs`) for stages 2–10.
- Stages 11–18 run on **Analyze** (and optionally as incremental “deep parse” jobs).
- Hard extraction gate on non-drawing text docs remains **[PYTHON]** and must not be overridden by AI.

---

## 2. Document Normalization Layer

### 2.1 Goal
Every supported format (PDF, Word, Excel, GAEB, IFC, DWG, DXF, XML, CSV, …) lands in **one canonical representation** before Rule Engine / LLM. The AI layer never sees raw format idiosyncrasies as its primary input.

### 2.2 Compatibility with today’s envelope
Extend — do not discard — current `Document.meta_json`:

```text
Document.meta_json
  extraction: { phase, progressPercent, method, confidenceScore, structured, notes, … }
  pages: […]          # OCR page results (existing)
  canonical: { … }    # NEW — Canonical Document Model (CDM)
```

Also keep `Document.extracted_text` as a **flattened corpus view** derived from CDM (backward compatible for current analyzer).

`NormalizedExtractionResult` (already in code) remains the **parser-facing** return type (`merged_text` + `method` + `confidence` + `structured`). A thin **Normalizer** maps `structured` + text → `canonical`.

### 2.3 Canonical Document Model (CDM) — conceptual schema

```text
CanonicalDocument
  document_id          → Document.id
  project_id           → Project.id
  category             → Document.category (tender|drawing|schedule|standard)
  subtype              → NEW fine type (contract|boq|specs|ifc_model|gaeb_lv|…)
  language_primary
  languages_detected[]
  extraction
    method             → ifc_native | gaeb_native | dxf_native | …
    confidence_score   → existing bands
    needs_manual_review
    source_formats[]   → e.g. ["application/x-ifc"]
  identity
    title
    revision
    revision_date
    authoring_system
    external_ids[]     → sheet no, GAEB OZ roots, IFC GlobalIds of roots
  content_units[]      → ordered units (see below)
  tables[]             → normalized grids
  spatial              → optional (IFC hierarchy / drawing levels)
  quantities_summary   → optional rollups from native parsers
  links_out[]          → unresolved refs as strings (resolved later in Relationship Extraction)
  provenance
    parser_version
    normalized_at
    content_hash
```

**ContentUnit** (shared atom for all docs):

```text
ContentUnit
  id                   # stable within document
  unit_type            # paragraph | heading | clause_candidate | note | title_block | label | other
  text
  language
  page_or_sheet        # nullable
  bbox                 # nullable
  reading_order
  confidence
  raw_refs[]           # e.g. "see Dwg A-101", "Pos 01.02.0030"
```

**NormalizedTable:**

```text
NormalizedTable
  id
  name
  headers[]
  rows[][]             # cell text
  role_hint            # boq_like | schedule_like | unknown  (hint only; type-specific design later)
  confidence
```

**SpatialSummary** (from IFC / drawing levels — still format-agnostic):

```text
SpatialSummary
  nodes[]              # { type, name, external_id, parent_id }
  element_counts{}     # discipline → counts (from IFC typed counts, etc.)
```

### 2.4 Mapping from native parsers (illustrative)

| Source | CDM fill |
|--------|----------|
| PDF OCR | content_units from pages; tables when extracted; method=`pdf_drawing_ocr` / searchable |
| DOCX / TXT | content_units from paragraphs |
| XLSX / CSV | tables[] primary; content_units optional |
| GAEB | tables[] or structured items → content_units + `extraction.structured.items` preserved under `canonical.quantities_summary` / typed bag |
| IFC | spatial + property highlights → content_units narrative + structured bag |
| DXF | layers/texts → content_units + spatial light |
| DWG/RVT harvest | content_units lower confidence |

**Confidence inheritance:** CDM `extraction.confidence_score` = parser confidence; individual units may be lower. Risk Engine must weight evidence by this score.

### 2.5 What normalization is *not*
- Not a parallel Document table  
- Not re-storage of file bytes  
- Not document-type business rules (those come in later parts)

---

## 3. Shared Construction Tender Ontology

### 3.1 Design rule
Ontology concepts are **extensions / enrichments** of existing MVP entities. They attach via foreign keys (or JSONB graphs keyed by `project_id` / `document_id`). They do **not** replace `Project`, `Document`, `ProjectStandard`, `Analysis`, or `Finding`.

### 3.2 Existing core (unchanged roles)

| Existing | Remains the source of truth for |
|----------|----------------------------------|
| **Project** | Tender package container: country, type, language, profile |
| **Document** | Uploaded file + extraction lifecycle + CDM in `meta_json` |
| **ProjectStandard** | Which catalog standards apply to this project (selection) |
| **Analysis** | One analysis run snapshot (readiness, summary, status) |
| **Finding** | User-visible risk/limitation/methodology outcome |

### 3.3 Ontology concepts → attachment map

| Ontology concept | Meaning | Attaches to (extension) | Notes |
|------------------|---------|-------------------------|-------|
| **Project** | Same as existing | **= `Project`** | Enrich with optional JSON profile fields later; no second Project table |
| **Employer** | Client / owner party | **NEW** `Party` row (role=`employer`) → `project_id` | Optional until contracts part |
| **Contractor** | Bidder / GC (often unknown pre-award) | **NEW** `Party` (role=`contractor` / `bidder`) → `project_id` | |
| **Contract** | The agreement package / draft | **NEW** `ContractPackage` → `project_id`; links to one+ `Document` (tender) | Not a replacement for Document |
| **Clause** | Numbered/obligation unit in contract/specs | **NEW** `ExtractedClause` → `document_id` (+ optional `contract_package_id`) | Distinct from **StandardClause** (global standards store — already designed) |
| **Drawing** | Sheet / model view | **NEW** `DrawingSheet` or `ModelRoot` → `document_id` | Document.category=`drawing` remains the file |
| **Specification** | Spec section/doc | Often a `Document` subtype; sections as **NEW** `SpecSection` → `document_id` | |
| **BOQ Item** | Position / line | **NEW** `BoqItem` → `document_id` (GAEB fills from structured) | |
| **Activity** | Schedule task | **NEW** `ScheduleActivity` → `document_id` | |
| **Material** | Material / product | **NEW** `MaterialMention` → `project_id`, optional `document_id` | |
| **Equipment** | Plant / equipment | **NEW** `EquipmentMention` → same pattern | |
| **Location** | Site / place | Prefer link to Project + IFC Site; **NEW** `LocationNode` if needed | |
| **Structure** | Building / wing | Map to IFC Building / spatial node → `document_id` | |
| **Room / Space** | Space | IFC Space / text mention → spatial or mention table | |
| **Foundation** | Foundation system | Discipline entity or tagged IFC elements | |
| **Grid** | Structural/architectural grid | Drawing/IFC annotation entity | |
| **Level** | Storey | IFC BuildingStorey / drawing level | |
| **Standard** | Catalog standard | **= catalog + `ProjectStandard`** | Edition binding via pre-designed StandardVersion |
| **Requirement** | Normative requirement instance | **NEW** `Requirement` → may link `ExtractedClause` and/or `StandardClause` | Bridge tender text ↔ standards |
| **Risk** | Internal risk object pre-Finding | Optional **NEW** `RiskCandidate` → becomes `Finding` | Or map directly to Finding |
| **Finding** | Published outcome | **= `Finding`** | Add fields: `validation_layer` (python\|ai\|hybrid), `evidence_refs[]`, `ontology_links[]` (**additive columns** — not breaking) |

### 3.4 Relationship types (cross-cutting)

Stored as **NEW** `OntologyEdge` (or JSONB graph on Project):

```text
OntologyEdge
  project_id
  from_type / from_id
  to_type / to_id
  predicate     # references | conflicts_with | quantifies | governs | scheduled_as | located_in | …
  confidence
  source        # python | ai | hybrid
  document_id   # optional provenance
```

Examples (generic — not type-specific rule design):
- BOQ Item **quantifies** Material / work described in SpecSection  
- ExtractedClause **references** DrawingSheet  
- ScheduleActivity **implements** contractual duration Requirement  
- Requirement **governed_by** StandardClause (edition-bound)

### 3.5 Standards integration (pointer only)
- **StandardClause** / **StandardVersion*** : global, persistent (prior design)  
- **ProjectStandard** : project selection  
- **Requirement** / edges : project-instance application of clauses  
Do **not** re-parse standards per project; bind edition once, reuse clauses.

### 3.6 Finding enrichment (additive)
Extend `Finding` (or `Finding.meta`) with:
- `validation_layer`: `python` | `ai` | `hybrid`
- `evidence`: list of `{ document_id, content_unit_id | boq_item_id | …, excerpt }`
- `confidence` separate from severity score when needed  

**Migration:** nullable columns / JSON; old findings remain valid. **Not a breaking change.**

---

## 4. How the two layers consume the foundation

```text
                    ┌─────────────────────────┐
  Native parsers    │  CDM + Ontology facts   │
  OCR / tables  ──► │  (counts, IDs, links)   │──► Rule Engine [PYTHON]
                    │                         │──► LLM Reasoning [AI]
                    └────────────┬────────────┘
                                 │
                                 ▼
                          Risk Engine [HYBRID]
                                 │
                                 ▼
                     Analysis + Finding (existing)
```

- **[PYTHON]** reads countable ontology fields and CDM confidence.  
- **[AI]** reads CDM content_units + graph neighborhood; must cite evidence IDs.  
- **[HYBRID]** pairs them into one Finding.

---

## 5. Implementation sequencing (foundation only)

1. Formalize **CDM** writer behind extractor facade (fill `meta_json.canonical`).  
2. Additive **Finding** evidence/layer fields.  
3. Introduce **OntologyEdge** + first entity tables used by multiple doc types (`BoqItem`, `ExtractedClause`, spatial nodes from IFC).  
4. Wire Analyze to prefer CDM over raw text when present.  
5. Add LLM Reasoning stage as optional behind feature flag — never bypass extraction gate.

Document-type rule catalogs arrive in later parts, each rule tagged `[PYTHON]` / `[AI]` / `[HYBRID]`.

---

## 6. Breaking change register (Part 1)

| Change | Breaking? | Why / impact / migration |
|--------|-----------|---------------------------|
| CDM under `meta_json.canonical` | **No** | Additive JSON |
| Ontology sub-tables | **No** | New tables; old analyze path still uses `extracted_text` |
| Finding layer/evidence fields | **No** | Nullable / JSON defaults |
| Replacing keyword analyzer wholesale | **Deferred** | Behavior change for users; migrate rule-by-rule in later parts with dual-run comparison — **not** done in Part 1 |
| Replacing Project/Document/Finding | **Forbidden** | Would break API & UI |

---

## 7. Explicitly deferred to next prompts

- Contract / particular conditions analysis design  
- BOQ (GAEB / Fehrest / Excel) validation catalog  
- Drawings / IFC constructability & reference checks  
- Schedule logic deep rules  
- Specs ↔ standards clause mapping workflows  
- Cross-document conflict matrices  

---

## 8. One-line summary

**Extend the existing extract → analyze spine with a Canonical Document Model and a shared ontology that hangs off Project/Document/Finding, then run every future check as Deterministic [PYTHON], Semantic [AI], or [HYBRID] — without replacing the MVP schema or redesigning StandardClause/versioning.**
