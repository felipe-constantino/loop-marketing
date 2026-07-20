"""P7 privacy and determinism tests for metadata-only observability."""

from __future__ import annotations

import copy
import unittest
from unittest import mock

from loop_marketing_runtime.errors import LoopRuntimeError
from loop_marketing_runtime.observability import AuditCollector, build_audit_record


class ObservabilityTests(unittest.TestCase):
    @staticmethod
    def _dimensions():
        return {
            "component": "evaluator",
            "operation": "aggregate",
            "pillar": "verbalizar",
            "maturity": "em_desenvolvimento",
            "permission": "read_only",
            "duration_bucket": "under_10ms",
            "error_family": "none",
        }

    def test_collection_and_persistence_are_disabled_by_default(self) -> None:
        collector = AuditCollector()
        self.assertFalse(collector.enabled)
        self.assertFalse(collector.persistence_enabled)
        with mock.patch(
            "loop_marketing_runtime.observability.build_audit_record",
            side_effect=AssertionError("disabled telemetry must not process metadata"),
        ):
            self.assertIsNone(collector.emit("evaluation_completed", "passed"))
        self.assertEqual((), collector.records())

    def test_enabled_collection_is_in_memory_allowlisted_and_deterministic(self) -> None:
        collector = AuditCollector(enabled=True)
        dimensions = self._dimensions()
        metrics = {"item_count": 5, "violation_count": 0}
        with mock.patch("builtins.open", side_effect=AssertionError("no persistence")):
            first = collector.emit(
                "evaluation_completed",
                "passed",
                dimensions=dimensions,
                metrics=metrics,
            )
        second = build_audit_record(
            "evaluation_completed",
            "passed",
            dimensions=copy.deepcopy(dimensions),
            metrics=copy.deepcopy(metrics),
        )
        self.assertEqual(first, second)
        self.assertRegex(first["record_fingerprint"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(
            {"schema_version", "event_type", "outcome", "dimensions", "metrics", "record_fingerprint"},
            set(first),
        )
        self.assertFalse(collector.persistence_enabled)

    def test_records_are_defensive_copies(self) -> None:
        collector = AuditCollector(enabled=True)
        emitted = collector.emit("route_evaluated", "passed", metrics={"item_count": 1})
        emitted["metrics"]["item_count"] = 999
        exported = collector.records()
        self.assertEqual(1, exported[0]["metrics"]["item_count"])
        exported[0]["metrics"]["item_count"] = 777
        self.assertEqual(1, collector.records()[0]["metrics"]["item_count"])
        collector.clear()
        self.assertEqual((), collector.records())

    def test_payload_prompt_pii_secret_and_unbounded_metadata_are_unrepresentable(self) -> None:
        forbidden = (
            {"payload": "person@example.com"},
            {"prompt": "Bearer ghp_abcdefghijklmnopqrstuvwxyz123456"},
            {"email": "person@example.com"},
            {"secret": "super-secret-password"},
        )
        for dimensions in forbidden:
            with self.subTest(field=next(iter(dimensions))):
                with self.assertRaises(LoopRuntimeError) as caught:
                    build_audit_record(
                        "security_denial",
                        "denied",
                        dimensions=dimensions,
                    )
                self.assertEqual("ERR_AUDIT_CONTRACT", caught.exception.code)
                rendered = str(caught.exception.to_dict())
                self.assertNotIn("person@example.com", rendered)
                self.assertNotIn("ghp_", rendered)
                self.assertNotIn("super-secret-password", rendered)

        with self.assertRaises(LoopRuntimeError):
            build_audit_record(
                "evaluation_completed",
                "passed",
                metrics={"item_count": 1_000_001},
            )
        with self.assertRaises(LoopRuntimeError) as hostile:
            build_audit_record(
                "evaluation_completed",
                "passed",
                dimensions={"component": ["evaluator"]},
            )
        self.assertEqual("ERR_AUDIT_CONTRACT", hostile.exception.code)

    def test_configuration_and_enumerations_fail_closed(self) -> None:
        for invalid in (None, 1, "yes"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(LoopRuntimeError) as caught:
                    AuditCollector(enabled=invalid)
                self.assertEqual("ERR_AUDIT_CONFIG", caught.exception.code)
        with self.assertRaises(LoopRuntimeError):
            build_audit_record("unknown", "passed")
        with self.assertRaises(LoopRuntimeError):
            build_audit_record("route_evaluated", "unknown")
        with self.assertRaises(LoopRuntimeError):
            build_audit_record(
                "security_denial",
                "passed",
                dimensions={"component": "security", "error_family": "none"},
                metrics={"violation_count": 0},
            )
        with self.assertRaises(LoopRuntimeError):
            build_audit_record(
                "permission_evaluated",
                "passed",
                dimensions={"component": "security", "operation": "permission", "permission": "external_mutation", "error_family": "none"},
                metrics={"violation_count": 0},
            )
        with self.assertRaises(LoopRuntimeError):
            build_audit_record(
                "security_denial",
                "denied",
                dimensions={"component": "security", "error_family": "none"},
                metrics={"violation_count": 0},
            )


if __name__ == "__main__":
    unittest.main()
