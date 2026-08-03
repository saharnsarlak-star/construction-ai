# TenderRisk AI — Architecture Part 3  
## Document Types (Batch 2): Tender Documents · Technical Specifications · Standards and Codes

**Depends on:**  
- [ARCHITECTURE-PART1-FOUNDATION.md](./ARCHITECTURE-PART1-FOUNDATION.md)  
- [ARCHITECTURE-PART2-CONTRACT-BOQ-DRAWINGS.md](./ARCHITECTURE-PART2-CONTRACT-BOQ-DRAWINGS.md)  

**Status:** Design complete for Batch 2 document types (Tender Documents · Technical Specifications · Standards and Codes).  
**Scope:** Full-depth (same 12 sections as Part 2) for **three** types only.  
**Deferred:** Schedule, Geotechnical Reports, Employer Requirements, Addenda.  
**Constraints:** No code/pseudocode. No keyword-as-intelligence. Existing confidence bands only. §§8–9 fully tagged. Ontology/pipeline from Part 1 unchanged.  
**Standards invariant:** StandardClause / StandardVersion / StandardVersionDiff / per-project edition binding — **integrate, never redesign**. Parse once at library ingestion; Analyze only looks up.  
**Later seed alignment:** `TEN-SEED-*`, `SPEC-SEED-*`, `STD-SEED-*` instantiate subsets of §§8–9.

---

## 0. Category mapping

| Document type | Existing `Document.category` | `CDM.subtype` examples | New category? |
|---------------|------------------------------|------------------------|---------------|
| **Tender Documents** (ITT / invitation pack, instructions to tenderers, forms, bid data — *excluding* dedicated Contract/BOQ files already in Part 2) | **`tender`** | `itt`, `instructions_to_tenderers`, `bid_form`, `tender_data`, `procurement_notice` | **No** |
| **Technical Specifications** | **`tender`** (uploaded with tender pack) *or* custom file under same bucket | `specs`, `particular_specs`, `method_specs` | **No** |
| **Standards and Codes** | **`standard`** (project upload of custom/local code PDF) **plus** catalog selection via **`ProjectStandard`** (not always a file) | `catalog_standard`, `uploaded_standard_pdf` | **No** |

**Separation of concerns vs Part 2:**  
- Part 2 **Contract** = agreement conditions (GC/PC).  
- Part 3 **Tender Documents** = procurement envelope (how to bid, forms, ITB, evaluation criteria, submission rules).  
- Both share category `tender`; distinguished by **CDM.subtype** + classification stage (Part 1).

**Standards dual path (critical):**  
1. **Catalog standards** — selected on project (`ProjectStandard`); text lives in persistent **StandardClause** store bound to **StandardVersion**.  
2. **Uploaded standard files** — `Document.category = standard`; parsed **once** into StandardClause/version pipeline when first ingested into the platform library (or linked), **not** re-parsed on every project analyze.

**BREAKING CHANGE:** None.

**Shared Finding fields:** same normative dictionary as Part 2 §12 (including `source_layer`).

---

# A. TENDER DOCUMENTS  
*(ITT / Instructions to Tenderers / forms / bid data — procurement envelope)*

## A1. Supported file formats

| Tier | Formats |
|------|---------|
| **Preferred** | Searchable PDF, DOCX |
| **Good** | Mixed PDF (text + forms), XLSX for bid schedules / price forms |
| **Acceptable** | Scanned PDF (good dpi), DOC |
| **Poor** | Image-only low-dpi packs, photographed forms |
| **Unsupported** | Portal-only content with no export, encrypted without credentials |

## A2. Extraction confidence (existing bands only)

| Situation | Band |
|-----------|------|
| Searchable PDF / DOCX / XLSX forms | Numeric weight **70–85** (structured native text policy — same as Part 2 contracts; no new named band) |
| Vision/layout-assisted form recovery | **`pdf_drawing_vision` 35–55** |
| OCR-dominated scans | **`pdf_drawing_ocr` 20–45** |

## A3. OCR strategy

- Reuse `ocr/classifier` + `DocumentPipeline`.  
- OCR only when not searchable.  
- **Layout analysis:** yes (headers, form fields, evaluation tables).  
- **Table detection:** yes (submission checklist, evaluation criteria weights, bid bond tables).  
- Drawing OCR: no. Vision AI: optional for checkbox/form geometry on scans.

## A4. Semantic understanding strategy

An experienced **Tender / Procurement lead** reads for:

