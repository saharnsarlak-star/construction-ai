# Seed Rules — Batch 1 (Prompt 8)

**Purpose:** Populate domain validation rules for **6 of 10** canonical document types.  
**Not covered here:** Standards and Codes, Geotechnical Reports, Employer Requirements, Addenda (follow-up seed).  
**Registry:** `backend/app/knowledge/seed_rules_batch1.py` → extended into `GLOBAL_RULES` via `rules_registry.py`.

Canonical types used: Construction Schedule · Contract Documents · Technical Specifications · Bill of Quantities (BOQ) · Engineering Drawings · Tender Documents.

Categories: `intra-document` | `inter-document` | `standard-compliance`  
Ownership: `[PYTHON]` | `[AI]` | `[HYBRID]`

---

## Construction Schedule (10)

| rule_id | category | ownership | ontology_entities | risk_id_mapping | description |
|---------|----------|-----------|-------------------|-----------------|-------------|
| SCH-SEED-001 | intra-document | PYTHON | Activity, Schedule, Dependency | RISK-SCHED-ISLAND-001 | Activity with no predecessor/successor (floating/island) |
| SCH-SEED-002 | intra-document | PYTHON | Activity, Milestone | RISK-SCHED-DURATION-001 | Zero or negative duration for non-milestone activities |
| SCH-SEED-003 | intra-document | PYTHON | Activity | RISK-SCHED-DURATION-001 | End date earlier than start date |
| SCH-SEED-004 | intra-document | HYBRID | Activity, Schedule, Project | RISK-SCHED-CRITICALPATH-001 | Unreasonably long/short critical path relative to project logic |
| SCH-SEED-005 | intra-document | PYTHON | Activity, Dependency | RISK-SCHED-FLOAT-001 | Negative float (relationship contradiction) |
| SCH-SEED-006 | intra-document | HYBRID | Activity, Dependency | RISK-SCHED-LAG-001 | Missing/incorrect Lag/Lead (Python detects; AI explains) |
| SCH-SEED-007 | inter-document | PYTHON | Schedule, Contract, Contract Clause, Milestone | RISK-SCHED-NTP-MISMATCH-001 | Project start ≠ Contract NTP / commencement |
| SCH-SEED-008 | intra-document | HYBRID | Activity | RISK-SCHED-OVERLAP-001 | Duplicate/overlapping activities without justification |
| SCH-SEED-009 | intra-document | PYTHON | Activity, Labor, Equipment | RISK-SCHED-RESOURCE-001 | No resources on main activities |
| SCH-SEED-010 | intra-document | PYTHON | Activity, Milestone, Schedule | RISK-SCHED-HANDOVER-001 | Missing admin/provisional/final handover at end |

## Contract Documents (4)

| rule_id | category | ownership | ontology_entities | risk_id_mapping | description |
|---------|----------|-----------|-------------------|-----------------|-------------|
| CON-SEED-001 | intra-document | AI | Contract Clause, Employer, Contractor, Contract | RISK-CON-RESP-AMBIG-001 | Ambiguous Employer vs Contractor responsibility |
| CON-SEED-002 | inter-document | HYBRID | Contract Clause, Tender, Requirement, Document | RISK-CON-VS-ITT-001 | Clauses contradict Tender Documents (duration/deadlines) |
| CON-SEED-003 | intra-document | AI | Contract Clause, Payment, Constraint | RISK-CON-BOND-AMBIG-001 | Ambiguous/contradictory guarantee/bond clauses |
| CON-SEED-004 | inter-document | HYBRID | Contract Clause, BOQ Item, Requirement | RISK-CON-VS-BOQ-SCOPE-001 | Stated scope/volume ≠ BOQ quantities |

## Technical Specifications (3)

