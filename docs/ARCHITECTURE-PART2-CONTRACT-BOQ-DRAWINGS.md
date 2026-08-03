# TenderRisk AI — Architecture Part 2  
## Document Types (Batch 1): Contract · BOQ · Engineering Drawings

**Depends on:** [ARCHITECTURE-PART1-FOUNDATION.md](./ARCHITECTURE-PART1-FOUNDATION.md)  
**Status:** Design complete for Batch 1 document types (Contract · BOQ · Engineering Drawings).  
**Scope:** Full-depth analysis design for **three** document types only. Remaining types deferred.  
**Constraints:** No code / pseudocode. No keyword-as-intelligence. Reuse existing confidence bands only. Every validation in §§8–9 tagged `[PYTHON]` | `[AI]` | `[HYBRID]`.  
**Later seed alignment (non-blocking):** Seed rules `CON-SEED-*`, `BOQ-SEED-*`, `DRAW-SEED-*` instantiate subsets of §§8–9; this Part remains the design authority.

---

## 0. Category mapping (existing system)

| Document type (this part) | Existing `Document.category` | `CDM.subtype` (Part 1) | New category? |
|---------------------------|------------------------------|-------------------------|---------------|
| **Contract Documents** | **`tender`** | `contract` (also `general_conditions`, `particular_conditions`, `addendum` as refinements) | **No** |
| **Bill of Quantities (BOQ)** | **`tender`** | `boq` (also `gaeb_lv`, `fehrest_baha`, `excel_boq`) | **No** |
| **Engineering Drawings** | **`drawing`** | `drawing_sheet` \| `ifc_model` \| `cad_package` | **No** |

**Rationale:** Employer tender packs already upload contracts and BOQs under tender; drawings under drawing. Splitting categories would force API/UI migrations without analytical gain — subtype + CDM is enough.

**BREAKING CHANGE:** None. No new top-level category proposed.

**Shared Finding fields (all three types — §12 schema):**  
Finding Type · Severity · Confidence · `source_layer` (`rule_based` | `llm_based` | `hybrid`) · Source Document · Page · Paragraph · Exact Quotation · Reasoning · Cause · Effect · Business Impact · Recommendation · Cross References · Related Standards · Validation Evidence · Confidence Explanation · Missing Evidence.

---

# A. CONTRACT DOCUMENTS

## A1. Supported file formats

| Tier | Formats | Notes |
|------|---------|--------|
| **Preferred** | Searchable PDF (text layer), DOCX | Clean clauses, stable pagination |
| **Good** | PDF with mixed text + embedded images | Partial OCR |
| **Acceptable** | Scanned PDF (good dpi), DOC (legacy) | OCR required; review flag |
| **Poor** | Low-dpi scans, heavy stamps/signatures over text, photographed pages | High miss rate |
| **Unsupported** | Pure image galleries without OCR path, encrypted PDFs without password, audio/video | Reject or hold |

## A2. Extraction confidence (existing bands only)

| Situation | Band to apply |
|-----------|----------------|
| Native DOCX / searchable PDF text | Treat as high-quality text extract — **map operational confidence to upper half of `dxf_native` band for layout-stable text (70–85) when structure is clear; for fully native office text with clean paragraphs use 85 capped by product policy — *do not invent a new named band*; store numeric score inside existing envelope while `method` stays e.g. `docx_native` / `pdf_searchable` mapped to nearest published band for UI: prefer reporting **70–85** for structured office, and **20–45 (`pdf_drawing_ocr`)** when OCR-dominated** |
| OCR-heavy contract PDF | **`pdf_drawing_ocr` 20–45** |
| Vision-assisted layout on scans | **`pdf_drawing_vision` 35–55** |

*Clarification:* Named bands in the product are drawing/CAD-centric by history. For contracts, **reuse the same numeric bands** for Risk Engine weighting: searchable/native prose → score in **70–85**; OCR → **20–45**; vision layout assist → **35–55**. Do not create `contract_native`.

## A3. OCR strategy

