# TenderRisk AI — Architecture Part 6  
## Construction Tender Ontology (Authoritative Detail)

**Status:** Authoritative ontology — **supersedes and expands** the Part 1 sketch; does **not** create a parallel model.  
**Depends on:** Parts [1](./ARCHITECTURE-PART1-FOUNDATION.md)–[5](./ARCHITECTURE-PART5-GRAPH-RISK-XAI.md) (approved).  
**Constraint:** No implementation code. Extend and reconcile only.  
**Delivery:** Sections 1–4 = Message 1; Sections 5–7 = Message 2; Success + GAPs + summary = Message 3.

---

## 0. Continuity charter

| Rule | Application |
|------|-------------|
| Same names as Parts 1–5 | Prefer established terms; aliases only when expanding (see §0.1) |
| Standard | Gateway to **StandardVersion** + **StandardClause** (persistent parse, edition binding) — never a flat disconnected blob |
| Document / Finding / Project / ProjectStandard / Analysis | **Directly equivalent** to existing DB tables; ontology describes their role in the graph |
| Knowledge Graph (Part 5 Task 1) | **Reuse** OntologyEdge + node inventory; §5 maps 1:1 and resolves conflicts once |
| Country independence | Ontology has no DIN/VOB/NBR content; that lives in Standards KB + country RuleSets |
| Human Construction Experience | Unified umbrella over ExtractedInsight, LessonsLearned, ExpertReview, ReviewerProfile, ProjectOutcome — no duplicate parallel taxonomies |

### 0.1 Naming reconciliations (canonical)

| Part 1–5 term | Part 6 expansion | Resolution |
|---------------|------------------|------------|
| `Party` (role=employer/contractor) | **Employer**, **Contractor**, **Consultant**, **Stakeholder** | Canonical: keep **Party** as DB/graph node type with `party_role`; Employer/Contractor/… are **role views** of Party — not separate root tables |
| `ExtractedClause` | **Contract Clause** | Alias: Contract Clause = ExtractedClause when `source_kind=contract`; Specs use SpecSection / Requirement |
| `Level` / storey | **Level**, **Floor** | Canonical: **Level** (IFC BuildingStorey); Floor = synonym attribute/`level_kind=floor` |
| `Room` / Space | **Room** | Room covers IfcSpace; `space_kind` distinguishes corridor/room/zone cell |
| `DrawingSheet` / `ModelRoot` | **Drawing**, **Drawing Sheet**, **Drawing Detail** | Drawing = logical drawing product; Sheet = sheet/model root document slice; Detail = callout/subtree |
| Risk (ontology) vs Risk ID (RKB) | **Risk** | Risk node = instance link to RKB **Risk ID** (Part 5); RKB remains taxonomy |
| Recommendation (entity) | Field on Finding + optional node | Canonical: primary = Finding.recommendation text; optional **Recommendation** node only when tracked as reusable mitigation object linked to RKB |

**GAP-01 (Minor):** Part 1 used `Party`; this list names Employer/Contractor separately.  
**Resolution:** Party + `party_role` is canonical; display labels Employer/Contractor/Consultant/Stakeholder.

---

## 1. Core entities

Legend for schema mapping:  
**(a)** NEW conceptual entity (additive table or typed node)  
**(b)** Attribute / sub-object of an existing table  
**(c)** Directly equivalent to an EXISTING table  

