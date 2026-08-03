# TenderRisk AI — Architecture Part 4  
## Document Types (Batch 3): Schedule · Geotechnical · Employer Requirements · Addenda

**Depends on:** Parts [1](./ARCHITECTURE-PART1-FOUNDATION.md), [2](./ARCHITECTURE-PART2-CONTRACT-BOQ-DRAWINGS.md), [3](./ARCHITECTURE-PART3-TENDER-SPECS-STANDARDS.md)  

**Status:** Design complete for Batch 3 — **all 10** canonical document types now covered across Parts 2–4.  
**Scope:** Full-depth (same 12 sections) for the **remaining four** document types.  
**Out of scope here:** Knowledge Graph global design, Risk Knowledge Base, Explainable AI framework → **Part 5**.  

**Constraints:** No code/pseudocode. No keyword-as-intelligence. Existing confidence bands only. StandardClause/StandardVersion lookup model unchanged. §§8–9 fully tagged. Ontology/pipeline unchanged.  
**Later seed alignment:** `SCH-SEED-*`, `GEO-SEED-*`, `REQ-SEED-*`, `ADD-SEED-*`.

---

## 0. Category mapping (all four)

| Document type | Existing `Document.category` | `CDM.subtype` examples | New category? |
|---------------|------------------------------|------------------------|---------------|
| **Construction Schedule** | **`schedule`** | `baseline_programme`, `tender_programme`, `milestone_schedule` | **No** |
| **Geotechnical Reports** | **`tender`** (site data pack) *preferred* — or `standard` only if mis-filed (discourage) | `geotech_report`, `site_investigation`, `groundwater_memo` | **No** — keep under `tender` as supporting tender technical data |
| **Employer Requirements** | **`tender`** | `employer_requirements`, `ers`, `design_brief`, `performance_brief` | **No** |
| **Addenda** | **`tender`** | `addendum`, `clarification_bulletin`, `tender_amendment` | **No** |

**Rationale:**  
- Schedule already has a first-class category.  
- Geotech / ER / Addenda are tender-pack artifacts; subtype + classification avoids BREAKING category proliferation.  
- Geotech is **not** a “standard”; must not use StandardClause ingestion path.

**BREAKING CHANGE:** None.

**Shared Finding fields:** same Part 2 dictionary including `source_layer` (`rule_based` | `llm_based` | `hybrid`).

---

# A. CONSTRUCTION SCHEDULE

## A1. Supported file formats

| Tier | Formats |
|------|---------|
| **Preferred** | XLSX / CSV with explicit activity ID, name, start, finish, predecessors; Primavera/MS Project XML exports when structured |
| **Good** | Searchable PDF Gantt with readable activity tables |
| **Acceptable** | DOCX narrative programmes with dated milestones only |
| **Poor** | Image-only Gantt screenshots, scanned bar charts |
| **Unsupported** | Proprietary locked scheduling DBs without export; video-only presentations |

## A2. Extraction confidence (existing bands only)

| Situation | Band |
|-----------|------|
| Native Excel/CSV/XML activity tables | **70–85** numeric (structured native policy) |
| Searchable PDF tables | **70–85** if clean text tables; else **`pdf_drawing_vision` 35–55** with layout/table recovery |
| OCR from scanned Gantt | **`pdf_drawing_ocr` 20–45** |

## A3. OCR strategy

- Prefer native spreadsheet/XML — **no OCR**.  
- PDF: table extraction first; OCR only if scanned.  
- Layout analysis for Gantt axis/legend when needed.  
- Vision AI optional for bar-chart date inference (low confidence → vision band).  
- Reuse existing OCR modules for PDF pages only.

## A4. Semantic understanding strategy

An experienced **Planner / Tender PM / Claim consultant** looks for:

- Unrealistic durations vs scope/BOQ volumes  
- Impossible or missing **logic** (open ends, cyclic logic, missing FS links)  
- Missing contractual **milestones** / possession / sectional completion  
- Procurement / long-lead items not on critical path  
- Float ownership / negative float / excessive terminal float games  
- Weather / calendar assumptions inconsistent with geotech/site  
- Compression that implies unstated overtime/shift risk  
- Alignment (or not) with Contract time for completion and ITT deadlines  

