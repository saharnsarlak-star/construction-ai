-- Phase B / KG-1 — Ontology tables (Party, Element Registry, OntologyEdge).
-- Relational graph per ARCHITECTURE-PART5/PART6; additive only.

CREATE TABLE IF NOT EXISTS parties (
  id bigserial PRIMARY KEY,
  project_id bigint NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  legal_name varchar(512) NOT NULL,
  party_role varchar(64) NOT NULL DEFAULT 'unknown',
  contact_ref varchar(512),
  meta_json text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, legal_name, party_role)
);

CREATE INDEX IF NOT EXISTS idx_parties_project ON parties (project_id);

CREATE TABLE IF NOT EXISTS project_elements (
  id bigserial PRIMARY KEY,
  project_id bigint NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  element_type varchar(128) NOT NULL DEFAULT 'element',
  name_label varchar(512),
  type_mark varchar(128),
  ifc_global_id varchar(64),
  match_key varchar(255) NOT NULL,
  fire_rating varchar(64),
  host_level varchar(128),
  material_ref varchar(255),
  drawing_ref varchar(128),
  confidence integer,
  meta_json text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, match_key)
);

CREATE INDEX IF NOT EXISTS idx_project_elements_project ON project_elements (project_id);
CREATE INDEX IF NOT EXISTS idx_project_elements_ifc ON project_elements (ifc_global_id);

CREATE TABLE IF NOT EXISTS element_document_refs (
  id bigserial PRIMARY KEY,
  project_id bigint NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  element_id bigint NOT NULL REFERENCES project_elements(id) ON DELETE CASCADE,
  document_id bigint NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  source_kind varchar(64) NOT NULL,
  source_local_id varchar(128) NOT NULL DEFAULT '',
  excerpt text,
  confidence integer,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (element_id, document_id, source_kind, source_local_id)
);

CREATE INDEX IF NOT EXISTS idx_element_doc_refs_project ON element_document_refs (project_id);
CREATE INDEX IF NOT EXISTS idx_element_doc_refs_element ON element_document_refs (element_id);

CREATE TABLE IF NOT EXISTS ontology_edges (
  id bigserial PRIMARY KEY,
  project_id bigint NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  from_type varchar(64) NOT NULL,
  from_id varchar(128) NOT NULL,
  to_type varchar(64) NOT NULL,
  to_id varchar(128) NOT NULL,
  predicate varchar(64) NOT NULL,
  confidence integer,
  origin_kind varchar(32) NOT NULL DEFAULT 'python',
  document_id bigint REFERENCES documents(id) ON DELETE SET NULL,
  evidence_json text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ontology_edges_project ON ontology_edges (project_id);
CREATE INDEX IF NOT EXISTS idx_ontology_edges_predicate ON ontology_edges (predicate);
CREATE INDEX IF NOT EXISTS idx_ontology_edges_from ON ontology_edges (from_type, from_id);
CREATE INDEX IF NOT EXISTS idx_ontology_edges_to ON ontology_edges (to_type, to_id);

-- Idempotent upsert helper index for common edge lookups
CREATE UNIQUE INDEX IF NOT EXISTS uq_ontology_edge_tuple
  ON ontology_edges (project_id, from_type, from_id, to_type, to_id, predicate);
