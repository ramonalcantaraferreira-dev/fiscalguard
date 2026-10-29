-- =============================================================================
-- FiscalGuard — Row Level Security e funções de autorização
-- -----------------------------------------------------------------------------
-- Modelo de perfis (RBAC):
--   admin    → acesso total à organização (empresas, usuários, regras, auditoria)
--   operator → leitura/escrita apenas nas empresas vinculadas (company_memberships);
--              pode gerenciar fornecedores e compliance da organização
--   viewer   → somente leitura nas empresas vinculadas
-- A API valida as mesmas regras; o banco é a segunda linha de defesa.
-- =============================================================================

-- Funções SECURITY DEFINER evitam recursão de RLS ao consultar memberships.
create or replace function app.org_role(p_org uuid) returns public.member_role
language sql stable security definer set search_path = '' as $$
  select m.role from public.organization_members m
   where m.organization_id = p_org and m.user_id = auth.uid()
$$;

create or replace function app.is_org_member(p_org uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select app.org_role(p_org) is not null
$$;

create or replace function app.is_org_admin(p_org uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select coalesce(app.org_role(p_org) = 'admin', false)
$$;

create or replace function app.can_write_org(p_org uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select coalesce(app.org_role(p_org) in ('admin', 'operator'), false)
$$;

create or replace function app.can_read_company(p_company uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1
      from public.client_companies c
      join public.organization_members m
        on m.organization_id = c.organization_id and m.user_id = auth.uid()
     where c.id = p_company
       and (m.role = 'admin'
            or exists (select 1 from public.company_memberships cm
                        where cm.company_id = c.id and cm.user_id = auth.uid()))
  )
$$;

create or replace function app.can_write_company(p_company uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1
      from public.client_companies c
      join public.organization_members m
        on m.organization_id = c.organization_id and m.user_id = auth.uid()
     where c.id = p_company
       and (m.role = 'admin'
            or (m.role = 'operator'
                and exists (select 1 from public.company_memberships cm
                             where cm.company_id = c.id and cm.user_id = auth.uid())))
  )
$$;

-- Cria organização e torna o chamador administrador (operação atômica).
create or replace function public.create_organization(p_name text, p_cnpj text default null)
returns uuid
language plpgsql security definer set search_path = '' as $$
declare
  v_uid uuid := auth.uid();
  v_org uuid;
begin
  if v_uid is null then
    raise exception 'não autenticado' using errcode = 'insufficient_privilege';
  end if;
  if not exists (select 1 from public.users where id = v_uid) then
    insert into public.users (id, email)
    select id, coalesce(email, '') from auth.users where id = v_uid;
  end if;
  insert into public.organizations (name, cnpj) values (p_name, p_cnpj) returning id into v_org;
  insert into public.organization_members (organization_id, user_id, role) values (v_org, v_uid, 'admin');
  return v_org;
end $$;

-- Sincroniza auth.users → public.users (apenas no Supabase real; o shim local não usa).
create or replace function app.handle_new_auth_user() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  insert into public.users (id, email, full_name)
  values (new.id, coalesce(new.email, ''), new.raw_user_meta_data ->> 'full_name')
  on conflict (id) do nothing;
  return new;
end $$;

do $$
begin
  if exists (select 1 from information_schema.columns
              where table_schema = 'auth' and table_name = 'users' and column_name = 'raw_user_meta_data') then
    execute 'create trigger on_auth_user_created after insert on auth.users
               for each row execute function app.handle_new_auth_user()';
  end if;
end $$;

-- -----------------------------------------------------------------------------
-- Permissões básicas (RLS controla as linhas)
-- -----------------------------------------------------------------------------
revoke all on all tables in schema public from anon;
grant usage on schema app to authenticated, service_role;
grant execute on all functions in schema app to authenticated, service_role;
grant select, insert, update, delete on all tables in schema public to authenticated, service_role;
grant usage, select on all sequences in schema public to authenticated, service_role;
revoke update, delete on public.audit_events from authenticated;
revoke insert on public.audit_events from authenticated;
grant execute on function public.create_organization(text, text) to authenticated;
revoke execute on function public.create_organization(text, text) from anon, public;

-- -----------------------------------------------------------------------------
-- Habilita RLS em todas as tabelas
-- -----------------------------------------------------------------------------
do $$
declare t text;
begin
  for t in select tablename from pg_tables where schemaname = 'public' loop
    execute format('alter table public.%I enable row level security', t);
  end loop;
end $$;

-- organizations
create policy org_select on public.organizations for select to authenticated
  using (app.is_org_member(id));
create policy org_update on public.organizations for update to authenticated
  using (app.is_org_admin(id)) with check (app.is_org_admin(id));

-- users: o próprio usuário e colegas de organização
create policy users_select on public.users for select to authenticated
  using (id = auth.uid() or exists (
    select 1 from public.organization_members a
      join public.organization_members b on a.organization_id = b.organization_id
     where a.user_id = auth.uid() and b.user_id = users.id));
create policy users_insert_self on public.users for insert to authenticated
  with check (id = auth.uid());
create policy users_update_self on public.users for update to authenticated
  using (id = auth.uid()) with check (id = auth.uid());

-- organization_members
create policy members_select on public.organization_members for select to authenticated
  using (app.is_org_member(organization_id));
create policy members_admin_all on public.organization_members for all to authenticated
  using (app.is_org_admin(organization_id)) with check (app.is_org_admin(organization_id));

-- client_companies
-- Não usa app.can_read_company(id): a função não enxerga a linha recém-inserida
-- (snapshot do comando), o que quebraria INSERT ... RETURNING.
create policy companies_select on public.client_companies for select to authenticated
  using (app.is_org_admin(organization_id)
         or (app.is_org_member(organization_id)
             and exists (select 1 from public.company_memberships cm
                          where cm.company_id = client_companies.id and cm.user_id = auth.uid())));
create policy companies_insert on public.client_companies for insert to authenticated
  with check (app.is_org_admin(organization_id));
create policy companies_update on public.client_companies for update to authenticated
  using (app.is_org_admin(organization_id)) with check (app.is_org_admin(organization_id));
create policy companies_delete on public.client_companies for delete to authenticated
  using (app.is_org_admin(organization_id));

-- company_memberships
create policy cm_select on public.company_memberships for select to authenticated
  using (app.is_org_admin(organization_id) or user_id = auth.uid());
create policy cm_admin_all on public.company_memberships for all to authenticated
  using (app.is_org_admin(organization_id)) with check (app.is_org_admin(organization_id));

-- suppliers (cadastro compartilhado na organização)
create policy suppliers_select on public.suppliers for select to authenticated
  using (app.is_org_member(organization_id));
create policy suppliers_insert on public.suppliers for insert to authenticated
  with check (app.can_write_org(organization_id));
create policy suppliers_update on public.suppliers for update to authenticated
  using (app.can_write_org(organization_id)) with check (app.can_write_org(organization_id));
create policy suppliers_delete on public.suppliers for delete to authenticated
  using (app.is_org_admin(organization_id));

-- supplier_company_links
create policy scl_select on public.supplier_company_links for select to authenticated
  using (app.can_read_company(company_id));
create policy scl_insert on public.supplier_company_links for insert to authenticated
  with check (app.can_write_company(company_id));
create policy scl_delete on public.supplier_company_links for delete to authenticated
  using (app.can_write_company(company_id));

-- evidence_documents
create policy evidence_select on public.evidence_documents for select to authenticated
  using (app.is_org_member(organization_id)
         and (company_id is null or app.can_read_company(company_id)));
create policy evidence_insert on public.evidence_documents for insert to authenticated
  with check (app.can_write_org(organization_id)
              and (company_id is null or app.can_write_company(company_id)));

-- compliance_checks (append-only: sem update/delete)
create policy checks_select on public.compliance_checks for select to authenticated
  using (app.is_org_member(organization_id));
create policy checks_insert on public.compliance_checks for insert to authenticated
  with check (app.can_write_org(organization_id));

-- fiscal_documents
create policy fd_select on public.fiscal_documents for select to authenticated
  using (app.can_read_company(company_id));
create policy fd_insert on public.fiscal_documents for insert to authenticated
  with check (app.can_write_company(company_id));
create policy fd_update on public.fiscal_documents for update to authenticated
  using (app.can_write_company(company_id)) with check (app.can_write_company(company_id));
create policy fd_delete on public.fiscal_documents for delete to authenticated
  using (app.is_org_admin(organization_id));

-- fiscal_document_items (herdam o acesso do documento)
create policy fdi_select on public.fiscal_document_items for select to authenticated
  using (exists (select 1 from public.fiscal_documents d
                  where d.id = document_id and app.can_read_company(d.company_id)));
create policy fdi_insert on public.fiscal_document_items for insert to authenticated
  with check (exists (select 1 from public.fiscal_documents d
                       where d.id = document_id and app.can_write_company(d.company_id)));
create policy fdi_delete on public.fiscal_document_items for delete to authenticated
  using (exists (select 1 from public.fiscal_documents d
                  where d.id = document_id and app.can_write_company(d.company_id)));

-- tax_rules: globais visíveis a todos; regras da organização geridas por admins
create policy rules_select on public.tax_rules for select to authenticated
  using (organization_id is null or app.is_org_member(organization_id));
create policy rules_insert on public.tax_rules for insert to authenticated
  with check (organization_id is not null and app.is_org_admin(organization_id));
create policy rules_update on public.tax_rules for update to authenticated
  using (organization_id is not null and app.is_org_admin(organization_id))
  with check (organization_id is not null and app.is_org_admin(organization_id));

-- tax_assessments
create policy ta_select on public.tax_assessments for select to authenticated
  using (app.can_read_company(company_id));
create policy ta_insert on public.tax_assessments for insert to authenticated
  with check (app.can_write_company(company_id));
create policy ta_update on public.tax_assessments for update to authenticated
  using (app.can_write_company(company_id)) with check (app.can_write_company(company_id));
-- Só resultados ainda não revisados podem ser descartados (reprocessamento).
create policy ta_delete on public.tax_assessments for delete to authenticated
  using (app.can_write_company(company_id) and review_status = 'pending_review');

-- alerts
create policy alerts_select on public.alerts for select to authenticated
  using (app.is_org_member(organization_id)
         and (company_id is null or app.can_read_company(company_id)));
create policy alerts_insert on public.alerts for insert to authenticated
  with check (app.can_write_org(organization_id));
create policy alerts_update on public.alerts for update to authenticated
  using (app.can_write_org(organization_id)) with check (app.can_write_org(organization_id));

-- erp_connections (apenas admin/operator; configuração sem segredos)
create policy erp_select on public.erp_connections for select to authenticated
  using (app.can_write_org(organization_id));
create policy erp_admin_all on public.erp_connections for all to authenticated
  using (app.is_org_admin(organization_id)) with check (app.is_org_admin(organization_id));

-- integration_jobs
create policy jobs_select on public.integration_jobs for select to authenticated
  using (app.is_org_member(organization_id)
         and (company_id is null or app.can_read_company(company_id)));
create policy jobs_insert on public.integration_jobs for insert to authenticated
  with check (app.can_write_org(organization_id)
              and (company_id is null or app.can_write_company(company_id)));
create policy jobs_update on public.integration_jobs for update to authenticated
  using (app.can_write_org(organization_id)) with check (app.can_write_org(organization_id));

-- audit_events: somente leitura para administradores
create policy audit_select on public.audit_events for select to authenticated
  using (organization_id is not null and app.is_org_admin(organization_id));

-- Eventos de aplicação (importações, exportações, reprocessamentos) na trilha de auditoria.
create or replace function app.log_event(
  p_org uuid, p_action text, p_entity_type text, p_entity_id uuid default null,
  p_metadata jsonb default '{}'::jsonb
) returns void
language plpgsql security definer set search_path = '' as $$
begin
  if not app.is_org_member(p_org) then
    raise exception 'sem acesso à organização' using errcode = 'insufficient_privilege';
  end if;
  insert into public.audit_events (organization_id, actor_id, action, entity_type, entity_id, metadata)
  values (p_org, auth.uid(), p_action, p_entity_type, p_entity_id, coalesce(p_metadata, '{}'::jsonb));
end $$;
grant execute on function app.log_event(uuid, text, text, uuid, jsonb) to authenticated;

-- Adiciona um usuário já cadastrado (por e-mail) à organização. Apenas administradores.
create or replace function public.add_org_member(p_org uuid, p_email text, p_role public.member_role)
returns uuid
language plpgsql security definer set search_path = '' as $$
declare
  v_user uuid;
  v_id uuid;
begin
  if not app.is_org_admin(p_org) then
    raise exception 'apenas administradores' using errcode = 'insufficient_privilege';
  end if;
  select id into v_user from public.users where lower(email) = lower(trim(p_email));
  if v_user is null then
    raise exception 'usuário não encontrado' using errcode = 'no_data_found';
  end if;
  insert into public.organization_members (organization_id, user_id, role)
  values (p_org, v_user, p_role)
  on conflict (organization_id, user_id) do update set role = excluded.role
  returning id into v_id;
  return v_id;
end $$;
grant execute on function public.add_org_member(uuid, text, public.member_role) to authenticated;
revoke execute on function public.add_org_member(uuid, text, public.member_role) from anon, public;

-- Impede que a organização fique sem administrador.
create or replace function app.keep_one_admin() returns trigger
language plpgsql as $$
declare v_org uuid := coalesce(old.organization_id, new.organization_id);
begin
  if old.role = 'admin' and (tg_op = 'DELETE' or new.role <> 'admin') then
    if not exists (select 1 from public.organization_members
                    where organization_id = v_org and role = 'admin' and id <> old.id)
       and exists (select 1 from public.organizations where id = v_org) then
      raise exception 'a organização precisa de ao menos um administrador' using errcode = 'check_violation';
    end if;
  end if;
  return coalesce(new, old);
end $$;
create trigger organization_members_keep_admin before update or delete on public.organization_members
  for each row execute function app.keep_one_admin();
