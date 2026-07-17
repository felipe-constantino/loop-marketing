# Checkpoint CP-0011

Atualizado em: 2026-07-17

## Objetivo

Executar P4 para definir contratos versionados de estado, eventos, handoffs e migração, usando P2 e o catálogo P3 selado.

## Estado atual

- Repositório-fonte: `/Users/enorm/Documents/Claude/loop-marketing`
- Branch de baseline: `main`
- Commit de baseline: `3cbf0cf84a038f2cd570883b70988889f037c28e`
- Worktree no baseline: limpo
- Biblioteca canônica: 100 prompts
- Autorização do usuário: recebida em 2026-07-17 (`pode iniciar`)
- Implementação v2: P1, P2 e P3 concluídas; P4 iniciada em modo de contratos sidecar
- Validação determinística: aprovada, sem erros
- Teste de retomada sem histórico: aprovado; fragilidades encontradas foram corrigidas
- Hash canônico da biblioteca: `0ef879b760619509adda24a7d928098f77cd2d4c392f53a3be7f530f14d549b1`
- Histórico dos arquivos de controle: ancorado em Git local, sem reescrita
- Commit inicial da âncora de controle: `ad3e04c61c89cc08a77089714f96d99fb15bbbfc`
- Validação dos logs: estrutura, campos, sequência, status, evidência e prefixo append-only
- Bundle de recuperação: `/Users/enorm/Documents/Claude/loop-marketing-v2-control-backup.bundle`
- Remoto: não configurado; requer autorização explícita
- Cobertura P1: 117/117 arquivos classificados; três frentes integradas
- Achados P1: 34 achados brutos consolidados em 19 riscos priorizados
- Critérios de saída P1: 5/5 comprovados por validação determinística
- Fonte após P1: limpa e no commit de baseline
- P2: quatro artefatos oficiais + manifesto de integração concluídos
- P2: dois gates independentes aprovaram; último gate com zero achados bloqueantes e não bloqueantes
- Contrato P2: cinco papéis, um owner por decisão, 22 campos de handoff e 30 códigos de rejeição
- Compatibilidade P2: comandos curtos canônicos, aliases v1.x e estado único em `.loop-marketing/`
- Schema P3: válido e com política confirmed-only para efeito normativo
- Workstreams P3: 4/4 válidos, 100 entradas únicas e 100/100 prompts preservados
- Revisão integral registrada: 17.454 linhas nos 100 corpos canônicos
- Políticas de execução: 100/100 válidas, com 323 conflitos de linha e 278 handoffs
- Modos: 3 canonical_safe, 91 sidecar_constrained e 6 base_method_only
- Seleção: 3 allowed, 91 planner_review_required e 6 forbidden
- Relações: 106/106 hipóteses reproduzidas; 91 confirmadas e 12 rejeitadas após consolidação
- Metadados: 55 táticas em desenvolvimento, 37 maduras, 5 nascentes e 3 avançadas
- Qualidade: 38 entradas precisam de revisão editorial; flags não alteram o canônico
- Proveniência: individual_source_verified=false e redistribution_review=not_reviewed em 100/100
- Red-team semântico: primeiro gate FAIL, segundo gate FAIL e reteste final PASS com histórico preservado
- Regressão negativa: baselines PASS e 16/16 mutações inseguras corretamente rejeitadas
- Artefatos oficiais P3: catálogo 100, mapa 91 relações, relatório de preservação e manifesto selado
- Gate final P3: validator PASS, auditoria PASS, regressão 16/16 e selo verificável
- Gate atual: `G5 — concluir contratos e migração P4`

## Decisões vigentes

- Preservar integralmente a biblioteca tática canônica.
- Usar uma pasta de controle externa ao repositório da skill.
- Usar o agente principal como arquiteto e integrador.
- Executar subagentes em ondas, com arquivos e contratos não sobrepostos.
- Controlar fatos, decisões, estado e evidências em artefatos persistentes.
- P1 permaneceu read-only e foi concluída antes de abrir a especificação da v2.
- Fixar contratos e fronteiras canônicas antes de implementar runtime, estado ou segurança.
- Tratar aliases e metadados como camadas sobre a biblioteca; não fundir ou remover prompts canônicos.
- Usar zero táticas quando não houver match seguro; uma por padrão e no máximo duas por `route_node_id`.
- Tratar maturidade ausente como `unknown`, nunca como `nascente` por fallback.
- Permitir efeito normativo no roteador somente para relações confirmadas; relações propostas são audit-only.
- Tratar revisão jurídica de redistribuição como restrição de release, não como autorização implícita de P3.
- Aplicar um de três modos por tática: canonical_safe, sidecar_constrained ou base_method_only.
- Exigir fail-closed quando overlay, revisão do planner ou handoff obrigatório não estiver disponível.

## Artefatos de continuidade

- `PROJECT.json`: objetivo, restrições, fases e critérios de aceite.
- `CONTEXT_PROTOCOL.md`: regras de reidratação, checkpoint e delegação.
- `DECISIONS.jsonl`: log append-only de decisões.
- `WORKLOG.jsonl`: log append-only de execução e verificações.
- `SOURCE_INDEX.json`: snapshot gerado dos arquivos-fonte e hashes.
- `CONTEXT_INDEX.json`: selo dos arquivos de controle e prefixos append-only dos logs.
- `scripts/context_guard.py`: snapshot e validação determinística.