| Entity | Mapping | Notes |
|--------|---------|--------|
| **Project** | **(c)** `Project` | Root container |
| **Employer** | **(b)** of Party | `party_role=employer` |
| **Consultant** | **(b)** of Party | engineer / designer / QS roles |
| **Contractor** | **(b)** of Party | often unknown pre-award; bidder slots |
| **Stakeholder** | **(b)** of Party | residual roles |
| **Party** *(canonical)* | **(a)** | Introduced explicitly as the shared table behind role views |
| **Tender** | **(b)** of Project *or* **(a)** light TenderPackage | Procurement envelope metadata; docs remain Document |
| **Package** | **(a)** | Bid package / lot grouping under Tender |
| **Contract** | **(a)** = Part 1 `ContractPackage` | Linked Documents (GC/PC) |
| **Contract Clause** | **(a)** = Part 1 `ExtractedClause` | Evidence-backed clause unit |
| **Employer Requirement** | **(a)** = Part 1 `Requirement` with `source=employer` | From ER docs |
| **Technical Specification** | **(b)** Document subtype + **(a)** SpecSection tree | Document.category tender/specs |
| **BOQ Item** | **(a)** `BoqItem` | GAEB/Excel/PDF |
| **Drawing** | **(a)** logical drawing product | May span sheets |
| **Drawing Sheet** | **(a)** = Part 1 DrawingSheet/ModelRoot | One sheet or IFC model root file slice |
| **Drawing Detail** | **(a)** | Callout / detail id under sheet |
| **Revision** | **(a)** | Rev id/date; sheets/docs **belong_to** Revision |
| **Activity** | **(a)** = ScheduleActivity | |
| **Milestone** | **(b)** of Activity | `activity_kind=milestone` |
| **Procurement Item** | **(a)** | Long-lead / buy item; may link Material/Equipment |
| **Material** | **(a)** = MaterialMention (elevated) | Shared concept across docs |
| **Equipment** | **(a)** | |
| **Labor** | **(a)** | Crew/trade resource (schedule/BOQ) |
| **Location** | **(a)** | Site / place |
| **Building** | **(a)** | Spatial; IFC Building |
| **Zone** | **(a)** | Planning zone |
| **Floor** | **(b)** of Level | synonym |
| **Room** | **(a)** | |
| **Grid** | **(a)** | |
| **Axis** | **(b)** of Grid or **(a)** | Grid line/axis |
| **Level** | **(a)** | Storey |
| **Foundation** | **(a)** | Element class / system |
| **Column** | **(a)** | Physical element type |
| **Beam** | **(a)** | |
| **Wall** | **(a)** | Shared engineering object (see §6) |
| **Slab** | **(a)** | |
| **Opening** | **(a)** | |
| **Door** | **(a)** | |
| **Window** | **(a)** | |
| **MEP Element** | **(a)** | Typed MEP |
| **Risk** | **(a)** instance ↔ RKB Risk ID **(c-ish catalog)** | Finding maps to Risk ID |
| **Finding** | **(c)** `Finding` | Explainable instance (Part 5) |
| **Recommendation** | **(b)** Finding field; optional **(a)** reusable mitigation | Prefer field unless curated library item |
| **Standard** | **(a)** catalog gateway | → StandardVersion → StandardClause |
| **StandardVersion** | **(a)** prior design | Edition |
| **StandardClause** | **(a)** prior design | Persistent clauses |
| **Requirement** | **(a)** | Traceable obligation (ER/spec/contract-derived) |
| **Assumption** | **(a)** | Explicit tender assumption |
| **Constraint** | **(a)** | Hard limit (site, legal, ER) |
| **Dependency** | **(a)** *or* edge-only | Prefer OntologyEdge `depends_on`; entity if attributed |
| **Issue** | **(a)** | Open tender issue / RFI-like |
| **Change** | **(a)** | Addendum change operation / variation foreshadow |
| **Claim** | **(a)** | Claim scenario / foreshadow (pre-award risk) or post-award record |
| **Payment** | **(a)** | Payment milestone / mechanism concept |
| **Schedule** | **(b)** Document (`schedule`) + programme root node | |
| **Document** | **(c)** `Document` | |
| **Document Section** | **(a)** | SpecSection / generic section |
| **Table** | **(b)** CDM NormalizedTable | |
| **Figure** | **(a)** | |
| **Image** | **(b)** page/image asset under Document | |

### Human Construction Experience Knowledge (unified layer)

**Umbrella concept:** `ExperienceKnowledge` (conceptual).  
**Do not invent parallel LessonLearned / ExperienceCase tables if existing suffice.**

| Capability | Canonical existing / additive | Mapping |
|------------|-------------------------------|---------|
| External extracted knowledge | **ExtractedInsight** | ExperienceKnowledge subtype `external_insight` |
| Project outcome feedback | **LessonsLearned** + **ProjectOutcome** | subtype `project_lesson` / outcome record |
| Expert review of AI/findings | **ExpertReview** + **ReviewerProfile** | validation path, not a second lesson store |
| Admin-curated expert entry | **(a)** `ExperienceKnowledgeItem` **only if** ExtractedInsight cannot carry admin authorship cleanly | **GAP-02 resolution below** |

