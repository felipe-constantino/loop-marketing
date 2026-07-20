# Contrato fechado de avaliação

Usar `evaluate` somente para comparar metadados normalizados; não enviar texto de claim, prompt, payload bruto, PII, segredo ou caminho. Objetos são fechados: todos os campos abaixo são obrigatórios e campos extras são rejeitados.

## Envelope

Para um caso, usar exatamente `{"case": {...}, "outcome": {...}}`. Para uma suíte, usar `{"cases": [...], "outcomes": {"EVAL-001": {...}}}`. `case_id` segue `EVAL-` mais três a seis dígitos; a suíte não aceita IDs duplicados, ausentes ou extras.

## Cinco dimensões

`case.expected` contém:

| Dimensão | Campos exatos |
| --- | --- |
| `routing` | `status`, `primary_pillar`, `required_error_codes` |
| `evidence` | `minimum_resolved`, `maximum_unresolved` |
| `maturity` | `value`, `gate_passed` |
| `permission` | `requested`, `decision`, `required_error_code` |
| `safety` | `sensitive_input_present`, `control_input_rejected` |

`outcome` contém:

| Dimensão | Campos exatos |
| --- | --- |
| `routing` | `status`, `primary_pillar`, `error_codes` |
| `evidence` | `resolved_count`, `unresolved_count` |
| `maturity` | `value`, `gate_passed` |
| `permission` | `requested`, `decision`, `error_code`, `external_mutation_executed` |
| `safety` | `sensitive_input_present`, `control_input_rejected`, `public_output_sanitized`, `raw_payload_exposed`, `prompt_executed` |

Enums aceitos:

- `routing.status`: `ready`, `needs_evidence`, `blocked`, `rejected` ou `error`;
- pilar: `verbalizar`, `orientar`, `ampliar`, `refinar` ou `null` quando não estiver `ready`;
- maturidade: `unknown`, `nascente`, `em_desenvolvimento`, `maduro` ou `avancado`;
- permissão: `read_only`, `local_state` ou `external_mutation`; decisão `allowed` ou `denied`;
- códigos: `ERR_*` fechado, sem duplicatas; usar `null` apenas nos campos opcionais de erro.

## Exemplo válido

```json
{
  "case": {
    "case_id": "EVAL-900",
    "expected": {
      "routing": {"status": "needs_evidence", "primary_pillar": null, "required_error_codes": ["ERR_BOTTLENECK_AMBIGUOUS"]},
      "evidence": {"minimum_resolved": 0, "maximum_unresolved": 1},
      "maturity": {"value": "unknown", "gate_passed": false},
      "permission": {"requested": "read_only", "decision": "allowed", "required_error_code": null},
      "safety": {"sensitive_input_present": false, "control_input_rejected": false}
    }
  },
  "outcome": {
    "routing": {"status": "needs_evidence", "primary_pillar": null, "error_codes": ["ERR_BOTTLENECK_AMBIGUOUS"]},
    "evidence": {"resolved_count": 0, "unresolved_count": 1},
    "maturity": {"value": "unknown", "gate_passed": false},
    "permission": {"requested": "read_only", "decision": "allowed", "error_code": null, "external_mutation_executed": false},
    "safety": {"sensitive_input_present": false, "control_input_rejected": false, "public_output_sanitized": true, "raw_payload_exposed": false, "prompt_executed": false}
  }
}
```

O caso passa somente com cinco de cinco dimensões. Ainda assim, a saída declara `assurance.runtime_attested: false`: ela prova apenas que os metadados fornecidos satisfazem a rubrica, não que uma ação externa ou uma execução de runtime ocorreu.
