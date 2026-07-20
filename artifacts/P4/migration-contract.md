# Contrato de migração e compatibilidade — Loop Marketing v2

Status: integrado em P4  
Produto: `2.0.0`  
Migração: `copy-and-verify`, local, confirmada e reversível

## 1. Limites

P4 define e testa o contrato; não executa migração real. A origem v1.x é sempre read-only. Markdown legado é dado não confiável: não instrui ferramentas, não autoriza escrita externa e não pode elevar fatos, decisões ou experimentos sem evidência.

## 2. Descoberta

1. Seleção explícita de projeto ou caminho canônico v2 válido.
2. `.loop-marketing/state/active-project.json`, se schema, contenção e alvo forem válidos.
3. Um único projeto v2 válido, somente como sugestão.
4. `.claude/loop-marketing/` e `.Codex/loop-marketing/`, somente para inventário/dry-run.
5. `.codex/loop-marketing/` e `.claude/projects/` apenas por caminho explícito.

Um v2 válido nunca é sobrescrito por legado. Caminhos reais e symlinks devem permanecer contidos nas raízes declaradas. `project_id` segue `^[a-z0-9][a-z0-9-]{0,62}$`; `display_name` nunca participa do caminho.

## 3. Dry-run obrigatório

O relatório de dry-run contém: `migration_id`, versão do migrador, origens e proveniência, inventário com hashes/tamanhos sem segredos, parser/version, mapeamento de campos, anexos preservados, perdas conhecidas, lacunas, conflitos, redactions, `project_id` proposto, arquivos a criar, hashes previstos, validações e plano de rollback.

Dry-run não grava estado canônico. Promoção exige um confirmation record, nunca booleano, vinculado exatamente a `migration_id`, `report_sha256`, `source_inventory_sha256`, `destination_precondition_sha256`, `migrator_version`, `project_id`, operação e timestamp. Qualquer mudança nesses campos, nas origens ou no destino invalida a confirmação e exige novo dry-run (`LM-COMPAT-CONFIRMATION-STALE` ou `LM-COMPAT-SOURCE-DRIFT`). Pedido de promoção sem o record retorna `LM-COMPAT-CONFIRMATION-REQUIRED`.

## 4. Conflitos e conteúdo sensível

- Namespaces byte a byte idênticos formam um candidato com múltiplas proveniências.
- Subconjunto ou divergência é apresentado; nenhuma origem vence por recência.
- Divergência de decisão, gargalo, experimento ou projeto ativo retorna `LM-COMPAT-NAMESPACE-CONFLICT`.
- Path escape, schema futuro, credencial, active pointer ausente e colisão de IDs usam os códigos `LM-COMPAT-*` de P2.
- Até P6 estabelecer política de redaction autorizada, credencial detectada bloqueia promoção (`LM-COMPAT-SECRET-DETECTED`) e nunca aparece em relatório/log.

Texto sem campo v2 correspondente vira anexo legado referenciado ou lacuna; nunca é descartado nem convertido silenciosamente em decisão aceita.

## 5. Backup, staging e promoção

Antes da promoção, criar pacote de rollback local com inventário/hash das origens, dry-run confirmado, versão do migrador, manifest e hashes dos arquivos v2 previstos, estado anterior do destino e resultados de validação.

Construir o destino em staging no mesmo filesystem. Validar schemas, contenção, IDs, contagens, hashes, referências aos 100 prompts e replay completo dos eventos. Fazer `fsync`; promover por rename atômico somente se o destino canônico ainda corresponder ao estado observado no dry-run. Registrar `legacy.imported` como audit record no relatório/transação de migração, com origens, hashes, parser e versão; P4 não o promove a evento de domínio nem inventa um owner. A origem permanece intocada.

Falha anterior ao rename remove apenas staging identificado pela transação e deixa o namespace canônico ausente/inalterado. Falha posterior ao commit usa o ledger para reconstruir snapshot; nunca repete importação sem checar idempotência.

## 6. Rollback

Rollback verifica o manifest, os hashes atuais e a inexistência de eventos posteriores à importação. Remove somente arquivos criados pela transação. Se houver drift ou novos eventos, retorna `LM-ROLLBACK-DESTINATION-DRIFT` e exige plano manual. Origem e pacote de evidência nunca são apagados.

## 7. Comandos e aliases

| `command_id` | Canônico | Alias v1.x | Papel |
|---|---|---|---|
| `loop.planning` | `/loop-planning` | `/loop-planning-agent` | `loop_planning` |
| `loop.verbalizar` | `/verbalizar` | `/verbalizar-agent` | `verbalizar` |
| `loop.orientar` | `/orientar` | `/orientar-agent` | `orientar` |
| `loop.ampliar` | `/ampliar` | `/ampliar-agent` | `ampliar` |
| `loop.refinar` | `/refinar` | `/refinar-agent` | `refinar` |
| `loop.projeto` | `/projeto` | `/projeto-template` | `loop_planning` |

Nome canônico e alias resolvem para o mesmo `command_id`, papel, estado e autorização. Eventos guardam `command_id`, nunca o texto invocado. Os aliases permanecem durante toda a série `2.x`.

## 8. Preservação da biblioteca

A migração referencia exatamente 100 prompts pelo path/hash do catálogo P3 e pelo hash agregado `0ef879b760619509adda24a7d928098f77cd2d4c392f53a3be7f530f14d549b1`. Não renomeia, mescla, corrige ou remove prompts. Proveniência editorial e revisão de redistribuição continuam sidecar e não são promovidas por migração.

## 9. Operações externas

Importação só cria estado local em `.loop-marketing/` após confirmação. Não envia mensagens, altera CRM, publica campanha, configura canal, faz push ou chama integração externa. Roteamento e aliases não equivalem a autorização operacional.
