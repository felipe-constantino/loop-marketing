# Loop Marketing v1.1 — Sistema de Decisao para CRM/Lifecycle

Sistema de decisao estruturada para CRM e lifecycle marketing, baseado na metodologia **Loop Marketing da HubSpot** (loop continuo Express → Tailor → Amplify → Evolve). Produz decisoes operacionais com thresholds, verificacoes e handoffs — nao listas de sugestoes.

## Arquitetura de dois niveis

**Nivel 1 — Decisao:** 6 comandos (1 orquestrador + 4 especialistas + 1 template). Decidem *o que* fazer, *em que ordem* e *com qual intensidade*, calibrado por maturidade.

**Nivel 2 — Execucao:** biblioteca tatica de 100 prompts (25 por vertical). Os especialistas acionam esses prompts **sob demanda** para produzir entregaveis especificos, reenquadrando o resultado no proprio contrato de saida.

```
Loop Planning (orquestrador)
        │  diagnostica e roteia
        ▼
┌───────────────┬───────────────┬───────────────┬───────────────┐
│  Verbalizar   │   Orientar    │    Ampliar    │   Refinar     │
│  (Express)    │   (Tailor)    │   (Amplify)   │   (Evolve)    │
└──────┬────────┴──────┬────────┴──────┬────────┴──────┬────────┘
       │ consulta INDEX.md e carrega 1-2 prompts sob demanda
       ▼               ▼               ▼               ▼
  biblioteca/     biblioteca/     biblioteca/     biblioteca/
  Verbalizar/     Orientar/       Ampliar/        Refinar/
  (25 prompts)    (25 prompts)    (25 prompts)    (25 prompts)
```

---

## Instalacao

### 1. Copiar os comandos

Copie a pasta `commands/` para `.claude/commands/` do seu projeto:

```
seu-projeto/
└── .claude/
    └── commands/
        ├── loop-planning-agent.md
        ├── orientar-agent.md
        ├── verbalizar-agent.md
        ├── ampliar-agent.md
        ├── refinar-agent.md
        └── projeto-template.md
```

### 2. Copiar a biblioteca tatica

Copie a pasta `biblioteca/` para a raiz do projeto (mesmo nivel de `.claude/`). Os agentes referenciam os arquivos por `biblioteca/<vertical>/...`:

```
seu-projeto/
├── biblioteca/
│   ├── Verbalizar/  (INDEX.md + 25 prompts)
│   ├── Orientar/    (INDEX.md + 25 prompts)
│   ├── Ampliar/     (INDEX.md + 25 prompts)
│   └── Refinar/     (INDEX.md + 25 prompts)
└── .claude/
```

### 3. Copiar CLAUDE.md

Copie o `CLAUDE.md` para a raiz do projeto. Se ja existir um, adicione o conteudo ao final.

### 4. Criar a pasta de contexto de projeto

```bash
mkdir -p .claude/loop-marketing
```

### 5. Pronto

Os comandos estarao disponiveis via `/nome-do-comando`. A biblioteca tatica e usada automaticamente pelos agentes — voce nao precisa invoca-la.

---

## Os 6 comandos

| Comando | O que faz | Use quando... |
|---------|----------|---------------|
| `/loop-planning-agent` | Diagnostica onde esta o problema e define sequencia | Nao sabe por onde comecar, ou problema em varios lugares |
| `/verbalizar-agent` | Mensagem e proposta de valor (Express) | Mensagem nao converte, e generica, ou precisa de comunicacao nova |
| `/orientar-agent` | Segmentacao, lifecycle, elegibilidade (Tailor) | Precisa segmentar base, mapear lifecycle, tratar churn |
| `/ampliar-agent` | Canais e coordenacao de touchpoints (Amplify) | Canais descoordenados, opt-out subindo, mesma mensagem em tudo |
| `/refinar-agent` | Diagnostico de performance e testes (Evolve) | Entender queda, decidir o que escalar/parar, montar testes |
| `/projeto-template` | Cria ou atualiza arquivo de contexto do projeto | Inicio de cliente novo ou para revisar o estado atual |

---

## Como usar

### Regra de ouro: na duvida, comece pelo Loop Planning

Se nao tem certeza de qual comando usar, use `/loop-planning-agent`. Ele pontua cada pilar de 0 a 10 e diz qual skill acionar primeiro.

### Fluxo basico

```
/projeto-template        (1x por cliente — cria contexto)
       |
/loop-planning-agent     (diagnostica e sequencia)
       |
/orientar-agent          (segmentacao e lifecycle)
       |
/verbalizar-agent        (mensagens por estagio)
       |
/ampliar-agent           (canais por segmento)
       |
/refinar-agent           (medir, testar, aprender)
       |
(proximo ciclo)
```

### Cenarios comuns

**Churn alto** → `/loop-planning-agent` → `/orientar-agent` (mapeia lifecycle, identifica estagnacao)

**Email nao converte** → `/refinar-agent` (entende por que) → skill que ele apontar

