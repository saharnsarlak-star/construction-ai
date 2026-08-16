-- Additive migration: extend existing catalog_standard_assets for Standards Engine.
-- Safe to re-run on existing Supabase MVP projects (ADD COLUMN IF NOT EXISTS).

ALTER TABLE catalog_standard_assets ADD COLUMN IF NOT EXISTS country_code VARCHAR(8);
ALTER TABLE catalog_standard_assets ADD COLUMN IF NOT EXISTS standard_version VARCHAR(64);
ALTER TABLE catalog_standard_assets ADD COLUMN IF NOT EXISTS effective_date DATE;
