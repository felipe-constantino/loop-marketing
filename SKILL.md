---
name: Loop Marketing
description: "Sistema de decisao para CRM e lifecycle marketing baseado na metodologia Loop Marketing (HubSpot). 6 comandos + biblioteca tatica de 100 prompts. Use quando o usuario descrever problemas de segmentacao, lifecycle, churn, mensagem, proposta de valor, canais, distribuicao, performance de campanha, testes, ou qualquer cenario de CRM/lifecycle. Inclui: /loop-planning-agent (orquestrador), /orientar-agent (segmentacao e lifecycle), /verbalizar-agent (mensagem e proposta de valor), /ampliar-agent (canais e distribuicao), /refinar-agent (diagnostico e testes), /projeto-template (contexto de projeto)."
---

# Loop Marketing v1.2 — Sistema de Decisao para CRM/Lifecycle

Sistema de decisao estruturada para operacoes de CRM e lifecycle marketing, baseado na metodologia Loop Marketing da HubSpot (loop continuo Express → Tailor → Amplify → Evolve, em vez de funil linear).

## Arquitetura de dois niveis

**Nivel 1 — Decisao (6 comandos):** orquestrador + 4 especialistas + template. Diagnosticam, priorizam e decidem *o que* fazer, *em que ordem* e *com qual intensidade*. Produzem decisoes calibradas por maturidade, com thresholds, grau de confianca e handoff — nao analises genericas.

**Nivel 2 — Execucao (biblioteca tatica, 100 prompts):** 25 prompts por vertical em `biblioteca/<vertical>/`. Cada especialista consulta o `INDEX.md` da sua vertical e carrega 1-2 prompts **sob demanda** quando precisa de um entregavel especifico. O output do prompt volta SEMPRE pelo contrato de saida do agente (a decisao continua sendo do especialista, nunca o output cru da biblioteca).

## Comandos instalados (nivel 1)

| Comando | Funcao | Vertical Loop Marketing |
|---------|--------|-------------------------|
| `/loop-planning-agent` | Diagnostica onde esta o gargalo e define a sequencia de resolucao | (orquestrador) |
| `/verbalizar-agent` | Mensagem, proposta de valor e hierarquia de comunicacao | Express |
| `/orientar-agent` | Segmentacao, lifecycle, elegibilidade e personalizacao | Tailor |
| `/ampliar-agent` | Canais, coordenacao de touchpoints e distribuicao | Amplify |
| `/refinar-agent` | Diagnostico de performance, testes e aprendizado | Evolve |
| `/projeto-template` | Cria e mantem contexto de projeto por cliente | (memoria) |

## Biblioteca tatica (nivel 2)

100 prompts especializados (25 por vertical) em `biblioteca/`. **Nao sao comandos invocaveis pelo usuario** — sao recursos lidos pelos agentes sob demanda. Cada vertical tem um `INDEX.md` que mapeia `arquivo → use quando`, permitindo ao agente escolher o aprofundamento certo sem ler os 25.

```
biblioteca/
├── Verbalizar/  (INDEX.md + 25 prompts)
├── Orientar/    (INDEX.md + 25 prompts)
├── Ampliar/     (INDEX.md + 25 prompts)
└── Refinar/     (INDEX.md + 25 prompts)
```

## Como usar

1. Inicie com `/projeto-template` para criar o contexto do cliente
2. Use `/loop-planning-agent` para diagnosticar o gargalo principal
3. Execute o especialista indicado pelo diagnostico (ele aciona a biblioteca tatica quando precisar)
4. O arquivo do projeto e atualizado automaticamente a cada execucao
5. Use `/refinar-agent` para medir resultados e alimentar o proximo ciclo

## Regra de ouro

Na duvida, comece pelo `/loop-planning-agent`. Ele analisa o cenario, pontua cada pilar de 0 a 10, e indica qual skill acionar primeiro.

## Contexto automatico

O sistema mantem memoria entre sessoes em `.claude/loop-marketing/`. Apos criar o projeto com `/projeto-template`, cada skill le o contexto antes de iniciar, atualiza decisoes/testes/aprendizados ao concluir (politica append-only) e nao repete diagnosticos ja realizados.
