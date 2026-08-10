-- Additive migration: Standards Engine (standards, standard_clauses, requirements).
-- Safe to re-run on existing Supabase MVP projects (IF NOT EXISTS).
--
-- NOTE: If schema_ctkm.sql was already applied, a different ``standards`` table
-- (UUID-based) may exist — do not run this migration on that database without
-- reconciling table names first.

create table if not exists standards (
  id bigserial primary key,
  country_code varchar(8) not null,
  standard_code varchar(64) not null,
  title_fa varchar(512) not null,
  title_en varchar(512),
  version varchar(64),
  effective_date date,
  created_at timestamptz not null default now()
);

create table if not exists standard_clauses (
  id bigserial primary key,
  standard_id bigint not null references standards(id) on delete cascade,
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
