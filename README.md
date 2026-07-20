# Loop Marketing v2.0

Skill composta para transformar a metodologia Loop Marketing em um fluxo operacional de CRM e lifecycle marketing, orientado por evidências.

O planner identifica o gargalo global e coordena quatro especialistas:

- **Verbalizar (Express):** posicionamento, proposta de valor e mensagem.
- **Orientar (Tailor):** lifecycle, segmentação, elegibilidade e personalização.
- **Ampliar (Amplify):** canais, cadência e coordenação de touchpoints.
- **Refinar (Evolve):** diagnóstico, experimentação, métricas e aprendizado.

## Versão atual

- Produto: **2.0.0**
- Status: **release interno estável**
- Biblioteca: **100 prompts canônicos e quatro índices, preservados integralmente**
- Interface: planner, especialistas, integração de estado e avaliação sem mutação

## Estrutura

```text
loop-marketing/
├── SKILL.md
├── agents/
├── scripts/
└── references/
    ├── library/
    └── runtime-data/
```

A pasta [`loop-marketing/`](loop-marketing/) é a skill instalável completa. Ela deve ser copiada como uma unidade; não é necessário instalar arquivos isolados.

## Instalação

Copie `loop-marketing/` para o diretório de skills do ambiente que executará a ferramenta. No Codex, o destino convencional é o diretório pessoal de skills com o mesmo nome da pasta.

Depois da instalação, invoque a skill pelo nome:

```text
Use $loop-marketing para diagnosticar o gargalo de CRM deste projeto e propor o próximo ciclo com base nas evidências disponíveis.
```

O fluxo operacional completo, os comandos do runtime e os limites de segurança estão documentados dentro da própria skill em [`SKILL.md`](loop-marketing/SKILL.md).

## Compatibilidade

Os nomes da v1.x continuam reconhecidos como aliases, sem criar um segundo estado. Projetos antigos podem ser migrados para o namespace v2 de forma controlada. A versão anterior permanece recuperável no histórico e na tag `v1.2.0`.
