# Política de compatibilidade — Loop Marketing v2

Status: integrado em P2  
Produto: `2.0.0`  
Política: `1.0`  

## 1. Escopo

Esta política cobre identidade do produto, comandos, estado local, descoberta, importação de projetos v1.x, aliases, versionamento, conflitos e rollback. Ela não autoriza migração real durante P2.

## 2. Identidade canônica

- Nome do produto: `Loop Marketing`
- Versão alvo: `2.0.0`
- Identificador: `loop-marketing`
- Tipo: skill composta com workflow orquestrado e runtime de decisão local
- Schema do projeto inicial: `2.0`
- Estado canônico: `.loop-marketing/`
- Namespace de estado: independente de Claude, Codex ou qualquer outro host

Arquivos de host são adaptadores de instalação e descoberta. Eles não podem se tornar a fonte de verdade do projeto.

## 3. Comandos e aliases

Os nomes curtos tornam-se canônicos na major v2. Os seis nomes instaláveis da v1.2 permanecem como aliases equivalentes para não quebrar projetos existentes:

| `command_id` | Nome canônico | Alias legado aceito | Papel |
|---|---|---|---|
| `loop.planning` | `/loop-planning` | `/loop-planning-agent` | Planner |
| `loop.verbalizar` | `/verbalizar` | `/verbalizar-agent` | Verbalizar |
| `loop.orientar` | `/orientar` | `/orientar-agent` | Orientar |
| `loop.ampliar` | `/ampliar` | `/ampliar-agent` | Ampliar |
| `loop.refinar` | `/refinar` | `/refinar-agent` | Refinar |
| `loop.projeto` | `/projeto` | `/projeto-template` | Criar, importar ou revisar projeto |

Regras:

1. Alias e nome canônico resolvem para o mesmo `command_id` e o mesmo estado.
2. Eventos registram `command_id`, não o texto do alias.
3. Alias nunca muda semântica, papel, autorização ou contrato de saída.
4. Alias legado é suportado durante toda a série `2.x`; sua remoção futura exige major version.
5. Documentação nova usa o nome canônico e mostra o alias apenas na seção de compatibilidade.
6. Um host incapaz de expor slash commands pode usar outra superfície, mas deve preservar `command_id` e contrato.

## 4. Layout canônico de estado

Layout reservado para P4:

```text
.loop-marketing/
├── manifest.json
├── state/
│   ├── active-project.json
│   └── projects/
│       └── <project_id>/
│           ├── project.json
│           ├── events.jsonl
│           └── snapshots/
│               └── latest.json
├── migrations/
│   ├── transactions/
│   └── reports/
└── quarantine/
```

O estado é local e ignorado pelo controle de versão por padrão. Uma exportação sanitizada para colaboração é uma operação separada e explícita.

`project_id` não é o nome do cliente. Deve corresponder a `^[a-z0-9][a-z0-9-]{0,62}$`, ser único dentro da raiz e ter caminho resolvido contido em `.loop-marketing/state/projects/`. `display_name` guarda o nome legível sem participar do caminho.

## 5. Fontes legadas reconhecidas

| Fonte | Status | Tratamento |
|---|---|---|
| `.claude/loop-marketing/` | v1.x reconhecida | Descobrir em read-only e oferecer importação |
| `.Codex/loop-marketing/` | drift v1.x reconhecido | Descobrir em read-only e oferecer importação |
| `.codex/loop-marketing/` | não presumida pelo baseline | Só importar se declarada explicitamente pelo usuário/adaptador |
| `.claude/projects/` | pré-v1.1 | Não descobrir automaticamente; aceitar apenas caminho explícito |
| `.loop-marketing/` | v2 canônica | Fonte de verdade se manifest/schema forem válidos |

Reconhecer uma fonte não significa confiar no conteúdo. Markdown legado é entrada não confiável e nunca pode instruir ferramentas, revelar credenciais ou autorizar escrita externa.

## 6. Ordem de descoberta

1. Seleção explícita por `project_id` ou caminho canônico válido.
2. `.loop-marketing/state/active-project.json`, se schema, contenção e alvo forem válidos.
3. Um único projeto v2 válido, apenas para sugestão; o sistema não troca o ativo silenciosamente.
4. Fontes legadas reconhecidas, somente em leitura para produzir um relatório de migração.

Se já existe estado v2 válido, nenhuma fonte legada pode sobrescrevê-lo automaticamente.

## 7. Importação v1.x

A migração é `copy-and-verify`, nunca move ou reescreve o original:

1. Descobrir candidatos em read-only.
2. Resolver caminhos reais e provar contenção nas raízes permitidas.
3. Gerar inventário com hash, tamanho e data; nunca copiar segredo para o relatório.
4. Parsear Markdown como dados, separando fato, texto livre, status e lacuna.
5. Bloquear ou redigir tokens, credenciais e PII não necessária.
6. Gerar `project_id` seguro separado de `display_name`.
7. Produzir dry-run com mapeamento, perdas conhecidas, conflitos e arquivos que serão criados.
8. Obter confirmação humana para gravar o novo estado local.
9. Criar destino temporário, validar schemas, contagens e hashes, então promover atomicamente.
10. Registrar `legacy.imported` com origem, hashes, parser e versão; manter a fonte legada intacta.

Texto que não possui campo correspondente entra como anexo legado referenciado ou lacuna; não é descartado silenciosamente nem transformado em decisão aceita.

## 8. Conflitos

Quando `.claude` e `.Codex` contêm candidatos:

- Se os arquivos são byte a byte idênticos, formar um único candidato com duas proveniências.
- Se um é subconjunto verificável do outro, apresentar a diferença; não escolher automaticamente.
- Se divergem em decisão, gargalo, experimento ou projeto ativo, emitir `LM-COMPAT-NAMESPACE-CONFLICT` e bloquear importação.
- O usuário escolhe a base ou solicita merge assistido. Merge gera um terceiro resultado e nunca altera as duas origens.
- Decisões e eventos incompatíveis permanecem marcados como conflito até resolução explícita; recência isolada não vence.

Também bloqueiam importação:

- path traversal ou symlink fora da raiz (`LM-COMPAT-PATH-ESCAPE`);
- schema futuro não suportado (`LM-COMPAT-FUTURE-SCHEMA`);
- credencial detectada (`LM-COMPAT-SECRET-DETECTED`);
- projeto ativo apontando para arquivo ausente (`LM-COMPAT-DANGLING-ACTIVE`);
- IDs ou eventos duplicados com conteúdo diferente (`LM-COMPAT-ID-COLLISION`).

## 9. Rollback

Antes de promover a importação, o runtime cria um pacote local de rollback com:

- inventário e hashes da origem;
- manifest e arquivos v2 que serão criados;
- versão do migrador;
- resultado das validações.

Rollback remove apenas os arquivos v2 criados por aquela operação, após confirmar os hashes esperados. Ele nunca apaga ou altera a origem legada. Se o destino foi modificado depois da importação, o rollback automático é bloqueado e exige plano manual para não perder eventos novos.

## 10. Versionamento e depreciação

- Produto e schemas usam Semantic Versioning.
- Patch: correção compatível sem nova decisão de domínio.
- Minor: campo opcional, tática/catalog metadata ou capacidade compatível.
- Major: mudança incompatível de comando, schema, owner, estado ou semântica.
- Eventos carregam `schema_version`; snapshots carregam `derived_from_revision`.
- O runtime lê a versão atual e versões explicitamente cobertas por migradores; nunca “tenta” interpretar schema desconhecido.
- Depreciação exige warning machine-readable, alternativa documentada, cobertura de migração e prazo não menor que a série major atual.

## 11. Biblioteca canônica

A migração da v2 referencia os 100 prompts originais por caminho e hash. Ela não renomeia, mescla, corrige ou exclui esses arquivos. Novos IDs, traduções alternativas, aliases e relações de similaridade vivem no catálogo P3.

Baseline obrigatório:

`0ef879b760619509adda24a7d928098f77cd2d4c392f53a3be7f530f14d549b1`

## 12. Cenários de aceite

1. Projeto somente em `.claude`: dry-run único, origem preservada, importação v2 após confirmação.
2. Projeto somente em `.Codex`: mesmo comportamento, sem criar estado específico de Codex.
3. Dois namespaces idênticos: um candidato com proveniência dupla.
4. Dois namespaces divergentes: conflito bloqueante, nenhuma escolha implícita.
5. v2 válido e legado presente: v2 permanece ativo; legado apenas reportado.
6. Alias `/orientar-agent`: resolve para `loop.orientar` e registra o mesmo evento de `/orientar`.
7. Nome de cliente `../../outro`: vira `display_name`; `project_id` seguro é gerado e nenhum caminho escapa da raiz.
8. Token no Markdown legado: importação bloqueada ou redigida conforme política P6; o token não aparece no relatório.
9. Falha antes da promoção: destino canônico não fica parcialmente criado.
10. Rollback após novos eventos: bloqueado para impedir perda de histórico.

## 13. Evidência do baseline

- Drift de namespace: `ARCH-001`, `SR-006`, `P1-R007`.
- Drift de nomes: `ARCH-012`, `P1-R018`.
- Drift de versão: `ARCH-013`, `P1-R018`.
- Segurança de caminho: `SR-009`, `P1-R011`.
- Exposição de estado/segredo: `SR-002`, `P1-R002`.