Reason about network logic and feasibility — not searching for the word “milestone”.

## A5. Metadata extraction

- Programme title, revision, data date, calendar name  
- Start/finish of project, time unit  
- Software origin if declared  
- Milestone list count, activity count  
- CDM subtype `baseline_programme` / `tender_programme`

## A6. Entity extraction → ontology

| Extracted | Ontology |
|-----------|----------|
| Schedule file | `Document` (`schedule`) |
| Task / activity | `ScheduleActivity` |
| Milestone | `ScheduleActivity` (type=milestone) or Milestone subtype |
| Links / lags | OntologyEdge `precedes` / `lags` |
| Calendar constraints | metadata on activities / project |

## A7. Relationship extraction

- Activity **precedes** Activity  
- Milestone **implements** contractual Completion Requirement  
- Activity **quantifies_effort_for** BoqItem / trade (when mapped)  
- Programme **conflicts_with** Contract duration  
- Procurement activity **requires** long-lead Material/Equipment  

## A8. Validation rules

| ID | Rule | Tag |
|----|------|-----|
| SCH-P01 | Activities with start≤finish; parseable dates | **[PYTHON]** |
| SCH-P02 | Detect cycles in predecessor graph | **[PYTHON]** |
| SCH-P03 | Orphan activities (no pred/succ) beyond allowed terminals | **[PYTHON]** |
| SCH-P04 | Contract duration (days) vs programme overall duration compare | **[PYTHON]** |
| SCH-P05 | Required milestone names/dates from contract present in schedule set | **[PYTHON]** |
| SCH-A01 | Duration realism vs scope complexity | **[AI]** |
| SCH-A02 | Missing procurement / permitting logic | **[AI]** |
| SCH-A03 | Float manipulation / claim-oriented programming patterns | **[AI]** |
| SCH-A04 | Seasonal/geotech constraints ignored in sequencing | **[AI]** |
| SCH-H01 | Python negative float or zero-float cluster → AI explains delay/claim exposure | **[HYBRID]** |
| SCH-H02 | Python contract end date ≠ schedule end → AI assesses EOT/LD risk | **[HYBRID]** |

## A9. Cross-document validation

| Check | Against | Tag |
|-------|---------|-----|
| Overall duration vs Contract Time for Completion | Contract | **[PYTHON]** / explain **[HYBRID]** |
| Milestones vs ITT / Contract sectional completion | Tender Documents / Contract | **[HYBRID]** |
| Quantities-driven durations vs BOQ magnitudes | BOQ | **[HYBRID]** |
| Earthworks season vs Geotech groundwater / weather notes | Geotechnical | **[AI]** |
| Design release gates vs Employer Requirements design stages | Employer Requirements | **[AI]** |
| Addendum time extensions reflected in programme | Addenda | **[HYBRID]** |

## A10. Typical risk contribution

- **Delay:** very high  
- **Claim risk:** very high (EOT, disruption)  
- **Cost overrun:** high (acceleration, prolongation)  
- **Quality:** low–medium  
- **Constructability:** high (sequence feasibility)

## A11. Cause → effect examples

**Example 1 — Duration shorter than contract without method**  
- **Cause:** Programme finishes 60 days early with no acceleration resources stated.  
- **Effect:** Unrealistic tender programme; later EOT/cost claims or failure to complete.  
- **source_layer:** `hybrid`

**Example 2 — Missing foundation milestone after geotech risk**  
- **Cause:** Geotech flags high water; schedule shows deep excavation in wet season with no dewatering activity.  
- **Effect:** Delay, variation, safety incidents.  
- **source_layer:** `llm_based` / `hybrid`

## A12. Finding output model

Activity IDs in Cross References; Validation Evidence = graph metrics, date diffs; Confidence Explanation = Excel vs OCR band; `source_layer` mandatory; Missing Evidence = “no baseline logic exported”.

---

