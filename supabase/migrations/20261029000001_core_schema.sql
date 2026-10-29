-- =============================================================================
-- FiscalGuard — Esquema principal (multi-tenant)
-- -----------------------------------------------------------------------------
-- Convenções:
--   * Toda tabela com dados de clientes possui organization_id (tenant).
--   * FKs compostas (id, organization_id) impedem referências entre tenants
--     mesmo que a aplicação tenha um bug.
--   * Timestamps em timestamptz; valores monetários em numeric(18,2);
--     quantidades e alíquotas com maior precisão.
-- =============================================================================

create extension if not exists pgcrypto;
create schema if not exists app;

-- -----------------------------------------------------------------------------
-- Tipos enumerados
-- -----------------------------------------------------------------------------
create type public.member_role as enum ('admin', 'operator', 'viewer');
create type public.tax_regime as enum ('simples_nacional', 'mei', 'lucro_presumido', 'lucro_real', 'outro');
create type public.compliance_status as enum ('unknown', 'regular', 'pending', 'irregular', 'expired');
create type public.check_type as enum (
  'cadastro_cnpj', 'cnd_federal', 'crf_fgts', 'cndt', 'cnd_estadual', 'cnd_municipal', 'sintegra', 'outro'
);
create type public.check_result as enum ('regular', 'irregular', 'pending', 'not_found', 'error');
create type public.document_status as enum ('received', 'validated', 'invalid');
create type public.document_direction as enum ('inbound', 'outbound', 'unrelated');
create type public.rule_status as enum ('draft', 'published', 'retired');
create type public.rule_scope as enum ('item', 'document');
create type public.review_status as enum ('pending_review', 'approved', 'rejected', 'needs_info');
create type public.alert_severity as enum ('info', 'warning', 'critical');
create type public.alert_status as enum ('open', 'acknowledged', 'resolved');
create type public.job_status as enum ('queued', 'running', 'succeeded', 'failed', 'dead');

-- -----------------------------------------------------------------------------
-- Funções utilitárias
-- -----------------------------------------------------------------------------
create or replace function app.set_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end $$;

