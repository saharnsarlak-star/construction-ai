-- Additive migration: optional subtopic array on requirements (Standards Engine).
-- Safe to re-run on existing Supabase MVP projects (ADD COLUMN IF NOT EXISTS).
--
-- subtopic holds free-form finer-grained codes under each topic (not a fixed Enum).

ALTER TABLE requirements ADD COLUMN IF NOT EXISTS subtopic varchar(64)[] DEFAULT '{}';
