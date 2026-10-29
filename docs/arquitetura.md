# Arquitetura

```
Navegador (Next.js / TypeScript)
   │  1. login → Supabase Auth (JWT)
   │  2. chamadas REST com Authorization: Bearer <JWT>
   ▼
API FastAPI ──────────────► Supabase Storage (bucket privado)
   │  valida JWT, RBAC, regras de negócio
   │  cada requisição: SET LOCAL ROLE authenticated + claims do JWT
   ▼
PostgreSQL (Supabase) — RLS em todas as tabelas, auditoria por trigger
   ▲
Worker (python -m app.cli worker) — fila em integration_jobs (FOR UPDATE SKIP LOCKED)
```

## Decisões principais

**Defesa em profundidade no isolamento.** A API verifica o perfil do usuário na
organização (`deps.OrgContext`) e, além disso, executa todo SQL de usuário sob o
role `authenticated` com as claims do JWT, exatamente como o PostgREST do Supabase.
As políticas RLS valem, portanto, também para a API. FKs compostas
`(id, organization_id)` impedem referências entre tenants no nível do esquema.

**SQL explícito, sem ORM.** O esquema é definido em migrações SQL (fonte única de
verdade, aplicável com `supabase db push`). O backend usa SQLAlchemy Core com SQL
parametrizado — legível, auditável e sem divergência entre modelos e banco.

**Fila sobre PostgreSQL.** `integration_jobs` funciona como fila (sem Redis). Lotes
pequenos de XML são processados na própria requisição; lotes grandes ou
`?async=true` vão para o worker. O worker **impersona o usuário que criou a
tarefa**, então a RLS continua valendo e a auditoria registra o autor real.
Falhas são reprocessadas com backoff exponencial; após `max_attempts` a tarefa vai
para `dead` e pode ser reprocessada manualmente (`POST /jobs/{id}/retry`).

**Regras como dados.** Regras tributárias são JSON declarativo (sem código
executável), versionadas, com hash de conteúdo e imutáveis após publicação. Veja
[motor-de-regras.md](motor-de-regras.md).

**Idempotência.** NF-e é única por `(company_id, access_key)`; reenvio retorna
`duplicate`. Lotes idênticos reutilizam a mesma tarefa (chave de idempotência =
hash dos arquivos). Fornecedores via CSV fazem upsert por CNPJ. Reanálises nunca
sobrescrevem resultados já revisados.

## Fluxo de importação de NF-e

1. Upload → cada arquivo é salvo no storage com caminho derivado do SHA-256.
2. Cria `integration_job` (`nfe_import`).
3. Para cada arquivo, em SAVEPOINT próprio (falha isolada):
   - parser seguro (sem DTD/entidades) → normalização → validações
     (DV e campos da chave, CNPJ/CPF, soma dos itens × totais, protocolo);
   - verifica se a empresa é emitente (saída) ou destinatária (entrada);
     documentos de terceiros são rejeitados;
   - em entradas, cadastra/vincula o emitente como fornecedor;
   - grava documento e itens (tributos brutos em `raw_taxes`, preservando grupos
     futuros como IBS/CBS);
   - aplica as regras vigentes na data de emissão.
4. Resultado por arquivo (`imported`, `imported_with_errors`, `duplicate`,
   `rejected`, `failed`) fica registrado na tarefa.

## Pontos de extensão

| Necessidade | Onde |
|---|---|
| Conector ERP | Novo handler em `services/jobs.py` (`@handler("erp_sync")`), configuração em `erp_connections` (segredos em cofre, referenciados por `secret_ref`) |
| Consulta automática a fontes oficiais | Handler que grava `compliance_checks` com `source`/`source_reference` e evidência; o `scan_compliance` já recalcula status e alertas |
| Novos documentos (NFS-e, CT-e) | Novo parser em `services/` produzindo a mesma estrutura de documento/itens |
| Novos fatos para regras | Colunas em `fiscal_documents`/`items`/`client_companies` ficam disponíveis automaticamente como `document.*`, `item.*`, `company.*` |
| Notificações (e-mail) | Consumir `alerts` abertos em um handler agendado |
