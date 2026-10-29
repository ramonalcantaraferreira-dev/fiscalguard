-- =============================================================================
-- Bucket privado para XML, evidências e relatórios (somente no Supabase).
-- Nenhuma política de acesso é criada para anon/authenticated: os arquivos são
-- lidos e gravados exclusivamente pela API (service role) após checar permissões,
-- ou entregues por URLs assinadas de curta duração.
-- =============================================================================
do $$
begin
  if exists (select 1 from information_schema.tables where table_schema = 'storage' and table_name = 'buckets') then
    insert into storage.buckets (id, name, public, file_size_limit)
    values ('fiscalguard-private', 'fiscalguard-private', false, 10485760)
    on conflict (id) do update set public = false;
  end if;
end $$;
