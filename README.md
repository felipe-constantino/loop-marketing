# Loop Marketing v2.1

Skill conversacional para transformar a metodologia Loop Marketing em ciclos de decisão, execução e aprendizado de CRM e lifecycle marketing.

O **Loop Agent** mantém o contexto global e propõe a rota. Quatro especialistas discutem suas decisões com o usuário:

- **Express · Verbalizar:** posicionamento, proposta de valor e mensagem;
- **Tailor · Orientar:** lifecycle, segmentação, elegibilidade e personalização;
- **Amplify · Ampliar:** canais, cadência e coordenação de touchpoints;
- **Evolve · Refinar:** diagnóstico, experimentação, métricas e aprendizado.

Cada mensagem identifica o agente ativo. Nenhum handoff acontece sem aprovação explícita do usuário. Ao final, Loop Agent integra um plano de execução e define quais resultados devem voltar para iniciar o ciclo seguinte.

## Versão atual

- Produto: **2.1.0**
- Status: **release conversacional para validação interna**
- Biblioteca: **100 prompts canônicos e quatro índices, preservados integralmente**
- Handoffs: contrato **1.1**, com aprovação humana obrigatória
- Interface: conversa por agentes, runtime determinístico, estado local e avaliação sem mutação

## Estrutura instalável

```text
loop-marketing/
├── SKILL.md
├── agents/
├── scripts/
└── references/
    ├── conversation-contract.md
    ├── library/
    └── runtime-data/
```

A pasta interna [`loop-marketing/`](loop-marketing/) é a skill completa. Copiá-la como uma unidade; não instalar arquivos isolados.

## Instalação no Codex

Copiar a pasta interna `loop-marketing/` para o diretório pessoal de skills, mantendo `SKILL.md`, `scripts/`, `references/` e `agents/` juntos.

## Instalação no Claude

Compactar **a pasta interna** `loop-marketing/`. O ZIP deve ter esta estrutura:

```text
loop-marketing.zip
└── loop-marketing/
    ├── SKILL.md
    ├── agents/
    ├── scripts/
    └── references/
```

Não compactar o repositório externo, pois isso criaria `loop-marketing/loop-marketing/SKILL.md` e o Claude rejeitaria o pacote.

## Uso

```text
Use $loop-marketing para discutir esta estratégia comigo por agentes. Não aprove decisões nem passe o bastão sem minha validação. Ao final, entregue um plano de execução e o pacote de dados que devo trazer para o próximo ciclo.
```

O fluxo, os critérios de aprovação, os comandos do runtime e os limites de segurança estão em [`SKILL.md`](loop-marketing/SKILL.md).

## Compatibilidade

Os aliases da v1.x continuam reconhecidos sem criar um segundo estado. O estado local permanece no schema v2; handoffs novos usam o contrato 1.1. A biblioteca original continua íntegra e versões anteriores permanecem recuperáveis no histórico Git.
