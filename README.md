# FiscalGuard

SaaS multi-tenant para escritórios de contabilidade: gestão de empresas atendidas,
**compliance de fornecedores** e identificação de **potenciais** oportunidades
tributárias a partir de XML de NF-e, com regras determinísticas, versionadas e
sujeitas a revisão humana.

> Nenhum resultado do sistema representa crédito tributário definitivamente
> aproveitável. Cada oportunidade traz justificativa, critérios avaliados,
> evidências e status de revisão. As regras incluídas são **exemplos** e precisam
> ser validadas por especialista antes do uso real.

## Estrutura

```
fiscalguard/
├── backend/            API FastAPI (Python 3.13)
│   ├── app/
│   │   ├── routers/    endpoints REST (organizações, fornecedores, fiscal, regras, revisão, operação)
│   │   ├── services/   parser NF-e, motor de regras, análise, compliance, importações, fila, storage
│   │   ├── domain/     CNPJ (inclusive alfanumérico), CPF, chave de acesso
│   │   ├── rules/      regras de EXEMPLO
│   │   └── cli.py      migrate · seed-rules · worker
│   └── tests/          unitários + integração com PostgreSQL real (RLS)
├── frontend/           Next.js 16 + TypeScript + Tailwind
├── supabase/
│   ├── migrations/     esquema, RLS, funções, bucket privado
│   └── local/          shim do Supabase para rodar em PostgreSQL puro (dev/testes)
├── samples/            CSV de fornecedores e XMLs de NF-e de exemplo
└── docs/               arquitetura, banco, regras, segurança/LGPD, implantação
```

## Início rápido (desenvolvimento local)

Pré-requisitos: Python 3.12+, Node 22+, PostgreSQL 15+ (ou Supabase CLI).

```bash
# 1. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # ajuste DATABASE_URL e SUPABASE_*
python -m app.cli migrate --local-shim   # PostgreSQL puro; com Supabase use `supabase db push`
python -m app.cli seed-rules --publish   # regras de EXEMPLO (somente desenvolvimento)
uvicorn app.main:app --reload            # http://localhost:8000/docs
python -m app.cli worker                 # em outro terminal: fila de importações
```

```bash
# 2. Frontend
cd frontend
npm install
cp .env.example .env.local      # URL/anon key do Supabase e URL da API
npm run dev                     # http://localhost:3000
```

Fluxo sugerido: criar conta → cadastrar escritório → cadastrar empresa →
importar `samples/fornecedores_exemplo.csv` → registrar certidões → selecionar a
empresa no topo e importar `samples/nfe_exemplo_*.xml` → revisar oportunidades.

## Testes

```bash
cd backend
TEST_DATABASE_ADMIN_URL=postgresql://postgres:postgres@localhost:5432/postgres python -m pytest
```

Os testes recriam o banco `fiscalguard_test`, aplicam as migrações com o shim do
Supabase e cobrem: validação de CNPJ/chave, parser NF-e (incluindo XXE), motor de
regras, compliance, importação CSV, **isolamento entre organizações (API e SQL
direto sob RLS)**, perfis de acesso, idempotência de importação, worker
assíncrono, versionamento/imutabilidade de regras e trilha de auditoria.

```bash
cd frontend && npm run typecheck && npm run build
```

## Documentação

| Documento | Conteúdo |
|---|---|
| [docs/arquitetura.md](docs/arquitetura.md) | Componentes, fluxos, decisões e pontos de extensão |
| [docs/banco-de-dados.md](docs/banco-de-dados.md) | Entidades, multi-tenancy, RLS, auditoria |
| [docs/motor-de-regras.md](docs/motor-de-regras.md) | Formato das regras, versionamento, reprodutibilidade |
| [docs/api.md](docs/api.md) | Visão geral dos endpoints (detalhes em `/docs`) |
| [docs/seguranca-lgpd.md](docs/seguranca-lgpd.md) | Controles de segurança e LGPD |
| [docs/implantacao.md](docs/implantacao.md) | Ambientes, variáveis, Supabase, Vercel, Render, backups |
