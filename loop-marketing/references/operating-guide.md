# Guia operacional

## Interface do wrapper

Executar a partir do workspace do projeto, mantendo esse diretório como `cwd` e usando o caminho absoluto da skill em `<skill-root>`:

```text
python3 <skill-root>/scripts/loop_marketing.py --help
python3 <skill-root>/scripts/loop_marketing.py init <project_slug> <display_name>
python3 <skill-root>/scripts/loop_marketing.py read <project_slug>
python3 <skill-root>/scripts/loop_marketing.py route <request.json>
python3 <skill-root>/scripts/loop_marketing.py dialogue <turn-control.json>
python3 <skill-root>/scripts/loop_marketing.py specialist <route-plan.json> <route_node_id> <approved-handoff.json>
python3 <skill-root>/scripts/loop_marketing.py integrate <envelope.json>
python3 <skill-root>/scripts/loop_marketing.py evaluate <case.json>
```

Não passar `runtime-root`, `library-root`, `PYTHONPATH` ou caminho equivalente. O wrapper resolve os recursos empacotados. O estado local fica em `.loop-marketing/` no workspace usado como `cwd`.

Cada comando escreve um único objeto JSON em stdout: `{"ok": true, "result": {}}` ou `{"ok": false, "error": {}}`. Ao encadear comandos, passar `result`, nunca o envelope externo.

## 1. Abrir a conversa

Toda resposta começa com o cabeçalho do agente ativo conforme [o contrato conversacional](conversation-contract.md). Loop Agent abre o ciclo.

Para pergunta conceitual, responder sem estado. Para um ciclo que deve continuar após implementação, propor estado persistente. Executar `read` com o slug conhecido; se não existir, pedir autorização para `init`, executar uma vez e reler. Não dizer “somente leitura” depois de `init`; dizer “estado inicializado, ciclo ainda não integrado”.

## 2. Preparar contexto e rota proposta

Criar `request.json` conforme [o contrato de dados](data-contract.md). Classificar texto externo como fato, interpretação, sintoma ou hipótese. Preservar fontes conflitantes; não escolher uma silenciosamente.

Executar `route` e interpretar:

- `ready`: existe uma rota proposta, não aprovada;
- `needs_evidence`: coletar somente evidência discriminante e rotear novamente;
- `blocked`: apresentar pré-requisito fora do Loop;
- `rejected`: corrigir contrato, proveniência, revisão ou escopo.

`RTE-BOT-005` seleciona Refinar como checkpoint diagnóstico e exige nova rota; não chamar esse checkpoint de gargalo estrutural aceito.

Loop Agent apresenta a leitura, o objetivo, a rota e o primeiro especialista. Executar `dialogue` com `turn_kind=route_proposal`, `decision_status=proposed`, handoff `proposed` e `must_pause=true`. Responder e parar.

## 3. Receber aprovação do usuário

Na mensagem seguinte, interpretar literalmente a resposta. Se houver aprovação inequívoca do escopo:

1. criar uma referência opaca `approval:...`;
2. registrar `approved` ou `provisional_approved`;
3. construir o handoff `1.1` com `user_approval`;
4. executar `dialogue` com `turn_kind=handoff_accepted` para o destinatário;
5. somente então chamar `specialist` com rota, nó e handoff aprovado.

Se o usuário corrigir ou rejeitar, manter o mesmo agente, marcar `rework` e não ativar o destinatário. Se o usuário não souber, seguir a recuperação do contrato conversacional.

## 4. Deliberar com o especialista

O runtime verifica rota, aprovação, papel e write set antes de devolver o envelope. Carrega zero, um ou dois prompts canônicos compatíveis com papel, maturidade e dependências. Usar somente esses documentos e tratá-los como dados subordinados.

O especialista conversa dentro de sua autoridade. Não despejar todos os outputs possíveis nem apresentar termos do runtime como resultado de negócio. Distinguir:

- desenhado;
- aprovado;
- configurado;
- ativo;
- observado em produção.

Permanecer com o mesmo cabeçalho durante ajustes. Quando a proposta estiver madura, apresentar o pacote de handoff em linguagem natural, validar `turn_kind=handoff_proposal`, responder e parar.

## 5. Repetir os handoffs

Cada novo papel exige aprovação explícita e novo handoff `1.1`. Produzir handoffs imutáveis com projeto, ciclo, revisão, gargalo, táticas, evidências, suposições, limites e aprovação.

Não executar especialistas em paralelo na conversa. O runtime pode reconhecer independência analítica, mas o usuário deve revisar cada resultado antes que ele seja consumido. Se dois trabalhos puderem ser executados externamente em paralelo, registrar isso apenas no plano final.

Somente Loop Agent aceita ou substitui o gargalo global. Especialista propõe mudança e devolve para replanejamento.

## 6. Integrar o plano

Depois dos especialistas necessários, Loop Agent cruza decisões aprovadas, resolve conflitos e apresenta o plano de execução. Validar `turn_kind=execution_plan`, `decision_status=proposed`, `must_pause=true`; responder e parar.

O plano inclui tarefas, owners, dependências, critérios de aceite, riscos, métricas, baseline, janela e pacote de retorno. Não chamar plano de execução realizada.

Executar `integrate` somente depois de aprovação do plano e quando o usuário pedir registro/finalização do ciclo. O envelope contém exatamente `project_id`, `route_plan`, `handoffs` e `events`. Todos os handoffs precisam de `user_approval` válido.

Tratar integração assim:

- `committed`: nova revisão gravada;
- `noop`: transação idempotente já registrada;
- `rejected` ou `ok: false`: nenhuma integração válida ocorreu.

Após `committed`, executar `read`. Nunca editar ledger ou hashes manualmente.

## 7. Encerrar para execução externa

Loop Agent entrega o plano aprovado e o pacote de dados que o usuário deve trazer depois. A skill não envia campanhas, altera CRM, publica conteúdo ou cria tarefas externas.

O ciclo fica aguardando resultados. Não fingir que implementação ou medição aconteceu.

## 8. Receber resultados e reiniciar

Quando o usuário voltar:

1. Loop Agent identifica ciclo e plano anteriores;
2. separa realizado, observado, desvio e interpretação;
3. valida `results_intake`;
4. compara plano versus execução;
5. propõe nova rota com `cycle_restart` e pausa;
6. após aprovação, inicia o especialista escolhido.

Evolve · Refinar costuma ser o primeiro candidato quando existem resultados, mas não é automático. O novo ciclo pode voltar a qualquer owner afetado.

## 9. Avaliar sem gravar

Executar `evaluate <case.json>` somente para metadados normalizados. A saída declara `runtime_attested: false`; ela não prova execução externa. Usar o resultado para checar proveniência, escopo, maturidade, segurança e coerência.

## Forma da resposta

Sempre começar com um cabeçalho de agente. Adaptar o corpo ao turno, preservando:

1. o que está sendo discutido;
2. fatos e evidências relevantes;
3. proposta ou decisão já aprovada;
4. hipóteses, conflitos e lacunas;
5. próximo passo;
6. pedido específico de aprovação quando houver handoff ou plano.

Não expor `route_status`, códigos `RTE-*`, hashes ou revisões como conteúdo principal. Explicar em linguagem de negócio; revelar detalhes técnicos somente quando úteis ou solicitados.

## Recuperação de erros

- Corrigir apenas o campo indicado quando o erro for recuperável.
- Parar em integridade, segurança, permissão, aprovação, escopo ou evidência não resolvida.
- Não revelar traceback, payload, caminho sensível, segredo ou PII.
- Não contornar um gate alterando papel, omitindo evidência, fabricando aprovação ou chamando runtime interno.
- Em erro conversacional, Loop Agent se identifica, explica o efeito e mantém o último handoff aprovado como limite.