**Melhorar mensagem de upsell** → `/verbalizar-agent` (direto)

**Muitos canais, nada funciona** → `/ampliar-agent` (audita touchpoints, define papeis)

**Pipeline cheio, conversao baixa** → `/loop-planning-agent` (cenario multi-pilar classico)

**Montar operacao do zero** → `/orientar-agent` → `/verbalizar-agent` → `/ampliar-agent` → `/refinar-agent`

---

## A biblioteca tatica (nivel 2)

Sao 100 prompts especializados (25 por vertical) em `biblioteca/`. **Voce nao os invoca diretamente** — quando um especialista precisa de um entregavel especifico (ex: estrategia de conteudo entre plataformas, modelo de scoring preditivo, design de teste multivariado), ele:

1. Le o `INDEX.md` da sua vertical
2. Escolhe 1-2 prompts pelo criterio "use quando"
3. Executa o prompt como insumo
4. Reenquadra o resultado no proprio contrato de saida (maturidade, confianca, threshold, handoff)

Os prompts originais sao genericos e em estilo "analise abrangente" — o agente os converte em decisao calibrada. Para ver o que cada vertical cobre, abra o `INDEX.md` correspondente.

> Nota de qualidade: os 100 prompts vieram de uma biblioteca traduzida e ainda tem artefatos de traducao automatica (ex: termos em ingles soltos, terminologia inconsistente). A integracao via INDEX + contrato de saida ja funciona; a limpeza de texto dos prompts e incremental.

---

## O que informar ao agente

Funciona mesmo com pouca informacao (entra em "modo minimo viavel" e diz o que falta). Sempre util: tamanho da base, como segmenta hoje, metricas, ferramenta de CRM, tamanho da equipe.

Nao precisa ter: lifecycle formal (o agente monta um), dados perfeitos (sinaliza o que e inferencia), conhecimento da metodologia (aplica sozinho).

---

## O que esperar do output

- **Decisoes** (nao sugestoes) com grau de confianca
- **Verificacoes** — testa as proprias recomendacoes contra criterios de falha
- **Thresholds numericos** — numeros concretos, nao "quando apropriado"
- **O que NAO fazer** — acoes prematuras bloqueadas
- **Lacunas** — o que falta para diagnostico mais preciso
- **Handoff** — qual skill acionar depois e com qual input

| Confianca | Acao recomendada |
|-----------|-----------------|
| Alta | Implementar diretamente |
| Media | Implementar como teste |
| Baixa | Nao implementar — coletar dados primeiro |

---

## Contexto de projeto (automatico)

O sistema mantem contexto entre sessoes em `.claude/loop-marketing/`:

1. Crie o projeto com `/projeto-template` (1x por cliente) → gera `.claude/loop-marketing/[cliente].md` e `.claude/loop-marketing/_active.md`
2. A cada skill executado, o arquivo do projeto e atualizado (decisoes, testes, aprendizados, proximo passo) seguindo politica append-only
3. Na proxima sessao, qualquer skill le o projeto e continua de onde parou

---

## 3 coisas para nao fazer

1. **Nao pule para Ampliar** sem clareza de mensagem (Verbalizar) e publico (Orientar). Amplificar mensagem confusa para publico errado multiplica o erro.
2. **Nao ignore o modo de operacao.** Se o agente diz "modo parcial", as recomendacoes precisam ser validadas. Nao trate inferencia como certeza.
3. **Nao tente resolver tudo de uma vez.** Resolva o gargalo principal, meca com Refinar, ataque o proximo no ciclo seguinte.

---

## Estrutura da pasta

```
loop-marketing-v1.1/
├── LEIAME.md            ← este arquivo
├── SKILL.md             ← manifesto do skill
├── CLAUDE.md            ← copiar para raiz do projeto
├── commands/            ← copiar para .claude/commands/
│   ├── loop-planning-agent.md
│   ├── orientar-agent.md
│   ├── verbalizar-agent.md
│   ├── ampliar-agent.md
│   ├── refinar-agent.md
│   └── projeto-template.md
└── biblioteca/          ← copiar para a raiz do projeto
    ├── Verbalizar/  (INDEX.md + 25 prompts)
    ├── Orientar/    (INDEX.md + 25 prompts)
    ├── Ampliar/     (INDEX.md + 25 prompts)
    └── Refinar/     (INDEX.md + 25 prompts)
```

---

## Mudancas da v1.1

- **Biblioteca tatica integrada:** os 100 prompts deixaram de ser arquivos orfaos dentro de `commands/` e viraram um nivel de execucao real, acionado pelos agentes via `INDEX.md` por vertical + contrato de saida.
- **Caminho de contexto renomeado:** `.claude/projects/` → `.claude/loop-marketing/` (evita colisao com o namespace interno do Claude Code).
- **Benchmark removido:** as alegacoes de performance da versao anterior apontavam para arquivos inexistentes e foram retiradas ate existir uma avaliacao reproduzivel.
- **CLAUDE.md unico e canonico** na raiz do skill.
