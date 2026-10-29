# Implantação e operação

## Ambientes

Use **três projetos Supabase** (dev, homologação, produção) e, para cada um, um
par de serviços de API/worker e um ambiente na Vercel. Nunca compartilhe banco
ou chaves entre ambientes.

| Ambiente | Branch | Frontend | API/Worker | Banco/Auth/Storage |
|---|---|---|---|---|
| Desenvolvimento | qualquer | `npm run dev` | `uvicorn --reload` | Supabase CLI local ou projeto dev |
| Homologação | `staging` | Vercel Preview | Render (serviços `-staging`) | Projeto Supabase staging |
| Produção | `main` | Vercel Production | Render | Projeto Supabase produção |

## 1. Supabase

1. Crie o projeto e anote `Project URL`, `anon key`, `service_role key` e a
   connection string do Postgres.
2. Aplique as migrações:
   ```bash
   supabase link --project-ref <ref>
   supabase db push
   ```
3. Confirme que o bucket `fiscalguard-private` existe e está **privado**.
4. Em Auth: habilite confirmação de e-mail, configure URLs de redirecionamento do
   frontend e, se possível, MFA.
5. **Não** rode `seed-rules --publish` em produção: regras de exemplo não são
   validadas. Cadastre regras reais pela API/tela com validação de especialista.

## 2. API e worker (Render ou equivalente)

`render.yaml` define o serviço web (FastAPI) e o worker usando `backend/Dockerfile`
(contexto na raiz do repositório):

```bash
docker build -f backend/Dockerfile -t fiscalguard-api .
docker run --env-file backend/.env -p 8000:8000 fiscalguard-api
docker run --env-file backend/.env fiscalguard-api python -m app.cli worker
```

Health check: `GET /health`. Escale a API horizontalmente; múltiplos workers são
seguros (`FOR UPDATE SKIP LOCKED`).

## 3. Frontend (Vercel)

Diretório raiz `frontend/`, framework Next.js. Variáveis públicas:
`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_URL`.
Inclua o domínio do frontend em `CORS_ORIGINS` da API.

## Variáveis de ambiente — backend

| Variável | Obrigatória | Descrição |
|---|---|---|
| `ENVIRONMENT` | sim | `development`, `staging`, `production`, `test` |
| `DATABASE_URL` | sim | `postgresql+psycopg://…` — o usuário precisa poder executar `SET ROLE authenticated` (o `postgres` do Supabase pode) |
| `SUPABASE_URL` | sim* | Usada para JWKS (chaves assimétricas) e Storage |
| `SUPABASE_JWT_SECRET` | sim* | Segredo HS256 (projetos com chave JWT legada) |
| `SUPABASE_JWT_AUDIENCE` | não | Padrão `authenticated` |
| `SUPABASE_SERVICE_ROLE_KEY` | com storage Supabase | Somente no backend/worker |
| `STORAGE_BACKEND` | não | `local` (dev) ou `supabase` |
| `STORAGE_BUCKET` | não | Padrão `fiscalguard-private` |
| `LOCAL_STORAGE_DIR` | dev | Diretório do storage local |
| `SIGNED_URL_TTL_SECONDS` | não | Validade de URLs assinadas (padrão 300) |
| `MAX_UPLOAD_BYTES`, `MAX_FILES_PER_UPLOAD`, `INLINE_IMPORT_LIMIT`, `MAX_CSV_ROWS` | não | Limites de importação |
| `COMPLIANCE_REQUIRED_CHECKS` | não | JSON com verificações obrigatórias |
| `COMPLIANCE_EXPIRY_WARNING_DAYS` | não | Antecedência dos alertas de vencimento (padrão 15) |
| `CORS_ORIGINS` | sim | JSON com as origens do frontend |

\* ao menos uma forma de validação de JWT.

## Rotinas de operação

- **Varredura diária de compliance**: agende `POST /api/v1/organizations/{id}/compliance/scan/async`
  (ou um cron no Render executando um script equivalente) para gerar alertas de vencimento.
- **Reprocessamento**: tarefas com falha aparecem em "Importações e tarefas"; use
  "Reprocessar". Reanálise completa de uma empresa: `POST …/companies/{id}/reanalyze`.
- **Backups**: habilite backups diários e PITR no Supabase; o Storage deve ter
  política própria de backup/replicação. Teste a restauração trimestralmente em
  um projeto separado (restaurar → aplicar migrações pendentes → rodar a suíte de
  testes de isolamento contra a cópia).
- **Atualizações de esquema**: sempre por nova migração em `supabase/migrations/`,
  aplicada primeiro em homologação.
- **Logs**: a API registra em stdout (formato com data/nível/módulo); centralize
  no provedor de hospedagem.

## Dependências

| Backend | Uso |
|---|---|
| FastAPI / Uvicorn | API REST e servidor ASGI |
| SQLAlchemy Core + psycopg 3 | Acesso ao PostgreSQL |
| Pydantic / pydantic-settings | Validação e configuração |
| PyJWT[crypto] | Validação do JWT do Supabase |
| lxml | Parser XML seguro |
| python-multipart | Upload de arquivos |
| httpx | Supabase Storage |

| Frontend | Uso |
|---|---|
| Next.js / React | Interface |
| @supabase/ssr, @supabase/supabase-js | Autenticação |
| Tailwind CSS | Estilos |
