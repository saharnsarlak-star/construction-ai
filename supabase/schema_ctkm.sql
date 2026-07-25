-- =============================================================================
-- TenderRisk AI — CTKM schema (Supabase / Postgres)
-- Separate from SitePilot. Do not share these tables with SitePilot.
--
-- IMPORTANT IF YOU ALREADY RAN schema.sql (MVP):
--   Your DB already has tables named projects/documents/analyses/findings with
--   a different shape. Before running this file, rename them:
--     alter table projects rename to projects_mvp;
--     alter table documents rename to documents_mvp;
--     alter table analyses rename to analyses_mvp;
--     alter table findings rename to findings_mvp;
--   Then run this file, then optionally schema_ctkm_migrate_from_mvp.sql
--
-- Fresh database: just run this file.
--
-- HOW TO RUN (SQL Editor → New query → Paste → Run):
--   1) Run THIS file.
--   2) Create Storage bucket: project-documents (private) if missing.
--   3) Optional: schema_ctkm_migrate_from_mvp.sql
--
-- Locked defaults for this migration:
--   - Multi-tenant organizations from day one
--   - Soft archive (status), not hard-delete of learning data
--   - Country + project_type as data filters (no per-country schemas)
--   - Lessons/knowledge org-scoped by default
--   - Full CTKM document_types seeded; UI can phase which types are shown
-- =============================================================================

create extension if not exists "pgcrypto";

-- -----------------------------------------------------------------------------
-- Helpers
-- -----------------------------------------------------------------------------

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create or replace function public.is_org_member(p_org_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.organization_members m
    where m.organization_id = p_org_id
      and m.user_id = auth.uid()
  );
$$;

create or replace function public.org_role(p_org_id uuid)
returns text
language sql
stable
security definer
set search_path = public
as $$
  select m.role
  from public.organization_members m
  where m.organization_id = p_org_id
    and m.user_id = auth.uid()
  limit 1;
$$;

-- -----------------------------------------------------------------------------
-- Tenancy
-- -----------------------------------------------------------------------------

