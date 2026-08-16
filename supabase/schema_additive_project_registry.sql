-- Project registry: categorized editable work log in Supabase.

CREATE TABLE IF NOT EXISTS registry_categories (
  id BIGSERIAL PRIMARY KEY,
  code VARCHAR(64) NOT NULL UNIQUE,
  title_fa VARCHAR(255) NOT NULL,
  title_en VARCHAR(255),
  description_fa TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  color_index INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_registry_categories_sort
  ON registry_categories (sort_order);

ALTER TABLE implementation_steps
  ADD COLUMN IF NOT EXISTS deliverables_fa TEXT,
  ADD COLUMN IF NOT EXISTS related_paths TEXT,
  ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_implementation_steps_category
  ON implementation_steps (category);
