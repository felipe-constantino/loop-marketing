"""Closed validation for the user-facing Loop Marketing conversation protocol."""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping

from .errors import LoopRuntimeError, require


SPEAKER_LABELS = {
    "loop_planning": "Loop Agent",
    "verbalizar": "Express · Verbalizar",
    "orientar": "Tailor · Orientar",
    "ampliar": "Amplify · Ampliar",
    "refinar": "Evolve · Refinar",
}

TURN_KINDS = frozenset((
    "context_review",
    "route_proposal",
    "specialist_deliberation",
    "clarification",
    "handoff_proposal",
    "handoff_accepted",
    "execution_plan",
    "cycle_closed",
    "results_intake",
    "cycle_restart",
    "status_update",
))

DECISION_STATUSES = frozenset((
    "not_applicable",
    "draft",
    "proposed",
    "user_approved",
    "provisional_user_approved",
    "user_rejected",
    "rework",
))

HANDOFF_STATUSES = frozenset(("none", "proposed", "approved", "rework"))


def speaker_header(role_id: str) -> str:
    require(role_id in SPEAKER_LABELS, "ERR_DIALOGUE_SPEAKER", "Unknown conversational speaker role.")
    return "---\n**%s**\n---" % SPEAKER_LABELS[role_id]


def _valid_ref(value: Any, prefix: str) -> bool:
    return isinstance(value, str) and re.fullmatch(
        r"%s[A-Za-z0-9][A-Za-z0-9._:-]{0,127}" % re.escape(prefix), value
    ) is not None


def validate_dialogue_turn(control: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate metadata for one visible assistant turn without inspecting content."""

    require(isinstance(control, Mapping), "ERR_DIALOGUE_CONTRACT", "Dialogue control must be an object.")
    required = {
        "conversation_version",
        "cycle_id",
        "turn_id",
        "speaker_role",
        "speaker_label",
        "speaker_header",
        "turn_kind",
        "decision_status",
        "handoff",
        "user_approval_ref",
        "must_pause",
    }
    require(
        set(control) == required,
        "ERR_DIALOGUE_CONTRACT",
        "Dialogue control fields do not match the closed contract.",
        required_fields=sorted(required),
    )
    require(control["conversation_version"] == "1.0", "ERR_DIALOGUE_CONTRACT", "Unsupported conversation version.")
    require(_valid_ref(control["cycle_id"], "cycle:"), "ERR_DIALOGUE_CONTRACT", "Invalid cycle_id.")
    require(_valid_ref(control["turn_id"], "turn:"), "ERR_DIALOGUE_CONTRACT", "Invalid turn_id.")

    role = control["speaker_role"]
    require(role in SPEAKER_LABELS, "ERR_DIALOGUE_SPEAKER", "Unknown conversational speaker role.")
    require(control["speaker_label"] == SPEAKER_LABELS[role], "ERR_DIALOGUE_SPEAKER", "Speaker label does not match role.")
    expected_header = speaker_header(role)
    require(control["speaker_header"] == expected_header, "ERR_DIALOGUE_SPEAKER", "Every visible turn must start with the exact speaker header.")

    kind = control["turn_kind"]
    status = control["decision_status"]
    require(kind in TURN_KINDS, "ERR_DIALOGUE_CONTRACT", "Unknown dialogue turn kind.")
    require(status in DECISION_STATUSES, "ERR_DIALOGUE_CONTRACT", "Unknown dialogue decision status.")
    require(type(control["must_pause"]) is bool, "ERR_DIALOGUE_CONTRACT", "must_pause must be boolean.")

    handoff = control["handoff"]
    require(isinstance(handoff, Mapping), "ERR_DIALOGUE_HANDOFF", "handoff must be an object.")
    require(set(handoff) == {"status", "from_role", "to_role"}, "ERR_DIALOGUE_HANDOFF", "handoff fields do not match the closed contract.")
    handoff_status = handoff["status"]
    require(handoff_status in HANDOFF_STATUSES, "ERR_DIALOGUE_HANDOFF", "Unknown handoff status.")
    approval_ref = control["user_approval_ref"]

    if handoff_status == "none":
        require(handoff["from_role"] is None and handoff["to_role"] is None, "ERR_DIALOGUE_HANDOFF", "A non-handoff turn cannot name roles.")
    else:
        require(handoff["from_role"] in SPEAKER_LABELS and handoff["to_role"] in SPEAKER_LABELS,
                "ERR_DIALOGUE_HANDOFF", "A handoff must name canonical roles.")
        require(handoff["from_role"] != handoff["to_role"], "ERR_DIALOGUE_HANDOFF", "A role cannot hand off to itself.")

    if kind in {"route_proposal", "handoff_proposal", "cycle_restart"}:
        require(handoff_status == "proposed", "ERR_DIALOGUE_HANDOFF", "This turn must present a proposed handoff.")
        require(handoff["from_role"] == role, "ERR_DIALOGUE_HANDOFF", "The active speaker must own the proposed handoff.")
        require(status == "proposed", "ERR_DIALOGUE_APPROVAL_REQUIRED", "A proposed handoff cannot be marked accepted.")
        require(approval_ref is None, "ERR_DIALOGUE_APPROVAL_REQUIRED", "A proposal cannot fabricate an approval reference.")
        require(control["must_pause"] is True, "ERR_DIALOGUE_APPROVAL_REQUIRED", "A proposed handoff must pause for user approval.")
    elif kind == "handoff_accepted":
        require(handoff_status == "approved", "ERR_DIALOGUE_HANDOFF", "An accepted turn requires an approved handoff.")
        require(handoff["to_role"] == role, "ERR_DIALOGUE_HANDOFF", "Only the approved destination may become the active speaker.")
        require(status in {"user_approved", "provisional_user_approved"},
                "ERR_DIALOGUE_APPROVAL_REQUIRED", "A handoff requires explicit user approval.")
        require(_valid_ref(approval_ref, "approval:"), "ERR_DIALOGUE_APPROVAL_REQUIRED", "Approved handoff lacks a valid approval_ref.")
    else:
        require(handoff_status in {"none", "rework"}, "ERR_DIALOGUE_HANDOFF", "This turn cannot silently advance to another role.")
        require(approval_ref is None or _valid_ref(approval_ref, "approval:"),
                "ERR_DIALOGUE_APPROVAL_REQUIRED", "Invalid approval_ref.")

    if kind == "execution_plan":
        require(role == "loop_planning", "ERR_DIALOGUE_SPEAKER", "Only Loop Agent may integrate the execution plan.")
        require(status == "proposed" and control["must_pause"] is True,
                "ERR_DIALOGUE_APPROVAL_REQUIRED", "The execution plan must be proposed for user approval.")
    if kind in {"context_review", "results_intake", "cycle_restart", "cycle_closed"}:
        require(role == "loop_planning", "ERR_DIALOGUE_SPEAKER", "This turn belongs to Loop Agent.")

    return {
        "valid": True,
        "speaker_role": role,
        "speaker_label": SPEAKER_LABELS[role],
        "speaker_header": expected_header,
        "turn_kind": kind,
        "must_pause": control["must_pause"],
        "handoff_status": handoff_status,
        "may_start_destination": kind == "handoff_accepted",
    }


__all__ = ("SPEAKER_LABELS", "speaker_header", "validate_dialogue_turn")
