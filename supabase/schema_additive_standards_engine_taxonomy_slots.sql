-- Stable family + taxonomy slot codes on catalog standards and clauses.
-- Enables edition replacement: same slot_code, new raw_text / standard_version.

ALTER TABLE catalog_standard_assets
  ADD COLUMN IF NOT EXISTS family_code VARCHAR(32);

CREATE INDEX IF NOT EXISTS idx_catalog_standard_assets_family_code
  ON catalog_standard_assets (family_code);

ALTER TABLE standard_clauses
  ADD COLUMN IF NOT EXISTS section_title VARCHAR(512),
  ADD COLUMN IF NOT EXISTS slot_code VARCHAR(160),
  ADD COLUMN IF NOT EXISTS taxonomy_code VARCHAR(32),
  ADD COLUMN IF NOT EXISTS taxonomy_confidence DOUBLE PRECISION;

CREATE INDEX IF NOT EXISTS idx_standard_clauses_slot_code
  ON standard_clauses (slot_code);

CREATE INDEX IF NOT EXISTS idx_standard_clauses_taxonomy_code
  ON standard_clauses (taxonomy_code);

CREATE UNIQUE INDEX IF NOT EXISTS uq_standard_clauses_standard_slot
  ON standard_clauses (standard_id, slot_code)
  WHERE slot_code IS NOT NULL;
