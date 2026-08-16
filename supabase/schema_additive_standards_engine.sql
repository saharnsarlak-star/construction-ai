-- Additive migration: Standards Engine (standard_clauses, requirements).
-- Uses existing catalog_standard_assets as the standards catalog (no new standards table).
-- Safe to re-run on existing Supabase MVP projects (IF NOT EXISTS).
--
-- Prerequisite: run schema_additive_standards_engine_catalog_columns.sql first if
-- catalog_standard_assets needs country_code / standard_version / effective_date.

create table if not exists standard_clauses (
  id bigserial primary key,
  standard_id bigint not null references catalog_standard_assets(id) on delete cascade,
  clause_number varchar(64) not null,
  chapter varchar(128),
  section varchar(128),
  raw_text text not null,
  source_page integer,
  created_at timestamptz not null default now()
);

create index if not exists standard_clauses_standard_id_idx on standard_clauses(standard_id);

create table if not exists requirements (
  id bigserial primary key,
  clause_id bigint not null references standard_clauses(id) on delete cascade,
  discipline varchar(32) not null,
  topic varchar(64)[] not null default '{}',
  element varchar(64)[] not null default '{}',
  material varchar(64)[] not null default '{}',
  requirement_type varchar(32) not null,
  requirement_text text not null,
  min_value double precision,
  max_value double precision,
  unit varchar(64),
  conditions_text text,
  created_at timestamptz not null default now()
);

create index if not exists requirements_clause_id_idx on requirements(clause_id);