- Prefer **existing** `ocr/classifier` + `DocumentPipeline` for PDFs.  
- OCR **only** when page kind ≠ searchable.  
- **Layout analysis:** required for clause numbering, headers, annexes (NEW stage on CDM — Part 1).  
- **Table detection:** yes for payment schedules, LD tables, milestones embedded in contract.  
- **Drawing OCR / vision AI:** only for stamped scanned packs; optional vision for reading-order recovery — not for inventing clause meaning.  
- Reuse Tesseract fa/de/eng + RapidOCR; no parallel OCR stack.

## A4. Semantic understanding strategy (engineer mindset)

An experienced **Contract Manager / Claim Consultant** reads for:

- Ambiguous allocation of **design / construction / site** responsibility  
- Undefined or circular **defined terms**  
- **Conflicts** between General Conditions, Particular Conditions, and annexes  
- **Claim triggers:** notice periods, time bars, condition precedents  
- **Payment risks:** retention, payment timelines, set-off, measurement basis  
- **Delay / EOT:** concurrent delay, float ownership, force majeure scope  
- **Change / variation** order mechanics and pricing rules  
- Unfair or one-sided **termination / suspension** rights  
- Gaps vs **governing law / dispute** forum clarity  
- Interface with **BOQ / drawings / specs** (“documents hierarchy” / order of precedence)

Understanding is structural + semantic (obligation modality, party roles), **not** word lists.

## A5. Metadata extraction

- Document title, revision/amendment ID, issue date  
- Parties named (Employer, Engineer, Contractor if present)  
- Contract form family hint (FIDIC/VOB/CCDC/Iran PCC — from structure, not keyword bingo)  
- Language(s), page count, annex list  
- Precedence clause presence (boolean + pointer)  
- CDM: `subtype`, `identity.*`, language

## A6. Entity extraction → Part 1 ontology

| Extracted | Ontology |
|-----------|----------|
| Parties | `Party` (employer / engineer / contractor) |
| Agreement body | `ContractPackage` ← linked `Document` |
| Numbered obligations | `ExtractedClause` |
| Defined terms | attributes on clauses / term glossary on package |
| Payment / LD / milestone tables | `NormalizedTable` + later typed money entities |
| References to drawings/BOQ/specs | unresolved `links_out` → edges |

## A7. Relationship extraction

- Clause **conflicts_with** / **amends** Clause  
- Clause **references** DrawingSheet / BoqItem / SpecSection (when resolvable)  
- Clause **governed_by** StandardClause (edition-bound — later standards part)  
- ContractPackage **includes** Document (GC, PC, forms)  
- Requirement **derived_from** ExtractedClause  

## A8. Validation rules (each tagged)

| ID | Rule | Tag |
|----|------|-----|
| C-P01 | Detect missing order-of-precedence / document hierarchy section via structure (TOC/heading model) | **[PYTHON]** |
| C-P02 | Detect undefined cross-references (clause cites annex/drawing ID not present in package file set) | **[PYTHON]** |
| C-P03 | Flag empty mandatory annex slots declared in TOC but zero pages/files | **[PYTHON]** |
| C-P04 | Notice-period numeric consistency (same period cited differently in two tables — arithmetic/compare) | **[PYTHON]** |
| C-A01 | Ambiguous responsibility for design vs build vs site information | **[AI]** |
| C-A02 | Claim time-bar / condition-precedent harshness and hidden traps | **[AI]** |
| C-A03 | Payment / retention / set-off imbalance vs local market norms (reasoning, not statute invent) | **[AI]** |
| C-A04 | Concurrent delay / float ownership ambiguity | **[AI]** |
| C-A05 | Variation pricing rules incomplete or circular | **[AI]** |
| C-H01 | Python finds conflicting numeric LD rates across exhibits → AI explains claim exposure | **[HYBRID]** |
| C-H02 | Python finds GC vs PC clause number collision → AI interprets which likely prevails and risk | **[HYBRID]** |
| C-H03 | Python detects missing termination-for-convenience clause where form usually has one → AI assesses gap | **[HYBRID]** |