**GAP-02 (Minor → resolved):** Admin-curated entries vs ExtractedInsight overlap.  
**Canonical solution:** One table/concept **ExperienceKnowledgeItem** with `origin_kind`:  
`admin_curated` | `extracted_insight` | `project_lesson` | `expert_observation` | `failure_pattern` | `claim_pattern`  
- Map **ExtractedInsight** → `origin_kind=extracted_insight` (same store or 1:1 view).  
- Map **LessonsLearned** → `origin_kind=project_lesson` linked to ProjectOutcome.  
- **ExpertReview** validates items/findings (`validated_by`), does not duplicate content.  
- **ReviewerProfile** = author/validator identity.  
- Historical failure / claim patterns = same item with `category` + `pattern_kind` — **not** new root entities.

Each ExperienceKnowledgeItem supports: Source, Author/Contributor, Validation Status, Confidence Level, Related Project Type, Related Risk Category / Risk ID, Related Documents, Related Clauses (Contract Clause / StandardClause), Related Outcomes, Version History.

---

## 2. Relationships

### 2.1 Core predicates (align Part 5 OntologyEdge)

| Predicate | Meaning | Part 5 alignment |
|-----------|---------|------------------|
| `references` | Citation / pointer | **Same** as Part 5 |
| `depends_on` | Prerequisite | **Same** |
| `belongs_to` | Ownership / containment | Maps to Part 5 parent/child & package links; additive name OK |
| `located_in` | Spatial containment | **Same** |
| `requires` | Hard prerequisite requirement | Related to `depends_on`; use `requires` for normative need, `depends_on` for sequencing/physical |
| `implements` | Fulfils a requirement/milestone | **Same** |
| `violates` | Contradicts mandatory requirement/standard | Stronger form of conflict vs mandatory; additive |
| `supersedes` | Replaces prior revision/addendum | **Same** |
| `conflicts_with` | Inconsistency | **Same** |
| `derived_from` | Provenance derivation | Additive; Finding/`derived_from` evidence |
| `approved_by` | Approval party | Additive |
| `prepared_by` | Author party | Additive |
| `affects` | General impact | Includes Part 5 `affects_payment` as specialized |
| `causes` | Causal link in risk chain | Additive (Finding cause modeling) |
| `mitigates` | Mitigation against Risk | Additive; RKB / Recommendation |
| `linked_to` | Weak generic association | Use sparingly; prefer typed edges |

### 2.2 Experience predicates

| Predicate | Meaning |
|-----------|---------|
| `learned_from` | ExperienceItem ← Project / Finding / Claim |
| `validated_by` | ExperienceItem ← ExpertReview / ReviewerProfile |
| `observed_in` | Pattern observed in Project / Document |
| `resulted_in` | Issue/Risk → ProjectOutcome |
| `applies_to_future_projects` | ExperienceItem → ProjectType / country tag (advisory) |
| `supported_by_experience` | Finding / Risk assessment ← ExperienceKnowledgeItem |

**GAP-03 (Minor):** Part 5 listed `quantifies`, `governed_by`, `precedes`, `clarifies`, `evidences`, `gaps`, `allocates_responsibility`, `amends`.  
**Resolution:** Those remain **first-class** graph predicates; §2 list is the prompt set plus experience set. Full edge vocabulary = Part 5 ∪ Part 6 (no deletion).

---

## 3. Entity attributes (principal)

### 3.1 Cross-cutting attributes (all nodes)

`id`, `project_id` (null for library standards/experience), `document_id?`, `external_keys[]`, `name/label`, `language?`, `confidence`, `extraction_method_band?`, `created_at`, `version`

### 3.2 Selected entities

**Project:** name, country, project_type, ui/report language, country_profile_code, status  

**Party:** legal_name, party_role, contact_ref  

**Tender / Package:** reference_no, closing_at, submission_mode, lot_id  

**Contract:** form_family_hint, governing_law_hint, linked_document_ids  

**Contract Clause:** clause_no, text, modality (shall/should), parties_addressed, page/unit refs  

**Employer Requirement / Requirement:** req_id, text, measurability, acceptance_criteria?, source_document  

**BOQ Item:** code/OZ, description, unit, quantity, unit_price?, total?, drawing_refs[], spec_refs[], risk_refs[]  

**Drawing / Sheet / Detail / Revision:** sheet_id, discipline, scale?, rev_id, rev_date, title  

**Activity / Milestone:** activity_id, name, start, finish, calendar, float?, is_milestone, predecessors[]  

**Procurement Item:** lead_time?, supplier_hint?, linked_material/equipment  

**Material / Equipment / Labor:** designation, spec_refs, standard_refs  

**Spatial (Location…Level, Grid, Axis):** code/name, elev?, parent spatial id  

