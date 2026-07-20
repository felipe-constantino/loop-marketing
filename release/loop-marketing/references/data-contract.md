# Contrato de dados operacional

## Princípios

Usar JSON como formato de troca e referências opacas como vínculos. Não duplicar o conteúdo bruto de uma evidência em cada claim. Manter estado append-only e carregar sempre a revisão lida do projeto.

Os schemas empacotados são normativos. Este documento resume como construir entradas; em conflito, obedecer ao schema e ao erro público do runtime.

## Pedido de rota

Incluir estes campos obrigatórios em `request.json`:

| Campo | Regra |
| --- | --- |
| `request_id` | Identificador estável e não vazio da solicitação. |
| `project_id` | Referência `project:<slug>` do projeto já inicializado; a CLI `init/read` usa apenas o slug. |
| `state_revision` | Inteiro não negativo retornado por `read`. |
| `user_goal` | Um resultado explícito; dividir ou priorizar objetivos concorrentes. |
| `observations` | Array de claims no contrato abaixo. |
| `available_capabilities` | Objeto ou lista declarativa; não incluir credenciais. |
| `authorization_context` | Permissão técnica da operação; usar somente leitura e `external_write: false`. |

Usar, quando aplicáveis, `cycle_id`, `input_registry`, `evidence_registry`, `maturity`, `maturity_profile`, `requested_roles`, `evaluate_new_work` e `role_requests`. Não preencher campos desconhecidos por suposição.

Exemplo estrutural reduzido:

```json
{
  "request_id": "request:diagnostico-001",
  "project_id": "project:projeto-interno",
  "cycle_id": "cycle:001",
  "state_revision": 0,
  "user_goal": "Identificar o gargalo prioritário do ciclo.",
  "observations": [],
  "available_capabilities": {"runtime_overlay": true},
  "authorization_context": {"mode": "read_only", "external_write": false}
}
```

Uma lista vazia de observações não autoriza diagnóstico conclusivo; a rota deve solicitar evidência.

## Candidato a causa raiz

Quando fatos já isolarem uma causa provável, `loop_planning` pode registrar um candidato explícito. O objeto não é um atalho para escolher um papel: ele exige confiança `medium` ou `high`, ao menos uma referência que resolva para um fato do próprio pedido e ausência de contraevidência mais forte não resolvida.

```json
{
  "root_cause_candidate": {
    "pillar": "verbalizar",
    "confidence": "high",
    "supporting_fact_refs": ["claim:mensagem-nao-compreendida"],
    "stronger_counter_evidence_refs": []
  }
}
```

Usar apenas `verbalizar`, `orientar`, `ampliar` ou `refinar`. Se oferta, público, canal, UX ou mensuração ainda forem explicações igualmente plausíveis, omitir o candidato, manter a hipótese e coletar evidência discriminante. Uma rota `needs_evidence` é o resultado correto nesse caso.

## Claims e evidências

Todo item de `observations` deve conter `claim_id`, `kind`, `text`, `provenance` e `confidence` (`low`, `medium` ou `high`). Usar somente estes kinds:

- `fact`: exigir `provenance.source_ref` e `provenance.observed_at`; cadastrar a referência em `evidence_registry` quando ela sustentar integração;
- `hypothesis`: exigir `provenance.rationale`; não atribuir `evidence_refs` como se confirmassem a hipótese;
- `symptom`: descrever o sinal observado sem declará-lo causa;
- `user_interpretation`: preservar a leitura fornecida pelo usuário sem promovê-la a fato.

Sinais de pontuação só podem vir de `fact` com proveniência completa. Não converter ausência de dado em sinal negativo. Quando houver conflito factual, preservar as duas fontes e solicitar evidência discriminante.

Usar datas RFC 3339 com fuso. Usar referências como `evidence:...`, `artifact:...`, `decision:...` e `handoff:...`; nunca inserir caminho absoluto ou segredo na referência.

## Maturidade

