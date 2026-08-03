# Seed Rules — Batch 2 (Prompt 9)

**Purpose:** Seed the remaining **4 of 10** canonical document types.  
**Companion:** Batch 1 = `docs/SEED-RULES-BATCH1.md` (29 rules).  
**Registry:** `backend/app/knowledge/seed_rules_batch2.py` → extended into `GLOBAL_RULES` (alongside Batch 1).

Canonical types seeded here: Standards and Codes · Geotechnical Reports · Employer Requirements · Addenda.

**Entity naming:** `document_type` = **"Employer Requirements"** (plural); ontology entity = **"Employer Requirement"** (singular).

**Standards special rule:** checks use **already-parsed** `StandardClause` / `StandardVersion` — never re-parse standard text per project.

---

## Collision check vs Batch 1

| | Batch 1 prefixes | Batch 2 prefixes |
|--|------------------|------------------|
| rule_id | SCH-/CON-/SPEC-/BOQ-/DRAW-/TEN-SEED | STD-/GEO-/REQ-/ADD-SEED |
| risk_id | RISK-SCHED-/CON-/SPEC-/BOQ-/DRAW-/TEN- | RISK-STD-/GEO-/REQ-/ADD- |

**Result:** zero `rule_id` / `risk_id` collisions.

---

## Standards and Codes (5)

| rule_id | category | ownership | ontology_entities | risk_id_mapping | description |
|---------|----------|-----------|-------------------|-----------------|-------------|
| STD-SEED-001 | standard-compliance | PYTHON | Standard, StandardVersion, Project | RISK-STD-SUPERSEDED-001 | Bound StandardVersion superseded (is_current check) |
| STD-SEED-002 | standard-compliance | PYTHON | Standard, StandardVersion, Project | RISK-STD-MANDATORY-MISSING-001 | Mandatory Standard not selected/uploaded |
| STD-SEED-003 | standard-compliance | HYBRID | StandardClause, StandardVersion, Document, Requirement, Project | RISK-STD-CLAUSE-COMPLIANCE-001 | No semantic compliance evidence vs pre-parsed StandardClause |
| STD-SEED-004 | inter-document | HYBRID | Standard, StandardVersion, Contract, Contract Clause, Project | RISK-STD-FRAMEWORK-CONFLICT-001 | Contradictory contractual frameworks across selected Standards |
| STD-SEED-005 | intra-document | PYTHON | Standard, StandardClause, Document | RISK-STD-LOW-CONFIDENCE-001 | Custom Standard low OCR/extraction confidence |

## Geotechnical Reports (5)

| rule_id | category | ownership | ontology_entities | risk_id_mapping | description |
|---------|----------|-----------|-------------------|-----------------|-------------|
| GEO-SEED-001 | standard-compliance | PYTHON | Document, Project, Location | RISK-GEO-MISSING-001 | No Geotech report where typically required |
| GEO-SEED-002 | intra-document | AI | Document, Document Section, Constraint | RISK-GEO-GROUNDWATER-001 | Groundwater table absent/insufficient |
| GEO-SEED-003 | inter-document | HYBRID | Document, Drawing Sheet, Foundation, Material, Constraint | RISK-GEO-VS-FOUNDATION-001 | Foundation design vs bearing capacity mismatch |
| GEO-SEED-004 | intra-document | PYTHON | Document, Project | RISK-GEO-STALE-001 | Report date much older than project start |
| GEO-SEED-005 | intra-document | HYBRID | Document, Location, Building, Project | RISK-GEO-BOREHOLE-001 | Insufficient boreholes vs footprint/area |

## Employer Requirements (4)

| rule_id | category | ownership | ontology_entities | risk_id_mapping | description |
|---------|----------|-----------|-------------------|-----------------|-------------|
| REQ-SEED-001 | inter-document | HYBRID | Employer Requirement, Requirement, Document Section | RISK-REQ-VS-SPEC-001 | ER conflicts with Technical Specification |
| REQ-SEED-002 | inter-document | PYTHON | Employer Requirement, BOQ Item, Drawing Sheet, Drawing | RISK-REQ-UNFUNDED-001 | ER with no BOQ/Drawing counterpart |
| REQ-SEED-003 | intra-document | AI | Employer Requirement, Requirement | RISK-REQ-VAGUE-001 | Vague/unmeasurable performance requirement |
| REQ-SEED-004 | inter-document | HYBRID | Employer Requirement, StandardClause, Standard, Requirement | RISK-REQ-VS-STD-CLAUSE-001 | ER contradicts mandatory StandardClause |

## Addenda (4)