**Physical elements (Wall, Slab, …):** element_type, type_mark?, fire_rating?, material_ref?, ifc_global_id?, host_level  

**MEP Element:** system, service, ifc_type?  

**Document:** category, subtype, filename, extraction envelope, CDM pointer **(c)**  

**Document Section / Table / Figure / Image:** local ids, captions, page  

**Standard:** code, title, publisher, jurisdiction_tags → **versions[]**  

**StandardVersion:** edition, year, ingestion_confidence, status  

**StandardClause:** clause_id, text, normative_flag, parent_clause  

**Risk:** risk_id (RKB), category, probability/impact overrides?  

**Finding:** full Part 5 canonical fields + risk_id + source_layer **(c)**  

**Assumption / Constraint / Issue / Change / Claim / Payment:** type-specific text, status, links  

**Schedule:** data_date, software_hint, document_id  

**ExperienceKnowledgeItem:** experience_id, category, description, source, origin_kind, author, validation_status, confidence, related_risk_id, related_project_types[], prevention_action, version_history  

**ProjectOutcome:** outcome metrics, claim_occurred?, delay_days?, cost_delta?  

**ExpertReview / ReviewerProfile:** reviewer_id, decision, notes, timestamp  

---

## 4. Ontology rules (semantic integrity)

### 4.1 Structural

1. Every **BOQ Item** *should* `references` ≥1 Specification section **or** carry explicit Missing Evidence if not *(soft rule → Finding, not hard DB reject)*.  
2. Every **Drawing Sheet** `belongs_to` exactly one current **Revision** (history via `supersedes`).  
3. Every **Contract Clause** `belongs_to` a **Contract**.  
4. Every **Requirement** `derived_from` or `belongs_to` a source **Document** (traceability).  
5. Every **Finding** must `evidences` ≥1 evidence node (Document section/clause/item/sheet/standard/experience) — Part 5 guardrail.  
6. Every **Standard** used on a project must resolve through **ProjectStandard** → **StandardVersion** → **StandardClause** (no floating standard text).  
7. Physical elements (Wall, …) are **shared**: multiple Documents may `references` the same element id within a Project.  

### 4.2 Experience

1. Every ExperienceKnowledgeItem has provenance **Source** + **origin_kind**.  
2. `validation_status ≠ validated` ⇒ must **not** be treated as mandatory fact in Rule Engine.  
3. Validated experience may contribute to **[AI]/[HYBRID]** risk reasoning with `supported_by_experience`.  
4. Experience-based conclusions on Findings must expose confidence + validation_status + experience_id.  
5. LLM must **not** treat experience as a StandardClause obligation.

### 4.3 Layer tags

Integrity checks that are countable → **[PYTHON]**; meaning conflicts → **[AI]**; detect-then-explain → **[HYBRID]** (consistent Parts 1–5).

---

## 5. Knowledge Graph integration (reconcile Part 5 — no redesign)

### 5.1 Node mapping

| Ontology entity | Part 5 KG node |
|-----------------|----------------|
| Project, Document, Finding, Analysis | Same existing tables as nodes |
| Party / Employer / Contractor / … | Party node |
| Contract, Contract Clause, SpecSection, BoqItem, Drawing Sheet, Activity, Requirement, Material, … | Same as Part 5 inventory (+ physical element types as nodes) |
| Standard / StandardVersion / StandardClause | Library nodes (Part 5 regulatory) |
| Risk | Node pointing at RKB Risk ID |
| ExperienceKnowledgeItem, ProjectOutcome, ExpertReview | **Human Experience** nodes (Part 5 Task 1/2 extended explicitly) |

### 5.2 Edge mapping

Part 6 predicates ⊇ Part 5 predicates. Implement as one OntologyEdge.predicate enum/string space.

### 5.3 Conflicts and ONE resolution each

| Conflict | Classification | Canonical resolution |
|----------|----------------|----------------------|
| Employer vs Party | Minor Gap (GAP-01) | Party + role |
| Recommendation entity vs Finding field | Minor | Field primary; optional mitigation library later |
| Dependency entity vs `depends_on` edge | Minor | Edge-first; entity only if attributed dependency register needed |
| ExperienceCase-like new nouns vs ExtractedInsight/LessonsLearned | Major if duplicated | **ExperienceKnowledgeItem** umbrella (GAP-02) |
| Part 5 edge list vs Part 6 list | Minor (GAP-03) | Union vocabulary |
| Floor vs Level | Minor | Level canonical |

