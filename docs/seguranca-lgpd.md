# Segurança e LGPD

## Controles implementados

| Tema | Controle |
|---|---|
| Isolamento entre escritórios | RLS em todas as tabelas + checagem na API + FKs compostas por organização; testes automatizados de isolamento |
| Autenticação | JWT do Supabase Auth validado na API (HS256 ou JWKS/assimétrico), audiência `authenticated`, expiração obrigatória |
| Autorização | RBAC por organização (`admin`, `operator`, `viewer`) + liberação por empresa; somente leitura para `viewer` |
| Arquivos | Bucket privado; acesso apenas via API autenticada ou URL assinada de curta duração (`SIGNED_URL_TTL_SECONDS`); tipos de evidência restritos; limite de tamanho |
| XML | Parser sem DTD, entidades externas ou rede (proteção XXE / billion laughs) |
| CSV | Limites de tamanho/linhas; exportações protegidas contra injeção de fórmulas |
| Segredos | Somente em variáveis de ambiente; `service_role` nunca vai ao frontend; `erp_connections` guarda apenas `secret_ref` |
| Auditoria | Trigger em tabelas relevantes (antes/depois, autor); eventos de importação/exportação/reprocessamento; tabela append-only |
| Erros | Formato padronizado; mensagens internas de banco não são expostas |
| Transporte | HTTPS (Vercel/Render/Supabase); cabeçalhos de segurança no frontend; CORS restrito |

## LGPD — pontos para formalização

O sistema trata predominantemente dados de pessoas jurídicas, mas há dados
pessoais (usuários, e-mails/telefones de contato, CPF de destinatários em NF-e,
nomes em documentos).

- **Papéis**: o escritório contábil é, em regra, **controlador** dos dados dos
  seus clientes; o FiscalGuard (operador da plataforma) atua como **operador**.
  Formalizar em contrato/DPA, com lista de suboperadores (Supabase, Vercel,
  Render) e localização dos dados.
- **Bases legais** a documentar pelo controlador: cumprimento de obrigação legal
  /regulatória (art. 7º, II) e execução de contrato (art. 7º, V).
- **Minimização**: apenas os campos necessários do XML são normalizados; o XML
  original fica em armazenamento privado para fins de evidência.
- **Retenção**: definir prazo (ex.: prazo decadencial/prescricional tributário)
  e rotina de descarte; exclusão de organização remove dados em cascata.
- **Direitos dos titulares**: exportação via API/CSV; atendimento coordenado com
  o controlador.
- **Incidentes**: logs de aplicação + trilha de auditoria apoiam investigação;
  definir plano de resposta e comunicação à ANPD.
- **Acesso interno**: uso de `service_role` restrito ao backend/worker; acesso
  administrativo ao banco com MFA e registro.

## Recomendações antes da produção

1. Ativar MFA no Supabase Auth para administradores dos escritórios.
2. Configurar backups com PITR no Supabase e testar restauração periodicamente.
3. Rate limiting no proxy/hosting da API (uploads e autenticação).
4. Monitoramento de erros (ex.: Sentry) e alertas para tarefas `dead`.
5. Revisão de segurança independente (pentest) antes da operação comercial.
