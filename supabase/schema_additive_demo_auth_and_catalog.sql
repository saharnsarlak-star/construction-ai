-- Additive migration: demo auth columns + catalog PDF text cache + finding source fields.
-- Safe to re-run on existing Supabase projects (IF NOT EXISTS).

ALTER TABLE app_users ADD COLUMN IF NOT EXISTS email VARCHAR(255);
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'approved';
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS full_name VARCHAR(255);
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS company VARCHAR(255);
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS phone VARCHAR(64);
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS message TEXT;
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS demo_project_id INTEGER;
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS is_demo_user BOOLEAN DEFAULT FALSE;
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS demo_expires_at TIMESTAMPTZ;
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS demo_analyses_used INTEGER DEFAULT 0;

CREATE UNIQUE INDEX IF NOT EXISTS app_users_email_uidx ON app_users (email) WHERE email IS NOT NULL;

ALTER TABLE projects ADD COLUMN IF NOT EXISTS owner_user_id INTEGER;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_demo BOOLEAN DEFAULT FALSE;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS project_type VARCHAR(64);
ALTER TABLE projects ADD COLUMN IF NOT EXISTS country_profile_code VARCHAR(64);

ALTER TABLE findings ADD COLUMN IF NOT EXISTS finding_category VARCHAR(32) DEFAULT 'risk';
ALTER TABLE findings ADD COLUMN IF NOT EXISTS risk_score INTEGER;
ALTER TABLE findings ADD COLUMN IF NOT EXISTS source_excerpt TEXT;
ALTER TABLE findings ADD COLUMN IF NOT EXISTS source_document_name VARCHAR(512);
ALTER TABLE findings ADD COLUMN IF NOT EXISTS source_page INTEGER;
ALTER TABLE findings ADD COLUMN IF NOT EXISTS cause_effect_json TEXT;
ALTER TABLE findings ADD COLUMN IF NOT EXISTS data_completeness_caveat TEXT;
ALTER TABLE findings ADD COLUMN IF NOT EXISTS estimated_impact VARCHAR(512);
ALTER TABLE findings ADD COLUMN IF NOT EXISTS source_layer VARCHAR(32);
ALTER TABLE findings ADD COLUMN IF NOT EXISTS confidence_score INTEGER;

ALTER TABLE experience_knowledge_items ADD COLUMN IF NOT EXISTS match_keywords_json TEXT;

ALTER TABLE catalog_standard_assets ADD COLUMN IF NOT EXISTS extracted_text TEXT;
ALTER TABLE catalog_standard_assets ADD COLUMN IF NOT EXISTS extraction_status VARCHAR(32);

UPDATE app_users SET status = 'approved' WHERE status IS NULL OR status = '';