create table if not exists public.organizations (
  id uuid primary key default gen_random_uuid(),
  name varchar(255) not null,
  slug varchar(100) unique,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  display_name varchar(255),
  default_organization_id uuid references public.organizations(id) on delete set null,
  preferred_locale varchar(8) default 'fa',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.organization_members (
  organization_id uuid not null references public.organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role varchar(32) not null default 'analyst'
    check (role in ('owner', 'admin', 'analyst', 'viewer')),
  created_at timestamptz not null default now(),
  primary key (organization_id, user_id)
);

create index if not exists organization_members_user_id_idx
  on public.organization_members(user_id);

-- -----------------------------------------------------------------------------
-- Catalogs (add countries / types as DATA, not new tables)
-- -----------------------------------------------------------------------------

create table if not exists public.countries (
  code varchar(8) primary key,
  name_en varchar(100) not null,
  name_fa varchar(100),
  default_locale varchar(8) not null default 'en',
  currency varchar(8),
  status varchar(32) not null default 'active'
    check (status in ('active', 'deprecated'))
);

create table if not exists public.project_types (
  code varchar(64) primary key,
  name_en varchar(100) not null,
  name_fa varchar(100),
  description text,
  status varchar(32) not null default 'active'
    check (status in ('active', 'deprecated'))
);

create table if not exists public.document_types (
  code varchar(64) primary key,
  name_en varchar(100) not null,
  name_fa varchar(100),
  sort_order int not null default 100,
  extraction_profile_key varchar(64),
  status varchar(32) not null default 'active'
    check (status in ('active', 'deprecated'))
);

create table if not exists public.risk_categories (
  code varchar(64) primary key,
  name_en varchar(100) not null,
  name_fa varchar(100),
  sort_order int not null default 100
);

-- Which document types are typically expected for a country + project type
create table if not exists public.expected_documents (
  id uuid primary key default gen_random_uuid(),
  country_code varchar(8) references public.countries(code) on delete cascade,
  project_type_code varchar(64) references public.project_types(code) on delete cascade,
  document_type_code varchar(64) not null references public.document_types(code) on delete cascade,
  is_mandatory boolean not null default true,
  unique (country_code, project_type_code, document_type_code)
);

-- -----------------------------------------------------------------------------
-- Projects
-- -----------------------------------------------------------------------------

create table if not exists public.projects (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  name varchar(255) not null,
  description text,
  country_code varchar(8) not null references public.countries(code),
  project_type_code varchar(64) not null references public.project_types(code),
  status varchar(32) not null default 'active'
    check (status in ('draft', 'active', 'archived')),
  ui_language varchar(8) not null default 'fa',
  report_language varchar(8) not null default 'fa',
  location_text varchar(512),
  employer_name varchar(255),
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  archived_at timestamptz
);

create index if not exists projects_org_idx on public.projects(organization_id);
create index if not exists projects_country_type_idx
  on public.projects(country_code, project_type_code);
create index if not exists projects_status_idx on public.projects(status);

drop trigger if exists projects_set_updated_at on public.projects;
create trigger projects_set_updated_at
  before update on public.projects
  for each row execute function public.set_updated_at();

-- -----------------------------------------------------------------------------
-- Documents + immutable versions
-- -----------------------------------------------------------------------------

create table if not exists public.documents (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  project_id uuid not null references public.projects(id) on delete restrict,
  document_type_code varchar(64) not null references public.document_types(code),
  title varchar(512),
  external_ref varchar(255),
  current_version_id uuid,
  status varchar(32) not null default 'expected'
    check (status in ('expected', 'uploaded', 'extracted', 'failed')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists documents_project_idx on public.documents(project_id);
create index if not exists documents_org_idx on public.documents(organization_id);
create index if not exists documents_type_idx on public.documents(document_type_code);

drop trigger if exists documents_set_updated_at on public.documents;
create trigger documents_set_updated_at
  before update on public.documents
  for each row execute function public.set_updated_at();

create table if not exists public.document_versions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  document_id uuid not null references public.documents(id) on delete restrict,
  version_no int not null,
  storage_path varchar(1024) not null,
  original_filename varchar(512) not null,
  content_type varchar(255),
  size_bytes bigint not null default 0,
  checksum varchar(128),
  extracted_text text,
  structured_json jsonb not null default '{}'::jsonb,
  extraction_status varchar(32) not null default 'pending'
    check (extraction_status in ('pending', 'running', 'succeeded', 'failed', 'skipped')),
  extraction_engine varchar(64),
  superseded_by_version_id uuid references public.document_versions(id) on delete set null,
  uploaded_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (document_id, version_no)
);

create index if not exists document_versions_document_idx
  on public.document_versions(document_id);
create index if not exists document_versions_org_idx
  on public.document_versions(organization_id);

-- deferred FK: documents.current_version_id → document_versions.id
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'documents_current_version_id_fkey'
  ) then
    alter table public.documents
      add constraint documents_current_version_id_fkey
      foreign key (current_version_id)
      references public.document_versions(id)
      on delete set null;
  end if;
end $$;

-- -----------------------------------------------------------------------------
-- Standards catalog + project linkage
-- -----------------------------------------------------------------------------

create table if not exists public.standards (
  id uuid primary key default gen_random_uuid(),
  code varchar(128) not null,
  title varchar(512) not null,
  publisher varchar(255),
  year int,
  scope varchar(16) not null default 'country'
    check (scope in ('global', 'country')),
  country_code varchar(8) references public.countries(code) on delete set null,
  organization_id uuid references public.organizations(id) on delete cascade,
  mandatory_default boolean not null default false,
  status varchar(32) not null default 'active'
    check (status in ('active', 'deprecated')),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

drop index if exists standards_code_scope_uidx;
create unique index standards_code_scope_uidx
  on public.standards (
    code,
    coalesce(country_code, ''),
    coalesce(organization_id::text, '')
  );

create table if not exists public.standard_project_types (
  standard_id uuid not null references public.standards(id) on delete cascade,
  project_type_code varchar(64) not null references public.project_types(code) on delete cascade,
  primary key (standard_id, project_type_code)
);

create table if not exists public.project_standards (
  project_id uuid not null references public.projects(id) on delete cascade,
  standard_id uuid not null references public.standards(id) on delete cascade,
  source varchar(32) not null default 'auto'
    check (source in ('auto', 'manual', 'upload')),
  created_at timestamptz not null default now(),
  primary key (project_id, standard_id)
);

-- -----------------------------------------------------------------------------
-- Risks + Rules (global vs country-scoped rows)
-- -----------------------------------------------------------------------------

create table if not exists public.risks (
  id uuid primary key default gen_random_uuid(),
  code varchar(64) not null unique,
  title varchar(512) not null,
  description text,
  category_code varchar(64) references public.risk_categories(code) on delete set null,
  scope varchar(16) not null default 'global'
    check (scope in ('global', 'country')),
  country_code varchar(8) references public.countries(code) on delete set null,
  default_severity varchar(16) not null default 'medium'
    check (default_severity in ('high', 'medium', 'low')),
  status varchar(32) not null default 'active'
    check (status in ('active', 'deprecated')),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.risk_project_types (
  risk_id uuid not null references public.risks(id) on delete cascade,
  project_type_code varchar(64) not null references public.project_types(code) on delete cascade,
  primary key (risk_id, project_type_code)
);

create table if not exists public.rules (
  id uuid primary key default gen_random_uuid(),
  code varchar(64) not null,
  risk_id uuid references public.risks(id) on delete set null,
  title varchar(512) not null,
  description text,
  scope varchar(16) not null default 'global'
    check (scope in ('global', 'country')),
  country_code varchar(8) references public.countries(code) on delete set null,
  organization_id uuid references public.organizations(id) on delete cascade,
  severity_default varchar(16) not null default 'medium'
    check (severity_default in ('high', 'medium', 'low')),
  logic_type varchar(32) not null default 'keyword'
    check (logic_type in ('presence', 'keyword', 'field_compare', 'llm', 'ml', 'manual')),
  logic_config jsonb not null default '{}'::jsonb,
  applies_to_document_types text[] not null default '{}',
  version int not null default 1,
  enabled boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists rules_code_version_org_uidx
  on public.rules (
    code,
    version,
    coalesce(organization_id::text, ''),
    coalesce(country_code, '')
  );

create table if not exists public.rule_project_types (
  rule_id uuid not null references public.rules(id) on delete cascade,
  project_type_code varchar(64) not null references public.project_types(code) on delete cascade,
  primary key (rule_id, project_type_code)
);

drop trigger if exists rules_set_updated_at on public.rules;
create trigger rules_set_updated_at
  before update on public.rules
  for each row execute function public.set_updated_at();

-- -----------------------------------------------------------------------------
-- Assessments, findings, recommendations
-- -----------------------------------------------------------------------------

create table if not exists public.risk_assessments (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  project_id uuid not null references public.projects(id) on delete restrict,
  run_no int not null default 1,
  status varchar(32) not null default 'completed'
    check (status in ('running', 'completed', 'failed')),
  report_language varchar(8) not null default 'fa',
  readiness_score numeric(5,2),
  summary text,
  counts_json jsonb not null default '{}'::jsonb,
  engine_versions jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (project_id, run_no)
);

create index if not exists risk_assessments_project_idx
  on public.risk_assessments(project_id);

create table if not exists public.findings (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  project_id uuid not null references public.projects(id) on delete restrict,
  risk_assessment_id uuid not null references public.risk_assessments(id) on delete cascade,
  rule_id uuid references public.rules(id) on delete set null,
  risk_id uuid references public.risks(id) on delete set null,
  document_version_id uuid references public.document_versions(id) on delete set null,
  code varchar(64) not null,
  category varchar(100) not null,
  severity varchar(16) not null
    check (severity in ('high', 'medium', 'low')),
  title varchar(512) not null,
  description text not null,
  evidence_snippet text,
  financial_impact varchar(64),
  schedule_impact varchar(64),
  source_layer varchar(32) not null default 'rules'
    check (source_layer in ('rules', 'cross_doc', 'llm', 'ml', 'human')),
  status varchar(32) not null default 'open'
    check (status in ('open', 'accepted', 'rejected', 'dismissed')),
  reviewer_id uuid references auth.users(id) on delete set null,
  reviewed_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists findings_assessment_idx on public.findings(risk_assessment_id);
create index if not exists findings_project_idx on public.findings(project_id);
create index if not exists findings_status_idx on public.findings(status);

create table if not exists public.recommendations (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  finding_id uuid not null references public.findings(id) on delete cascade,
  text text not null,
  priority varchar(16) not null default 'medium'
    check (priority in ('high', 'medium', 'low')),
  owner_role varchar(64),
  status varchar(32) not null default 'suggested'
    check (status in ('suggested', 'accepted', 'done')),
  created_at timestamptz not null default now()
);

create index if not exists recommendations_finding_idx on public.recommendations(finding_id);

-- -----------------------------------------------------------------------------
-- Learning layer (org-scoped by default)
-- -----------------------------------------------------------------------------

create table if not exists public.lessons_learned (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  source_project_id uuid references public.projects(id) on delete set null,
  source_finding_id uuid references public.findings(id) on delete set null,
  risk_id uuid references public.risks(id) on delete set null,
  country_code varchar(8) references public.countries(code) on delete set null,
  project_type_code varchar(64) references public.project_types(code) on delete set null,
  what_happened text not null,
  what_should_change text,
  proposed_rule_patch jsonb not null default '{}'::jsonb,
  review_status varchar(32) not null default 'candidate'
    check (review_status in ('candidate', 'approved', 'rejected')),
  is_promoted_global boolean not null default false,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists lessons_org_idx on public.lessons_learned(organization_id);
create index if not exists lessons_country_type_idx
  on public.lessons_learned(country_code, project_type_code);

drop trigger if exists lessons_set_updated_at on public.lessons_learned;
create trigger lessons_set_updated_at
  before update on public.lessons_learned
  for each row execute function public.set_updated_at();

create table if not exists public.knowledge_nodes (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid references public.organizations(id) on delete cascade,
  node_type varchar(64) not null
    check (node_type in ('concept', 'clause_pattern', 'risk_pattern', 'standard_ref', 'boilerplate')),
  scope varchar(16) not null default 'global'
    check (scope in ('global', 'country')),
  country_code varchar(8) references public.countries(code) on delete set null,
  title varchar(512) not null,
  body text,
  source varchar(32) not null default 'seed'
    check (source in ('seed', 'lesson', 'curated')),
  source_lesson_id uuid references public.lessons_learned(id) on delete set null,
  status varchar(32) not null default 'active'
    check (status in ('active', 'deprecated')),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.knowledge_node_project_types (
  knowledge_node_id uuid not null references public.knowledge_nodes(id) on delete cascade,
  project_type_code varchar(64) not null references public.project_types(code) on delete cascade,
  primary key (knowledge_node_id, project_type_code)
);

create table if not exists public.knowledge_edges (
  id uuid primary key default gen_random_uuid(),
  from_node_id uuid not null references public.knowledge_nodes(id) on delete cascade,
  to_node_id uuid not null references public.knowledge_nodes(id) on delete cascade,
  relation_type varchar(64) not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  check (from_node_id <> to_node_id)
);

create index if not exists knowledge_edges_from_idx on public.knowledge_edges(from_node_id);
create index if not exists knowledge_edges_to_idx on public.knowledge_edges(to_node_id);

-- -----------------------------------------------------------------------------
-- AI prompt audit (Layer 4)
-- -----------------------------------------------------------------------------

create table if not exists public.ai_prompt_logs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  project_id uuid references public.projects(id) on delete set null,
  risk_assessment_id uuid references public.risk_assessments(id) on delete set null,
  document_version_id uuid references public.document_versions(id) on delete set null,
  provider varchar(64),
  model varchar(128),
  prompt_template_key varchar(128),
  input_hash varchar(128),
  prompt_tokens int,
  completion_tokens int,
  raw_response_ref text,
  latency_ms int,
  success boolean not null default true,
  error text,
  created_at timestamptz not null default now()
);

create index if not exists ai_prompt_logs_org_created_idx
  on public.ai_prompt_logs(organization_id, created_at desc);
create index if not exists ai_prompt_logs_project_idx
  on public.ai_prompt_logs(project_id);

-- -----------------------------------------------------------------------------
-- Seed catalogs
-- -----------------------------------------------------------------------------

insert into public.countries (code, name_en, name_fa, default_locale, currency) values
  ('IR', 'Iran', 'ایران', 'fa', 'IRR'),
  ('DE', 'Germany', 'آلمان', 'de', 'EUR'),
  ('CA', 'Canada', 'کانادا', 'en', 'CAD'),
  ('EU', 'European Union', 'اتحادیه اروپا', 'en', 'EUR')
on conflict (code) do nothing;

insert into public.project_types (code, name_en, name_fa, description) values
  ('residential', 'Residential', 'مسکونی', 'Housing and residential complexes'),
  ('hospital', 'Hospital / Healthcare', 'بیمارستان / درمانی', 'Hospitals and clinical facilities'),
  ('industrial', 'Industrial', 'صنعتی', 'Plants, factories, warehouses'),
  ('infrastructure', 'Infrastructure', 'زیرساخت', 'Roads, utilities, civil infrastructure')
on conflict (code) do nothing;

insert into public.document_types (code, name_en, name_fa, sort_order, extraction_profile_key) values
  ('TENDER', 'Tender / ITT', 'اسناد مناقصه', 10, 'tender'),
  ('BOQ', 'Bill of Quantities', 'فهرست بها / مقادیر', 20, 'boq'),
  ('DRAWING', 'Drawings', 'نقشه‌ها', 30, 'drawing'),
  ('SPEC', 'Specifications', 'مشخصات فنی', 40, 'spec'),
  ('CONTRACT', 'Contract conditions', 'شرایط قرارداد', 50, 'contract'),
  ('SCHEDULE', 'Schedule / Programme', 'برنامه زمان‌بندی', 60, 'schedule'),
  ('GEOTECH', 'Geotechnical report', 'گزارش ژئوتکنیک', 70, 'geotech'),
  ('EMPLOYER_REQ', 'Employer requirements', 'الزامات کارفرما', 80, 'employer_req'),
  ('STANDARD', 'Standards', 'استانداردها', 90, 'standard'),
  ('PERMIT', 'Permits / Approvals', 'مجوزها', 100, 'permit'),
  ('ADDENDUM', 'Addenda / Clarifications', 'الحاقیه / توضیحات', 110, 'addendum')
on conflict (code) do nothing;

insert into public.risk_categories (code, name_en, name_fa, sort_order) values
  ('scope', 'Scope', 'محدوده کار', 10),
  ('financial', 'Financial', 'مالی', 20),
  ('schedule', 'Schedule', 'زمان‌بندی', 30),
  ('technical', 'Technical', 'فنی', 40),
  ('geotech', 'Geotechnical', 'ژئوتکنیک', 50),
  ('compliance', 'Compliance', 'انطباق', 60),
  ('claims', 'Claims / Variations', 'ادعا / تغییرات', 70),
  ('process', 'Process', 'فرآیند', 80)
on conflict (code) do nothing;

-- Baseline expected docs for all active countries × core types (mandatory subset)
insert into public.expected_documents (country_code, project_type_code, document_type_code, is_mandatory)
select c.code, pt.code, dt.code, true
from public.countries c
cross join public.project_types pt
cross join (
  values
    ('TENDER'),
    ('BOQ'),
    ('DRAWING'),
    ('SPEC'),
    ('CONTRACT'),
    ('SCHEDULE'),
    ('STANDARD')
) as dt(code)
where c.status = 'active' and pt.status = 'active'
on conflict do nothing;

-- Hospital / infrastructure extras
insert into public.expected_documents (country_code, project_type_code, document_type_code, is_mandatory)
select c.code, 'hospital', 'EMPLOYER_REQ', true
from public.countries c
on conflict do nothing;

insert into public.expected_documents (country_code, project_type_code, document_type_code, is_mandatory)
select c.code, pt.code, 'GEOTECH', true
from public.countries c
cross join (values ('infrastructure'), ('hospital'), ('industrial')) as pt(code)
on conflict do nothing;

-- Sample country-scoped standard stubs (not the full KB)
insert into public.standards (code, title, publisher, year, scope, country_code, mandatory_default)
values
  ('IR-NBR', 'Iranian National Building Regulations (stub)', 'Iran', null, 'country', 'IR', true),
  ('IR-BOQ-REF', 'Iranian Bill of Quantities / فهرست بها (stub)', 'Iran', null, 'country', 'IR', true),
  ('DE-VOB', 'VOB (stub)', 'DIN/Germany', null, 'country', 'DE', true),
  ('DE-DIN-REF', 'DIN referenced standards pack (stub)', 'DIN', null, 'country', 'DE', false),
  ('CA-NBC', 'National Building Code of Canada (stub)', 'NRC', null, 'country', 'CA', true),
  ('CA-CCDC', 'CCDC contract forms (stub)', 'CCDC', null, 'country', 'CA', false),
  ('GLOBAL-FIDIC', 'FIDIC conditions (stub)', 'FIDIC', null, 'global', null, false)
on conflict do nothing;

-- -----------------------------------------------------------------------------
-- Row Level Security
-- -----------------------------------------------------------------------------

alter table public.organizations enable row level security;
alter table public.profiles enable row level security;
alter table public.organization_members enable row level security;
alter table public.projects enable row level security;
alter table public.documents enable row level security;
alter table public.document_versions enable row level security;
alter table public.project_standards enable row level security;
alter table public.risk_assessments enable row level security;
alter table public.findings enable row level security;
alter table public.recommendations enable row level security;
alter table public.lessons_learned enable row level security;
alter table public.knowledge_nodes enable row level security;
alter table public.knowledge_edges enable row level security;
alter table public.ai_prompt_logs enable row level security;

-- Catalogs: readable by authenticated users
alter table public.countries enable row level security;
alter table public.project_types enable row level security;
alter table public.document_types enable row level security;
alter table public.risk_categories enable row level security;
alter table public.expected_documents enable row level security;
alter table public.standards enable row level security;
alter table public.risks enable row level security;
alter table public.rules enable row level security;

-- Profiles
drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own on public.profiles
  for select using (user_id = auth.uid());

drop policy if exists profiles_upsert_own on public.profiles;
create policy profiles_upsert_own on public.profiles
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

-- Organization members: see own memberships
drop policy if exists org_members_select on public.organization_members;
create policy org_members_select on public.organization_members
  for select using (user_id = auth.uid() or public.is_org_member(organization_id));

-- Organizations: members can select
drop policy if exists orgs_select_member on public.organizations;
create policy orgs_select_member on public.organizations
  for select using (public.is_org_member(id));

-- Tenant data policies (pattern)
drop policy if exists projects_tenant_all on public.projects;
create policy projects_tenant_all on public.projects
  for all using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

drop policy if exists documents_tenant_all on public.documents;
create policy documents_tenant_all on public.documents
  for all using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

drop policy if exists document_versions_tenant_all on public.document_versions;
create policy document_versions_tenant_all on public.document_versions
  for all using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

drop policy if exists project_standards_tenant on public.project_standards;
create policy project_standards_tenant on public.project_standards
  for all using (
    exists (
      select 1 from public.projects p
      where p.id = project_id and public.is_org_member(p.organization_id)
    )
  )
  with check (
    exists (
      select 1 from public.projects p
      where p.id = project_id and public.is_org_member(p.organization_id)
    )
  );

drop policy if exists assessments_tenant_all on public.risk_assessments;
create policy assessments_tenant_all on public.risk_assessments
  for all using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

drop policy if exists findings_tenant_all on public.findings;
create policy findings_tenant_all on public.findings
  for all using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

drop policy if exists recommendations_tenant_all on public.recommendations;
create policy recommendations_tenant_all on public.recommendations
  for all using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

drop policy if exists lessons_tenant_all on public.lessons_learned;
create policy lessons_tenant_all on public.lessons_learned
  for all using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

drop policy if exists knowledge_nodes_select on public.knowledge_nodes;
create policy knowledge_nodes_select on public.knowledge_nodes
  for select using (
    organization_id is null
    or public.is_org_member(organization_id)
  );

drop policy if exists knowledge_nodes_write_org on public.knowledge_nodes;
create policy knowledge_nodes_write_org on public.knowledge_nodes
  for all using (
    organization_id is not null and public.is_org_member(organization_id)
  )
  with check (
    organization_id is not null and public.is_org_member(organization_id)
  );

drop policy if exists knowledge_edges_select on public.knowledge_edges;
create policy knowledge_edges_select on public.knowledge_edges
  for select using (
    exists (
      select 1 from public.knowledge_nodes n
      where n.id = from_node_id
        and (n.organization_id is null or public.is_org_member(n.organization_id))
    )
  );

drop policy if exists ai_logs_tenant_all on public.ai_prompt_logs;
create policy ai_logs_tenant_all on public.ai_prompt_logs
  for all using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

-- Public/platform catalogs
drop policy if exists countries_read on public.countries;
create policy countries_read on public.countries for select to authenticated using (true);

drop policy if exists project_types_read on public.project_types;
create policy project_types_read on public.project_types for select to authenticated using (true);

drop policy if exists document_types_read on public.document_types;
create policy document_types_read on public.document_types for select to authenticated using (true);

drop policy if exists risk_categories_read on public.risk_categories;
create policy risk_categories_read on public.risk_categories for select to authenticated using (true);

drop policy if exists expected_documents_read on public.expected_documents;
create policy expected_documents_read on public.expected_documents for select to authenticated using (true);

drop policy if exists standards_read on public.standards;
create policy standards_read on public.standards
  for select to authenticated using (
    organization_id is null or public.is_org_member(organization_id)
  );

drop policy if exists risks_read on public.risks;
create policy risks_read on public.risks for select to authenticated using (true);

drop policy if exists rules_read on public.rules;
create policy rules_read on public.rules
  for select to authenticated using (
    organization_id is null or public.is_org_member(organization_id)
  );

-- -----------------------------------------------------------------------------
-- Notes for Storage (Dashboard, not SQL):
--   Bucket: project-documents (private)
--   Object key convention: {organization_id}/{project_id}/{document_type}/{version}/{filename}
--   Backend (Railway) uses service_role for OCR workers; browser uses user JWT + RLS.
-- =============================================================================