### 5.4 Three knowledge sources in one graph

```text
Regulatory:     Standard → StandardVersion → StandardClause
Project:        Document → Clause/BOQ/Drawing/Activity/Finding/Claim/Outcome
Experience:     ExperienceKnowledgeItem ←validated_by— ExpertReview
                      ↑ learned_from Project / Finding
```

**Reasoning path (required):**

```text
Finding
  → Evidence Source (Document / Clause / StandardClause / Experience item)
  → Knowledge Type (Standard | Project | Human Experience)
  → Reasoning Method (rule_based | llm_based | hybrid)
  → Risk Assessment (Risk ID + impacts)
```

---

## 6. Multi-document mapping (consistent with Parts 2–4)

| Document type (Parts 2–4) | Primary ontology targets |
|---------------------------|-------------------------|
| Contract | Contract, Contract Clause, Party, Payment, Requirement, Constraint |
| BOQ | BOQ Item, Material, Labor, references→ Drawing/Spec |
| Drawings / IFC | Drawing, Sheet, Detail, Revision, Level, Grid, Wall… MEP, Location, Building |
| Tender Documents (ITT) | Tender, Package, Requirement (procedural), Party |
| Technical Specifications | Document Section, Requirement, Material, references→ StandardClause |
| Standards and Codes | Standard → Version → Clause (library; project binds) |
| Schedule | Schedule, Activity, Milestone, Procurement Item, Dependency edges |
| Geotechnical | Document, Location, Investigation points, Material (soil), Constraint, Foundation advice → Foundation/Requirement |
| Employer Requirements | Employer Requirement, Requirement, Room programme, Constraint |
| Addenda | Change, supersedes/amends edges to any of the above |

**Also listed in prompt (future subtypes, same ontology — no core redesign):**  
Calculation Reports → elements + Requirement/Assumption; Site Reports → Location/Issue; Correspondence → Issue/Clarification edges; Claims Documents → Claim, Finding, Risk, Outcome.

**Shared object example — Wall W-01:**

- Drawing Sheet references Wall W-01  
- BOQ Item quantifies Wall W-01  
- Spec section specifies Wall W-01 finish/fire  
- Calculation report verifies Wall W-01  
- Contract/ER may require fire rating on Wall W-01  
- Finding may `gaps` StandardClause on Wall W-01  
- Experience item “fire compartment walls often underspecified in tender” `applies_to` similar walls  

All resolve to the **same Wall node** id within the Project graph.

---

## 7. AI usage (Layer 2 Semantic)

The LLM reasons **only inside ontology-bounded context packs**:

1. **Regulatory knowledge** — retrieved StandardClause text for bound versions (DIN/Eurocode/VOB/NBR/… content from KB, not hard-coded in ontology).  
2. **Project document knowledge** — CDM excerpts + graph neighborhood of entities.  
3. **Human Construction Experience** — validated ExperienceKnowledgeItems linked by risk/project_type; must show validation_status.

**Must distinguish in output:** mandatory standard requirement vs project fact vs assumption vs experience indicator vs expert opinion.

**Must attach:** provenance, confidence, validation status, reasoning path (Finding → evidence → knowledge type → method → Risk ID).

**Must not:** invent quantities contradicting BoqItem/IFC counts; treat unvalidated experience as code; bypass Part 5 evidence guardrails.

Ontology reduces hallucination by forcing entity IDs in prompts and rejecting answers without evidence IDs **[PYTHON] guardrail**.

---

## 8. Architecture gaps register (Parts 1–6 final review)

| ID | Gap | Impact | Class | Canonical solution |
|----|-----|--------|-------|-------------------|
| GAP-01 | Employer/Contractor vs Party naming | Ambiguous tables | Minor | Party + party_role |
| GAP-02 | Experience entities vs ExtractedInsight/LessonsLearned | Duplicates | Major if ignored | ExperienceKnowledgeItem umbrella + origin_kind |
| GAP-03 | Edge vocabulary split Part 5 vs 6 | Incomplete traversal | Minor | Union predicate set |
| GAP-04 | Soft ontology rules (BOQ↔Spec) vs hard DB constraints | Over-strict ingest | Minor | Enforce as Findings, not insert blockers |
| GAP-05 | Physical element identity across files (same wall) | Fragmented graph | Major if ignored | Project-scoped Element registry with stable `type_mark`/IFC guid merge rules **[HYBRID]** |
| GAP-06 | Recommendation as entity vs field | Schema clutter | Minor | Field default; library later |
| GAP-07 | Calculation/Correspondence/Claims docs only lightly in Parts 2–4 | Coverage hole | Minor | Map into same ontology when implemented (Part 6 §6); no new core |
| GAP-08 | Current MVP analyzer still keyword-ish | Violates success “no keyword intelligence” until migrated | Major (implementation debt, not design conflict) | Migrate rule-by-rule to PYTHON/AI/HYBRID per Parts 2–5; dual-run |
| GAP-09 | RKB vs Risk ontology node | Confusion | Minor | RKB = catalog; Risk node = project binding to Risk ID |
| GAP-10 | Dependency entity vs edge | Redundancy | Minor | Edge-first |