- Unclear **submission requirements** (copies, seals, e-bid vs paper)  
- **Evaluation criteria** that are vague, conflicting, or non-measurable  
- Hidden **disqualification** traps  
- Inconsistency between ITT and Contract/BOQ on scope or pricing basis  
- Unrealistic **tender timelines** vs document volume  
- Bid bond / guarantee rules that create unfair barriers or ambiguity  
- Clarification / addendum process gaps (who may ask, binding answers)  
- Confidentiality / IP rules affecting design-build tenders  
- Alternative offers / partial bids allowed or forbidden — clarity  

Understanding = procedural + commercial fairness semantics, not word spotting.

## A5. Metadata extraction

- Tender / ITT title, reference number, issue date, closing date/time, timezone  
- Employer / procuring entity names  
- Submission mode (electronic/physical), language of bid  
- Evaluation method stated (lowest price, QCBS, etc.) — as structured fields when explicit  
- List of required forms / attachments  
- CDM subtype `itt` / `instructions_to_tenderers` / …

## A6. Entity extraction → ontology

| Extracted | Ontology |
|-----------|----------|
| Procuring entity | `Party` (employer / procuring_entity) |
| Tender envelope doc | `Document` + optional `ContractPackage`-adjacent **TenderPackage** node *or* tag on Project (prefer Project + Document links — no parallel project) |
| Instructions / rules as units | `ExtractedClause` (procedural clauses) or `Requirement` (submission requirements) |
| Forms / mandatory attachments | Requirements + `links_out` to expected filenames |
| Evaluation criteria rows | `NormalizedTable` + Requirement entities |
| Dates / deadlines | typed metadata on Document / Project |

## A7. Relationship extraction

- Requirement **requires_document** (form X)  
- ITT clause **conflicts_with** Contract clause / BOQ instruction  
- Deadline **constrains** Schedule of tender process (meta)  
- Evaluation criterion **weights** another criterion (table relations)  
- Clarification process **amends** TenderPackage (when addenda exist — Part 4)

## A8. Validation rules

| ID | Rule | Tag |
|----|------|-----|
| T-P01 | Closing datetime parseable and in the future relative to issue date | **[PYTHON]** |
| T-P02 | Mandatory forms list vs uploaded tender attachments checklist completeness | **[PYTHON]** |
| T-P03 | Evaluation weight column sums to 100% (±tolerance) when numeric weights present | **[PYTHON]** |
| T-P04 | Duplicate form IDs / contradictory copy-count integers across sections | **[PYTHON]** |
| T-A01 | Evaluation criteria vagueness / non-measurability | **[AI]** |
| T-A02 | Hidden disqualification or unfair procedural burden | **[AI]** |
| T-A03 | Conflict between ITT pricing instructions and Contract/BOQ measurement narrative | **[AI]** |
| T-A04 | Tender period adequacy vs document set size/complexity | **[AI]** |
| T-H01 | Python finds missing mandatory form file → AI explains disqualification risk | **[HYBRID]** |
| T-H02 | Python finds weight sum ≠ 100 → AI assesses evaluation dispute risk | **[HYBRID]** |

## A9. Cross-document validation

| Check | Against | Tag |
|-------|---------|-----|
| ITT scope / pricing basis vs Contract | Contract | **[AI]** |
| ITT BOQ instructions vs BOQ structure | BOQ | **[HYBRID]** |
| Required drawing list in ITT vs uploaded drawings | Drawings | **[PYTHON]** |
| Cited standards in ITT vs ProjectStandard selection | Standards | **[PYTHON]** |
| Spec pack completeness vs ITT annex list | Technical Specifications | **[PYTHON]** |
| Addenda acknowledgment rules vs issued addenda (Part 4) | Addenda | **[HYBRID]** |

## A10. Typical risk contribution

- **Claim risk:** medium–high (procedural disputes, evaluation challenges)  
- **Cost overrun:** medium (wrong bid basis → change orders later)  
- **Delay:** high (failed tender, retender, clarification storms)  
- **Quality:** low–medium  
- **Constructability:** low (unless design-build ITB poorly framed)

## A11. Cause → effect examples

**Example 1 — Non-measurable evaluation**  
- **Cause:** QCBS “methodology” criterion has no scoring rubric.  
- **Effect:** Award challenges, retender delay, political/legal exposure for Employer.  
- **source_layer:** `llm_based`

**Example 2 — Missing mandatory form**  
- **Cause:** ITT lists Form C as mandatory; package has no Form C file.  
- **Effect:** All bids non-compliant or unequal; tender failure.  
- **source_layer:** `hybrid`

## A12. Finding output model

All shared fields; emphasize deadlines in Validation Evidence; `source_layer`; Missing Evidence = absent forms; Confidence Explanation tied to OCR vs searchable band.

