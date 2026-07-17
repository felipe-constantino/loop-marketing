# Checkpoint CP-0003

Atualizado em: 2026-07-17

## Objetivo

Preservar continuidade durável enquanto a implementação da nova versão do Loop Marketing aguarda autorização.

## Estado atual

- Repositório-fonte: `/Users/enorm/Documents/Claude/loop-marketing`
- Branch de baseline: `main`
- Commit de baseline: `3cbf0cf84a038f2cd570883b70988889f037c28e`
- Worktree no baseline: limpo
- Biblioteca canônica: 100 prompts
- Implementação v2: **não iniciada**
- Validação determinística: aprovada, sem erros
- Teste de retomada sem histórico: aprovado; fragilidades encontradas foram corrigidas
- Hash canônico da biblioteca: `0ef879b760619509adda24a7d928098f77cd2d4c392f53a3be7f530f14d549b1`
- Histórico dos arquivos de controle: ancorado em Git local, sem reescrita
- Gate atual: `G1 — aguardar autorização do usuário para iniciar a implementação`

## Decisões vigentes

- Preservar integralmente a biblioteca tática canônica.
- Usar uma pasta de controle externa ao repositório da skill.
- Usar o agente principal como arquiteto e integrador.
- Executar subagentes em ondas, com arquivos e contratos não sobrepostos.
- Controlar fatos, decisões, estado e evidências em artefatos persistentes.
- Não iniciar mudanças na skill antes da confirmação do usuário.

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

Após autorização explícita do usuário, iniciar P1 — auditoria e baseline — sem alterar a biblioteca canônica.

## Proibido até nova autorização

- Alterar arquivos em `/Users/enorm/Documents/Claude/loop-marketing`.
- Reescrever, remover ou reduzir a biblioteca tática.
- Iniciar agentes de implementação.
- Executar migrações ou integrações externas.
