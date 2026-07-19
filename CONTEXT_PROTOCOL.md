# Protocolo de continuidade — Loop Marketing v2

Este diretório é o plano de controle durável do projeto. Ele fica separado do repositório da skill para preservar a fonte canônica e permitir retomadas sem depender da conversa.

## Reidratação obrigatória

Ao iniciar ou retomar qualquer turno material:

1. Ler `PROJECT.json`.
2. Ler `CHECKPOINT.md`.
3. Ler apenas as últimas entradas relevantes de `DECISIONS.jsonl` e `WORKLOG.jsonl`.
4. Executar `python3 scripts/context_guard.py validate`.
5. Abrir somente os arquivos-fonte citados no checkpoint para a unidade atual.
6. Não reler a biblioteca inteira; selecionar recursos pelo índice ou catálogo.

Se houver divergência entre conversa e arquivos, o estado registrado prevalece até que o agente principal documente uma nova decisão.

## Regra de checkpoint

Somente o agente principal atualiza o checkpoint canônico. Atualizar `CHECKPOINT.md`, os logs e o snapshot:

- antes e depois de cada fase;
- antes de delegar trabalho;
- após integrar um subagente;
- após qualquer alteração material no repositório-fonte;
- antes de testes longos;
- sempre que uma decisão mudar escopo, arquitetura ou critério de aceite;
- antes de encerrar um turno com trabalho incompleto.

Cada checkpoint deve registrar objetivo, gate atual, fatos verificados, decisões vigentes, arquivos alterados, testes executados, riscos, pendências e próxima ação única.

## Disciplina de contexto

- Manter o checkpoint curto: estado atual, não narrativa histórica.
- Manter decisões em `DECISIONS.jsonl`, uma entrada JSON por linha, sem reescrever o passado.
- Manter execução em `WORKLOG.jsonl`, com evidência e caminhos de arquivos, sem colar dumps extensos.
- Guardar detalhes grandes nos arquivos de origem e referenciá-los por caminho e hash.
- Carregar no máximo os recursos necessários para a unidade de trabalho atual.
- Para subagentes, fornecer apenas contrato da tarefa, fontes mínimas, arquivos sob responsabilidade e critério de aceite.
- Não passar ao subagente a conclusão esperada durante avaliações independentes.

## Proteção da qualidade

- Nenhuma decisão arquitetural existe apenas na conversa.
- Nenhuma conclusão de teste existe apenas em comentário do agente.
- Nenhum agente declara trabalho de outro agente como integrado.
- Nenhuma compactação autoriza rediagnosticar ou mudar decisões silenciosamente.
- Nenhuma limitação de contexto justifica pular validação, reduzir cobertura da biblioteca ou aceitar evidência incompleta.

## Snapshot e validação

Executar após uma unidade material:

```bash
python3 scripts/context_guard.py snapshot
python3 scripts/context_guard.py seal
python3 scripts/context_guard.py validate
```

`snapshot` registra hashes e estado do repositório-fonte. `seal` ancora o checkpoint e aceita apenas extensão append-only dos logs. `validate` confirma integridade dos arquivos de controle, consistência com o snapshot, baseline da biblioteca e presença dos 100 prompts canônicos.

Após `validate`, registrar o checkpoint no Git local desta pasta de controle. Não usar amend, rebase ou qualquer reescrita de histórico. O histórico Git é a âncora recuperável dos arquivos centrais; `CONTEXT_INDEX.json` protege continuidade entre checkpoints.

Após o commit, atualizar e verificar `/Users/enorm/Documents/Claude/loop-marketing-v2-control-backup.bundle`. O bundle é uma segunda cópia local recuperável. Não configurar remoto nem fazer push sem autorização explícita do usuário.

## Gate de autorização atual

A implementação da nova versão foi autorizada pelo usuário em 2026-07-17 com `pode iniciar`. A autorização não inclui push, publicação, migração real, mutação em plataformas externas nem alteração da biblioteca canônica.