---

# B. TECHNICAL SPECIFICATIONS

## B1. Supported file formats

| Tier | Formats |
|------|---------|
| **Preferred** | Searchable PDF, DOCX with numbered sections |
| **Good** | Multi-volume searchable PDF set |
| **Acceptable** | Scanned specs (high dpi), Excel performance schedules |
| **Poor** | Image scans, unsearchable compilations |
| **Unsupported** | Specs only as undownloadable web pages |

## B2. Extraction confidence

| Situation | Band |
|-----------|------|
| Searchable PDF / DOCX | **70–85** numeric (native text policy) |
| Vision/layout section recovery | **`pdf_drawing_vision` 35–55** |
| OCR scans | **`pdf_drawing_ocr` 20–45** |

## B3. OCR strategy

- Same OCR stack as contracts; OCR if needed.  
- **Layout analysis:** essential (division/section/part numbering).  
- **Table detection:** yes (performance criteria, material schedules, tolerances).  
- Drawing OCR: only if specs embed detail drawings as images.  
- Vision: optional for column layouts in scanned volumes.

## B4. Semantic understanding strategy

A **Spec writer / Technical tender reviewer / Claim consultant** looks for:

- Underspecified **performance vs prescriptive** mix that invites claims  
- Conflicts between divisions (e.g. finishes vs structural tolerances)  
- Orphan references to drawings/standards/BOQ items  
- Missing testing / commissioning / handover criteria  
- Unclear **submittal** / approval timelines  
- Materials allowed lists vs “or equal” ambiguity  
- Interfaces between trades not specified  
- Inconsistency with Contract quality regime and selected codes  

Semantic parse of obligations, acceptance criteria, and interfaces — not keyword lists of material names.

## B5. Metadata extraction

- Spec title, volume/division IDs, revision, date  
- MasterFormat / local division scheme if detectable from structure  
- Language(s), page counts per volume  
- Referenced standard codes list (as citations — resolution via Standards store)  
- CDM subtype `specs`

## B6. Entity extraction → ontology

| Extracted | Ontology |
|-----------|----------|
| Spec document | `Document` |
| Division / section | `SpecSection` |
| Normative requirements in prose | `Requirement` linked to SpecSection |
| Material / product requirements | `MaterialMention` / Equipment |
| References to drawings / BOQ | `links_out` → edges |
| Citations to codes | links toward `StandardClause` / StandardVersion (lookup, not re-parse) |

## B7. Relationship extraction

- SpecSection **references** DrawingSheet / BoqItem  
- Requirement **governed_by** StandardClause (via citation resolution to bound edition)  
- SpecSection **conflicts_with** SpecSection  
- SpecSection **amplifies** ExtractedClause (contract quality clauses)  
- MaterialMention **specified_in** SpecSection  

## B8. Validation rules

| ID | Rule | Tag |
|----|------|-----|
| S-P01 | Section numbering continuity / broken TOC vs body | **[PYTHON]** |
| S-P02 | Citation strings resolve to a ProjectStandard-selected code (presence check) | **[PYTHON]** |
| S-P03 | Drawing/BOQ IDs cited in specs exist in uploaded sets | **[PYTHON]** |
| S-P04 | Empty required divisions declared in TOC | **[PYTHON]** |
| S-A01 | Ambiguous acceptance / testing criteria | **[AI]** |
| S-A02 | Prescriptive vs performance conflict inside section | **[AI]** |
| S-A03 | Trade interface gaps | **[AI]** |
| S-A04 | “Or equal” / proprietary product lock-in risk | **[AI]** |
| S-H01 | Python unresolved standard citation → AI explains compliance/claim risk | **[HYBRID]** |
| S-H02 | Python detects tolerance numbers conflicting across sections → AI interprets constructability impact | **[HYBRID]** |

## B9. Cross-document validation

| Check | Against | Tag |
|-------|---------|-----|
| Spec requirements vs Contract quality / defects clauses | Contract | **[AI]** |
| Spec measurement language vs BOQ descriptions | BOQ | **[AI]** |
| Spec drawing refs vs drawing set | Drawings | **[PYTHON]** |
| Spec citations vs **StandardClause** content of **bound StandardVersion** | Standards and Codes | **[HYBRID]** — Python retrieves clauses; AI judges adequacy/conflict |
| Spec fire/acoustic/energy topics vs selected standards topics | Standards | **[HYBRID]** |
| Spec commissioning vs schedule logic (Part 4) | Schedule | **[AI]** |

## B10. Typical risk contribution