# B. GEOTECHNICAL REPORTS

## B1. Supported file formats

| Tier | Formats |
|------|---------|
| **Preferred** | Searchable PDF with borehole logs + lab tables |
| **Good** | DOCX + Excel lab data |
| **Acceptable** | Scanned reports high dpi; CAD logs as DXF/PDF |
| **Poor** | Photo-only logs, incomplete annexes |
| **Unsupported** | Raw instrument files without report narrative |

## B2. Extraction confidence

| Situation | Band |
|-----------|------|
| Searchable PDF/DOCX + Excel labs | **70–85** numeric |
| Vision/layout for log columns | **`pdf_drawing_vision` 35–55** |
| OCR scans | **`pdf_drawing_ocr` 20–45** |
| Embedded DXF site plans | **`dxf_native` 70–85** for plan layers; report body still per above |

## B3. OCR strategy

- OCR if scanned; layout for borehole log grids.  
- Table detection critical (SPT, gradation, Atterberg, chemistry).  
- Drawing/plan pages: reuse CAD/PDF drawing path when applicable.  
- Vision optional for skewed log sheets.

## B4. Semantic understanding strategy

A **Geotech-aware tender engineer / foundation designer / claim consultant** looks for:

- Insufficient investigation density vs footprint / structure type  
- Missing **groundwater** levels / seasonal variation  
- Aggressive soils / contamination not carried into specs/ER  
- Foundation recommendations mismatched to structural concept on drawings  
- Liquefaction / settlement / slope risks understated relative to location  
- Gaps between factual data and interpretive conclusions  
- Missing parameters needed for Contract risk allocation (unforeseen ground)  

Interpret engineering sufficiency — not keyword hits for “groundwater”.

## B5. Metadata extraction

- Report title, author firm, date, revision  
- Site coordinates / project name match  
- Number of boreholes / trial pits / lab tests  
- Groundwater observation dates  
- CDM subtype `geotech_report`

## B6. Entity extraction → ontology

| Extracted | Ontology |
|-----------|----------|
| Report | `Document` (`tender`, subtype geotech) |
| Borehole / TP | Location-linked investigation points (extend Location / new InvestigationPoint → Document) |
| Stratum / soil units | MaterialMention (geomaterial) |
| Groundwater observations | typed facts on Location / Project site node |
| Recommendations (foundation type) | Requirement / design constraint entities |
| Lab result tables | NormalizedTable |

## B7. Relationship extraction

- InvestigationPoint **located_in** Site/Location  
- Foundation Recommendation **constrains** Structure / Drawing foundation  
- Geotech risk **allocates_under** Contract unforeseen-ground clause  
- Parameter **supports** SpecSection (earthworks/foundation)  
- Addendum **updates** geotech interpretation (if issued)

## B8. Validation rules

| ID | Rule | Tag |
|----|------|-----|
| GEO-P01 | Min investigation count / coverage vs building footprint metadata when both present | **[PYTHON]** |
| GEO-P02 | Groundwater table present as structured fact or explicit “not encountered” flag | **[PYTHON]** |
| GEO-P03 | Lab tables parse with required columns for declared test types | **[PYTHON]** |
| GEO-P04 | Report date ≤ tender issue date (staleness flag if years apart — threshold config) | **[PYTHON]** |
| GEO-A01 | Investigation adequacy for proposed foundation system | **[AI]** |
| GEO-A02 | Interpretive conclusions weaker/stronger than data support | **[AI]** |
| GEO-A03 | Contamination / aggressivity implications for materials specs | **[AI]** |
| GEO-H01 | Python missing GW data → AI explains foundation/claim risk | **[HYBRID]** |
| GEO-H02 | Python foundation type on drawings ≠ recommended type table → AI explains redesign risk | **[HYBRID]** |

## B9. Cross-document validation

