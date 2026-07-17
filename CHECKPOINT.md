# Checkpoint CP-0006

Atualizado em: 2026-07-17

## Objetivo

Executar P1 como auditoria read-only completa do baseline antes de qualquer alteração na skill.

## Estado atual

- Repositório-fonte: `/Users/enorm/Documents/Claude/loop-marketing`
- Branch de baseline: `main`
- Commit de baseline: `3cbf0cf84a038f2cd570883b70988889f037c28e`
- Worktree no baseline: limpo
- Biblioteca canônica: 100 prompts
- Autorização do usuário: recebida em 2026-07-17 (`pode iniciar`)
- Implementação v2: P1 iniciada em modo read-only
- Validação determinística: aprovada, sem erros
- Teste de retomada sem histórico: aprovado; fragilidades encontradas foram corrigidas
- Hash canônico da biblioteca: `0ef879b760619509adda24a7d928098f77cd2d4c392f53a3be7f530f14d549b1`
- Histórico dos arquivos de controle: ancorado em Git local, sem reescrita
- Commit inicial da âncora de controle: `ad3e04c61c89cc08a77089714f96d99fb15bbbfc`
- Validação dos logs: estrutura, campos, sequência, status, evidência e prefixo append-only
- Bundle de recuperação: `/Users/enorm/Documents/Claude/loop-marketing-v2-control-backup.bundle`
- Remoto: não configurado; requer autorização explícita
- Gate atual: `G2 — concluir e integrar a auditoria P1`

## Decisões vigentes

- Preservar integralmente a biblioteca tática canônica.
- Usar uma pasta de controle externa ao repositório da skill.
- Usar o agente principal como arquiteto e integrador.
- Executar subagentes em ondas, com arquivos e contratos não sobrepostos.
- Controlar fatos, decisões, estado e evidências em artefatos persistentes.
- Não alterar a skill durante P1; primeiro concluir o baseline auditável.

## Artefatos de continuidade

- `PROJECT.json`: objetivo, restrições, fases e critérios de aceite.
- `CONTEXT_PROTOCOL.md`: regras de reidratação, checkpoint e delegação.
- `DECISIONS.jsonl`: log append-only de decisões.
- `WORKLOG.jsonl`: log append-only de execução e verificações.
- `SOURCE_INDEX.json`: snapshot gerado dos arquivos-fonte e hashes.
- `CONTEXT_INDEX.json`: selo dos arquivos de controle e prefixos append-only dos logs.
- `scripts/context_guard.py`: snapshot e validação determinística.

## Critério de conclusão de P1

P1 é uma auditoria read-only. Ela termina apenas quando os 117 arquivos do baseline estiverem classificados; contradições, duplicidades, riscos e drift estiverem registrados com evidência; o hash dos 100 prompts permanecer intacto; e o agente principal integrar os três entregáveis definidos em `PROJECT.json`.

## Fontes mínimas para iniciar P1 após autorização

- `/Users/enorm/Documents/Claude/loop-marketing/SKILL.md`
- `/Users/enorm/Documents/Claude/loop-marketing/README.md`
- `/Users/enorm/Documents/Claude/loop-marketing/LEIAME.md`
- `/Users/enorm/Documents/Claude/loop-marketing/CLAUDE.md`
- `/Users/enorm/Documents/Claude/loop-marketing/AGENTS.md`
- `/Users/enorm/Documents/Claude/loop-marketing/commands/*.md`
- `/Users/enorm/Documents/Claude/loop-marketing/biblioteca/*/INDEX.md`
- `SOURCE_INDEX.json` para hashes; não carregar os 100 prompts em contexto.

## Próxima ação única

Executar as três frentes de auditoria, integrar os entregáveis de P1 e verificar os cinco critérios de saída.

## Proibido durante P1

- Alterar arquivos em `/Users/enorm/Documents/Claude/loop-marketing`.
- Reescrever, remover ou reduzir a biblioteca tática.
- Permitir que subagentes alterem o repositório-fonte ou o checkpoint canônico.
- Executar migrações ou integrações externas.
