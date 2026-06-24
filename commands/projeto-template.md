---
name: projeto-template
description: "Template para criar e manter contexto de projeto de CRM/lifecycle. Use este comando para iniciar um novo projeto, atualizar contexto após rodar qualquer skill do Loop Marketing, ou revisar o estado atual do projeto. Use sempre que o usuário mencionar 'novo projeto', 'iniciar projeto', 'atualizar projeto', 'contexto do projeto', ou referenciar um cliente específico."
---

# Template de Projeto — Loop Marketing

Ao receber este comando, faça o seguinte:

1. Se o usuário está **iniciando um projeto novo**: preencha o template abaixo com as informações fornecidas. Pergunte o que faltar.
2. Se o usuário está **atualizando um projeto existente**: leia o arquivo do projeto, incorpore as novas decisões/testes/aprendizados, e atualize o gargalo atual.
3. Se o usuário está **revisando**: leia o arquivo e apresente um resumo do estado atual com recomendação de próxima ação.

O arquivo de projeto deve ser salvo em:
```
.claude/loop-marketing/[nome-do-cliente].md
```

Após criar ou ativar o projeto, criar/atualizar o ponteiro de projeto ativo:
```
.claude/loop-marketing/_active.md
```
Conteúdo do `_active.md`:
```
projeto: [nome-do-cliente]
arquivo: .claude/loop-marketing/[nome-do-cliente].md
ativado_em: [data]
```
Este arquivo é lido por todos os skills para identificar o projeto corrente sem precisar perguntar ao usuário.

---

## Template

```markdown
# Projeto: [Nome do cliente]
Última atualização: [data]

---

## 1. CONTEXTO

- Cliente: [nome]
- Objetivo principal: [1 frase]
- Métrica principal: [KPI que define sucesso]
- Canais ativos: [lista]
- Base: [tamanho + como é segmentada hoje]
- Ferramentas: [CRM, automação, analytics]
- Equipe: [tamanho e composição]

---

## 2. MATURIDADE

- Classificação: [nascente | em desenvolvimento | maduro | avançado]
- Data: [quando foi classificado]
- Justificativa: [1-2 frases]
- Sub-métodos bloqueados: [o que NÃO recomendar nesta maturidade]

---

## 3. GARGALO ATUAL

- Pilar: [Orientar | Verbalizar | Ampliar | Refinar]
- Scoring: [X/10]
- Descrição: [1 frase]
- Evidência: [dado ou observação que sustenta]
- Desde: [data em que foi identificado]

---

## 4. DECISÕES TOMADAS

Formato: [Data] Skill → Gargalo atacado → Decisão — Confiança — Status

Exemplo:
- [2026-04-12] Orientar → segmentação inexistente → 3 segmentos comportamentais definidos — Confiança: média — Status: ativo
- [2026-04-15] Verbalizar → mensagem genérica → L1 reformulada com teste de diferenciação — Confiança: média (modo parcial) — Status: em teste

---

## 5. TESTES ATIVOS

Formato:
- [Data] Hipótese: [se X, então Y]
  - Skill de origem: [qual skill propôs]
  - Variável isolada: [o que muda]
  - Métrica de sucesso: [KPI + meta numérica]
  - Prazo: [duração]
  - Critério de decisão: [se >X implementar, se <Y descartar]
  - Status: [proposto | aprovado | instrumentado | em execução | concluído]  ← começa em "proposto"; só avança com evidência real (não narrar progresso que não aconteceu)

---

## 6. APRENDIZADOS

Formato:
- [Data] [O que foi testado/observado] → [Resultado] → [Aprendizado]
  - Impacto: [o que muda na operação]
  - Origem: [teste | refinar | observação direta]
  - Implicações: [qual skill deve considerar isso]

---

## 7. PRÓXIMA AÇÃO

- Skill recomendado: [/comando]
- Objetivo: [1 frase]
- Input necessário: [o que fornecer ao skill]
- Depende de: [resultado de teste, dado a coletar, ou nada]
- Prazo sugerido: [quando executar]

---

## 8. HISTÓRICO DE GARGALOS

Formato: [Data] Pilar (score) → Status

Exemplo:
- [2026-04-01] Orientar (9/10) → resolvido em 2026-04-12 (lifecycle + segmentos definidos)
- [2026-04-12] Verbalizar (7/10) → ativo (mensagem genérica, modo parcial)
- [2026-04-20] Ampliar (6/10) → pendente (aguardando output do Verbalizar)

Este histórico mostra a evolução do projeto. Se o mesmo pilar aparece como gargalo por mais de 2 ciclos, o problema não está sendo resolvido — escalar ou mudar abordagem.
```

---

## Regras de atualização

1. **Após cada skill**: adicionar decisões na seção 4, testes na seção 5, atualizar gargalo na seção 3
2. **Após cada Refinar**: adicionar aprendizados na seção 6, atualizar status dos testes na seção 5
3. **Quando gargalo muda**: mover o anterior para seção 8 com status, atualizar seção 3
4. **Maturidade**: reavaliar a cada 30 dias ou quando houver mudança estrutural significativa

## Política append-only (obrigatória)

| Seção | Política |
|---|---|
| 4. Decisões | Append-only — nunca remover ou reescrever entradas |
| 5. Testes | Append-only — atualizar `Status` da linha, nunca apagar |
| 6. Aprendizados | Append-only — nunca remover |
| 8. Histórico de gargalos | Append-only — sempre acrescentar, nunca reescrever |
| 3. Gargalo atual | Overwrite permitido — mover anterior para seção 8 antes |
| 7. Próxima ação | Overwrite permitido |
| 1. Contexto | Overwrite se dado factual mudou |
| 2. Maturidade | Overwrite + registrar revisão como entrada na seção 4 |

**Nunca reescrever o passado.** O arquivo é um log auditável de decisões, não um snapshot do momento atual.

## Critério de saúde do projeto

O projeto está saudável quando:
- Seção 4 cresce a cada ciclo (decisões sendo tomadas)
- Seção 5 tem pelo menos 1 teste ativo (hipóteses sendo validadas)
- Seção 6 cresce a cada Refinar (aprendizado acumulando)
- Seção 8 mostra gargalos mudando (progresso real)

O projeto está estagnado quando:
- Seção 3 não muda por mais de 2 ciclos
- Seção 5 está vazia (nenhum teste rodando)
- Seção 6 não cresce (sem aprendizado)
- Decisões na seção 4 ficam com status "ativo" indefinidamente sem virar aprendizado
