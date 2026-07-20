# Biblioteca Tática — Orientar (fase Tailor)

> Recursos táticos do **orientar-agent**. NÃO são comandos invocáveis pelo usuário — são arquivos de aprofundamento que o agente lê **sob demanda** quando precisa produzir um entregável específico de segmentação/lifecycle/personalização.
>
> **Como usar (instrução para o agente):**
> 1. Identifique a necessidade tática durante o método base.
> 2. Escolha **UM** arquivo abaixo pelo "use quando".
> 3. Leia `biblioteca/Orientar/<arquivo>.md` e use as instruções dele como **insumo**.
> 4. **O resultado volta SEMPRE pelo contrato de saída do orientar-agent**: gating de maturidade, critérios mensuráveis, verificação de viabilidade técnica, grau de confiança e handoff. O prompt da biblioteca gera matéria-prima; a decisão continua sendo do agente.
>
> Regra: no máximo 1-2 arquivos por ciclo. **Respeite o gating de maturidade** — os arquivos marcados [MADURO+] não devem ser acionados em operação nascente/em desenvolvimento. Se nenhum "use quando" casa, **não force**.

## Índice

- **construtor-de-segmentacao-comportamental.md** — use quando: precisa criar segmentos baseados em comportamento (Passo 2 do agente).
- **mapeador-de-ciclos-de-vida-do-cliente.md** — use quando: precisa mapear ou redesenhar os estágios do lifecycle com estratégia por fase.
- **identificador-de-sinal-de-intencao.md** — use quando: precisa transformar comportamento observável em sinais de intenção/prontidão.
- **estrategia-de-comunicacao-segmentada.md** — use quando: precisa definir a estratégia de comunicação por segmento (handoff com Verbalizar/Ampliar).
- **estrategista-de-enriquecimento-de-dados-do-cliente.md** — use quando: a segmentação esbarra em falta de dados e precisa de plano de enriquecimento.
- **estrutura-de-mensagens-contextuais.md** — use quando: precisa definir como a comunicação se adapta a contexto/situação/timing.
- **otimizador-de-caminho-de-conversao.md** — use quando: precisa desenhar rotas de conversão distintas por tipo de cliente.
- **personalizacao-da-jornada-do-cliente.md** — use quando: precisa personalizar a jornada ponta a ponta por características individuais.
- **personalizacao-de-email-de-ciclo-de-vida.md** — use quando: precisa de personalização de email por fase do lifecycle.
- **otimizador-de-personalizacao-de-email.md** — use quando: o foco é melhorar performance de email via personalização.
- **otimizador-de-conteudo-dinamico.md** — use quando: o CRM suporta conteúdo dinâmico e precisa de regras de entrega. [MADURO+]
- **mecanismo-de-hiperpersonalizacao.md** — use quando: operação madura/avançada com dados comportamentais ricos. [MADURO+]
- **modelo-de-pontuacao-preditiva.md** — use quando: há dados e capacidade para scoring preditivo. [AVANÇADO]
- **personalizacao-baseada-em-conta.md** — use quando: o modelo é ABM / contas estratégicas de alto valor. [MADURO+]
- **personalizador-de-experiencia-da-onboarding.md** — use quando: o gargalo é onboarding e precisa de trilhas personalizadas.
- **personalizador-de-renovacao-e-expansao.md** — use quando: o foco é retenção, renovação ou expansão (upsell/cross-sell).
- **personalizador-de-tratamento-de-objecao.md** — use quando: precisa mapear e tratar objeções por segmento ao longo do fluxo.
- **personalizador-de-viagens-baseado-em-persona.md** — use quando: precisa diferenciar a jornada por persona.
- **personalizacao-orientada-por-comentarios.md** — use quando: quer um loop de melhoria de personalização guiado por feedback.
- **personalizador-da-experiencia-de-suporte.md** — use quando: precisa personalizar a experiência de suporte por tipo de cliente.
- **personalizador-de-prova-social.md** — use quando: precisa entregar a prova social mais relevante por perfil/contexto.
- **personalizador-de-landings-page.md** — use quando: precisa personalizar landing pages por segmento/comportamento. [MADURO+]
- **mecanismo-de-personalizacao-redirecionamento.md** — use quando: precisa de estratégia de retargeting comportamental.
- **sequencias-de-personalizacao-automatizada.md** — use quando: precisa desenhar sequências automatizadas relevantes (anti-genérico). [EM DESENVOLVIMENTO+]
- **sincronizacao-de-mensagens-entre-canais.md** — use quando: precisa manter contexto/continuidade de personalização entre canais (coordenar com Ampliar).