## A9. Cross-document validation

| Check | Against | Tag |
|-------|---------|-----|
| Scope of works in contract vs BOQ item coverage | BOQ | **[HYBRID]** |
| Contract drawing list vs uploaded drawing set | Drawings | **[PYTHON]** |
| Contract duration / milestones vs schedule (when present) | Schedule *(later type; stub interface)* | **[HYBRID]** |
| Measurement / payment basis vs BOQ method of measurement | BOQ | **[AI]** |
| Spec references in contract vs specs pack | Specs *(later)* | **[HYBRID]** |
| Precedence vs actual conflicting texts across tender docs | BOQ + Drawings + Specs | **[AI]** |
| Standards cited in contract vs ProjectStandard selection | Standards catalog | **[PYTHON]** |

## A10. Typical risk contribution

- **Claim risk:** high (notice, EOT, variations)  
- **Cost overrun:** high (payment, variations, LD asymmetry)  
- **Delay:** high (EOT mechanics, possession, approvals)  
- **Quality:** medium (standards of care, defects liability drafting)  
- **Constructability:** low–medium (unless design-responsibility ambiguity)

## A11. Cause → effect examples (≥2)

**Example 1 — Ambiguous design responsibility**  
- **Cause:** Particular Conditions assign “design of temporary works” vaguely between Contractor and Engineer without deliverable list.  
- **Effect:** Disputes at site, stoppages, variation claims; Employer absorbs delay/cost.  
- **Finding type:** Claim / Responsibility ambiguity · **Severity:** High · **source_layer:** `llm_based` or `hybrid`

**Example 2 — Conflicting notice periods**  
- **Cause:** GC requires 14-day notice; PC exhibit table states 7 days for same event class.  
- **Effect:** Time-bar fights; Contractor claims waiver; Employer defense weak.  
- **Finding type:** Contract conflict · **Severity:** High · **source_layer:** `hybrid` (Python conflict detect + AI impact)

## A12. Finding output model (Contract)

Populate all shared fields; Contract-specific emphasis:

- **Exact Quotation:** cited clause text  
- **Page / Paragraph:** CDM content_unit pointers  
- **Related Standards:** only if contract cites them  
- **Validation Evidence:** clause IDs, annex presence matrix  
- **Confidence Explanation:** tied to extraction band (searchable vs OCR)  
- **Missing Evidence:** e.g. “Particular Conditions PDF not uploaded”

---

# B. BILL OF QUANTITIES (BOQ)

## B1. Supported file formats

| Tier | Formats |
|------|---------|
| **Preferred** | **GAEB DA XML** (`.X81`–`.X86`, XML `.D8x`), structured Excel with clear headers |
| **Good** | Searchable PDF BOQ with consistent tables; Fehrest-style Excel (IR) |
| **Acceptable** | OCR’d PDF tables (clean grid), CSV exports |
| **Poor** | Merged cells chaos, scanned handwritten quantities, images of BOQ |
| **Unsupported** | GAEB 90 fixed-width without converter (Phase-2), proprietary locked estimating DBs |

## B2. Extraction confidence (existing bands only)

| Source | Band |
|--------|------|
| GAEB native parse | **`gaeb_native` 90–98** |
| Structured Excel/CSV (native cells) | Use **70–85** numeric weighting (same as structured native text policy in A2 — no new named band) |
| PDF table extract / good layout | **`pdf_drawing_vision` 35–55** if vision/layout table; else searchable text **70–85** |
| OCR table from scan | **`pdf_drawing_ocr` 20–45** |

## B3. OCR strategy

- **GAEB / Excel / CSV:** no OCR — native parsers (`gaeb_extractor`, openpyxl).  
- **PDF BOQ:** table extraction first; OCR only if not searchable.  
- Layout + table detection critical.  
- Drawing OCR not applicable. Vision AI optional for table border recovery on scans.  
- Reuse existing OCR pipeline for PDF pages only.

## B4. Semantic understanding strategy

A **Cost Engineer / Quantity Surveyor / Claim Consultant** looks for:

- Incomplete trade coverage vs project type  
- Ambiguous **unit / measurement** rules  
- Provisional sums / contingencies without governance  
- Duplicate or overlapping positions  
- Missing preliminaries / temporary works  
- Descriptions that don’t match drawing/spec intent  
- Unbalanced rates risk (if prices present)  
- Quantity realism vs model/drawing scale (order-of-magnitude)  
- Change-order vulnerability from vague long text  

Meaning of **work description** and **measurement intent**, not string search for “m2”.

## B5. Metadata extraction

- BOQ title, currency, revision, date  
- GAEB: `source_version`, `exchange_phase`, `grand_total`  
- Hierarchy depth (lot / category / item)  
- Whether unit prices present (bid vs tender blank)  
- Method of measurement reference if stated  
- CDM subtype `boq` / `gaeb_lv` / …

## B6. Entity extraction → ontology

| Extracted | Ontology |
|-----------|----------|
| Position / OZ / line | `BoqItem` |
| Category / trade | hierarchy on `BoqItem` / parent nodes |
| Qty, unit, unit_price, total | fields on `BoqItem` |
| Long/short text | content linked to item |
| Material mentions in description | `MaterialMention` |
| Document | `Document` category `tender` |

## B7. Relationship extraction

- BoqItem **quantifies** work described in SpecSection / Drawing  
- BoqItem **conflicts_with** BoqItem (overlap)  
- BoqItem **references** DrawingSheet / Level  
- Sum(items) **reconciles_to** grand_total (deterministic)  
- BoqItem **governed_by** measurement standard / StandardClause (later)

## B8. Validation rules

| ID | Rule | Tag |
|----|------|-----|
| B-P01 | Item count > 0; required fields qty+unit present rate | **[PYTHON]** |
| B-P02 | Grand total vs sum of item totals (tolerance) | **[PYTHON]** |
| B-P03 | Duplicate OZ / codes | **[PYTHON]** |
| B-P04 | Invalid / empty units normalized set check | **[PYTHON]** |
| B-P05 | GAEB validation_results ERROR severity surfaced | **[PYTHON]** |
| B-A01 | Description ambiguity / unmeasurable work | **[AI]** |
| B-A02 | Missing trade packages vs project typology expectations | **[AI]** |
| B-A03 | Provisional sum / contingency governance gaps | **[AI]** |
| B-A04 | Overlap between positions (same work twice) | **[AI]** |
| B-H01 | Python flags extreme qty outliers vs peers → AI assesses realism vs drawings | **[HYBRID]** |
| B-H02 | Python finds zero-qty priced items → AI explains bid manipulation / claim risk | **[HYBRID]** |

## B9. Cross-document validation

| Check | Against | Tag |
|-------|---------|-----|
| BOQ trades/items vs IFC element discipline counts / drawing disciplines | Drawings / IFC | **[HYBRID]** |
| BOQ descriptions vs contract scope / measurement clauses | Contract | **[AI]** |
| Quantities vs schedule productivity assumptions (when schedule exists) | Schedule | **[HYBRID]** |
| Items citing standards vs selected ProjectStandards | Standards | **[PYTHON]** |
| Drawing references in item text vs uploaded sheets | Drawings | **[PYTHON]** |

## B10. Typical risk contribution

- **Claim risk:** very high (measurement disputes)  
- **Cost overrun:** very high  
- **Delay:** medium–high (re-measure, missing preliminaries)  
- **Quality:** medium (underspecified finishes)  
- **Constructability:** medium (missing temporary works / access items)

## B11. Cause → effect examples

**Example 1 — GAEB vs drawings discipline gap**  
- **Cause:** Many electrical positions in LV; IFC/drawings show negligible electrical elements / no E sheets.  
- **Effect:** Either drawings incomplete or BOQ padded → tender inequity, post-award claim.  
- **source_layer:** `hybrid`

**Example 2 — Ambiguous measurement**  
- **Cause:** Wall finish item lacks substrate/height measurement rule while specs conflict.  
- **Effect:** Remeasurement claims; cost overrun.  
- **source_layer:** `llm_based` or `hybrid`

