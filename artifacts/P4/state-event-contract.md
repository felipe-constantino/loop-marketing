# Contrato de estado e eventos — Loop Marketing v2

Status: integrado em P4  
Produto: `2.0.0`  
Schema de estado/evento: `2.0`

## 1. Autoridade e fonte de verdade

O ledger append-only `.loop-marketing/state/projects/<project_id>/events.jsonl` é a fonte de verdade. `snapshots/latest.json` é uma projeção derivada e descartável. Prosa, reinício do agente, reexecução de comando ou estado de conversa nunca avançam a revisão.

Cada linha do ledger é uma transação comprometida com um ou mais eventos. Todos os eventos do batch carregam a mesma revisão lida em `state_revision` e a mesma revisão pretendida em `resulting_state_revision`. Uma transação nova avança exatamente uma revisão. O snapshot registra a revisão aplicada e `derived_from_revision`; revisão zero não possui transação anterior.

## 2. Compare-and-swap e exclusão por projeto

1. Resolver o caminho real e provar contenção em `.loop-marketing/state/projects/`.
2. Ler e validar ledger e snapshot; se o snapshot estiver atrás, reconstruí-lo antes de aceitar escrita.
3. Comparar a revisão informada com a revisão do head do ledger. Divergência retorna `ERR_STATE_REVISION_STALE` sem escrita.
4. Adquirir lock exclusivo por projeto, reler o head e repetir a comparação.
5. Validar schema, autoridade, evidência, handoffs referenciados, write sets e transições de experimento antes de integrar o batch.
6. Calcular idempotência, hash canônico e encadeamento antes de preparar qualquer arquivo.

O lock reduz colisões, mas não substitui o compare-and-swap. A decisão é baseada na revisão relida após o lock.

## 3. Commit recuperável

1. Criar arquivos temporários no mesmo filesystem do projeto.
2. Materializar o ledger completo anterior mais uma única linha de transação JSON terminada por newline; o prefixo anterior deve permanecer byte-for-byte.
3. Materializar o snapshot derivado e um registro de transação `prepared` com hashes pré/pós.
4. Fazer `fsync` dos arquivos temporários.
5. Renomear atomicamente o novo ledger sobre `events.jsonl`; este rename é o ponto de commit.
6. Fazer `fsync` do diretório do projeto.
7. Renomear atomicamente o snapshot e fazer `fsync` dos diretórios envolvidos.
8. Marcar a transação `committed` sem reescrever o evento.

Falha antes do passo 5 não muda o estado. Falha entre os passos 5 e 7 deixa o ledger à frente; a recuperação valida o hash-chain e reconstrói o snapshot. Um snapshot à frente do ledger é inválido e retorna `ERR_STATE_FABRICATION`.

## 4. Hash-chain e idempotência

`event_hash` e `record_hash` usam SHA-256 sobre JSON canônico RFC 8785, excluindo respectivamente o próprio `event_hash` e `record_hash`. O primeiro head usa `GENESIS`; os seguintes apontam para o hash anterior. A transação possui hash-chain próprio e os eventos preservam ordem e chain dentro e entre batches.

- Mesmos IDs/chaves de transação e eventos com o mesmo conteúdo canônico: replay idempotente do batch inteiro, `noop`, sem nova revisão.
- Mesmo identificador com conteúdo diferente: `LM-EVENT-IDEMPOTENCY-CONFLICT`.
- Retry parcial de batch: rejeitado.
- Hash inválido: `LM-EVENT-HASH-MISMATCH`.
- Encadeamento inválido: `LM-EVENT-CHAIN-BROKEN`.

## 5. Evidência, autoridade e experimentos

O mapa `x-loop-contract.authority_by_role` de `event-schema.json` reproduz exatamente os 33 tipos autorizados de P2. Especialistas não aceitam gargalo, sequência ou fechamento de ciclo; roteamento nunca eleva autorização externa. `cycle_closed`, recovery, rollback e `legacy.imported` não ganham autoridade de domínio nesta fase: vivem em relatórios de auditoria/transação até contrato explícito posterior.

Eventos exigem ao menos uma referência de evidência. Fatos exigem `source_ref` e `observed_at`; hipóteses exigem `rationale`. A máquina de experimento em `event-schema.json` reproduz `RTE-EXP-001` a `RTE-EXP-007`. Não há salto, reversão ou avanço por narrativa. Aprovação e lançamento são apenas registrados por Refinar após validar referências do ator externo; isso não concede a Refinar autoridade de aprovação ou execução.

## 6. Recuperação e quarentena

Na inicialização, validar schema, newline final, unicidade, idempotência, revisões, hashes e autoridade. Cauda parcial ou arquivo conflitante é copiado para `.loop-marketing/quarantine/` e bloqueia escrita automática. A recuperação pode reconstruir snapshots a partir do último ledger integralmente válido, mas nunca apaga o material em quarentena nem inventa a transição faltante.
