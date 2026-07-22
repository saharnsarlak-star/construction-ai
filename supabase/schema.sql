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

-- Storage bucket is created from Dashboard → Storage (name: project-documents)