| rule_id | category | ownership | ontology_entities | risk_id_mapping | description |
|---------|----------|-----------|-------------------|-----------------|-------------|
| ADD-SEED-001 | inter-document | AI | Change, Contract Clause, Tender, Document | RISK-ADD-IMPLICIT-SUPERSEDE-001 | Contradiction without explicit supersedes |
| ADD-SEED-002 | inter-document | PYTHON | Change, Tender, Milestone | RISK-ADD-AFTER-DEADLINE-001 | Issued after bid deadline without extension |
| ADD-SEED-003 | inter-document | PYTHON | Change, BOQ Item, Drawing Sheet, Drawing | RISK-ADD-ORPHAN-001 | Not reflected in BOQ or Drawings |
| ADD-SEED-004 | intra-document | PYTHON | Change, Document | RISK-ADD-SEQUENCE-GAP-001 | Numbering gap in Addenda sequence |

**Batch 2 total:** 18 rules · **18 new Risk IDs**.

---

## NEW_RISK_IDS_BATCH2

| risk_id | category | cost | schedule | quality | short description |
|---------|----------|------|----------|---------|-------------------|
| RISK-STD-SUPERSEDED-001 | compliance | high | medium | high | Superseded StandardVersion binding |
| RISK-STD-MANDATORY-MISSING-001 | compliance | high | medium | high | Mandatory Standard missing |
| RISK-STD-CLAUSE-COMPLIANCE-001 | compliance | high | medium | high | No semantic clause compliance |
| RISK-STD-FRAMEWORK-CONFLICT-001 | claim | high | high | medium | Contradictory contract frameworks |
| RISK-STD-LOW-CONFIDENCE-001 | quality | medium | low | high | Low extraction confidence on custom Standard |
| RISK-GEO-MISSING-001 | constructability | high | high | high | Geotech report missing |
| RISK-GEO-GROUNDWATER-001 | quality | high | medium | high | Groundwater insufficient |
| RISK-GEO-VS-FOUNDATION-001 | constructability | high | high | high | Foundation vs bearing capacity |
| RISK-GEO-STALE-001 | quality | medium | medium | high | Stale geotech report |
| RISK-GEO-BOREHOLE-001 | constructability | high | medium | high | Insufficient boreholes |
| RISK-REQ-VS-SPEC-001 | claim | high | high | medium | ER vs Technical Spec conflict |
| RISK-REQ-UNFUNDED-001 | cost | high | medium | medium | Unfunded/unaddressed ER |
| RISK-REQ-VAGUE-001 | claim | medium | medium | medium | Vague performance ER |
| RISK-REQ-VS-STD-CLAUSE-001 | compliance | high | medium | high | ER vs StandardClause |
| RISK-ADD-IMPLICIT-SUPERSEDE-001 | claim | high | high | low | Implicit contradiction without supersedes |
| RISK-ADD-AFTER-DEADLINE-001 | procurement | medium | high | low | Addendum after deadline |
| RISK-ADD-ORPHAN-001 | cost | high | medium | medium | Orphaned addendum |
| RISK-ADD-SEQUENCE-GAP-001 | procurement | medium | medium | low | Addenda sequence gap |

---

## Registry fit / GAPs

| Item | Fit | Notes |
|------|-----|-------|
| RuleDef fields via `logic_config` | Fits | No schema change (same as Batch 1) |
| `DocumentCategory.STANDARD` for STD-* | Fits | Exists on models |
| GEO / REQ / ADD under upload `tender` + `cdm_subtype_hint` | **Minor Gap** | No dedicated `DocumentCategory` enum values yet (same pattern as Contract/Specs in Batch 1) |
| `StandardApplicability` as named Core Entity | **Minor Gap** | Completeness uses `country_profiles` / ProjectStandard; Part 6 has Standard→Version→Clause, not a separate Applicability entity |
| Geotech typed as `Document` (+ Location/Foundation) | Fits | Part 6 maps Geotech via Document / Investigation points — no separate “Geotechnical Report” Core Entity |
| Addenda ontology entity `Change` | Fits | Part 6 uses Change + `supersedes`/`amends` (Part 5 also uses AddendumChange as graph label) |
| Runners for graph / semantic / confidence gates | **Major Gap** (known) | Seed only — execution still pending (Batch 1+2) |

**Breaking Change:** none.

---

## Full coverage totals (Batch 1 + Batch 2)

| Metric | Count |
|--------|------:|
| Seed rules Batch 1 | 29 |
| Seed rules Batch 2 | 18 |
| **Total seed rules (10 document types)** | **47** |
| New Risk IDs Batch 1 | 28 |
| New Risk IDs Batch 2 | 18 |
| **Total new Risk IDs for Part 5 RKB** | **46** |

All 10 canonical document types now have seed rules.