- **Claim risk:** high  
- **Cost overrun:** high  
- **Delay:** high (submittals, rework)  
- **Quality:** very high  
- **Constructability:** high  

## B11. Cause → effect examples

**Example 1 — Unresolved code citation**  
- **Cause:** Specs cite a standard edition not in ProjectStandard binding / not in clause store.  
- **Effect:** Compliance vacuum; post-award variation.  
- **source_layer:** `hybrid`

**Example 2 — Conflicting tolerances**  
- **Cause:** Architectural finishes require flatness tighter than structural slab spec allows.  
- **Effect:** Rework, delay, claims between trades / against Employer docs.  
- **source_layer:** `hybrid`

## B12. Finding output model

Quote SpecSection IDs; Related Standards = StandardVersion + StandardClause IDs; Validation Evidence = citation resolution table; `source_layer` mandatory.

---

# C. STANDARDS AND CODES

## C0. Integration with prior persistent model (do not redesign)

| Prior concept | Role in Part 3 |
|---------------|----------------|
| **StandardVersion** | Immutable edition identity (e.g. NBR 3 / 1392, DIN edition year) |
| **StandardVersionDiff** | Lifecycle diff when editions change |
| **StandardClause** | Persistent parsed clause graph for an edition — **parsed once at library ingestion**, reused across all projects |
| **Per-project version binding** | Project pins selected `ProjectStandard` → specific **StandardVersion** |
| **ProjectStandard** | Which standards apply + selection source (system/user) |

**Per-project Analyze never re-parses the full standard PDF into clauses.** It **looks up** StandardClause records for the bound StandardVersion and compares them to project CDM/ontology (specs, contract, IFC properties, etc.).

Uploaded `Document.category = standard` (custom/local PDF) enters the **same** ingestion path: classify → normalize → **one-time** clause parse → persist StandardVersion/StandardClause → then projects only bind.

## C1. Supported file formats

| Tier | Formats |
|------|---------|
| **Preferred** | Structured digital editions already in catalog; searchable PDF for new uploads |
| **Good** | DOCX normative texts; HTML exports from standards bodies (when licensed) |
| **Acceptable** | Scanned official PDFs (high dpi) for one-time OCR ingest |
| **Poor** | Partial photocopies, watermark-heavy scans |
| **Unsupported** | Pirated aggregates, dynamic web-only viewers with no license to store |

## C2. Extraction confidence

**Timing:** Extraction/parsing confidence applies at **standard library ingestion** (once per StandardVersion), **not** per project analysis.

| Situation | Band |
|-----------|------|
| Born-digital searchable normative PDF/DOCX | **70–85** numeric (native text) for clause segmentation quality |
| Layout/vision-assisted clause boundary recovery | **`pdf_drawing_vision` 35–55** |
| OCR of scanned codes | **`pdf_drawing_ocr` 20–45** |
| Catalog entries already curated with structured clauses | Treat lookup confidence as **high**; inherit stored ingestion band on the StandardVersion record |

IFC/GAEB bands do not apply to standards files themselves; they apply when **project documents** (e.g. IFC fire Psets) are compared to clauses.

## C3. OCR strategy

- At **ingestion only**: reuse OCR pipeline if scan.  
- Layout analysis: yes (article/clause numbering).  
- Table detection: yes (normative tables).  
- Drawing OCR: rare (figures).  
- **Per-project analyze:** no OCR of standards; clause DB read only.

## C4. Semantic understanding strategy

At **ingestion (once):** segment normative vs informative text; identify mandatory language; build StandardClause graph (shall/should/may), definitions, references between clauses — **AI+deterministic hybrid for structure**, stored persistently.

At **project time:** a **Compliance / tender engineer** uses clauses to ask:

- Are selected standards’ **mandatory topics** evidenced in specs/contract/drawings/IFC?  
- Do project specs **weaken or contradict** bound clauses?  
- Is the **edition** appropriate (obsolete binding)?  
- Are cited project requirements **traceable** to clause IDs?  

No per-project keyword scan of the whole code PDF.

## C5. Metadata extraction

**At ingestion:** code designation, title (multilingual), publisher, edition/year, language, jurisdiction, ingestion confidence band, parser version.  

**At project:** binding metadata on ProjectStandard (selected_by, applicability_level, bound StandardVersion id).

## C6. Entity extraction → ontology

| Extracted | Ontology |
|-----------|----------|
| Catalog standard | Catalog + `ProjectStandard` |
| Edition | **StandardVersion** |
| Clause / article | **StandardClause** (persistent) |
| Edition change | **StandardVersionDiff** |
| Project application gap | `Requirement` / Finding linking project entity ↔ StandardClause |
| Uploaded file | `Document` (`standard`) pointing at library StandardVersion after ingest |

