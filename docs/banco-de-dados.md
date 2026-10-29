# Banco de dados

Migrações em `supabase/migrations/` (ordem pelo prefixo de data):

| Migração | Conteúdo |
|---|---|
| `…01_core_schema.sql` | Tipos, tabelas, índices, triggers de `updated_at`, auditoria e imutabilidade de regras |
| `…02_rls_policies.sql` | Funções de autorização, RLS, `create_organization`, `add_org_member`, `log_event` |
| `…03_storage.sql` | Bucket privado no Supabase Storage |

## Entidades

| Tabela | Descrição | Tenant |
|---|---|---|
| `organizations` | Escritórios contábeis | é o tenant |
| `users` | Perfil espelhado de `auth.users` | — |
| `organization_members` | Usuário × organização × perfil (`admin`, `operator`, `viewer`) | ✓ |
| `client_companies` | Empresas atendidas (regime tributário, indústria) | ✓ |
| `company_memberships` | Empresas liberadas para operadores/visualizadores | ✓ |
| `suppliers` | Fornecedores (cadastro único por organização) + status de compliance | ✓ |
| `supplier_company_links` | Fornecedor × empresa compradora | ✓ |
| `compliance_checks` | Histórico append-only de verificações (fonte, data, validade, evidência) | ✓ |
| `evidence_documents` | Metadados de arquivos de evidência (SHA-256, caminho privado) | ✓ |
| `fiscal_documents` | NF-e normalizada, validações, hash do XML | ✓ |
| `fiscal_document_items` | Itens e tributos (ICMS, IPI, PIS, COFINS + grupos brutos) | ✓ |
| `tax_rules` | Regras versionadas (globais: `organization_id` nulo) | ✓/global |
| `tax_assessments` | Resultado de regra por documento/item, trilha, justificativa, revisão | ✓ |
| `alerts` | Alertas deduplicados (vencimento, irregularidade, pendência) | ✓ |
| `erp_connections` | Configuração de conectores (sem segredos) | ✓ |
| `integration_jobs` | Fila e histórico de importações/reprocessamentos | ✓ |
| `audit_events` | Trilha append-only | ✓ |

## Isolamento multi-tenant

- RLS habilitada em todas as tabelas de `public`. O role `anon` não tem acesso.
- Funções `app.org_role`, `app.is_org_admin`, `app.can_write_org`,
  `app.can_read_company`, `app.can_write_company` (SECURITY DEFINER,
  `search_path` vazio) concentram as regras de acesso.
- FKs compostas `(x_id, organization_id)` garantem que nenhuma linha referencia
  registro de outra organização.
- Testes em `backend/tests/test_isolation.py` verificam o isolamento pela API e
  por SQL direto no contexto do usuário.

## Integridade e auditoria

- `tax_rules`: trigger impede alterar regra publicada (exceto encerrar vigência
  ou aposentar). Unicidade `(organization_id, code, version)` com `NULLS NOT DISTINCT`.
- `tax_assessments`: único por `(documento, item, regra)`; RLS só permite apagar
  resultados ainda não revisados.
- `audit_events`: preenchida por trigger em INSERT/UPDATE/DELETE das tabelas
  relevantes (antes/depois em JSONB, autor = `auth.uid()`) e por `app.log_event`
  para eventos de aplicação (importações, exportações, reprocessamentos).
  UPDATE/DELETE são bloqueados por trigger, inclusive para o owner.
- `organization_members`: trigger impede remover o último administrador.

## Convenções

- Chaves primárias UUID (`gen_random_uuid()`); auditoria usa `bigint identity`.
- Valores monetários `numeric(18,2)`; alíquotas `numeric(9,4)`; quantidades `numeric(20,6)`.
- CNPJ em `varchar(14)` normalizado (suporta o formato alfanumérico).