## B12. Finding output model (BOQ)

Emphasize: BoqItem codes in Cross References; Validation Evidence = totals math, duplicate OZ list; Confidence Explanation cites `gaeb_native` vs OCR band; Missing Evidence = “no drawings uploaded for cross-check”.

---

# C. ENGINEERING DRAWINGS

## C1. Supported file formats

| Tier | Formats |
|------|---------|
| **Preferred** | **IFC**, **DXF** (text/layers intact) |
| **Good** | DWG (with harvest or ODA→DXF), sheet PDFs searchable |
| **Acceptable** | Revit export harvest (`.rvt`), scanned drawing PDFs high dpi |
| **Poor** | Flattened image-only PDFs low dpi, huge RVT without useful strings |
| **Unsupported** | Proprietary locked viewers only, video walkthroughs as sole deliverable |

## C2. Extraction confidence (existing bands only)

| Source | Band |
|--------|------|
| IFC metadata/properties | **`ifc_native` 90–98** |
| DXF layers/TEXT | **`dxf_native` 70–85** |
| DWG harvest / ODA path | **`dwg_harvest` 40–60** |
| Revit harvest | **`rvt_harvest` 40–60** |
| PDF drawing vision/layout | **`pdf_drawing_vision` 35–55** |
| PDF drawing OCR | **`pdf_drawing_ocr` 20–45** |

## C3. OCR strategy

- **IFC / DXF / DWG / RVT:** no OCR; native/harvest modules (`ifc_extractor`, `cad_extractor`).  
- **PDF sheets:** classifier → OCR only if scanned; layout for title block; optional vision for sheet ID / stamp regions.  
- Reuse existing OCR package; never mesh IFC for analysis.

## C4. Semantic understanding strategy

A **Tender Engineer / Constructability reviewer** looks for:

- Incomplete discipline set (arch/struct/MEP) for project type  
- Missing levels/grids/fire strategy indications where expected  
- Title block revision chaos / superseded sheets  
- Conflicts between architectural and structural extents  
- Spec/BOQ references on sheets that don’t resolve  
- Constructability: access, temporary works cues, under-detailed junctions  
- Compliance hints (fire rating properties in IFC Psets vs selected fire standards) — semantic alignment, not keyword hit  

## C5. Metadata extraction

- Sheet ID, title, revision, date, scale, discipline  
- IFC: schema, project/site/building/storey names, element counts by discipline, fire/material/load Pset highlights  
- DXF: layer list, block names  
- Package completeness stats (sheet count, disciplines present)  
- CDM spatial summary

## C6. Entity extraction → ontology

| Extracted | Ontology |
|-----------|----------|
| Sheet / model file | `Document` + `DrawingSheet` / `ModelRoot` |
| Levels / storeys | `Level` |
| Grids | `Grid` |
| Spaces / rooms | `Room` / Space nodes |
| Walls/slabs/MEP counts | structure/MEP entities or counted `element_counts` |
| Materials / fire ratings | `MaterialMention` + property highlights |
| Title-block revision | metadata on DrawingSheet |

## C7. Relationship extraction

- DrawingSheet **supersedes** DrawingSheet (revision)  
- DrawingSheet **depicts** Level / Space  
- IFC element **satisfies_property** Requirement / StandardClause (later)  
- Drawing **referenced_by** Contract / BoqItem / Spec  
- Discipline package **completeness_of** Project typology expectation  

## C8. Validation rules

