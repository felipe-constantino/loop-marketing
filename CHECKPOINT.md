# Checkpoint CP-0007

Atualizado em: 2026-07-17

## Objetivo

Executar P2 como especificação canônica da v2, usando o baseline auditado e sem alterar ainda a skill nem a biblioteca tática.

## Estado atual

- Repositório-fonte: `/Users/enorm/Documents/Claude/loop-marketing`
- Branch de baseline: `main`
- Commit de baseline: `3cbf0cf84a038f2cd570883b70988889f037c28e`
- Worktree no baseline: limpo
- Biblioteca canônica: 100 prompts
- Autorização do usuário: recebida em 2026-07-17 (`pode iniciar`)
- Implementação v2: P1 concluída; P2 iniciada em modo de especificação
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
- Gate atual: `G3 — concluir e validar a especificação canônica P2`

## Decisões vigentes

- Preservar integralmente a biblioteca tática canônica.
- Usar uma pasta de controle externa ao repositório da skill.
- Usar o agente principal como arquiteto e integrador.
- Executar subagentes em ondas, com arquivos e contratos não sobrepostos.
- Controlar fatos, decisões, estado e evidências em artefatos persistentes.
- P1 permaneceu read-only e foi concluída antes de abrir a especificação da v2.
- Fixar contratos e fronteiras canônicas antes de implementar runtime, estado ou segurança.
- Tratar aliases e metadados como camadas sobre a biblioteca; não fundir ou remover prompts canônicos.

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

## Próxima ação única

Produzir, integrar e validar os quatro entregáveis canônicos de P2.

## Proibido durante P2

- Alterar arquivos em `/Users/enorm/Documents/Claude/loop-marketing`.
- Reescrever, remover ou reduzir a biblioteca tática.
- Permitir que subagentes alterem o repositório-fonte, artefatos oficiais integrados ou o checkpoint canônico.
- Executar migrações ou integrações externas.
