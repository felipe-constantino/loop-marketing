# Biblioteca Tática — Refinar (fase Evolve)

> Recursos táticos do **refinar-agent**. NÃO são comandos invocáveis pelo usuário — são arquivos de aprofundamento que o agente lê **sob demanda** quando precisa produzir um entregável específico de diagnóstico/teste/aprendizado.
>
> **Como usar (instrução para o agente):**
> 1. Identifique a necessidade tática durante o método base.
> 2. Escolha **UM** arquivo abaixo pelo "use quando".
> 3. Leia `biblioteca/Refinar/<arquivo>.md` e use as instruções dele como **insumo**.
> 4. **O resultado volta SEMPRE pelo contrato de saída do refinar-agent**: leitura sem viés, benchmark explícito, classificação com threshold (ESCALAR/OTIMIZAR/PARAR/TESTAR), bloco de IMPLICAÇÕES CROSS-PILAR e grau de confiança. O prompt da biblioteca gera matéria-prima; a decisão continua sendo do agente.
>
> Regra: no máximo 1-2 arquivos por ciclo. **Não repita teste já feito** (erro nº 5 do agente — checar Seção 6 do projeto). Se nenhum "use quando" casa, **não force**.

## Índice

- **diagnostico-de-desempenho-de-campanha.md** — use quando: precisa diagnosticar por que uma campanha performou como performou (Passo 3 do agente).
- **interprete-de-analises-da-jornada-do-cliente.md** — use quando: o diagnóstico é por atrito/conversão ao longo da jornada.
- **diagnostico-da-entrega-da-viagem-do-cliente.md** — use quando: precisa avaliar se a jornada está sendo entregue como desenhada.
- **analisador-de-desempenho-de-coorte.md** — use quando: precisa comparar coortes ao longo do tempo (retenção/LTV por safra).
- **designer-de-estrutura-de-teste-sistematica.md** — use quando: precisa montar um framework de testes estruturados (Passo 5 do agente).
- **construtor-de-estrutura-de-experimentacao-rapida.md** — use quando: precisa de uma estrutura de experimentação rápida/MVP.
- **mecanismo-de-experimentacao-rapida.md** — use quando: precisa rodar muitos testes pequenos com critério de escalonamento.
- **estrategista-de-teste-multi-variate.md** — use quando: precisa testar múltiplas variáveis com design multivariado. [MADURO+]
- **otimizador-de-testes-sequenciais.md** — use quando: precisa de testes sequenciais / inteligência competitiva contínua.
- **coordenador-de-testes-entre-canais.md** — use quando: há testes simultâneos em vários canais que podem conflitar.
- **calculadora-de-otimizacao.md** — use quando: precisa priorizar otimizações ao longo do funil completo.
- **gerador-de-relatorios-de-otimizacao-continua.md** — use quando: precisa consolidar resultados num relatório de otimização recorrente.
- **mecanismo-de-otimizacao-em-tempo-real.md** — use quando: campanha está rodando e precisa de otimização ao vivo. [MADURO+]
- **monitoramento-antecipado-de-sinais-e-otimizacao-em-tempo-real.md** — use quando: precisa detectar sinais precoces antes do resultado consolidar. [MADURO+]
- **mecanismo-de-previsao-de-desempenho.md** — use quando: precisa projetar tendência/desempenho futuro. [MADURO+]
- **modelador-de-desempenho-previsivel.md** — use quando: precisa de modelagem preditiva de desempenho para suporte à decisão. [AVANÇADO]
- **resultados-previsiveis-da-campanha-antes-do-lancamento.md** — use quando: quer estimar resultado de uma campanha antes de lançar. [MADURO+]
- **otimizador-de-atribuicao-de-marketing.md** — use quando: precisa de modelo de atribuição para medir contribuição real por toque.
- **modelador-de-combinacao-de-marketing.md** — use quando: precisa entender interação/sinergia entre atividades (marketing mix). [AVANÇADO]
- **otimizador-de-valor-do-ciclo-de-vida-do-cliente.md** — use quando: o foco é otimizar LTV e alocação de investimento por segmento.
- **acelerador-de-velocidade-de-marketing.md** — use quando: o gargalo é velocidade de execução/ciclo de decisão.
- **otimizador-de-agilidade-de-marketing.md** — use quando: o foco é capacidade de resposta/adaptação do time.
- **analise-competitiva-do-velocity.md** — use quando: precisa comparar sua velocidade de execução com a do mercado.
- **sintese-de-aprendizado-multi-loop.md** — use quando: precisa consolidar aprendizado acumulado de vários ciclos (alimenta Seção 6 do projeto).
- **sistema-de-integracao-de-aprendizagem.md** — use quando: precisa de processo para capturar e reaplicar aprendizado de forma sistemática.