| ID | Rule | Tag |
|----|------|-----|
| D-P01 | At least one drawing/model document present when project rules require | **[PYTHON]** |
| D-P02 | IFC/DXF parse success; element_count / layer_count thresholds | **[PYTHON]** |
| D-P03 | Duplicate sheet IDs different revisions without supersede link | **[PYTHON]** |
| D-P04 | Listed sheet index (from contract) minus uploaded set = missing list | **[PYTHON]** |
| D-P05 | IFC fire-rating Pset present/absent counts when fire standard selected | **[PYTHON]** |
| D-A01 | Constructability / under-detail risk from sheet content narrative | **[AI]** |
| D-A02 | Arch vs struct extent inconsistency (semantic) | **[AI]** |
| D-A03 | Discipline package adequacy for project type | **[AI]** |
| D-H01 | Python missing E-sheets vs BOQ electrical density → AI explains tender risk | **[HYBRID]** |
| D-H02 | Python IFC storey count vs schedule/building description mismatch → AI impact | **[HYBRID]** |

## C9. Cross-document validation

| Check | Against | Tag |
|-------|---------|-----|
| Sheet list vs contract drawing schedule | Contract | **[PYTHON]** |
| Discipline coverage vs BOQ trades | BOQ | **[HYBRID]** |
| Fire/property cues vs selected standards | Standards | **[HYBRID]** |
| Room/area cues vs BOQ area items | BOQ | **[HYBRID]** |
| Grid/level naming consistency vs specs | Specs *(later)* | **[AI]** |

## C10. Typical risk contribution

- **Claim risk:** high (scope/detail gaps)  
- **Cost overrun:** high  
- **Delay:** high (RFIs, redesign)  
- **Quality:** high  
- **Constructability:** very high  

## C11. Cause → effect examples

**Example 1 — Missing discipline package**  
- **Cause:** Architectural IFC/PDF only; no structural drawings while BOQ has extensive concrete.  
- **Effect:** Unpriced risk, redesign, delay, claims.  
- **source_layer:** `hybrid`

**Example 2 — Fire rating gap**  
- **Cause:** Fire standard selected; IFC walls lack FireRating Psets and no fire drawings uploaded.  
- **Effect:** Compliance / variation risk post-award.  
- **source_layer:** `hybrid`

## C12. Finding output model (Drawings)

Emphasize: sheet IDs, IFC GlobalIds in Validation Evidence; Confidence Explanation must state band (`ifc_native` vs `pdf_drawing_ocr`); Missing Evidence lists absent disciplines/sheets.

---

## Shared §12 field dictionary (normative for Part 2 findings)

| Field | Meaning |
|-------|---------|
| Finding Type | Taxonomy: conflict, omission, ambiguity, compliance, constructability, commercial, … |
| Severity | high / medium / low (existing enum) |
| Confidence | 0–100, informed by extraction band + rule strength |
| source_layer | `rule_based` (=PYTHON) · `llm_based` (=AI) · `hybrid` |
| Source Document | `Document.id` / name |
| Page | page/sheet index if any |
| Paragraph | content_unit id / clause no / OZ |
| Exact Quotation | verbatim excerpt |
| Reasoning | why this is a tender risk |
| Cause | root condition in documents |
| Effect | likely project outcome |
| Business Impact | cost / time / claim / quality narrative |
| Recommendation | actionable employer-side fix before award |
| Cross References | other docs / entity IDs |
| Related Standards | ProjectStandard / StandardClause ids |
| Validation Evidence | deterministic artifacts (diffs, counts, totals) |
| Confidence Explanation | band + what limited certainty |
| Missing Evidence | what file/field would raise confidence |

Map to existing `Finding` row + additive JSON (Part 1) — **not** a parallel findings system.

---

## Cross-type priority interactions (summary)

```text
Contract  ←→  BOQ       scope, measurement, money
Contract  ←→  Drawings  sheet lists, design responsibility
BOQ       ←→  Drawings  quantities, disciplines, references
```

All three feed one Risk Engine; extraction confidence **down-weights** AI claims when band is OCR/harvest.

---

## Deferred

Specs, Schedule, Reports, Correspondence, Geotech, Method Statements, Standards deep application — later parts.

---

## One-line summary

**Keep Contract & BOQ under `tender` and Drawings under `drawing`; analyze each with CDM + ontology; validate only with tagged [PYTHON]/[AI]/[HYBRID] rules; weight evidence by existing IFC/GAEB/DXF/OCR confidence bands — no new categories, no keyword engine.**