| rule_id | category | ownership | ontology_entities | risk_id_mapping | description |
|---------|----------|-----------|-------------------|-----------------|-------------|
| SPEC-SEED-001 | standard-compliance | HYBRID | Document Section, Requirement, Standard, StandardVersion, Project | RISK-SPEC-STD-MISMATCH-001 | Standards/codes referenced don't match project type |
| SPEC-SEED-002 | intra-document | AI | Requirement, Material, Document Section | RISK-SPEC-MISSING-GRADE-001 | Missing specs for sensitive items (concrete/steel grade) |
| SPEC-SEED-003 | inter-document | HYBRID | Requirement, Drawing Sheet, Wall, Material | RISK-SPEC-VS-DRAW-001 | Specs inconsistent with Engineering Drawings |

## Bill of Quantities (5)

| rule_id | category | ownership | ontology_entities | risk_id_mapping | description |
|---------|----------|-----------|-------------------|-----------------|-------------|
| BOQ-SEED-001 | inter-document | PYTHON | BOQ Item, Drawing Sheet, Document Section, Requirement | RISK-BOQ-UNIT-MISMATCH-001 | Unit mismatch vs Drawings or Specs |
| BOQ-SEED-002 | inter-document | PYTHON | BOQ Item, Drawing, Drawing Sheet | RISK-BOQ-DRAW-ABSENCE-001 | Item on Drawing absent in BOQ (or vice versa) |
| BOQ-SEED-003 | intra-document | PYTHON | BOQ Item, Table | RISK-BOQ-MATH-001 | Mathematical summation / extension errors |
| BOQ-SEED-004 | standard-compliance | PYTHON | BOQ Item, Standard | RISK-BOQ-CODING-001 | Coding inconsistent with Fehrest Baha / GAEB |
| BOQ-SEED-005 | intra-document | HYBRID | BOQ Item, Building, Location, Project | RISK-BOQ-QTY-OUTLIER-001 | Unreasonable quantities vs project area/volume |

## Engineering Drawings (4)

| rule_id | category | ownership | ontology_entities | risk_id_mapping | description |
|---------|----------|-----------|-------------------|-----------------|-------------|
| DRAW-SEED-001 | inter-document | PYTHON | Drawing Sheet, Revision, Drawing | RISK-DRAW-REV-MISMATCH-001 | Revision mismatch arch/structural/MEP |
| DRAW-SEED-002 | intra-document | HYBRID | Drawing Sheet, Figure | RISK-DRAW-SCALE-001 | Scale inconsistent with stated dimensions (Python/vision) |
| DRAW-SEED-003 | intra-document | AI | Drawing Detail, Drawing Sheet, Connection | RISK-DRAW-MISSING-DETAIL-001 | Missing execution detail for critical connections |
| DRAW-SEED-004 | intra-document | AI | Drawing Sheet, Level, Wall | RISK-DRAW-PLAN-SECTION-001 | Plan vs section/elevation contradiction |

## Tender Documents (3)

| rule_id | category | ownership | ontology_entities | risk_id_mapping | description |
|---------|----------|-----------|-------------------|-----------------|-------------|
| TEN-SEED-001 | inter-document | PYTHON | Tender, Schedule, Milestone, Document | RISK-TEN-DEADLINE-MISMATCH-001 | Deadline mismatch invitation / tender / schedule |
| TEN-SEED-002 | intra-document | AI | Tender, Requirement, Table | RISK-TEN-EVAL-UNCLEAR-001 | Unclear technical-financial evaluation criteria |
| TEN-SEED-003 | inter-document | PYTHON | Tender, Document, Document Section, Change | RISK-TEN-XREF-INCOMPLETE-001 | Incomplete numbering/cross-refs between appendices and Addenda |

**Total:** 29 rules (was 28; +TEN-SEED-003).

---

## New Risk IDs (add to Part 5 RKB)

All `risk_id_mapping` values below are **new** proposals for the Risk Knowledge Base (full records in `NEW_RISK_IDS_BATCH1` in `seed_rules_batch1.py`). **28 unique Risk IDs** (SCH-SEED-002 and SCH-SEED-003 share RISK-SCHED-DURATION-001).

