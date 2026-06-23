# Loop Marketing — Sistema de Decisão para CRM/Lifecycle

Sistema de decisão para CRM e lifecycle marketing baseado na metodologia **Loop Marketing da HubSpot** (loop contínuo Express → Tailor → Amplify → Evolve, no lugar do funil linear).

Não é uma lista de boas práticas: é um **copiloto que diagnostica onde está o seu gargalo e te dá a próxima decisão concreta** — calibrada por maturidade, com threshold e grau de confiança.

```
   EXPRESS  ──►  TAILOR  ──►  AMPLIFY  ──►  EVOLVE
  /verbalizar   /orientar    /ampliar     /refinar
  originar a    adaptar ao   distribuir   medir e
  tese          público      nos canais   realimentar
      ▲                                        │
      └────────────────────────────────────────┘
              Evolve realimenta Express
        (cada volta o loop fica mais inteligente)
```

## Documentação

- **O que é e pra que serve:** [SOBRE.md](SOBRE.md)
- **Como instalar e usar:** [LEIAME.md](LEIAME.md)
- **Manifesto do skill:** [SKILL.md](SKILL.md)

## O que tem aqui

**Nível 1 — Decisão (6 comandos):** orquestrador + 4 especialistas + template.

| Comando | Vertical | Função |
|---------|----------|--------|
| `/loop-planning-agent` | (orquestrador) | Diagnostica o gargalo e define a sequência |
| `/verbalizar-agent` | Express | Mensagem e proposta de valor |
| `/orientar-agent` | Tailor | Segmentação, lifecycle e personalização |
| `/ampliar-agent` | Amplify | Canais e distribuição |
| `/refinar-agent` | Evolve | Diagnóstico, testes e aprendizado |
| `/projeto-template` | (memória) | Contexto de projeto por cliente |

**Nível 2 — Execução:** biblioteca tática de 100 prompts (25 por vertical) em `biblioteca/`, acionada pelos agentes sob demanda via `INDEX.md`.

## Instalação rápida

1. Copie `commands/` para `.claude/commands/` do seu projeto.
2. Copie `biblioteca/` para a raiz do projeto.
3. Copie `CLAUDE.md` para a raiz do projeto.
4. `mkdir -p .claude/loop-marketing`

Passo a passo completo em [LEIAME.md](LEIAME.md).

## Estrutura

```
.
├── README.md            ← este arquivo
├── SOBRE.md             ← o que é / pra que serve
├── LEIAME.md            ← instalação e uso
├── SKILL.md             ← manifesto do skill
├── CLAUDE.md            ← regras do sistema (copiar p/ raiz do projeto)
├── AGENTS.md            ← espelho do CLAUDE.md para agentes estilo Codex
├── commands/            ← 6 comandos
└── biblioteca/          ← 4 verticais × (INDEX.md + 25 prompts)
```
