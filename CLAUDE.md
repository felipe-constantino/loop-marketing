# Loop Marketing — Instruções do Sistema

## Contexto de projeto (automático)

Ao executar qualquer skill do Loop Marketing (`/loop-planning-agent`, `/orientar-agent`, `/verbalizar-agent`, `/ampliar-agent`, `/refinar-agent`):

1. **ANTES de começar**: verificar se existe arquivo de projeto ativo em `.claude/loop-marketing/`. Checar primeiro se há um `.claude/loop-marketing/_active.md` — ele aponta para o projeto atual. Se não houver `_active.md`, listar os arquivos em `.claude/loop-marketing/` e perguntar qual projeto usar. Ler o arquivo do projeto e usar como contexto.

2. **DEPOIS de concluir**: atualizar o arquivo do projeto automaticamente, respeitando a política de escrita abaixo.

Se não existir arquivo de projeto e o usuário fornecer contexto de cliente específico, perguntar: "Quer que eu crie um arquivo de projeto para [cliente]?"

---

## Coleta proativa de contexto

**Antes de fazer qualquer pergunta ao usuário sobre inputs**, executar os seguintes passos:

1. **Buscar arquivos de processo no diretório do projeto**: procurar por arquivos `.md`, `.txt`, `.pdf` que possam conter jornada comercial, critérios de qualificação, playbooks, briefings ou documentação de produto. Ler o que for relevante antes de pedir ao usuário.

2. **Verificar credenciais de CRM/API na memória do projeto**: se houver token de API, pipeline IDs ou credenciais salvas nos arquivos de memória (`.claude/loop-marketing/memory/`), usá-los para puxar dados diretamente antes de perguntar ao usuário.

3. **Só perguntar o que não puder ser encontrado**: inputs que realmente dependem de julgamento humano ou que não existem em nenhum arquivo.

> Regra: perguntar ao usuário é o último recurso, não o primeiro.

---

## Política de escrita no arquivo de projeto (append-only)

Para garantir histórico auditável, a atualização do arquivo de projeto segue regras rígidas:

| Seção | Política | Regra |
|---|---|---|
| 4. Decisões tomadas | **Append-only** | Nunca remover ou reescrever entradas existentes. Só adicionar novas linhas ao final. |
| 5. Testes ativos | **Append-only** | Nunca remover testes. Atualizar o campo `Status` da linha existente se o teste mudou. |
| 6. Aprendizados | **Append-only** | Nunca remover aprendizados. Só adicionar novos. |
| 8. Histórico de gargalos | **Append-only** | Nunca reescrever. Só acrescentar nova linha quando gargalo muda. |
| 3. Gargalo atual | **Overwrite permitido** | Substituir pelo gargalo atual. Antes de substituir, mover o anterior para seção 8. |
| 7. Próxima ação | **Overwrite permitido** | Substituir pela próxima ação atualizada. |
| 1. Contexto | **Overwrite permitido** | Atualizar apenas se dado factual mudou (ex: nova ferramenta, novo canal). |
| 2. Maturidade | **Overwrite c/ registro** | Atualizar classificação + registrar na seção 4 como decisão: "[Data] Maturidade reclassificada de X para Y — Motivo: [1 frase]" |

**Revisão de scoring**: se o score de um pilar mudar após novos dados (ex: Orientar foi 8/10 e passou a 10/10 após auditoria de API), não substituir silenciosamente. Registrar na seção 4: "[Data] Loop Planning → revisão de scoring → Orientar reclassificado de 8/10 para 10/10 após [evidência]".

---

## Validação cruzada (multi-skill)

Quando 2 ou mais skills rodarem no mesmo ciclo, o loop-planning-agent (ou o analista, se estiver presente) deve executar o **Passo 5: Validação Cruzada** antes de encerrar o ciclo:

- Os segmentos definidos pelo Orientar são coerentes com o tom/mensagem definidos pelo Verbalizar?
- As regras de canal do Ampliar respeitam as regras de elegibilidade do Orientar?
- Algum skill recomendou algo que contradiz outro?

Se houver tensão: apresentar ao usuário com as duas perspectivas e recomendar resolução. Conflitos implícitos não são aceitáveis.

---

## Idioma

Responder em português (PT-BR) por padrão.

## Princípio

O sistema produz decisões, não análises. Todo output deve terminar em ação concreta. A disciplina de atualização do projeto não depende do analista lembrar — ela é automática por design.
