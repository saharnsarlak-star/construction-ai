-- LEGACY MVP schema (kept for existing Railway app compatibility).
-- New CTKM model: see schema_ctkm.sql (+ optional schema_ctkm_migrate_from_mvp.sql).
-- Run this once in Supabase: SQL Editor → New query → Paste → Run

create extension if not exists "pgcrypto";

create table if not exists projects (
  id bigserial primary key,
  name varchar(255) not null,
  country varchar(8) not null default 'IR',
  ui_language varchar(8) not null default 'fa',
  report_language varchar(8) not null default 'fa',
  description text,
  created_at timestamptz not null default now()
);

create table if not exists documents (
  id bigserial primary key,
  project_id bigint not null references projects(id) on delete cascade,
  category varchar(32) not null,
  original_name varchar(512) not null,
  stored_path varchar(1024) not null,
  content_type varchar(255),
  size_bytes integer not null default 0,
  extracted_text text,
  meta_json text,
  created_at timestamptz not null default now()
);

create index if not exists documents_project_id_idx on documents(project_id);

create table if not exists analyses (
  id bigserial primary key,
  project_id bigint not null references projects(id) on delete cascade,
  status varchar(50) not null default 'completed',
  summary text,
  report_language varchar(8) not null default 'fa',
  result_json text,
  created_at timestamptz not null default now()
);

create index if not exists analyses_project_id_idx on analyses(project_id);

create table if not exists findings (
  id bigserial primary key,
  analysis_id bigint not null references analyses(id) on delete cascade,
  code varchar(64) not null,
  category varchar(100) not null,
  severity varchar(16) not null,
  title varchar(512) not null,
  description text not null,
  recommendation text not null,
  financial_impact varchar(255),
  schedule_impact varchar(255),
  evidence text
);

create index if not exists findings_analysis_id_idx on findings(analysis_id);

-- Auth principals (admin/user API tokens)
create table if not exists app_users (
  id bigserial primary key,
  username varchar(128) not null unique,
  role varchar(16) not null default 'user',
  api_token varchar(128) not null unique,
  created_at timestamptz not null default now()
);

-- Per-project standard selection
create table if not exists project_standards (
  id bigserial primary key,
  project_id bigint not null references projects(id) on delete cascade,
  standard_code varchar(64) not null,
  is_selected boolean not null default true,
  selected_by varchar(32) not null default 'system_default',
  applicability_level varchar(32),
  standard_class varchar(32),
  title varchar(512),
  created_at timestamptz not null default now(),
  unique (project_id, standard_code)
);

create index if not exists project_standards_project_id_idx on project_standards(project_id);

-- Admin-uploaded original standard PDFs (user download source)
create table if not exists catalog_standard_assets (
  id bigserial primary key,
  standard_code varchar(64) not null unique,
  title varchar(512) not null,
  title_fa varchar(512),
  title_en varchar(512),
  title_de varchar(512),
  publisher varchar(255),
  standard_class varchar(32) not null default 'technical',
  original_name varchar(512) not null,
  stored_path varchar(1024) not null,
  content_type varchar(255),
  size_bytes integer not null default 0,
  uploaded_by varchar(128),
  created_at timestamptz not null default now()
);

-- Storage bucket is created from Dashboard → Storage (name: project-documents)