| risk_id | category | cost | schedule | quality | short description |
|---------|----------|------|----------|---------|-------------------|
| RISK-SCHED-ISLAND-001 | delay | medium | high | low | Island/floating activities |
| RISK-SCHED-DURATION-001 | delay | low | high | low | Invalid durations / date order |
| RISK-SCHED-CRITICALPATH-001 | delay | high | high | medium | Unrealistic critical path |
| RISK-SCHED-FLOAT-001 | claim | medium | high | low | Negative float / logic contradiction |
| RISK-SCHED-LAG-001 | delay | medium | high | low | Bad lag/lead usage |
| RISK-SCHED-NTP-MISMATCH-001 | claim | medium | high | low | Start vs contract NTP mismatch |
| RISK-SCHED-OVERLAP-001 | constructability | medium | medium | medium | Unjustified overlap/duplicate |
| RISK-SCHED-RESOURCE-001 | delay | medium | high | medium | No resources on main activities |
| RISK-SCHED-HANDOVER-001 | delay | medium | high | medium | Missing handover milestones |
| RISK-CON-RESP-AMBIG-001 | claim | high | high | medium | Ambiguous responsibility clauses |
| RISK-CON-VS-ITT-001 | claim | high | high | low | Contract vs tender deadlines |
| RISK-CON-BOND-AMBIG-001 | commercial | high | medium | low | Ambiguous bond/guarantee |
| RISK-CON-VS-BOQ-SCOPE-001 | cost | high | medium | medium | Contract scope vs BOQ |
| RISK-SPEC-STD-MISMATCH-001 | compliance | high | medium | high | Wrong standards for project type |
| RISK-SPEC-MISSING-GRADE-001 | quality | high | medium | high | Missing sensitive grades |
| RISK-SPEC-VS-DRAW-001 | claim | high | high | high | Specs vs drawings |
| RISK-BOQ-UNIT-MISMATCH-001 | cost | high | medium | low | Unit of measure mismatch |
| RISK-BOQ-DRAW-ABSENCE-001 | cost | high | medium | medium | Drawing↔BOQ absence |
| RISK-BOQ-MATH-001 | cost | high | low | low | BOQ arithmetic errors |
| RISK-BOQ-CODING-001 | compliance | medium | low | low | Fehrest/GAEB coding |
| RISK-BOQ-QTY-OUTLIER-001 | cost | high | medium | medium | Unreasonable quantities |
| RISK-DRAW-REV-MISMATCH-001 | claim | high | high | high | Cross-discipline revision mismatch |
| RISK-DRAW-SCALE-001 | quality | medium | medium | high | Scale vs dimensions |
| RISK-DRAW-MISSING-DETAIL-001 | constructability | high | high | high | Missing connection details |
| RISK-DRAW-PLAN-SECTION-001 | constructability | high | high | high | Plan vs section conflict |
| RISK-TEN-DEADLINE-MISMATCH-001 | procurement | medium | high | low | Cross-pack deadline mismatch |
| RISK-TEN-EVAL-UNCLEAR-001 | procurement | medium | high | low | Unclear evaluation criteria |
| RISK-TEN-XREF-INCOMPLETE-001 | procurement | medium | medium | low | Incomplete appendix/Addenda cross-refs |

---

## Notes

1. **Contract ≠ Tender Documents** — kept as separate `document_type` values; Contract rules use CDM subtype hints under upload category `tender`.
2. **No Scope-of-Work bucket** — responsibility/claim language → Contract; missing technical requirements → Specs.
3. **Analyzer:** most checks are registered with `logic_config.check` names; runners for graph/vision checks may still be `seed_pending` until Part 5/6 implementation lands.
4. **Batch 2** should seed Standards and Codes, Geotechnical Reports, Employer Requirements, and Addenda.
