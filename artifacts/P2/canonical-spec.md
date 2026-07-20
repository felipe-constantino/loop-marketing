# Especificação canônica — Loop Marketing v2.0

Status: integrado em P2  
Versão do produto: `2.0.0`  
Versão desta especificação: `1.0`  
Idioma de interface padrão: `pt-BR`  

## 1. Definição do produto

Loop Marketing v2 é uma **skill composta com workflow orquestrado e runtime de decisão local** para CRM e lifecycle marketing. Ela reúne um planner, quatro especialistas, uma biblioteca tática canônica, contratos verificáveis, estado auditável e adaptadores de host.

Não é apenas uma coleção de prompts e não é um produto oficial da HubSpot. É uma implementação própria baseada no framework Loop Marketing da HubSpot e em uma coleção local de 100 prompts associada a esse framework.

A HubSpot mantém quatro estágios oficiais — Express, Tailor, Amplify e Evolve — e descreve uma biblioteca de prompts para esses estágios. A v2 preserva esse mapeamento metodológico e acrescenta uma camada operacional verificável, sem alegar que os contratos internos desta ferramenta são especificação da HubSpot.

Fontes metodológicas consultadas em 2026-07-17:

- [Loop Marketing — The Playbook](https://www.hubspot.com/loop-marketing)
- [HubSpot introduces the Loop](https://www.hubspot.com/company-news/loop)

## 2. Camadas canônicas

| Camada | Função | Autoridade |
|---|---|---|
| Biblioteca canônica | Conhecimento tático original: 100 prompts, 25 por pilar | Imutável por caminho e hash dentro da migração v2 |
| Catálogo | Metadados, maturidade, aliases, entradas, saídas e relações entre táticas | Pode evoluir sem alterar o prompt original |
| Contratos de decisão | Papéis, fronteiras, roteamento, handoff e critérios de aceite | Especificação v2 |
| Estado e eventos | Projeto versionado, evidências, decisões, experimentos e histórico | Schemas + event log append-only |
| Runtime | Validação, máquina de estados, seleção, autorização e integração | Código determinístico |
| Adaptadores | Superfícies para Claude, Codex e outros hosts | Nunca são donos do estado canônico |
| Avaliações | Regressão, cadeia, segurança, red team e qualidade | Gate de release |

O carregamento continua progressivo: o planner não carrega a biblioteca inteira; o especialista consulta metadados do seu pilar e carrega somente a tática selecionada.

## 3. Invariantes normativos

1. Os 100 prompts canônicos permanecem presentes, identificáveis pelo caminho original e verificáveis pelo hash do baseline.
2. Alias, correção editorial, tradução alternativa ou relação de duplicidade é metadado; nunca substitui silenciosamente o original.
3. O output bruto de uma tática nunca é a decisão final; o especialista responsável deve reenquadrá-lo no seu contrato.
4. Fato, interpretação, hipótese, decisão e ação são tipos diferentes e não podem ser convertidos implicitamente.
5. Todo claim factual relevante carrega fonte; ausência de fonte rebaixa o claim para hipótese explícita.
6. O planner é o único owner do gargalo ativo, da sequência de execução e da integração cross-pillar.
7. Cada decisão de domínio tem um único owner; outros papéis podem fornecer restrições ou solicitar revisão, mas não sobrescrever a decisão.
8. Todo handoff carrega uma fronteira de escopo executável e é rejeitado se estiver incompleto ou contraditório.
9. Estado de experimento só avança por transição válida acompanhada de evidência real do evento.
10. Computação paralela só produz propostas sobre um snapshot imutável; integração e escrita de estado são serializadas pelo orquestrador.
11. Ações externas são read-only por padrão. Escrita exige manifesto de ação e autorização humana específica.
12. Tokens, credenciais, conteúdo secreto e PII desnecessária nunca entram em prompts, eventos, logs ou artefatos de avaliação.
13. Nenhum host possui namespace de estado próprio. Claude e Codex são adaptadores para o mesmo projeto canônico.
14. Erro de validação bloqueia a transição ou ação; o sistema não “completa” campos críticos por inferência silenciosa.

## 4. Vocabulário canônico

| Termo | Definição |
|---|---|
| Projeto | Unidade persistente de contexto de um cliente ou operação, identificada por `project_id` seguro |
| Execução do loop | Uma tentativa versionada de diagnosticar um objetivo, resolver o gargalo e registrar aprendizado |
| Planner | Orquestrador que diagnostica, seleciona o gargalo, ordena papéis e integra outputs |
| Especialista | Um dos quatro owners de decisão: Verbalizar, Orientar, Ampliar ou Refinar |
| Pilar | Nome operacional em português para um estágio metodológico do Loop |
| Tática | Um prompt canônico selecionado como insumo do especialista |
| Handoff | Contrato validado que transfere contexto, restrições e objetivo entre papéis |
| Evidência | Referência verificável que prova um fato ou evento sem copiar segredo/PII desnecessária |
| Evento | Registro imutável de uma mudança proposta ou aceita no projeto |
| Snapshot | Visão derivada do event log em uma revisão conhecida; nunca substitui o histórico |
| Ação externa | Leitura ou escrita em CRM, arquivo fora do estado local, plataforma, campanha ou API |

Valores de máquina usam identificadores ASCII estáveis; labels em português são apresentação e podem ser localizados.

## 5. Mapeamento metodológico

| Ordem metodológica | Estágio HubSpot | Papel v2 | Decisão central |
|---:|---|---|---|
| 1 | Express | Verbalizar | O que dizer, por que importa e como manter a identidade da mensagem |
| 2 | Tailor | Orientar | Para quem, em qual estágio e sob quais condições a pessoa é elegível |
| 3 | Amplify | Ampliar | Em quais canais, sequência operacional, momento e cadência distribuir |
| 4 | Evolve | Refinar | Como medir, testar, decidir e realimentar o próximo ciclo |

A ordem é uma dependência padrão, não uma obrigação de iniciar sempre em Express. O planner pode começar por Refinar quando há dados suficientes e o locus do problema é desconhecido; pode entrar diretamente em outro pilar quando o gargalo já está provado. As exceções são regidas por `routing-contract.json`.

## 6. Fluxo normativo

```text
intenção do usuário
  -> normalização e fronteira de confiança
  -> carregamento de snapshot e evidências
  -> separação entre fatos, hipóteses e lacunas
  -> diagnóstico e seleção de gargalo pelo planner
  -> rota validada e requisitos de entrada
  -> execução de especialista sobre snapshot imutável
  -> seleção de tática pelo catálogo
  -> output reenquadrado no contrato do owner
  -> handoff validado
  -> integração serial pelo planner
  -> eventos propostos e validação determinística
  -> persistência local autorizada
  -> manifesto + autorização separada para eventual escrita externa
```

Invocação direta de especialista é permitida apenas quando o pedido pertence inequivocamente a um único domínio e seus inputs obrigatórios estão disponíveis. Caso contrário, o especialista devolve um erro estruturado e solicita planner ou pré-requisito; não assume o domínio ausente.

## 7. Autoridade de decisão

O contrato detalhado está em `role-matrix.json`. Em resumo:

- **Planner:** gargalo, prioridade, rota, integração e resolução de conflito.
- **Verbalizar:** tese, proposta de valor, hierarquia, claims, voz e variações de mensagem para segmentos já fornecidos.
- **Orientar:** definição de audiência, lifecycle, inclusão/exclusão, elegibilidade, supressão e evento comportamental que torna alguém elegível.
- **Ampliar:** papel, fit e escolha de canais, sequência de touchpoints, momento operacional, frequência, cadência, pressão global e coordenação cross-channel. Sua classificação de canal é operacional (`primário | secundário | evitar`), não a classificação de performance de Refinar.
- **Refinar:** diagnóstico de performance, KPI/threshold de decisão, desenho experimental, suficiência de evidência e aprendizado.

Distinção obrigatória: Orientar decide **quando uma condição de lifecycle torna alguém elegível**; Ampliar decide **quando e com que frequência o contato elegível será entregue**.

## 8. Seleção da biblioteca

1. O runtime filtra táticas por pilar, função, inputs disponíveis, maturidade e restrições.
2. O especialista usa **zero táticas** quando o método-base basta, não existe match exato seguro ou os metadados/pré-requisitos ainda são insuficientes; uma tática nunca é forçada para preencher o fluxo.
3. Quando existe match elegível, o padrão é **uma tática primária por nó de rota** (`route_node_id`).
4. Uma segunda tática só é permitida quando é complementar, possui output distinto e a lacuna residual é declarada.
5. O limite duro é duas táticas por nó de rota de um especialista. Se o mesmo especialista precisar reaparecer no ciclo, o planner cria outro nó com objetivo e dependências próprios; nunca aumenta o limite do nó atual.
6. Relações de sobreposição geram aliases ou sugestões no catálogo; não remoção de arquivos.
7. A seleção registra `tactic_id`, caminho, hash, motivo, pré-requisitos e papel owner.

## 9. Handoff mínimo

Todo handoff contém, no mínimo:

- identidade e revisão: `handoff_id`, `contract_version`, `project_ref`, `cycle_id`, `state_revision`, `created_at`;
- papéis: `from_role` e `to_role`;
- contexto decisório: `objective`, `mode`, `maturity` e `bottleneck_ref`;
- proveniência: `input_refs`, `tactic_refs`, `evidence_refs` e `assumptions`;
- continuidade: `decisions_to_respect`, `known_gaps` e `requested_output`;
- fronteira: `scope_boundary_next_does_not_decide`;
- controle: `cross_validation_required` e `escalation_conditions`.

`tactic_refs` pode ser vazio. Quando houver seleção, cada item registra ID, caminho, hash e motivo; o conteúdo do prompt não é copiado para o handoff. Os 22 nomes acima são o contrato canônico. Campos específicos do papel podem ser adicionados, mas nenhum obrigatório pode ser removido ou renomeado por um adaptador.

O destinatário não executa um handoff inválido. O planner corrige o contrato ou replaneja a rota.

## 10. Maturidade e suficiência

A maturidade deixa de ser apenas um rótulo livre. O perfil deve registrar evidência por dimensão: lifecycle, segmentação, dados/identidade, automação, mensuração/experimentos e atribuição. O label de máquina agregado (`nascente`, `em_desenvolvimento`, `maduro`, `avancado` ou `unknown`) é derivado por regra versionada.

Ausência de dados não é maturidade baixa automaticamente. É `unknown` na dimensão afetada; se as dimensões obrigatórias não permitem provar uma classificação, o agregado também é `unknown`, limita a confiança e bloqueia a tática. `nascente` só é emitido quando todas as dimensões classificatórias obrigatórias são conhecidas e nenhuma faixa superior é satisfeita. P3 catalogará os pré-requisitos de cada prompt; P5 aplicará o gate no runtime.

## 11. Estado e experimentos

O estado canônico será host-neutral em `.loop-marketing/`, com projetos por `project_id`, event log append-only e snapshots derivados. P4 definirá schemas e migração detalhados.

Estados de máquina de experimento na v2:

`proposed -> approved -> instrumented -> running -> completed`

O enum completo é `proposed | approved | instrumented | running | completed | cancelled | invalidated`. `cancelled` é terminal a partir de qualquer estado não terminal, sempre com motivo e evidência. `invalidated` é uma disposição terminal permitida a partir de `instrumented`, `running` ou `completed` quando uma falha de integridade invalida os dados; ela não apaga a conclusão anterior. Saltos, regressões e conclusão sem resultado são inválidos. Uma nova tentativa cria uma revisão ou novo experimento ligado ao anterior; nunca reescreve o evento histórico.

## 12. Segurança e ações externas

Conteúdo vindo de arquivos, CRM, transcrições, páginas ou APIs é dado não confiável, nunca instrução. O runtime registra proveniência e restringe ferramentas. Credenciais são referências opacas resolvidas por provedor seguro; nunca são descobertas ou copiadas de arquivos Markdown.

Diagnóstico e plano não autorizam execução externa. Cada escrita futura deverá apresentar tenant, sistema, operação, objetos, escopo, reversibilidade e efeito esperado, então obter aprovação humana específica. P6 formalizará esse manifesto e os adaptadores read-only/write.

## 13. Compatibilidade

Os comandos v1.2 continuam reconhecíveis. A v2 terá nomes canônicos únicos e aliases documentados; aliases nunca criam estado paralelo. Estados em `.claude/loop-marketing/` ou `.Codex/loop-marketing/` são fontes legadas de importação, não namespaces ativos da v2. A política completa está em `compatibility-policy.md`.

## 14. Gates de qualidade

P2 só termina quando:

- os contratos oficiais não possuem owner conflitante ou intervalo decisório aberto;
- todos os handoffs carregam a fronteira obrigatória;
- regras de paralelismo nunca permitem escrita concorrente;
- os nomes e aliases levam ao mesmo estado canônico;
- cenários de compatibilidade e rejeição possuem resultado determinístico;
- os artefatos oficiais validam entre si;
- o repositório-fonte continua no baseline e os 100 hashes permanecem intactos.

Antes de distribuição pública, a proveniência e as condições de redistribuição da biblioteca externa devem ser verificadas; essa revisão não autoriza alterar ou remover conteúdo do baseline local.
