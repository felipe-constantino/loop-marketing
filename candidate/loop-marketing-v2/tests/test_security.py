"""Security-boundary tests for untrusted runtime data."""

from __future__ import annotations

import copy
import json
import math
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from loop_marketing_runtime.errors import LoopRuntimeError  # noqa: E402
from loop_marketing_runtime.security import (  # noqa: E402
    JsonBudgets,
    PermissionGuard,
    SecurityContext,
    guard_permission,
    safe_error,
    safe_fingerprint,
    sanitize_message,
    sanitize_structure,
    validate_and_copy_json,
)


class JsonBoundaryTests(unittest.TestCase):
    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(LoopRuntimeError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_accepts_json_and_returns_recursive_defensive_copy(self) -> None:
        value = {"ok": True, "count": 3, "ratio": 0.5, "items": [None, {"x": "y"}]}
        before = copy.deepcopy(value)
        result = validate_and_copy_json(value)
        self.assertEqual(result, value)
        self.assertIsNot(result, value)
        self.assertIsNot(result["items"], value["items"])
        self.assertIsNot(result["items"][1], value["items"][1])
        result["items"][1]["x"] = "changed"
        self.assertEqual(value, before)

    def test_rejects_non_json_values_without_invoking_custom_protocols(self) -> None:
        class Hostile:
            def __iter__(self):
                raise AssertionError("must not iterate")

            def __repr__(self):
                raise AssertionError("must not render")

        for value in (b"secret", bytearray(b"secret"), (1, 2), {1, 2}, Hostile()):
            with self.subTest(value_type=type(value).__name__):
                error = self.assert_code("ERR_SECURITY_JSON_TYPE", validate_and_copy_json, value)
                self.assertNotIn("secret", str(error.to_dict()).lower())

        class CustomDict(dict):
            pass

        self.assert_code("ERR_SECURITY_JSON_TYPE", validate_and_copy_json, CustomDict())
        self.assert_code("ERR_SECURITY_JSON_KEY_TYPE", validate_and_copy_json, {1: "x"})

    def test_rejects_non_finite_numbers_cycles_and_every_budget(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            self.assert_code("ERR_SECURITY_JSON_NON_FINITE", validate_and_copy_json, value)

        cycle = []
        cycle.append(cycle)
        self.assert_code("ERR_SECURITY_JSON_CYCLE", validate_and_copy_json, cycle)

        cases = (
            ({"a": {"b": 1}}, JsonBudgets(max_depth=1), "ERR_SECURITY_JSON_DEPTH"),
            ([1, 2], JsonBudgets(max_nodes=2), "ERR_SECURITY_JSON_NODES"),
            ("abcd", JsonBudgets(max_string_length=3), "ERR_SECURITY_JSON_STRING_SIZE"),
            ("áá", JsonBudgets(max_string_length=3), "ERR_SECURITY_JSON_STRING_SIZE"),
            ({"a": "x", "b": "y"}, JsonBudgets(max_total_string_utf8_bytes=3), "ERR_SECURITY_JSON_TOTAL_STRING_SIZE"),
            ({"abcd": 1}, JsonBudgets(max_key_utf8_bytes=3), "ERR_SECURITY_JSON_KEY_SIZE"),
            (10 ** 3, JsonBudgets(max_integer_decimal_digits=3), "ERR_SECURITY_JSON_INTEGER_SIZE"),
            ([1, 2], JsonBudgets(max_array_length=1), "ERR_SECURITY_JSON_ARRAY_SIZE"),
            ({"a": 1, "b": 2}, JsonBudgets(max_object_length=1), "ERR_SECURITY_JSON_OBJECT_SIZE"),
            ({"abcd": 1}, JsonBudgets(max_string_length=3), "ERR_SECURITY_JSON_STRING_SIZE"),
        )
        for value, budgets, code in cases:
            with self.subTest(code=code):
                error = self.assert_code(code, validate_and_copy_json, value, budgets)
                self.assertNotIn("abcd", str(error.to_dict()))

    def test_budget_edges_are_inclusive_and_configuration_fails_closed(self) -> None:
        value = {"abc": ["xyz"]}
        exact = JsonBudgets(
            max_depth=2,
            max_nodes=3,
            max_string_length=3,
            max_array_length=1,
            max_object_length=1,
        )
        self.assertEqual(validate_and_copy_json(value, exact), value)
        for bad in (-1, True, 1.5):
            with self.subTest(bad=bad):
                self.assert_code("ERR_SECURITY_CONFIG_INVALID", JsonBudgets, max_nodes=bad)


class PermissionGuardTests(unittest.TestCase):
    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(LoopRuntimeError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_default_policy_allows_only_declared_local_and_read_operations(self) -> None:
        self.assertIsNone(guard_permission("catalog.read", "read_only"))
        self.assertIsNone(guard_permission("state.write", "local_state"))
        self.assert_code(
            "ERR_SECURITY_PERMISSION_DENIED",
            guard_permission,
            "state.write",
            "read_only",
        )
        self.assert_code(
            "ERR_SECURITY_PERMISSION_DENIED",
            guard_permission,
            "undeclared.operation",
            "read_only",
        )

    def test_external_mutation_is_unconditionally_denied(self) -> None:
        guard = PermissionGuard({"anything": frozenset(("read_only",))})
        for operation in ("anything", "undeclared.operation", "external.send"):
            with self.subTest(operation=operation):
                self.assert_code(
                    "ERR_EXTERNAL_MUTATION_UNAUTHORIZED",
                    guard.require,
                    operation,
                    "external_mutation",
                )
        self.assert_code(
            "ERR_SECURITY_CONFIG_INVALID",
            PermissionGuard,
            {"anything": frozenset(("external_mutation",))},
        )

    def test_custom_policy_is_copied_and_closed(self) -> None:
        policy = {"inspect": frozenset(("read_only",))}
        guard = PermissionGuard(policy)
        policy["mutated_later"] = frozenset(("read_only",))
        self.assertIsNone(guard.require("inspect", "read_only"))
        self.assert_code(
            "ERR_SECURITY_PERMISSION_DENIED",
            guard.require,
            "mutated_later",
            "read_only",
        )

    def test_out_of_band_security_context_is_closed_and_typed(self) -> None:
        guard = PermissionGuard({"inspect": frozenset(("read_only",))})
        context = SecurityContext.for_operation("inspect", "read_only")
        self.assertIsNone(guard.require_context(context))
        self.assertRegex(context.request_id, r"^[0-9a-f]{32}$")
        self.assert_code("ERR_SECURITY_CONTEXT_INVALID", guard.require_context, {"operation": "inspect"})


class SanitizationTests(unittest.TestCase):
    RAW_VALUES = (
        "super-secret-password",
        "ghp_abcdefghijklmnopqrstuvwxyz123456",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature123",
        "person@example.com",
        "+55 (11) 98765-4321",
        "/Users/alice/private/customer.txt",
    )

    def assert_no_raw_values(self, value) -> None:
        rendered = str(value)
        for raw in self.RAW_VALUES:
            self.assertNotIn(raw, rendered)

    def test_key_and_pattern_redaction_in_nested_telemetry(self) -> None:
        source = {
            "password": self.RAW_VALUES[0],
            "nested": [
                {"api_key": self.RAW_VALUES[1]},
                "Authorization: Bearer %s" % self.RAW_VALUES[1],
                "jwt=%s" % self.RAW_VALUES[2],
                "Contact %s or %s" % (self.RAW_VALUES[3], self.RAW_VALUES[4]),
                "Read %s" % self.RAW_VALUES[5],
            ],
            "contact_email": "not-even-email-shaped",
        }
        before = copy.deepcopy(source)
        result = sanitize_structure(source)
        self.assertEqual(source, before)
        self.assertEqual(result["password"], "<REDACTED:SECRET>")
        self.assertEqual(result["nested"][0]["api_key"], "<REDACTED:SECRET>")
        self.assertEqual(result["contact_email"], "<REDACTED:EMAIL>")
        self.assertIn("<REDACTED:AUTH>", result["nested"][1])
        self.assertIn("<REDACTED:TOKEN>", result["nested"][2])
        self.assertIn("<REDACTED:EMAIL>", result["nested"][3])
        self.assertIn("<REDACTED:PHONE>", result["nested"][3])
        self.assertIn("<REDACTED:PATH>", result["nested"][4])
        self.assert_no_raw_values(result)

    def test_message_redaction_is_deterministic_and_idempotent(self) -> None:
        message = (
            "Authorization=Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ==; "
            "password=super-secret-password; person@example.com; "
            "/Users/alice/private/customer.txt"
        )
        first = sanitize_message(message)
        self.assertEqual(first, sanitize_message(message))
        self.assertEqual(first, sanitize_message(first))
        self.assert_no_raw_values(first)

    def test_safe_error_never_exposes_secret_in_message_or_details(self) -> None:
        error = safe_error(
            "ERR_TEST_SAFE",
            "Failed for person@example.com with password=super-secret-password",
            details={
                "authorization": "Bearer %s" % self.RAW_VALUES[1],
                "source": self.RAW_VALUES[5],
                "phone": self.RAW_VALUES[4],
            },
        )
        self.assertIsInstance(error, LoopRuntimeError)
        self.assertEqual(error.code, "ERR_TEST_SAFE")
        self.assert_no_raw_values(error.message)
        self.assert_no_raw_values(error.details)
        self.assertEqual(error.details["authorization"], "<REDACTED:AUTH>")
        self.assertEqual(error.details["phone"], "<REDACTED:PHONE>")

    def test_extended_declared_secret_and_pii_classes_are_redacted(self) -> None:
        source = {
            "cookie": "session=raw-cookie-value",
            "session_id": "raw-session-value",
            "private_key": "-----BEGIN PRIVATE KEY----- raw",
            "full_name": "Synthetic Person",
            "address": "Synthetic address",
            "cpf": "123.456.789-09",
            "nested": [
                "-----BEGIN RSA PRIVATE KEY-----",
                "postgresql://person:secret-value@database.example/internal",
                "CPF 123.456.789-09",
                "token=synthetic-secret-value",
            ],
        }
        result = sanitize_structure(source)
        self.assertEqual("<REDACTED:SECRET>", result["cookie"])
        self.assertEqual("<REDACTED:SECRET>", result["session_id"])
        self.assertEqual("<REDACTED:SECRET>", result["private_key"])
        self.assertEqual("<REDACTED:PII>", result["full_name"])
        self.assertEqual("<REDACTED:PII>", result["address"])
        self.assertEqual("<REDACTED:PII>", result["cpf"])
        rendered = str(result)
        for forbidden in ("raw-cookie-value", "raw-session-value", "Synthetic Person", "123.456.789-09", "secret-value", "synthetic-secret-value"):
            self.assertNotIn(forbidden, rendered)

    def test_hexadecimal_fingerprints_are_not_misclassified_as_cpf(self) -> None:
        fingerprint = "a12345678909b" + ("c" * 51)
        self.assertEqual(64, len(fingerprint))
        self.assertEqual(fingerprint, sanitize_message(fingerprint))
        self.assertNotIn("12345678909", sanitize_message("CPF 12345678909"))

    def test_public_error_budget_fails_to_constant_bounded_details(self) -> None:
        error = safe_error("ERR_TEST_SAFE", "x" * 9_000, details={"safe": "y" * 9_000})
        self.assertEqual({}, error.details)
        self.assertLess(len(json.dumps(error.to_dict()).encode("utf-8")), 8_192)

    def test_fingerprint_is_stable_and_derived_from_sanitized_content(self) -> None:
        first = safe_fingerprint({"token": "one", "value": 1})
        second = safe_fingerprint({"value": 1, "token": "two"})
        self.assertEqual(first, second)
        self.assertRegex(first, r"^sha256:[0-9a-f]{64}$")
        self.assertNotIn("one", first)
        self.assertNotIn("two", second)

    def test_prompt_and_canonical_body_remain_inert_uninterpreted_strings(self) -> None:
        payload = {
            "prompt": "__import__('os').system('do-not-run')",
            "canonical_body": "<script>external_mutation()</script>",
        }
        self.assertEqual(sanitize_structure(payload), payload)

    def test_thread_safety_and_determinism_under_shared_input(self) -> None:
        source = {
            "token": self.RAW_VALUES[1],
            "items": ["person@example.com", {"phone": self.RAW_VALUES[4]}],
        }
        before = copy.deepcopy(source)

        def run(_index):
            return sanitize_structure(source), safe_fingerprint(source)

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(run, range(128)))
        self.assertTrue(all(item == results[0] for item in results))
        self.assertEqual(source, before)
        self.assert_no_raw_values(results)


if __name__ == "__main__":
    unittest.main()