| Check | Against | Tag |
|-------|---------|-----|
| Foundation system on drawings vs geotech recommendations | Drawings / IFC | **[HYBRID]** |
| Earthworks/foundation BOQ vs expected ground model | BOQ | **[HYBRID]** |
| Unforeseen ground / differing site conditions clauses | Contract | **[AI]** |
| Spec material durability vs soil chemistry | Technical Specifications | **[AI]** |
| ER performance foundation criteria vs factual ground | Employer Requirements | **[AI]** |
| Schedule excavation season vs GW/weather | Schedule | **[AI]** |
| Addenda changing ground interpretation | Addenda | **[HYBRID]** |

## B10. Typical risk contribution

- **Claim risk:** very high (differing site conditions)  
- **Cost overrun:** very high  
- **Delay:** very high  
- **Quality:** high (foundation performance)  
- **Constructability:** very high  

## B11. Cause → effect examples

**Example 1 — No groundwater data**  
- **Cause:** Boreholes stop above expected formation; no piezometers.  
- **Effect:** Dewatering variations, delay, disputes.  
- **source_layer:** `hybrid`

**Example 2 — Pile vs raft mismatch**  
- **Cause:** Report recommends piles; structural drawings show shallow raft only.  
- **Effect:** Redesign, retender of foundations, cost/time blowout.  
- **source_layer:** `hybrid`

## B12. Finding output model

Cite borehole IDs / table refs; Related Standards only if geotech code bound (StandardClause lookup); Validation Evidence = counts/dates; `source_layer`; Missing Evidence = “no GW section”.

---

# C. EMPLOYER REQUIREMENTS (ER / Design Brief / Performance Brief)

## C1. Supported file formats

| Tier | Formats |
|------|---------|
| **Preferred** | Searchable PDF, DOCX |
| **Good** | Structured requirements Excel + narrative PDF |
| **Acceptable** | Scanned ER volumes |
| **Poor** | Slide-only briefs without normative language |
| **Unsupported** | Oral briefs with no record |

## C2. Extraction confidence

| Situation | Band |
|-----------|------|
| Searchable PDF/DOCX/Excel | **70–85** numeric |
| Vision/layout | **`pdf_drawing_vision` 35–55** |
| OCR | **`pdf_drawing_ocr` 20–45** |

## C3. OCR strategy

Same as specs/contracts: OCR if needed; layout + tables for room data sheets / performance matrices; reuse OCR package.

## C4. Semantic understanding strategy

An experienced **Employer’s agent / design-build tender reviewer / claim consultant** looks for:

- Performance requirements that are **unverifiable** or contradictory  
- Conflicts between ER and Contract/Specs (who designs what)  
- Missing functional programmes (areas, capacities, environmental targets)  
- Over-prescription that negates “Contractor design” while still allocating design risk to Contractor  
- Interface with operations/maintenance not thought through  
- Soft goals (“world-class”, “iconic”) without acceptance tests  
- Inconsistency with geotech/site constraints  

Understand intent vs enforceability.

## C5. Metadata extraction

- ER title, revision, project name, date  
- Design-build vs traditional role statement  
- Performance category list (energy, acoustics, capacity…)  
- CDM subtype `employer_requirements`

## C6. Entity extraction → ontology

| Extracted | Ontology |
|-----------|----------|
| ER document | `Document` |
| Numbered employer requirement | `Requirement` (source=employer) |
| Room/space programme | Room/Space + area requirements |
| Performance targets | Requirement with measurable attributes when explicit |
| Links to standards | toward StandardClause via citation resolution |

## C7. Relationship extraction

- Requirement **conflicts_with** ExtractedClause / SpecSection  
- Requirement **refined_by** SpecSection  
- Requirement **governed_by** StandardClause (lookup)  
- Space programme **depicts_on** Drawings  
- ER **allocates_design_to** Party (Contractor/Employer/Engineer)  

## C8. Validation rules

