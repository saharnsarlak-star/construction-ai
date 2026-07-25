-- =============================================================================
-- Optional: copy legacy MVP tables → CTKM model
-- Run AFTER schema_ctkm.sql
--
-- Legacy (from schema.sql):
--   projects(id bigserial), documents, analyses, findings
--
-- This creates one default organization and maps old integer IDs into UUIDs
-- via mapping tables, without deleting legacy rows.
-- =============================================================================

create extension if not exists "pgcrypto";

-- Mapping tables
create table if not exists public._mvp_project_map (
  old_id bigint primary key,
  new_id uuid not null unique references public.projects(id)
);

create table if not exists public._mvp_document_map (
  old_id bigint primary key,
  new_id uuid not null unique references public.documents(id)
);

create table if not exists public._mvp_analysis_map (
  old_id bigint primary key,
  new_id uuid not null unique references public.risk_assessments(id)
);

-- Default org for migrated data (adjust name as needed)
insert into public.organizations (id, name, slug)
values (
  '00000000-0000-4000-8000-000000000001',
  'Migrated Workspace',
  'migrated-workspace'
)
on conflict (id) do nothing;

-- Only proceed if legacy projects table exists with bigserial shape
do $$
begin
  if to_regclass('public.projects') is null then
    raise notice 'No legacy projects table found; skip MVP migrate.';
    return;
  end if;

  -- If CTKM projects already uses uuid and legacy also named projects, this migrate
  -- expects legacy to have been renamed first. Safe approach:
  --   alter table projects rename to projects_mvp;
  --   alter table documents rename to documents_mvp;
  --   alter table analyses rename to analyses_mvp;
  --   alter table findings rename to findings_mvp;
  -- then re-run schema_ctkm.sql and this file against *_mvp tables.

  if to_regclass('public.projects_mvp') is null then
    raise notice 'Rename legacy tables to *_mvp before running this migrate. Example:';
    raise notice '  alter table projects rename to projects_mvp;';
    raise notice '  alter table documents rename to documents_mvp;';
    raise notice '  alter table analyses rename to analyses_mvp;';
    raise notice '  alter table findings rename to findings_mvp;';
    return;
  end if;
end $$;

-- Projects
insert into public.projects (
  id, organization_id, name, description, country_code, project_type_code,
  status, ui_language, report_language, created_at
)
select
  gen_random_uuid(),
  '00000000-0000-4000-8000-000000000001'::uuid,
  p.name,
  p.description,
  case when p.country in ('IR','DE','CA','EU') then p.country else 'IR' end,
  'infrastructure',
  'active',
  coalesce(p.ui_language, 'fa'),
  coalesce(p.report_language, 'fa'),
  p.created_at
from public.projects_mvp p
where not exists (select 1 from public._mvp_project_map m where m.old_id = p.id);

insert into public._mvp_project_map (old_id, new_id)
select p.id, np.id
from public.projects_mvp p
join public.projects np
  on np.organization_id = '00000000-0000-4000-8000-000000000001'::uuid
 and np.name = p.name
 and np.created_at = p.created_at
where not exists (select 1 from public._mvp_project_map m where m.old_id = p.id);

-- Documents + first version
insert into public.documents (
  id, organization_id, project_id, document_type_code, title, status, created_at
)
select
  gen_random_uuid(),
  '00000000-0000-4000-8000-000000000001'::uuid,
  m.new_id,
  case d.category
    when 'tender' then 'TENDER'
    when 'drawing' then 'DRAWING'
    when 'schedule' then 'SCHEDULE'
    when 'standard' then 'STANDARD'
    else 'TENDER'
  end,
  d.original_name,
  'extracted',
  d.created_at
from public.documents_mvp d
join public._mvp_project_map m on m.old_id = d.project_id
where not exists (select 1 from public._mvp_document_map x where x.old_id = d.id);

insert into public._mvp_document_map (old_id, new_id)
select d.id, nd.id
from public.documents_mvp d
join public._mvp_project_map pm on pm.old_id = d.project_id
join public.documents nd
  on nd.project_id = pm.new_id
 and nd.title = d.original_name
 and nd.created_at = d.created_at
where not exists (select 1 from public._mvp_document_map x where x.old_id = d.id);

insert into public.document_versions (
  id, organization_id, document_id, version_no, storage_path, original_filename,
  content_type, size_bytes, extracted_text, structured_json, extraction_status, created_at
)
select
  gen_random_uuid(),
  '00000000-0000-4000-8000-000000000001'::uuid,
  dm.new_id,
  1,
  d.stored_path,
  d.original_name,
  d.content_type,
  d.size_bytes,
  d.extracted_text,
  coalesce(d.meta_json::jsonb, '{}'::jsonb),
  case when d.extracted_text is null or length(trim(d.extracted_text)) = 0
       then 'failed' else 'succeeded' end,
  d.created_at
from public.documents_mvp d
join public._mvp_document_map dm on dm.old_id = d.id
where not exists (
  select 1 from public.document_versions v where v.document_id = dm.new_id and v.version_no = 1
);

update public.documents doc
set current_version_id = v.id,
    status = 'extracted'
from public.document_versions v
where v.document_id = doc.id
  and v.version_no = 1
  and doc.current_version_id is null;

-- Analyses → risk_assessments
insert into public.risk_assessments (
  id, organization_id, project_id, run_no, status, report_language,
  readiness_score, summary, counts_json, created_at
)
select
  gen_random_uuid(),
  '00000000-0000-4000-8000-000000000001'::uuid,
  pm.new_id,
  row_number() over (partition by a.project_id order by a.id),
  coalesce(a.status, 'completed'),
  coalesce(a.report_language, 'fa'),
  nullif((a.result_json::jsonb ->> 'readiness_score'), '')::numeric,
  a.summary,
  coalesce(a.result_json::jsonb -> 'counts', '{}'::jsonb),
  a.created_at
from public.analyses_mvp a
join public._mvp_project_map pm on pm.old_id = a.project_id
where not exists (select 1 from public._mvp_analysis_map m where m.old_id = a.id);

insert into public._mvp_analysis_map (old_id, new_id)
select a.id, ra.id
from public.analyses_mvp a
join public._mvp_project_map pm on pm.old_id = a.project_id
join public.risk_assessments ra
  on ra.project_id = pm.new_id
 and ra.created_at = a.created_at
where not exists (select 1 from public._mvp_analysis_map m where m.old_id = a.id);

-- Findings + recommendations (recommendation text was inline in MVP)
insert into public.findings (
  id, organization_id, project_id, risk_assessment_id, code, category, severity,
  title, description, evidence_snippet, financial_impact, schedule_impact,
  source_layer, status, created_at
)
select
  gen_random_uuid(),
  '00000000-0000-4000-8000-000000000001'::uuid,
  ra.project_id,
  am.new_id,
  f.code,
  f.category,
  f.severity,
  f.title,
  f.description,
  f.evidence,
  f.financial_impact,
  f.schedule_impact,
  'rules',
  'open',
  now()
from public.findings_mvp f
join public._mvp_analysis_map am on am.old_id = f.analysis_id
join public.risk_assessments ra on ra.id = am.new_id;

insert into public.recommendations (organization_id, finding_id, text, priority, status)
select
  nf.organization_id,
  nf.id,
  f.recommendation,
  'medium',
  'suggested'
from public.findings_mvp f
join public._mvp_analysis_map am on am.old_id = f.analysis_id
join public.findings nf
  on nf.risk_assessment_id = am.new_id
 and nf.code = f.code
 and nf.title = f.title
where f.recommendation is not null and length(trim(f.recommendation)) > 0;
