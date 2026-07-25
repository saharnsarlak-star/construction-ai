-- =============================================================================
-- SAFE additive migration for EXISTING MVP Supabase (keeps live Railway app up)
-- Run in SQL Editor AFTER deploying the new backend that expects project_type.
-- Does NOT rename/drop projects/documents/analyses/findings.
-- =============================================================================

alter table if exists public.projects
  add column if not exists project_type varchar(64) not null default 'infrastructure';

alter table if exists public.projects
  add column if not exists country_profile_code varchar(64);

comment on column public.projects.project_type is
  'residential|hospital|industrial|infrastructure';
comment on column public.projects.country_profile_code is
  'Pinned CountryProfile code e.g. IR_PROFILE_V1';

-- Optional lookup seed tables (non-breaking; app also ships knowledge in Python)
create table if not exists public.country_profiles_seed (
  code varchar(64) primary key,
  country_code varchar(8) not null,
  version int not null default 1,
  currency varchar(8),
  primary_standards_system varchar(128),
  legal_contract_framework text,
  measurement_conventions text,
  default_ruleset_code varchar(64),
  config_json jsonb not null default '{}'::jsonb
);

insert into public.country_profiles_seed (
  code, country_code, version, currency, primary_standards_system,
  legal_contract_framework, measurement_conventions, default_ruleset_code, config_json
) values
  ('IR_PROFILE_V1', 'IR', 1, 'IRR', 'IR_NBR_FEHREST',
   'Iran public tender + General/Particular Conditions',
   'Metric; Fehrest Baha', 'IR_CORE_V1',
   '{"boq_format":"fehrest_baha"}'::jsonb),
  ('DE_PROFILE_V1', 'DE', 1, 'EUR', 'DE_VOB_DIN',
   'VOB/B + BGB', 'Metric; GAEB / LV', 'DE_CORE_V1',
   '{"boq_format":"gaeb"}'::jsonb),
  ('CA_PROFILE_V1', 'CA', 1, 'CAD', 'CA_NBC_CSA_CCDC',
   'CCDC + NBC/CSA', 'Metric; trade BoQ', 'CA_CORE_V1',
   '{"boq_format":"trade_boq"}'::jsonb),
  ('EU_PROFILE_V1', 'EU', 1, 'EUR', 'EU_DIRECTIVES_EN_STANDARDS',
   'EU procurement + EN / FIDIC overlays', 'Metric', 'EU_CORE_V1',
   '{"boq_format":"generic_en"}'::jsonb)
on conflict (code) do nothing;