| ID | Rule | Tag |
|----|------|-----|
| ER-P01 | Requirements IDs unique; measurable fields present when unit declared | **[PYTHON]** |
| ER-P02 | Cited standard codes resolve to ProjectStandard bindings | **[PYTHON]** |
| ER-P03 | Area schedule sum vs declared total GFA (±tolerance) | **[PYTHON]** |
| ER-A01 | Unverifiable / vague performance language | **[AI]** |
| ER-A02 | Design responsibility contradiction with Contract | **[AI]** |
| ER-A03 | Soft aesthetic goals without acceptance criteria | **[AI]** |
| ER-A04 | Operational requirements missing for stated building use | **[AI]** |
| ER-H01 | Python GFA mismatch → AI explains briefing risk | **[HYBRID]** |
| ER-H02 | Python finds ER “Contractor designs all” + Contract “Employer retains design of X” → AI explains claim path | **[HYBRID]** |

## C9. Cross-document validation

| Check | Against | Tag |
|-------|---------|-----|
| ER vs Contract design responsibility | Contract | **[AI]** |
| ER vs Technical Specs consistency | Technical Specifications | **[AI]** |
| ER area/capacity vs Drawings/IFC spaces | Drawings | **[HYBRID]** |
| ER performance targets vs selected codes (StandardClause) | Standards | **[HYBRID]** |
| ER vs BOQ (performance items / provisional sums) | BOQ | **[AI]** |
| ER constraints vs Geotech feasibility | Geotechnical | **[AI]** |
| Addenda modifying ER | Addenda | **[HYBRID]** |

## C10. Typical risk contribution

- **Claim risk:** very high (design-build)  
- **Cost overrun:** high  
- **Delay:** high  
- **Quality:** very high  
- **Constructability:** high  

## C11. Cause → effect examples

**Example 1 — Unmeasurable “world-class”**  
- **Cause:** ER demands “world-class acoustic comfort” with no metrics.  
- **Effect:** Subjective rejection of design; delay; claims.  
- **source_layer:** `llm_based`

**Example 2 — Split design responsibility**  
- **Cause:** ER assigns full design to Contractor; Contract retains Employer design for façade.  
- **Effect:** Interface claims, delay, cost.  
- **source_layer:** `hybrid`

## C12. Finding output model

Requirement IDs quoted; Related Standards via StandardClause IDs; `source_layer`; Missing Evidence = “no acceptance test annex”.

---

# D. ADDENDA  
*(tender amendments, clarification bulletins, Q&A compilations that change the pack)*

## D1. Supported file formats

| Tier | Formats |
|------|---------|
| **Preferred** | Searchable PDF/DOCX clearly numbered Addendum 1..n |
| **Good** | Email PDF + revised replacement files |
| **Acceptable** | Scanned stamped addenda |
| **Poor** | Informal chat exports without numbering |
| **Unsupported** | Unrecorded oral clarifications |

## D2. Extraction confidence

| Situation | Band |
|-----------|------|
| Searchable PDF/DOCX | **70–85** numeric |
| Vision/layout | **`pdf_drawing_vision` 35–55** |
| OCR | **`pdf_drawing_ocr` 20–45** |

## D3. OCR strategy

OCR if scanned; layout for “delete/replace” instructions and change tables; table detection for Q&A; reuse OCR stack.

## D4. Semantic understanding strategy

A **Tender coordinator / contract manager** looks for:

- Whether addendum **supersedes** specific clauses/drawings/BOQ items clearly  
- Silent contradictions (addendum text vs unmarked old files still in pack)  
- Time extensions / closing date changes  
- Scope growth disguised as clarification  
- Binding force of Q&A answers  
- Cumulative impact of multiple addenda on price/time  
- Failure to re-issue consolidated pack  

Track **change operations** (insert/delete/replace) semantically against prior CDM versions.

## D5. Metadata extraction

- Addendum number, date, issuer  
- Affected document list  
- New closing date if any  
- Acknowledgment requirement  
- CDM subtype `addendum` / `clarification_bulletin`

## D6. Entity extraction → ontology

| Extracted | Ontology |
|-----------|----------|
| Addendum doc | `Document` |
| Change instruction | Requirement or ChangeOperation entity linked to target Document/Clause/BoqItem/DrawingSheet |
| Q&A pairs | content units + edges `clarifies` |
| Supersession | OntologyEdge `supersedes` / `amends` |

## D7. Relationship extraction