**No Breaking Change** required to existing Project/Document/Finding/Analysis/ProjectStandard tables for this ontology to land.

---

## 9. Brief summary — unified architecture (Parts 1–6)

1. **Part 1:** Dual layer [PYTHON]+[AI]/[HYBRID]; ingestion pipeline; CDM; ontology sketch.  
2. **Parts 2–4:** Ten document types, full validation design, category mapping without breaking changes.  
3. **Part 5:** Project Knowledge Graph, Risk Knowledge Base, explainable Finding schema, country compatibility.  
4. **Part 6:** Authoritative ontology expanding Part 1; reconciles Party/Experience/edges; binds Standard to StandardVersion/Clause; grounds LLM in three knowledge sources; registers gaps with one resolution each.

**Success criteria (design-level):** Satisfied architecturally, subject to implementing GAP-02, GAP-05, and GAP-08 migration in build phases — not by redesigning Parts 1–5.

---

## 10. One-line close

**One shared, country-neutral ontology — rooted in existing Project/Document/Finding tables and StandardVersion/Clause — powers CDM, graph, rules, and LLM, with Human Construction Experience as a first-class validated knowledge source alongside regulatory and project evidence.**

---

---

## Appendix A — Part 7 confirmation (no redesign)

### A.1 Unlimited expandability

**Confirmed (design intent):** Counts of Risk IDs, Experience Knowledge items, Lessons Learned, Failure Patterns, Claim Patterns, and Best Practices are **data-volume concerns only**. There is **no** architectural ceiling, no fixed array size in the ontology, and no requirement to redesign DB schema or restructure the ontology to add new rows over time.

| Knowledge kind | How it grows | Architecture change needed? |
|----------------|--------------|----------------------------|
| RKB Risk IDs | Insert/version new Risk records in the platform catalog; Findings reference by ID | **No** |
| Experience / lessons / failure & claim patterns / best practices | New `ExperienceKnowledgeItem` rows (`origin_kind` + `category`); patterns are classifications, not separate capped entity types | **No** |
| RKB Mitigation / experience prevention actions (“best practices”) | Fields on Risk / Experience items; optional Recommendation library rows | **No** |

**Clarifications (not limits):**
- Part 5 “predefined Risk ID” means: at Finding-publish time the ID **must already exist in the RKB catalog** (referential integrity) — **not** that the catalog is closed forever. Admins/experts add Risk IDs without ontology change.
- Part 5 “fixed Risk ID map” on some **[PYTHON]** rules means each *rule* points at an ID; new risks/rules are additive configuration/data.

**GAP-11 (Minor):** If `OntologyEdge.predicate`, `origin_kind`, or Risk `category` were implemented as a **closed SQL ENUM** requiring a migration for every new value, that would violate unlimited expandability.  
**Canonical solution:** Extensible string + controlled vocabulary / lookup table (append-only), not a closed compile-time enum. Does **not** change ontology concepts.

**GAP-12 (Minor — implementation caution):** Hardcoding Risk IDs only inside application source (e.g. frozen list in code with no RKB admin path) would create a practical ceiling.  
**Canonical solution:** RKB remains the writable source of truth; code may ship seed data only.

### A.2 Naming clarity — “Construction Experience Brain”

**Confirmed:** “Construction Experience Brain” is **only a conceptual / product nickname** for the **same** Human Construction Experience Knowledge layer already designed in Parts 5–6 (umbrella over ExtractedInsight, LessonsLearned, ExpertReview, ReviewerProfile, ProjectOutcome → `ExperienceKnowledgeItem` + `origin_kind`).

It is **not** a new entity, table, graph node type, or parallel knowledge store, and requires **no** separate implementation track beyond that layer.