-- -----------------------------------------------------------------------------
-- Organizações (escritórios contábeis) e usuários
-- -----------------------------------------------------------------------------
create table public.organizations (
  id          uuid primary key default gen_random_uuid(),
  name        text not null check (length(trim(name)) > 0),
  cnpj        varchar(14) unique,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

-- Perfil público espelhando auth.users (Supabase Auth).
create table public.users (
  id          uuid primary key references auth.users(id) on delete cascade,
  email       text not null,
  full_name   text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create table public.organization_members (
  id               uuid primary key default gen_random_uuid(),
  organization_id  uuid not null references public.organizations(id) on delete cascade,
  user_id          uuid not null references public.users(id) on delete cascade,
  role             public.member_role not null default 'viewer',
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  unique (organization_id, user_id)
);
create index on public.organization_members (user_id);

-- -----------------------------------------------------------------------------
-- Empresas atendidas e vínculo de usuários por empresa
-- -----------------------------------------------------------------------------
create table public.client_companies (
  id                  uuid primary key default gen_random_uuid(),
  organization_id     uuid not null references public.organizations(id) on delete cascade,
  legal_name          text not null,
  trade_name          text,
  cnpj                varchar(14) not null,
  state_registration  text,
  uf                  char(2),
  tax_regime          public.tax_regime not null default 'outro',
  is_industrial       boolean not null default false,
  active              boolean not null default true,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique (organization_id, cnpj),
  unique (id, organization_id)
);
create index on public.client_companies (organization_id, active);

-- Concede a operadores/visualizadores acesso a empresas específicas.
-- Administradores do escritório acessam todas as empresas.
create table public.company_memberships (
  id               uuid primary key default gen_random_uuid(),
  organization_id  uuid not null,
  company_id       uuid not null,
  user_id          uuid not null references public.users(id) on delete cascade,
  created_at       timestamptz not null default now(),
  unique (company_id, user_id),
  foreign key (company_id, organization_id)
    references public.client_companies(id, organization_id) on delete cascade
);
create index on public.company_memberships (user_id, organization_id);

-- -----------------------------------------------------------------------------
-- Fornecedores e compliance
-- -----------------------------------------------------------------------------
create table public.suppliers (
  id                     uuid primary key default gen_random_uuid(),
  organization_id        uuid not null references public.organizations(id) on delete cascade,
  cnpj                   varchar(14) not null,
  legal_name             text not null,
  trade_name             text,
  uf                     char(2),
  tax_regime             public.tax_regime,
  email                  text,
  phone                  text,
  compliance_status      public.compliance_status not null default 'unknown',
  compliance_updated_at  timestamptz,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now(),
  unique (organization_id, cnpj),
  unique (id, organization_id)
);
create index on public.suppliers (organization_id, compliance_status);

create table public.supplier_company_links (
  id               uuid primary key default gen_random_uuid(),
  organization_id  uuid not null,
  supplier_id      uuid not null,
  company_id       uuid not null,
  notes            text,
  created_at       timestamptz not null default now(),
  unique (supplier_id, company_id),
  foreign key (supplier_id, organization_id)
    references public.suppliers(id, organization_id) on delete cascade,
  foreign key (company_id, organization_id)
    references public.client_companies(id, organization_id) on delete cascade
);
create index on public.supplier_company_links (company_id);

create table public.evidence_documents (
  id               uuid primary key default gen_random_uuid(),
  organization_id  uuid not null references public.organizations(id) on delete cascade,
  company_id       uuid,
  supplier_id      uuid,
  kind             text not null default 'outro',
  file_name        text not null,
  content_type     text not null,
  size_bytes       bigint not null check (size_bytes >= 0),
  sha256           char(64) not null,
  storage_path     text not null,
  uploaded_by      uuid references public.users(id),
  created_at       timestamptz not null default now(),
  unique (id, organization_id),
  foreign key (company_id, organization_id)
    references public.client_companies(id, organization_id) on delete cascade,
  foreign key (supplier_id, organization_id)
    references public.suppliers(id, organization_id) on delete cascade
);
create index on public.evidence_documents (organization_id, supplier_id);

-- Histórico append-only de verificações (fonte, data, resultado, evidência).
create table public.compliance_checks (
  id                    uuid primary key default gen_random_uuid(),
  organization_id       uuid not null,
  supplier_id           uuid not null,
  check_type            public.check_type not null,
  result                public.check_result not null,
  source                text not null,
  source_reference      text,
  issued_at             date,
  valid_until           date,
  checked_at            timestamptz not null default now(),
  checked_by            uuid references public.users(id),
  evidence_document_id  uuid,
  notes                 text,
  created_at            timestamptz not null default now(),
  check (valid_until is null or issued_at is null or valid_until >= issued_at),
  foreign key (supplier_id, organization_id)
    references public.suppliers(id, organization_id) on delete cascade,
  foreign key (evidence_document_id, organization_id)
    references public.evidence_documents(id, organization_id)
);
create index on public.compliance_checks (supplier_id, check_type, checked_at desc);
create index on public.compliance_checks (organization_id, valid_until);

-- -----------------------------------------------------------------------------
-- Integrações e tarefas assíncronas
-- -----------------------------------------------------------------------------
create table public.erp_connections (
  id               uuid primary key default gen_random_uuid(),
  organization_id  uuid not null references public.organizations(id) on delete cascade,
  company_id       uuid,
  provider         text not null,
  name             text not null,
  config           jsonb not null default '{}'::jsonb,  -- nunca armazenar segredos aqui
  secret_ref       text,                                -- referência ao cofre de segredos
  active           boolean not null default true,
  last_sync_at     timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  foreign key (company_id, organization_id)
    references public.client_companies(id, organization_id) on delete cascade
);

create table public.integration_jobs (
  id                uuid primary key default gen_random_uuid(),
  organization_id   uuid not null references public.organizations(id) on delete cascade,
  company_id        uuid,
  kind              text not null,
  status            public.job_status not null default 'queued',
  payload           jsonb not null default '{}'::jsonb,
  result            jsonb,
  error             text,
  attempts          int not null default 0,
  max_attempts      int not null default 3 check (max_attempts > 0),
  idempotency_key   text,
  run_after         timestamptz not null default now(),
  locked_at         timestamptz,
  locked_by         text,
  started_at        timestamptz,
  finished_at       timestamptz,
  created_by        uuid references public.users(id),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (organization_id, idempotency_key),
  unique (id, organization_id),
  foreign key (company_id, organization_id)
    references public.client_companies(id, organization_id) on delete cascade
);
create index integration_jobs_queue_idx on public.integration_jobs (run_after)
  where status = 'queued';
create index on public.integration_jobs (organization_id, created_at desc);

-- -----------------------------------------------------------------------------
-- Documentos fiscais (NF-e)
-- -----------------------------------------------------------------------------
create table public.fiscal_documents (
  id                 uuid primary key default gen_random_uuid(),
  organization_id    uuid not null,
  company_id         uuid not null,
  supplier_id        uuid,
  model              varchar(2) not null default '55',
  access_key         char(44) not null,
  number             bigint,
  series             int,
  issue_date         timestamptz,
  operation_type     smallint,             -- tpNF: 0 entrada / 1 saída (visão do emitente)
  direction          public.document_direction not null,
  issuer_cnpj        varchar(14),
  issuer_name        text,
  issuer_uf          char(2),
  issuer_crt         smallint,             -- código de regime tributário do emitente
  recipient_cnpj     varchar(14),
  recipient_name     text,
  recipient_uf       char(2),
  total_products     numeric(18,2) not null default 0,
  total_discount     numeric(18,2) not null default 0,
  total_icms         numeric(18,2) not null default 0,
  total_icms_st      numeric(18,2) not null default 0,
  total_ipi          numeric(18,2) not null default 0,
  total_pis          numeric(18,2) not null default 0,
  total_cofins       numeric(18,2) not null default 0,
  total_amount       numeric(18,2) not null default 0,
  protocol_number    text,
  status             public.document_status not null default 'received',
  validation_errors  jsonb not null default '[]'::jsonb,
  raw_sha256         char(64) not null,
  storage_path       text,
  import_job_id      uuid,
  analyzed_at        timestamptz,
  imported_by        uuid references public.users(id),
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  -- Idempotência: a mesma NF-e só existe uma vez por empresa.
  unique (company_id, access_key),
  unique (id, organization_id),
  foreign key (company_id, organization_id)
    references public.client_companies(id, organization_id) on delete cascade,
  foreign key (supplier_id, organization_id)
    references public.suppliers(id, organization_id) on delete set null (supplier_id),
  foreign key (import_job_id, organization_id)
    references public.integration_jobs(id, organization_id) on delete set null (import_job_id)
);
create index on public.fiscal_documents (organization_id, company_id, issue_date desc);
create index on public.fiscal_documents (organization_id, issuer_cnpj);

create table public.fiscal_document_items (
  id               uuid primary key default gen_random_uuid(),
  organization_id  uuid not null,
  document_id      uuid not null,
  item_number      int not null check (item_number > 0),
  product_code     text,
  description      text,
  ncm              varchar(8),
  cest             varchar(7),
  cfop             varchar(4),
  unit             text,
  quantity         numeric(20,6) not null default 0,
  unit_price       numeric(24,10) not null default 0,
  total_value      numeric(18,2) not null default 0,
  discount         numeric(18,2) not null default 0,
  icms_origin      smallint,
  icms_cst         varchar(3),             -- CST (2 dígitos) ou CSOSN (3 dígitos)
  icms_base        numeric(18,2),
  icms_rate        numeric(9,4),
  icms_value       numeric(18,2),
  icms_st_value    numeric(18,2),
  ipi_cst          varchar(2),
  ipi_value        numeric(18,2),
  pis_cst          varchar(2),
  pis_base         numeric(18,2),
  pis_rate         numeric(9,4),
  pis_value        numeric(18,2),
  cofins_cst       varchar(2),
  cofins_base      numeric(18,2),
  cofins_rate      numeric(9,4),
  cofins_value     numeric(18,2),
  raw_taxes        jsonb not null default '{}'::jsonb,
  created_at       timestamptz not null default now(),
  unique (document_id, item_number),
  unique (id, organization_id),
  foreign key (document_id, organization_id)
    references public.fiscal_documents(id, organization_id) on delete cascade
);
create index on public.fiscal_document_items (organization_id, ncm);
create index on public.fiscal_document_items (organization_id, cfop);

-- -----------------------------------------------------------------------------
-- Motor de regras tributárias (versionado e imutável após publicação)
-- -----------------------------------------------------------------------------
create table public.tax_rules (
  id                      uuid primary key default gen_random_uuid(),
  organization_id         uuid references public.organizations(id) on delete cascade, -- null = regra global
  code                    text not null check (code ~ '^[A-Z0-9_.-]{2,64}$'),
  version                 int not null check (version > 0),
  name                    text not null,
  description             text,
  tax                     text not null,
  legal_basis             text,
  scope                   public.rule_scope not null default 'item',
  conditions              jsonb not null,
  estimate                jsonb,
  justification_template  text not null,
  valid_from              date not null,
  valid_to                date,
  status                  public.rule_status not null default 'draft',
  content_hash            char(64) not null,
  supersedes_id           uuid references public.tax_rules(id),
  validated_by_specialist text,           -- nome/registro do especialista que validou
  created_by              uuid references public.users(id),
  published_at            timestamptz,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now(),
  check (valid_to is null or valid_to >= valid_from),
  unique nulls not distinct (organization_id, code, version)
);
create index on public.tax_rules (status, valid_from);

-- Regras publicadas são imutáveis: só é permitido aposentá-las ou encerrar vigência.
create or replace function app.protect_published_rule() returns trigger
language plpgsql as $$
begin
  if old.status <> 'draft' then
    if (to_jsonb(new) - array['status','valid_to','updated_at'])
       is distinct from (to_jsonb(old) - array['status','valid_to','updated_at']) then
      raise exception 'Regra % v% já publicada é imutável; crie uma nova versão', old.code, old.version
        using errcode = 'check_violation';
    end if;
    if new.status = 'draft' then
      raise exception 'Regra publicada não pode voltar a rascunho' using errcode = 'check_violation';
    end if;
  end if;
  return new;
end $$;

create trigger tax_rules_immutable before update on public.tax_rules
  for each row execute function app.protect_published_rule();

create table public.tax_assessments (
  id                uuid primary key default gen_random_uuid(),
  organization_id   uuid not null,
  company_id        uuid not null,
  document_id       uuid not null,
  item_id           uuid,
  rule_id           uuid not null references public.tax_rules(id),
  rule_code         text not null,
  rule_version      int not null,
  rule_hash         char(64) not null,
  run_id            uuid not null,
  tax               text not null,
  estimated_amount  numeric(18,2),
  inputs            jsonb not null,       -- snapshot dos dados avaliados
  criteria          jsonb not null,       -- trilha de avaliação de cada condição
  justification     text not null,
  evidence          jsonb not null default '[]'::jsonb,
  review_status     public.review_status not null default 'pending_review',
  reviewed_by       uuid references public.users(id),
  reviewed_at       timestamptz,
  review_notes      text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique nulls not distinct (document_id, item_id, rule_id),
  foreign key (company_id, organization_id)
    references public.client_companies(id, organization_id) on delete cascade,
  foreign key (document_id, organization_id)
    references public.fiscal_documents(id, organization_id) on delete cascade,
  foreign key (item_id, organization_id)
    references public.fiscal_document_items(id, organization_id) on delete cascade
);
create index on public.tax_assessments (organization_id, company_id, review_status);

-- -----------------------------------------------------------------------------
-- Alertas
-- -----------------------------------------------------------------------------
create table public.alerts (
  id               uuid primary key default gen_random_uuid(),
  organization_id  uuid not null references public.organizations(id) on delete cascade,
  company_id       uuid,
  supplier_id      uuid,
  kind             text not null,
  severity         public.alert_severity not null default 'warning',
  status           public.alert_status not null default 'open',
  title            text not null,
  message          text,
  due_date         date,
  dedupe_key       text not null,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  resolved_at      timestamptz,
  foreign key (company_id, organization_id)
    references public.client_companies(id, organization_id) on delete cascade,
  foreign key (supplier_id, organization_id)
    references public.suppliers(id, organization_id) on delete cascade
);
-- Um alerta ativo por chave de deduplicação.
create unique index alerts_active_dedupe on public.alerts (organization_id, dedupe_key)
  where status <> 'resolved';
create index on public.alerts (organization_id, status, severity);

-- -----------------------------------------------------------------------------
-- Auditoria (append-only)
-- -----------------------------------------------------------------------------
create table public.audit_events (
  id               bigint generated always as identity primary key,
  organization_id  uuid,
  actor_id         uuid,
  action           text not null,
  entity_type      text not null,
  entity_id        uuid,
  before           jsonb,
  after            jsonb,
  metadata         jsonb not null default '{}'::jsonb,
  created_at       timestamptz not null default now()
);
create index on public.audit_events (organization_id, created_at desc);
create index on public.audit_events (entity_type, entity_id);

create or replace function app.audit_events_append_only() returns trigger
language plpgsql as $$
begin
  raise exception 'audit_events é append-only' using errcode = 'insufficient_privilege';
end $$;

create trigger audit_events_no_update before update or delete on public.audit_events
  for each row execute function app.audit_events_append_only();

create or replace function app.audit_row_change() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  v_old jsonb := case when tg_op in ('UPDATE','DELETE') then to_jsonb(old) end;
  v_new jsonb := case when tg_op in ('INSERT','UPDATE') then to_jsonb(new) end;
  v_row jsonb := coalesce(v_new, v_old);
  v_org uuid;
begin
  if tg_op = 'UPDATE' and (v_old - 'updated_at') = (v_new - 'updated_at') then
    return null;  -- nada relevante mudou
  end if;
  v_org := coalesce((v_row ->> 'organization_id')::uuid,
                    case when tg_table_name = 'organizations' then (v_row ->> 'id')::uuid end);
  insert into public.audit_events (organization_id, actor_id, action, entity_type, entity_id, before, after)
  values (v_org, auth.uid(), lower(tg_op), tg_table_name, (v_row ->> 'id')::uuid, v_old, v_new);
  return null;
end $$;

do $$
declare t text;
begin
  foreach t in array array[
    'organizations','organization_members','client_companies','company_memberships',
    'suppliers','supplier_company_links','evidence_documents','compliance_checks',
    'fiscal_documents','tax_rules','tax_assessments','erp_connections','alerts'
  ] loop
    execute format(
      'create trigger %I after insert or update or delete on public.%I
         for each row execute function app.audit_row_change()', t || '_audit', t);
  end loop;

  foreach t in array array[
    'organizations','users','organization_members','client_companies','suppliers',
    'erp_connections','integration_jobs','fiscal_documents','tax_rules','tax_assessments','alerts'
  ] loop
    execute format(
      'create trigger %I before update on public.%I
         for each row execute function app.set_updated_at()', t || '_updated_at', t);
  end loop;
end $$;
