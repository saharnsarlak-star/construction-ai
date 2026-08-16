-- Editable, reorderable implementation roadmap (phases A–D + taxonomy + standards mapping).
-- Run in Supabase SQL Editor after other additive migrations.

CREATE TABLE IF NOT EXISTS implementation_steps (
  id BIGSERIAL PRIMARY KEY,
  step_code VARCHAR(64) NOT NULL UNIQUE,
  phase VARCHAR(32) NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  title_fa VARCHAR(512) NOT NULL,
  title_en VARCHAR(512),
  description_fa TEXT,
  description_en TEXT,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  category VARCHAR(64) NOT NULL DEFAULT 'general',
  notes TEXT,
  metadata_json TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_implementation_steps_sort
  ON implementation_steps (sort_order);

CREATE INDEX IF NOT EXISTS idx_implementation_steps_phase
  ON implementation_steps (phase);
