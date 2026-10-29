# API

Documentação interativa (OpenAPI/Swagger): `GET /docs` · especificação: `GET /openapi.json`.

Autenticação: `Authorization: Bearer <access_token do Supabase>`. Rotas de dados
ficam sob `/api/v1/organizations/{org_id}/…`; organização inexistente ou sem
acesso responde **404** (não revela outros tenants).

Erros seguem sempre o formato:

```json
{"error": {"code": "forbidden", "message": "Perfil somente leitura", "details": null}}
```

| Código HTTP | `code` | Situação |
|---|---|---|
| 401 | `unauthorized` | Token ausente, inválido ou expirado |
| 403 | `forbidden` | Perfil sem permissão / bloqueio de RLS |
| 404 | `not_found` | Recurso inexistente ou de outro tenant |
| 409 | `conflict` | Duplicidade ou transição de estado inválida |
| 422 | `validation_error` / `invalid` | Dados inválidos |

## Endpoints

| Método e rota | Perfil | Descrição |
|---|---|---|
| `GET /api/v1/me` | todos | Usuário e organizações |
| `GET/POST /api/v1/organizations` | todos | Listar / criar escritório (criador vira admin) |
| `GET/POST/PATCH/DELETE …/members[/{user_id}]` | admin (escrita) | Equipe e perfis |
| `GET/POST/PATCH …/companies[/{id}]` | admin (escrita) | Empresas atendidas |
| `POST/DELETE …/companies/{id}/members[/{user_id}]` | admin | Liberar empresa para operador/visualizador |
| `GET/POST/PATCH …/suppliers[/{id}]` | operador+ (escrita) | Fornecedores |
| `POST …/suppliers/import` | operador+ | Importação CSV (upsert por CNPJ, relatório por linha) |
| `POST/DELETE …/suppliers/{id}/companies/{company_id}` | operador+ | Vínculo fornecedor × empresa |
| `GET/POST …/suppliers/{id}/checks` | operador+ (escrita) | Histórico / registro de verificação de compliance |
| `POST …/suppliers/{id}/evidence` · `GET …/evidence/{id}/download` | operador+ | Evidências privadas |
| `POST …/compliance/scan` · `POST …/compliance/scan/async` | operador+ | Recalcula status e alertas |
| `GET …/compliance/report?format=json\|csv` | todos | Relatório de regularidade |
| `POST …/companies/{id}/fiscal-documents/import[?async=true]` | operador+ | Importação de XML de NF-e |
| `GET …/fiscal-documents[/{id}]` · `GET …/fiscal-documents/{id}/xml` | todos | Consulta e download do XML |
| `POST …/fiscal-documents/{id}/analyze` · `POST …/companies/{id}/reanalyze` | operador+ | Reprocessar análises |
| `GET/POST/PATCH …/tax-rules[/{id}]` · `/versions` · `/publish` · `/retire` · `/test` · `/validate` | admin (escrita) | Regras tributárias |
| `GET …/assessments` · `/summary` · `/export` · `/{id}` | todos | Oportunidades e riscos |
| `PATCH …/assessments/{id}/review` | operador+ | Revisão humana (aprovar, rejeitar, pedir informação) |
| `GET/PATCH …/alerts[/{id}]` | todos / operador+ | Alertas |
| `GET …/jobs[/{id}]` · `POST …/jobs/{id}/retry` | todos / operador+ | Tarefas e reprocessamento |
| `GET …/dashboard` | todos | Indicadores consolidados (filtro `company_id`) |
| `GET …/audit-events` | admin | Trilha de auditoria |
| `GET /health` | público | Verificação de saúde (inclui banco) |

"operador+" = administrador ou operador com acesso à empresa envolvida.
