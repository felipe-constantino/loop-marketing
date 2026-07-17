# Mapa da arquitetura atual

Este documento descreve o produto observado no commit de baseline, sem propor que a biblioteca tática seja reduzida. A P1 foi executada em modo somente leitura e não alterou o repositório-fonte.

## Baseline

- Fonte: `/Users/enorm/Documents/Claude/loop-marketing`
- Commit: `3cbf0cf84a038f2cd570883b70988889f037c28e`
- Arquivos rastreados e classificados: 117
- Biblioteca canônica: 100 prompts, 25 por pilar
- Hash agregado: `0ef879b760619509adda24a7d928098f77cd2d4c392f53a3be7f530f14d549b1`
- Composição: 116 arquivos Markdown e um `.gitignore`; não há runtime, schema executável, testes ou avaliações automatizadas no baseline.

O Loop Marketing atual é um framework decisório operado por instruções e prompts. Ele organiza diagnóstico, seleção de táticas, especialização por pilar e registro de projeto, mas depende do agente hospedeiro para interpretar e cumprir as regras. A arquitetura de divulgação progressiva — índice primeiro, prompt selecionado depois — é uma força que deve ser preservada.

## Fluxo observado

```text
Pedido do usuário
  -> memória Markdown do projeto
  -> Loop Planning Agent (diagnóstico, gargalo e roteamento)
  -> especialista de pilar
  -> INDEX do pilar
  -> 1–2 prompts táticos selecionados
  -> recomendação, decisão ou handoff
  -> atualização da memória do projeto
  -> validação cruzada por outro pilar quando necessária
```

| Componente | Responsabilidade observada | Persistência/saída atual |
|---|---|---|
| Loop Planning | Diagnosticar o loop, localizar o gargalo, ordenar pilares e decidir a próxima ação | Plano e alterações sugeridas na memória Markdown |
| Verbalizar | Clareza, posicionamento, mensagem, voz e expressão da proposta | Recomendações e handoff para lifecycle/canais |
| Orientar | Segmentação, lifecycle, personalização e jornada | Recomendações e handoff para mensagem/cadência |
| Ampliar | Distribuição, canais, alcance, remix e coordenação | Recomendações e handoff para mensagem/lifecycle |
| Refinar | Experimentação, benchmark, análise e decisão | Experimentos e transições de estado |
| Biblioteca | 100 táticas canônicas carregadas seletivamente pelos quatro índices | Prompts Markdown preservados por caminho e hash |
| Projeto | Contexto, gargalo, decisões, plano, experimentos e aprendizados | Um arquivo Markdown mutável por cliente |

As instruções descrevem atualizações automáticas e histórico append-only, porém não existe mecanismo que imponha atomicidade, autoria, revisão, evidência ou ordem de eventos. Portanto, “automático” significa comportamento esperado do modelo, não garantia do produto.

## Fronteiras observadas

| Decisão | Owner coerente para a v2 | Drift encontrado no baseline |
|---|---|---|
| Clareza, posicionamento, voz e mensagem | Verbalizar | Os handoffs não carregam sempre a fronteira obrigatória de escopo. |
| Elegibilidade, segmento, estágio e evento de lifecycle | Orientar | Algumas instruções também lhe atribuem timing, intensidade e frequência. |
| Timing operacional, frequência, cadência e coordenação cross-channel | Ampliar | Orientar e Verbalizar atribuem parte dessas decisões a Orientar. |
| Hipótese, desenho experimental, evidência e decisão | Refinar | Estados exigem evidência, mas a memória não possui campos executáveis para evidência, ator, data e transição. |
| Gargalo, sequência de pilares e integração | Loop Planning | Especialistas também são instruídos a sobrescrever o gargalo compartilhado. |

Há ainda drift de namespace: `CLAUDE.md` e os comandos usam `.claude`, enquanto `AGENTS.md` usa `.Codex`. A árvore de versão em `LEIAME.md` também mantém resíduo de v1.1 sob documentação v1.2. Esses casos são documentados em `workstreams/architecture.json` e consolidados no registro de riscos.

## Lacunas para a v2

1. **Especificação canônica:** uma única terminologia, matriz de autoridade, fluxo, limites completos e política de compatibilidade entre hosts.
2. **Catálogo sobreposto à biblioteca:** metadados de função, maturidade, entradas, saídas, aliases e relações entre táticas, sem editar os 100 originais.
3. **Contratos e estado:** schemas versionados para projeto, decisão, evidência, handoff e experimento; event log append-only e snapshots derivados.
4. **Orquestração determinística:** roteamento, validação de escopo, transições e integração executados por código, não apenas solicitados em texto.
5. **Segurança por padrão:** dados externos tratados como não confiáveis, nenhuma credencial em Markdown, leitura como padrão e autorização explícita para cada mutação externa.
6. **Testabilidade e observabilidade:** testes unitários, de regressão dos 100 prompts, de cadeia entre agentes, segurança, red team e trilha auditável sem segredos ou PII.
7. **Empacotamento:** instalação reproduzível, adaptadores explícitos para Claude/Codex, migração de projetos anteriores e versão única do produto.

A sequência de implementação deve resolver primeiro a especificação e os contratos; depois adicionar catálogo, estado, runtime, segurança, avaliações e empacotamento. A biblioteca canônica permanece a camada de conhecimento do produto e será referenciada, nunca silenciosamente reescrita.