## Resultado de P1

P1 foi concluída em modo read-only. Os 117 arquivos estão classificados; os achados possuem evidência; os três entregáveis oficiais foram integrados; e os 100 prompts mantêm o hash agregado do baseline.

## Entregáveis oficiais de P1

- `artifacts/P1/audit.json`
- `artifacts/P1/architecture-map.md`
- `artifacts/P1/risk-register.json`
- `artifacts/P1/inventory.json` e `artifacts/P1/workstreams/*.json` como evidências auxiliares

## Contrato de P2

- Definir a versão e a terminologia canônicas, independentes de Claude ou Codex.
- Definir autoridade, entradas, saídas e não-objetivos do planner e dos quatro pilares.
- Resolver ordem, paralelismo, colisões, handoffs, thresholds, enums e nomes de comandos.
- Definir aliases e migração compatível para o produto anterior.
- Não implementar sobre uma decisão ambígua e não alterar os 100 prompts durante a especificação.

## Resultado de P2

- `artifacts/P2/canonical-spec.md`: definição, camadas, invariantes e fluxo canônicos.
- `artifacts/P2/role-matrix.json`: owners, fronteiras, escalonamentos e handoff único.
- `artifacts/P2/routing-contract.json`: roteamento, maturidade, táticas, thresholds, estados e rejeições.
- `artifacts/P2/compatibility-policy.md`: comandos, aliases, namespace, migração e rollback.
- `artifacts/P2/integration-manifest.json`: hashes dos artefatos, workstreams e scripts.
- `artifacts/P2/workstreams/final-cross-audit.json` e `final-gate.json`: gates independentes aprovados.

## Contrato de P3

- Criar uma entrada sidecar para cada prompt, sem editar o arquivo canônico.
- Fixar IDs, tags funcionais, inputs, outputs, maturidade, pré-requisitos e contraindicações.
- Modelar dependência, complemento, sobreposição, alias e colisão como relações auditáveis.
- Registrar risco editorial/tradução como flag de revisão, não como prova automática de erro.
- Provar 100/100 paths e hashes antes de fechar a fase.

## Resultado intermediário de P3

- `artifacts/P3/catalog-schema.json`: schema sidecar e política relacional definidos.
- `artifacts/P3/workstreams/verbalizar.json`: 25/25 entradas e 14 relações internas.
- `artifacts/P3/workstreams/orientar.json`: 25/25 entradas e 28 relações internas.
- `artifacts/P3/workstreams/ampliar.json`: 25/25 entradas e 16 relações internas.
- `artifacts/P3/workstreams/refinar.json`: 25/25 entradas e 20 relações internas.
- `scripts/p3_validate.py`: valida schema, cada pilar, cobertura agregada, replay relacional e artefatos finais.
- `scripts/p3_integrate.py`: integração determinística preparada; só executa após workstreams e relações válidos.
- `scripts/p3_regression.py`: 16 casos negativos em sandbox temporário, todos aprovados.
- `scripts/p3_seal.py`: selo e verificação do conjunto de evidências após os gates finais.
- `artifacts/P3/workstreams/catalog-cross-audit-3pillars.json`: gate inicial FAIL, preservado.
- `artifacts/P3/workstreams/catalog-final-audit.json`: reteste final PASS, blockers=0 e FAIL anterior preservado.
- Gate agregado atual: `python3 scripts/p3_validate.py workstreams` aprovado com zero erros.
- Fonte canônica: limpa e ancorada no baseline após as quatro revisões.

## Resultado final de P3

- `artifacts/P3/tactic-catalog.json`: 100 táticas, paths/hashes e políticas de execução.
- `artifacts/P3/relationship-map.json`: 91 relações confirmadas; zero propostas normativas.
- `artifacts/P3/preservation-report.json`: cobertura, qualidade, proveniência e integridade comprovadas.
- `artifacts/P3/workstreams/relation-review.json`: replay de 106/106 inputs, 94 confirm e 12 reject.
- `artifacts/P3/integration-manifest.json`: 15 arquivos de evidência selados e verificados.
- `python3 scripts/p3_validate.py final`: PASS.
- `python3 scripts/p3_regression.py`: PASS, 16/16 casos negativos.
- `python3 scripts/p3_seal.py verify`: PASS.

## Contrato de P4

- Definir state schema, event ledger e atomicidade sem implementar ainda adaptadores de host.
- Materializar o handoff P2 de 22 campos e validar owner, revisão e scope boundary.
- Tornar transições de experimento evidence-gated e imutáveis no histórico.
- Definir migração v1.x com dry-run, backup, rollback e aliases completos.
- Manter `/Users/enorm/Documents/Claude/loop-marketing` read-only durante P4.

## Próxima ação única

Executar três workstreams P4 não sobrepostos, integrar schemas/contrato/fixtures e rodar red-team de migração e concorrência.

## Proibido durante P3

- Alterar arquivos em `/Users/enorm/Documents/Claude/loop-marketing`.
- Reescrever, remover ou reduzir a biblioteca tática.
- Permitir que subagentes alterem o repositório-fonte, artefatos oficiais integrados ou o checkpoint canônico.
- Executar migrações ou integrações externas.