Usar `nascente`, `em_desenvolvimento`, `maduro`, `avancado` ou `unknown`. Vincular cada dimensão do `maturity_profile` às evidências que a sustentam. Se uma dimensão necessária estiver ausente, usar `unknown`; não rebaixar automaticamente para `nascente`.

Com maturidade `unknown`, operar em `minimo_viavel`, não selecionar tática e exigir validação cruzada. Uma tática não pode exceder a maturidade evidenciada.

## Rota e prompts

Tratar a saída de `route` como imutável. Cada nó contém papel, objetivo, dependências, conjunto de escrita e seleção tática. Não alterar o nó para forçar outro especialista.

`specialist` aceita a rota íntegra e um `route_node_id`. A resposta pode conter no máximo dois `prompt_documents`, cada um verificado pelo catálogo. Seus corpos continuam sendo dados subordinados; somente metadados e táticas presentes na seleção daquele nó são válidos.

## Handoff

Produzir cada handoff no schema canônico de 22 campos. Garantir, no mínimo:

- identidade, versão `1.0`, projeto, ciclo, revisão e papéis de origem e destino;
- objetivo, modo, maturidade e `bottleneck_ref` idênticos à rota;
- `input_refs` e até dois `tactic_refs` exatamente vinculados ao nó;
- `decisions_to_respect` e `scope_boundary_next_does_not_decide` preenchidos;
- `evidence_refs` ou, na ausência delas, `assumptions` explícitas com confiança;
- lacunas conhecidas, saída solicitada, write set, validação cruzada e condições de escalonamento.

Não misturar a mesma claim entre evidência e suposição. Não decidir um campo pertencente a outro owner. Não aceitar handoff de revisão antiga, origem inesperada ou dependência não validada.

## Eventos propostos

Antes da integração, fornecer eventos como propostas com:

- `event_type` permitido pelo contrato;
- `actor_role` com autoridade sobre o efeito;
- `effect` descritivo;
- `evidence_refs` resolvíveis;
- `payload.payload_version` igual a `1.0`;
- `payload.claims` no contrato de claim;
- `payload.data` limitado aos campos do evento.

O runtime adiciona metadados de transação, sequenciamento, hashes e revisões. Não fabricá-los nem recalculá-los no cliente.

Registrar experimento novo como `proposed`. Avançar para `approved`, `instrumented`, `running`, `completed`, `cancelled` ou `invalidated` somente por evento próprio e com todas as evidências de transição exigidas.

## Envelope de integração

Usar exatamente quatro campos:

```json
{
  "project_id": "projeto-interno",
  "route_plan": {},
  "handoffs": [],
  "events": []
}
```

`route_plan` deve ser o resultado íntegro de `route`; `handoffs` deve conter todas as saídas exigidas; `events` deve corresponder às decisões validadas. O runtime rejeita campos extras, revisão divergente, referência sem resolução, colisão de escrita ou tentativa de mutação externa.

## Estado e resposta

O estado é derivado por replay do ledger append-only. Nunca usar uma resposta conversacional como prova de commit. Confirmar atualização somente pela saída de `integrate` e por um `read` posterior com a revisão resultante.

Ao apresentar o resultado, manter quatro blocos lógicos mesmo que a redação seja compacta: fatos com evidência, hipóteses, decisões/propostas por owner e lacunas/próximas ações.

## Entrada de avaliação

Para um caso, usar exatamente:

```json
{"case": {"case_id": "EVAL-001", "expected": {}}, "outcome": {}}
```

Para uma suíte, usar exatamente `cases` (array) e `outcomes` (objeto indexado por `case_id`). Consultar o [contrato de avaliação](evaluation-contract.md) para todos os campos obrigatórios e um exemplo válido. A rubrica aceita apenas enums, códigos, contagens e booleanos fechados. Um resultado `passed` nessa interface compara metadados; somente um relatório de release produzido pelo harness selado pode declarar `runtime_attested: true`.