- Addendum **amends** Contract / Specs / BOQ / Drawings / ER / ITT  
- Addendum **supersedes** prior Addendum  
- Q&A **clarifies** Requirement  
- Addendum **extends** tender deadline  
- Acknowledgment Requirement **binds** bidder Party  

## D8. Validation rules

| ID | Rule | Tag |
|----|------|-----|
| AD-P01 | Addendum numbers unique and sequential gaps flagged | **[PYTHON]** |
| AD-P02 | Stated “replace drawing X rev A with rev B” → target IDs exist in project docs | **[PYTHON]** |
| AD-P03 | New closing date parseable and ≥ previous | **[PYTHON]** |
| AD-P04 | Acknowledgment form listed vs uploaded | **[PYTHON]** |
| AD-A01 | Scope change disguised as clarification | **[AI]** |
| AD-A02 | Ambiguous replace instructions (unclear target) | **[AI]** |
| AD-A03 | Cumulative commercial impact narrative across addenda | **[AI]** |
| AD-H01 | Python finds referenced sheet not uploaded → AI explains unequal information risk | **[HYBRID]** |
| AD-H02 | Python detects deadline change → AI assesses bid period fairness vs pack size | **[HYBRID]** |

## D9. Cross-document validation

| Check | Against | Tag |
|-------|---------|-----|
| Amendments vs Contract clause text still showing old wording in pack | Contract | **[HYBRID]** |
| BOQ item replacements reflected in BOQ file revision | BOQ | **[HYBRID]** |
| Drawing revision cloud vs addendum instructions | Drawings | **[PYTHON]** |
| Spec section replace vs specs files | Technical Specifications | **[HYBRID]** |
| ER changes consistency | Employer Requirements | **[AI]** |
| ITT deadline vs Addendum deadline | Tender Documents | **[PYTHON]** |
| Schedule update instructions followed | Schedule | **[HYBRID]** |
| Geotech clarification incorporated | Geotechnical | **[AI]** |
| Standard edition changes → re-bind StandardVersion (lookup, not re-parse whole library) | Standards | **[PYTHON]** |

## D10. Typical risk contribution

- **Claim risk:** high (unequal info, late scope)  
- **Cost overrun:** high  
- **Delay:** high (retender, rushed bids)  
- **Quality:** medium  
- **Constructability:** medium–high when drawings change late  

## D11. Cause → effect examples

**Example 1 — Replace drawing not in pack**  
- **Cause:** Addendum 3 replaces S-201 rev C; package still only has rev B.  
- **Effect:** Bidders price different scopes; disputes / retender.  
- **source_layer:** `hybrid`

**Example 2 — Clarification adds storey**  
- **Cause:** Q&A “confirms” an extra floor without BOQ/drawing update.  
- **Effect:** Massive underprice risk or non-comparable bids.  
- **source_layer:** `llm_based`

## D12. Finding output model

Addendum number + target IDs in Cross References; Validation Evidence = sequential number check, file presence matrix; `source_layer`; Missing Evidence = “rev C file absent”; Confidence Explanation per band.

---

## Catalogue complete — 10 document types

| # | Type | Part |
|---|------|------|
| 1 | Contract Documents | 2 |
| 2 | BOQ | 2 |
| 3 | Engineering Drawings | 2 |
| 4 | Tender Documents (ITT/forms) | 3 |
| 5 | Technical Specifications | 3 |
| 6 | Standards and Codes | 3 |
| 7 | Construction Schedule | 4 |
| 8 | Geotechnical Reports | 4 |
| 9 | Employer Requirements | 4 |
| 10 | Addenda | 4 |

---

## Deferred to Part 5

- Global Knowledge Graph consolidation  
- Risk Knowledge Base  
- Explainable AI / evidence UX patterns across all findings  

---

## One-line summary

**Schedule uses `schedule`; Geotech, ER, and Addenda stay under `tender` with subtypes — each with tagged [PYTHON]/[AI]/[HYBRID] validations and cross-checks into Parts 2–3 docs, without new categories or keyword engines.**