## C7. Relationship extraction

- StandardClause **references** StandardClause (internal)  
- StandardVersion **supersedes** StandardVersion (via Diff)  
- ProjectStandard **binds** StandardVersion  
- Requirement / SpecSection / ExtractedClause **governed_by** StandardClause  
- IFC property / BoqItem / Drawing evidence **supports** or **gaps** StandardClause (project graph)

## C8. Validation rules

### At library ingestion (once per edition)

| ID | Rule | Tag |
|----|------|-----|
| ST-P01 | Clause segmentation produced ≥ N clauses; numbering unique | **[PYTHON]** |
| ST-P02 | Mandatory vs informative tagging coverage threshold | **[PYTHON]** |
| ST-A01 | Semantic quality of clause boundaries / merged articles | **[AI]** |
| ST-H01 | Python low OCR band on ingest → AI flags clauses needing human review before publish to library | **[HYBRID]** |

### At project analyze (lookup only — no re-parse)

| ID | Rule | Tag |
|----|------|-----|
| ST-P10 | Every selected ProjectStandard has a bound StandardVersion | **[PYTHON]** |
| ST-P11 | Bound version not marked obsolete without waiver flag | **[PYTHON]** |
| ST-P12 | Topic/coverage checklist: required StandardClause IDs have ≥1 evidence link from project graph **or** explicit gap Finding | **[PYTHON]** |
| ST-A10 | Spec/contract text contradicts retrieved StandardClause meaning | **[AI]** |
| ST-A11 | Edition suitability for project country/type | **[AI]** |
| ST-H10 | Python finds zero evidence links for mandatory fire clauses → AI explains compliance/claim risk | **[HYBRID]** |
| ST-H11 | Python detects citation to clause ID not in bound edition → AI assesses wrong-edition risk | **[HYBRID]** |

## C9. Cross-document validation

| Check | Against | Tag |
|-------|---------|-----|
| Mandatory clauses vs Specs narrative | Technical Specifications | **[HYBRID]** — lookup StandardClause **[PYTHON]**; adequacy **[AI]** |
| Contractual standard-of-care vs bound codes | Contract | **[AI]** |
| IFC fire/material/load properties vs clause requirements | Drawings / IFC | **[HYBRID]** |
| BOQ material items vs normative material clauses | BOQ | **[HYBRID]** |
| ITT-cited codes vs project bindings | Tender Documents | **[PYTHON]** |
| Custom uploaded standard vs catalog duplicate/conflict | Catalog StandardVersion | **[HYBRID]** |

## C10. Typical risk contribution

- **Claim risk:** high (non-compliance, wrong edition)  
- **Cost overrun:** high (remedial design)  
- **Delay:** high (approvals, redesign)  
- **Quality:** very high  
- **Constructability:** medium–high  

## C11. Cause → effect examples

**Example 1 — Unbound selected standard**  
- **Cause:** ProjectStandard selected but no StandardVersion binding / empty StandardClause set.  
- **Effect:** False sense of compliance; analysis cannot verify topics.  
- **source_layer:** `rule_based` / `hybrid`

**Example 2 — Spec weakens fire clause**  
- **Cause:** Bound fire-code StandardClause requires rated separations; specs allow combustible cladding without compensating measures.  
- **Effect:** Authority rejection, redesign, delay, liability.  
- **source_layer:** `hybrid` (clause lookup + AI contradiction)

## C12. Finding output model

Related Standards **must** include `StandardVersion` + `StandardClause` IDs; Validation Evidence = lookup keys and evidence-link table; Confidence Explanation distinguishes **ingestion band** (library) vs **project evidence band** (e.g. `ifc_native`); Missing Evidence = “no spec section linked to clause X”; `source_layer` mandatory. Never imply the full code was re-OCR’d during Analyze.

---

## Cross-type interactions (Part 3 focus)

```text
Tender Documents  →  lists required specs/standards/drawings (checklist [PYTHON])
Technical Specs   ↔  StandardClause (lookup [PYTHON] + contradiction [AI])
Standards         →  constrain Contract / BOQ / Drawings (Parts 2–3 graph)
```

---

## Deferred to next prompt

Schedule · Geotechnical Reports · Employer Requirements · Addenda.

---

## One-line summary

**ITT/forms stay under `tender`; specs under `tender`+subtype; codes use `standard` + ProjectStandard — with StandardClause/StandardVersion parsed once at ingestion and only looked up at analyze; all validations tagged [PYTHON]/[AI]/[HYBRID] without keyword engines or new categories.**
