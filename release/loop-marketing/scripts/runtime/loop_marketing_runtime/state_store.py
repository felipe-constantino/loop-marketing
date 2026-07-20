"""Transactional, append-only local project state store.

The ledger is authoritative.  ``project.json`` and ``snapshots/latest.json``
are replaceable derived caches and are never consulted to advance state.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import socket
import stat
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Tuple

from .errors import LoopRuntimeError, require
from .models import RuntimeConfig

if TYPE_CHECKING:
    from .validation import ContractValidator


PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
BASELINE_COMMIT = "3cbf0cf84a038f2cd570883b70988889f037c28e"
LIBRARY_SHA256 = "0ef879b760619509adda24a7d928098f77cd2d4c392f53a3be7f530f14d549b1"
GENESIS = "GENESIS"
DIR_MODE = 0o700
FILE_MODE = 0o600


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_text(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _canonical_bytes(value: Any) -> bytes:
    return _canonical_text(value).encode("utf-8")


def _canonical_hash(value: Mapping[str, Any], excluded: str) -> str:
    payload = {key: item for key, item in value.items() if key != excluded}
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class _LedgerView:
    raw: bytes
    records: List[Dict[str, Any]] = field(default_factory=list)
    revision: int = 0
    head_event_id: Optional[str] = None
    head_event_hash: Optional[str] = None
    head_record_hash: Optional[str] = None
    last_event_sequence: int = 0
    applied_event_count: int = 0
    transaction_by_id: Dict[str, Tuple[str, Dict[str, Any]]] = field(default_factory=dict)
    transaction_by_idempotency: Dict[str, Tuple[str, Dict[str, Any]]] = field(default_factory=dict)
    event_by_id: Dict[str, str] = field(default_factory=dict)
    event_by_idempotency: Dict[str, str] = field(default_factory=dict)


class _LedgerCorruption(Exception):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class ProjectStateStore:
    """Durable per-project CAS store over one canonical JSONL ledger."""

    def __init__(self, config: RuntimeConfig, validator: ContractValidator) -> None:
        self.config = config.normalized()
        self.validator = validator
        # RuntimeConfig.normalized() resolves the trust boundary.  All paths
        # below it are still checked component-by-component before use.
        self.state_root = Path(config.state_root).expanduser().absolute()
        self._state_dir = self.state_root / "state"
        self._projects_dir = self._state_dir / "projects"
        self._quarantine_dir = self.state_root / "quarantine"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def initialize_project(self, project_id: str, display_name: str) -> Dict[str, Any]:
        self._validate_project_id(project_id)
        require(
            isinstance(display_name, str) and 1 <= len(display_name) <= 200,
            "ERR_INPUT_REQUIRED",
            "display_name must contain between 1 and 200 characters.",
            retryable=True,
        )
        self._ensure_roots()
        project_dir = self._project_dir(project_id, must_exist=False)
        if project_dir.exists():
            snapshot = self.load(project_id)
            require(
                snapshot["display_name"] == display_name,
                "LM-COMPAT-ID-COLLISION",
                "The project_id already exists with different immutable identity metadata.",
                project_id=project_id,
            )
            return snapshot

        try:
            os.mkdir(str(project_dir), DIR_MODE)
        except FileExistsError:
            raise LoopRuntimeError(
                "LM-COMPAT-ID-COLLISION",
                "The project_id was initialized concurrently.",
                retryable=True,
                details={"project_id": project_id},
            )
        os.chmod(str(project_dir), DIR_MODE)
        self._fsync_dir(self._projects_dir)
        snapshots_dir = project_dir / "snapshots"
        self._mkdir_secure(snapshots_dir)

        ledger = project_dir / "events.jsonl"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(str(ledger), flags, FILE_MODE)
        except OSError as exc:
            raise LoopRuntimeError(
                "ERR_PROJECT_PATH_INVALID",
                "Unable to create the canonical ledger safely.",
                details={"project_id": project_id, "errno": exc.errno},
            ) from exc
        try:
            os.fchmod(fd, FILE_MODE)
            os.fsync(fd)
        finally:
            os.close(fd)
        self._fsync_dir(project_dir)

        timestamp = _now()
        identity = {
            "schema_version": "1.0",
            "project_id": project_id,
            "project_ref": "project:%s" % project_id,
            "display_name": display_name,
            "created_at": timestamp,
        }
        self._atomic_write_json(project_dir / "identity.json", identity)
        snapshot = self._initial_snapshot(project_id, display_name, timestamp)
        self._validate_state(snapshot)
        self._atomic_write_json(project_dir / "project.json", snapshot)
        self._atomic_write_json(snapshots_dir / "latest.json", snapshot)
        return copy.deepcopy(snapshot)

    def load(self, project_id: str) -> Dict[str, Any]:
        project_dir = self._project_dir(project_id, must_exist=True)
        view = self._read_ledger_or_quarantine(project_id, project_dir)
        identity = self._identity(project_id, project_dir, view)
        snapshot = self._snapshot_from_view(project_id, identity, view)
        self._validate_state(snapshot)

        cache_status = self._cache_status(project_dir, snapshot)
        if cache_status == "ahead":
            raise LoopRuntimeError(
                "ERR_STATE_FABRICATION",
                "A derived snapshot is ahead of the authoritative ledger.",
                details={"project_id": project_id, "ledger_revision": view.revision},
            )
        if cache_status != "current":
            lock_id = self._acquire_lock(project_id, project_dir, view.revision)
            try:
                # A writer may have advanced the ledger between the first read
                # and the recovery lock.  Rebuild from the post-lock head.
                view = self._read_ledger_or_quarantine(project_id, project_dir)
                identity = self._identity(project_id, project_dir, view)
                snapshot = self._snapshot_from_view(project_id, identity, view)
                self._validate_state(snapshot)
                self._publish_caches(project_dir, snapshot)
            finally:
                self._release_lock(project_dir, lock_id)
        return copy.deepcopy(snapshot)

    def replay(self, project_id: str) -> Dict[str, Any]:
        project_dir = self._project_dir(project_id, must_exist=True)
        view = self._read_ledger_or_quarantine(project_id, project_dir)
        identity = self._identity(project_id, project_dir, view)
        snapshot = self._snapshot_from_view(project_id, identity, view)
        self._validate_state(snapshot)
        return copy.deepcopy(snapshot)

    def is_exact_replay(self, project_id: str, record: Dict[str, Any]) -> bool:
        """Return true only when the complete canonical transaction already exists."""

        project_dir = self._project_dir(project_id, must_exist=True)
        view = self._read_ledger_or_quarantine(project_id, project_dir)
        return self._idempotency_result(record, view) is not None

    def commit(
        self,
        project_id: str,
        record: Dict[str, Any],
        expected_revision: int,
        expected_head_hash: str,
    ) -> Dict[str, Any]:
        project_dir = self._project_dir(project_id, must_exist=True)
        self._assert_writable(project_dir)
        require(isinstance(record, dict), "LM-EVENT-SCHEMA-INVALID", "Transaction record must be an object.")

        # First optimistic read: detect exact retry/conflict before stale CAS.
        view = self._read_ledger_or_quarantine(project_id, project_dir)
        self._assert_cache_not_ahead(project_id, project_dir, view)
        replay = self._idempotency_result(record, view)
        if replay is not None:
            return self._noop_result(replay, view)
        self._check_cas(view, expected_revision, expected_head_hash)

        lock_id = self._acquire_lock(project_id, project_dir, expected_revision)
        temps: List[Path] = []
        ledger_committed = False
        result: Optional[Dict[str, Any]] = None
        caught: Optional[BaseException] = None
        try:
            # Required post-lock CAS and idempotency recheck.
            view = self._read_ledger_or_quarantine(project_id, project_dir)
            self._assert_cache_not_ahead(project_id, project_dir, view)
            replay = self._idempotency_result(record, view)
            if replay is not None:
                return self._noop_result(replay, view)
            self._check_cas(view, expected_revision, expected_head_hash)
            self._validate_new_record(project_id, record, view, expected_revision)

            next_view = self._view_with_record(view, record)
            identity = self._identity(project_id, project_dir, view)
            snapshot = self._snapshot_from_view(project_id, identity, next_view)
            self._validate_state(snapshot)

            ledger_path = project_dir / "events.jsonl"
            ledger_temp = self._new_temp_path(project_dir, "events.jsonl", lock_id)
            project_temp = self._new_temp_path(project_dir, "project.json", lock_id)
            snapshot_dir = project_dir / "snapshots"
            snapshot_temp = self._new_temp_path(snapshot_dir, "latest.json", lock_id)
            temps.extend([ledger_temp, project_temp, snapshot_temp])

            line = _canonical_bytes(record) + b"\n"
            self._create_fsynced_file(ledger_temp, view.raw + line)
            self._create_fsynced_file(project_temp, _canonical_bytes(snapshot) + b"\n")
            self._create_fsynced_file(snapshot_temp, _canonical_bytes(snapshot) + b"\n")
            self._fault_hook("before_ledger_commit")

            self._assert_safe_target(ledger_path)
            os.replace(str(ledger_temp), str(ledger_path))
            temps.remove(ledger_temp)
            ledger_committed = True
            os.chmod(str(ledger_path), FILE_MODE)
            self._fsync_dir(project_dir)
            self._fault_hook("after_ledger_commit")

            self._assert_safe_target(project_dir / "project.json")
            os.replace(str(project_temp), str(project_dir / "project.json"))
            temps.remove(project_temp)
            os.chmod(str(project_dir / "project.json"), FILE_MODE)
            self._fsync_dir(project_dir)

            self._assert_safe_target(snapshot_dir / "latest.json")
            os.replace(str(snapshot_temp), str(snapshot_dir / "latest.json"))
            temps.remove(snapshot_temp)
            os.chmod(str(snapshot_dir / "latest.json"), FILE_MODE)
            self._fsync_dir(snapshot_dir)
            self._fsync_dir(project_dir)

            result = self._commit_result(record, snapshot, status="committed")
        except BaseException as exc:  # preserve commit-point information
            caught = exc
        finally:
            for temp in temps:
                self._unlink_owned_temp(temp)
            try:
                self._release_lock(project_dir, lock_id)
            except BaseException as release_exc:
                if caught is None:
                    caught = release_exc

        if caught is not None:
            if isinstance(caught, LoopRuntimeError) and not ledger_committed:
                raise caught
            raise LoopRuntimeError(
                "ERR_ATOMIC_COMMIT_FAILED",
                "The transaction did not complete every durable publication step.",
                retryable=True,
                details={
                    "project_id": project_id,
                    "transaction_id": record.get("transaction_id"),
                    "ledger_committed": ledger_committed,
                    "recovery_required": ledger_committed,
                    "failure_type": type(caught).__name__,
                },
            ) from caught
        assert result is not None
        return result

    def inspect_recovery(self, project_id: str) -> Dict[str, Any]:
        project_dir = self._project_dir(project_id, must_exist=True)
        marker = self._read_recovery_marker(project_dir)
        if marker is not None:
            return marker
        try:
            view = self._read_ledger(project_id, project_dir)
        except _LedgerCorruption as exc:
            return self._quarantine_ledger(project_id, project_dir, exc)

        identity = self._identity(project_id, project_dir, view)
        snapshot = self._snapshot_from_view(project_id, identity, view)
        cache_status = self._cache_status(project_dir, snapshot)
        lock_path = project_dir / ".write.lock"
        lock_status = "absent"
        lock_details: Dict[str, Any] = {}
        if lock_path.exists():
            _raw, lock_value, evidence = self._lock_evidence(lock_path)
            lock_status = evidence
            if isinstance(lock_value, dict):
                lock_details = {
                    "lock_id": lock_value.get("lock_id"),
                    "pid": lock_value.get("pid"),
                    "host_id": lock_value.get("host_id"),
                    "acquired_at": lock_value.get("acquired_at"),
                }
        if lock_status != "absent":
            status = {
                "active": "writer_active",
                "proven_dead_same_host": "stale_lock_recovery_required",
                "unverified": "stale_lock_unverified",
            }.get(lock_status, "stale_lock_unverified")
            return {
                "status": status,
                "writable": False,
                "project_id": project_id,
                "ledger_status": "clean",
                "ledger_revision": view.revision,
                "head_event_hash": view.head_event_hash or GENESIS,
                "head_record_hash": view.head_record_hash or GENESIS,
                "cache_status": cache_status,
                "lock_status": lock_status,
                "lock": lock_details,
                "quarantine_paths": [],
            }
        return {
            "status": "clean" if cache_status == "current" else "rebuild_required",
            "writable": cache_status != "ahead",
            "project_id": project_id,
            "ledger_status": "clean",
            "ledger_revision": view.revision,
            "head_event_hash": view.head_event_hash or GENESIS,
            "head_record_hash": view.head_record_hash or GENESIS,
            "cache_status": cache_status,
            "lock_status": lock_status,
            "quarantine_paths": [],
        }

    # ------------------------------------------------------------------
    # Path and filesystem safety
    # ------------------------------------------------------------------
    def _validate_project_id(self, project_id: str) -> None:
        require(
            isinstance(project_id, str) and PROJECT_ID_RE.fullmatch(project_id) is not None,
            "ERR_PROJECT_PATH_INVALID",
            "project_id violates the canonical safe slug contract.",
            project_id=str(project_id),
        )

    def _ensure_roots(self) -> None:
        if self.state_root.exists() and self.state_root.is_symlink():
            raise LoopRuntimeError("ERR_PROJECT_PATH_INVALID", "state_root must not be a symlink.")
        self.state_root.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
        os.chmod(str(self.state_root), DIR_MODE)
        self._mkdir_secure(self._state_dir)
        self._mkdir_secure(self._projects_dir)
        self._mkdir_secure(self._quarantine_dir)

    def _mkdir_secure(self, path: Path) -> None:
        self._assert_contained(path)
        if path.exists() and path.is_symlink():
            raise LoopRuntimeError("ERR_PROJECT_PATH_INVALID", "A write-path component is a symlink.")
        path.mkdir(exist_ok=True, mode=DIR_MODE)
        os.chmod(str(path), DIR_MODE)
        self._fsync_dir(path.parent)

    def _project_dir(self, project_id: str, must_exist: bool) -> Path:
        self._validate_project_id(project_id)
        if not self._projects_dir.exists():
            if must_exist:
                raise LoopRuntimeError(
                    "ERR_INPUT_REQUIRED",
                    "Project state root does not exist.",
                    retryable=True,
                    details={"project_id": project_id},
                )
            self._ensure_roots()
        project_dir = self._projects_dir / project_id
        self._assert_contained(project_dir)
        self._assert_no_symlink_components(project_dir)
        if must_exist:
            require(
                project_dir.is_dir(),
                "ERR_INPUT_REQUIRED",
                "Unknown project_id.",
                retryable=True,
                project_id=project_id,
            )
            self._assert_directory_mode(project_dir)
        return project_dir

    def _assert_contained(self, path: Path) -> None:
        root = self.state_root.resolve(strict=False)
        target = path.resolve(strict=False)
        try:
            contained = os.path.commonpath([str(root), str(target)]) == str(root)
        except ValueError:
            contained = False
        require(contained, "ERR_PROJECT_PATH_INVALID", "Resolved state path escapes state_root.")

    def _assert_no_symlink_components(self, path: Path) -> None:
        self._assert_contained(path)
        current = self.state_root
        if current.exists() and current.is_symlink():
            raise LoopRuntimeError("ERR_PROJECT_PATH_INVALID", "state_root is a symlink.")
        relative = path.relative_to(self.state_root)
        for part in relative.parts:
            current = current / part
            try:
                mode = current.lstat().st_mode
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(mode):
                raise LoopRuntimeError(
                    "ERR_PROJECT_PATH_INVALID",
                    "A write-path component is a symlink.",
                    details={"component": str(current.relative_to(self.state_root))},
                )

    def _assert_safe_target(self, path: Path) -> None:
        self._assert_contained(path)
        self._assert_no_symlink_components(path)
        if path.exists() and path.is_symlink():
            raise LoopRuntimeError("ERR_PROJECT_PATH_INVALID", "A write target is a symlink.")

    @staticmethod
    def _assert_directory_mode(path: Path) -> None:
        mode = stat.S_IMODE(path.stat().st_mode)
        require(
            mode == DIR_MODE,
            "ERR_PROJECT_PATH_INVALID",
            "Project directories must use mode 0700.",
            actual_mode=oct(mode),
        )

    @staticmethod
    def _assert_file_mode(path: Path) -> None:
        mode = stat.S_IMODE(path.stat().st_mode)
        require(
            mode == FILE_MODE,
            "ERR_PROJECT_PATH_INVALID",
            "State files must use mode 0600.",
            actual_mode=oct(mode),
        )

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        fd = os.open(str(path), flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _safe_read_bytes(self, path: Path) -> bytes:
        self._assert_safe_target(path)
        require(path.is_file(), "ERR_INPUT_REQUIRED", "Required state file is missing.", path=path.name)
        self._assert_file_mode(path)
        return self._read_bytes_nofollow(path)

    def _read_bytes_nofollow(self, path: Path) -> bytes:
        self._assert_safe_target(path)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(str(path), flags)
        try:
            chunks: List[bytes] = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(fd)

    def _create_fsynced_file(self, path: Path, payload: bytes) -> None:
        self._assert_safe_target(path)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(str(path), flags, FILE_MODE)
        try:
            os.fchmod(fd, FILE_MODE)
            offset = 0
            while offset < len(payload):
                written = os.write(fd, payload[offset:])
                if written <= 0:
                    raise OSError("short write while materializing state file")
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)

    def _atomic_write_json(self, path: Path, value: Dict[str, Any]) -> None:
        self._assert_safe_target(path)
        temp = self._new_temp_path(path.parent, path.name, uuid.uuid4().hex)
        try:
            self._create_fsynced_file(temp, _canonical_bytes(value) + b"\n")
            os.replace(str(temp), str(path))
            os.chmod(str(path), FILE_MODE)
            self._fsync_dir(path.parent)
        finally:
            self._unlink_owned_temp(temp)

    @staticmethod
    def _new_temp_path(parent: Path, target_name: str, token: str) -> Path:
        return parent / (".%s.tmp.%s" % (target_name, token))

    def _unlink_owned_temp(self, path: Path) -> None:
        try:
            if path.exists() and not path.is_symlink():
                path.unlink()
                self._fsync_dir(path.parent)
        except FileNotFoundError:
            pass

    # ------------------------------------------------------------------
    # Lock protocol
    # ------------------------------------------------------------------
    def _acquire_lock(self, project_id: str, project_dir: Path, expected_revision: int) -> str:
        lock_path = project_dir / ".write.lock"
        self._assert_safe_target(lock_path)
        lock_id = uuid.uuid4().hex
        payload = {
            "lock_id": lock_id,
            "pid": os.getpid(),
            "host_id": socket.gethostname(),
            "acquired_at": _now(),
            "project_id": project_id,
            "expected_revision": expected_revision,
        }
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        for attempt in range(2):
            try:
                fd = os.open(str(lock_path), flags, FILE_MODE)
                break
            except FileExistsError as exc:
                if lock_path.is_symlink():
                    raise LoopRuntimeError("ERR_PROJECT_PATH_INVALID", "The lock path is a symlink.") from exc
                if attempt:
                    raise LoopRuntimeError(
                        "ERR_LOCK_HELD",
                        "Another writer acquired the project lock during recovery.",
                        retryable=True,
                        details={"project_id": project_id},
                    ) from exc
                self._recover_abandoned_lock(project_id, project_dir, lock_path)
        else:  # pragma: no cover - loop either breaks or raises
            raise LoopRuntimeError("ERR_LOCK_HELD", "Unable to acquire the project lock.", retryable=True)
        try:
            os.fchmod(fd, FILE_MODE)
            data = _canonical_bytes(payload) + b"\n"
            offset = 0
            while offset < len(data):
                written = os.write(fd, data[offset:])
                if written <= 0:
                    raise OSError("short write while creating project lock")
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)
        self._fsync_dir(project_dir)
        return lock_id

    @staticmethod
    def _pid_is_alive(pid: int) -> Optional[bool]:
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            return None
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return None
        return True

    def _lock_evidence(self, lock_path: Path) -> Tuple[bytes, Optional[Dict[str, Any]], str]:
        try:
            raw = self._safe_read_bytes(lock_path)
            value = json.loads(raw.decode("utf-8"))
        except (LoopRuntimeError, UnicodeDecodeError, json.JSONDecodeError, OSError):
            return b"", None, "unverified"
        if not isinstance(value, dict) or value.get("host_id") != socket.gethostname():
            return raw, value if isinstance(value, dict) else None, "unverified"
        alive = self._pid_is_alive(value.get("pid"))
        if alive is True:
            return raw, value, "active"
        if alive is False:
            return raw, value, "proven_dead_same_host"
        return raw, value, "unverified"

    def _recover_abandoned_lock(
        self,
        project_id: str,
        project_dir: Path,
        lock_path: Path,
    ) -> None:
        raw, value, status = self._lock_evidence(lock_path)
        if status == "active":
            raise LoopRuntimeError(
                "ERR_LOCK_HELD",
                "Another live writer owns the project lock.",
                retryable=True,
                details={"project_id": project_id, "pid": value.get("pid") if value else None},
            )
        if status != "proven_dead_same_host" or value is None:
            raise LoopRuntimeError(
                "ERR_LOCK_STALE_UNVERIFIED",
                "Existing lock ownership or process liveness cannot be proven safely.",
                retryable=True,
                details={"project_id": project_id},
            )
        report = {
            "schema_version": "1.0",
            "status": "stale_lock_recovered",
            "project_id": project_id,
            "recovered_lock_id": value.get("lock_id"),
            "dead_pid": value.get("pid"),
            "host_id": value.get("host_id"),
            "lock_sha256": _sha256(raw),
            "recovered_at": _now(),
        }
        report_path = project_dir / ("lock-recovery-%s.json" % _sha256(raw))
        if not report_path.exists():
            self._atomic_write_json(report_path, report)
        try:
            current = self._safe_read_bytes(lock_path)
        except LoopRuntimeError as exc:
            raise LoopRuntimeError(
                "ERR_LOCK_STALE_UNVERIFIED",
                "Lock changed while abandonment was being verified.",
                retryable=True,
            ) from exc
        require(
            current == raw,
            "ERR_LOCK_STALE_UNVERIFIED",
            "Lock changed while abandonment was being verified.",
            retryable=True,
        )
        lock_path.unlink()
        self._fsync_dir(project_dir)

    def _release_lock(self, project_dir: Path, lock_id: str) -> None:
        lock_path = project_dir / ".write.lock"
        if not lock_path.exists():
            return
        data = self._safe_read_bytes(lock_path)
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LoopRuntimeError("ERR_LOCK_STALE_UNVERIFIED", "Lock ownership cannot be verified.") from exc
        require(
            value.get("lock_id") == lock_id,
            "ERR_LOCK_STALE_UNVERIFIED",
            "Refusing to remove a lock owned by another operation.",
            retryable=True,
        )
        lock_path.unlink()
        self._fsync_dir(project_dir)

    # ------------------------------------------------------------------
    # Ledger validation, replay, and idempotency
    # ------------------------------------------------------------------
    def _read_ledger_or_quarantine(self, project_id: str, project_dir: Path) -> _LedgerView:
        marker = self._read_recovery_marker(project_dir)
        if marker is not None:
            raise LoopRuntimeError(
                "ERR_RECOVERY_REQUIRED",
                "The project is degraded read-only after ledger corruption.",
                retryable=True,
                details=marker,
            )
        try:
            return self._read_ledger(project_id, project_dir)
        except _LedgerCorruption as exc:
            report = self._quarantine_ledger(project_id, project_dir, exc)
            raise LoopRuntimeError(
                "ERR_RECOVERY_REQUIRED",
                "The authoritative ledger is corrupt and the project is read-only.",
                retryable=True,
                details=report,
            ) from exc

    def _read_ledger(self, project_id: str, project_dir: Path) -> _LedgerView:
        ledger_path = project_dir / "events.jsonl"
        try:
            raw = self._safe_read_bytes(ledger_path)
        except LoopRuntimeError as exc:
            if exc.code == "ERR_PROJECT_PATH_INVALID":
                raise
            raise _LedgerCorruption(exc.code, exc.message, **exc.details) from exc
        if raw and not raw.endswith(b"\n"):
            raise _LedgerCorruption("LM-EVENT-CHAIN-BROKEN", "Ledger has an incomplete final line.")
        view = _LedgerView(raw=raw)
        if not raw:
            return view

        for line_number, line in enumerate(raw.splitlines(), 1):
            if not line:
                raise _LedgerCorruption("LM-EVENT-CHAIN-BROKEN", "Ledger contains an empty record line.", line=line_number)
            try:
                record = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise _LedgerCorruption(
                    "LM-EVENT-SCHEMA-INVALID",
                    "Ledger record is not valid UTF-8 JSON.",
                    line=line_number,
                ) from exc
            if line != _canonical_bytes(record):
                raise _LedgerCorruption(
                    "LM-EVENT-HASH-MISMATCH",
                    "Ledger record is not in canonical serialized form.",
                    line=line_number,
                )
            try:
                self._validate_record_core(project_id, record, view)
                self._validate_transaction(record, self._validation_context(view))
                self._index_record(view, record, reject_duplicates=True)
            except LoopRuntimeError as exc:
                raise _LedgerCorruption(exc.code, exc.message, line=line_number, **exc.details) from exc
        return view

    @staticmethod
    def _validation_context(view: _LedgerView) -> Dict[str, Any]:
        return {
            "current_revision": view.revision,
            "previous_record_hash": view.head_record_hash or GENESIS,
            "previous_event_hash": view.head_event_hash or GENESIS,
            "last_event_sequence": view.last_event_sequence,
        }

    def _validate_record_core(self, project_id: str, record: Dict[str, Any], view: _LedgerView) -> None:
        require(isinstance(record, dict), "LM-EVENT-SCHEMA-INVALID", "Ledger record must be an object.")
        required = {
            "schema_version", "record_type", "transaction_id", "project_ref",
            "expected_state_revision", "resulting_state_revision", "committed_at",
            "integrated_by_role", "reducer_version", "idempotency_key",
            "previous_record_hash", "record_hash", "events",
        }
        require(required.issubset(record), "LM-EVENT-SCHEMA-INVALID", "Transaction record is missing required fields.")
        require(record["project_ref"] == "project:%s" % project_id, "LM-EVENT-SCHEMA-INVALID", "Transaction project_ref mismatch.")
        require(
            record["expected_state_revision"] == view.revision
            and record["resulting_state_revision"] == view.revision + 1,
            "ERR_STATE_REVISION_STALE",
            "Transaction revision is not the next ledger revision.",
            retryable=True,
        )
        require(
            record["previous_record_hash"] == (view.head_record_hash or GENESIS),
            "LM-EVENT-CHAIN-BROKEN",
            "Transaction record chain does not reference the verified head.",
        )
        require(
            record["record_hash"] == _canonical_hash(record, "record_hash"),
            "LM-EVENT-HASH-MISMATCH",
            "Transaction record_hash does not match canonical content.",
        )
        events = record.get("events")
        require(isinstance(events, list) and events, "LM-EVENT-SCHEMA-INVALID", "Transaction must contain one or more events.")

        expected_previous = view.head_event_hash or GENESIS
        expected_sequence = view.last_event_sequence + 1
        batch_ids = set()
        batch_idempotency = set()
        for event in events:
            require(isinstance(event, dict), "LM-EVENT-SCHEMA-INVALID", "Nested event must be an object.")
            require(event.get("transaction_id") == record["transaction_id"], "LM-EVENT-SCHEMA-INVALID", "Nested transaction_id mismatch.")
            require(event.get("project_ref") == record["project_ref"], "LM-EVENT-SCHEMA-INVALID", "Nested project_ref mismatch.")
            require(
                event.get("state_revision") == view.revision
                and event.get("resulting_state_revision") == view.revision + 1,
                "ERR_STATE_REVISION_STALE",
                "Nested event revision does not match the batch.",
                retryable=True,
            )
            require(
                event.get("event_sequence") == expected_sequence
                and event.get("previous_event_hash") == expected_previous,
                "LM-EVENT-CHAIN-BROKEN",
                "Nested event chain or sequence is not contiguous.",
            )
            require(
                event.get("event_hash") == _canonical_hash(event, "event_hash"),
                "LM-EVENT-HASH-MISMATCH",
                "Nested event_hash does not match canonical content.",
            )
            event_id = event.get("event_id")
            idem = event.get("idempotency_key")
            require(event_id not in batch_ids and idem not in batch_idempotency, "LM-EVENT-IDEMPOTENCY-CONFLICT", "Duplicate event identity inside a batch.")
            batch_ids.add(event_id)
            batch_idempotency.add(idem)
            expected_previous = event["event_hash"]
            expected_sequence += 1

    def _validate_new_record(
        self,
        project_id: str,
        record: Dict[str, Any],
        view: _LedgerView,
        expected_revision: int,
    ) -> None:
        require(
            record.get("expected_state_revision") == expected_revision,
            "ERR_STATE_REVISION_STALE",
            "Method CAS revision and transaction revision differ.",
            retryable=True,
        )
        self._validate_record_core(project_id, record, view)
        self._validate_transaction(record, self._validation_context(view))

    def _validate_transaction(self, record: Dict[str, Any], context: Dict[str, Any]) -> None:
        result = self.validator.validate_transaction(record, context)
        self._raise_validation_failure(result, "LM-EVENT-SCHEMA-INVALID", "Transaction failed the injected contract validator.")

    def _validate_state(self, snapshot: Dict[str, Any]) -> None:
        result = self.validator.validate_state(snapshot)
        self._raise_validation_failure(result, "ERR_STATE_FABRICATION", "Derived snapshot failed the injected contract validator.")

    @staticmethod
    def _raise_validation_failure(result: Any, fallback: str, message: str) -> None:
        if result is None:
            return
        ok = result.get("ok") if isinstance(result, dict) else getattr(result, "ok", False)
        if ok:
            return
        code = result.get("primary_code") if isinstance(result, dict) else getattr(result, "primary_code", None)
        violations = result.get("violations", ()) if isinstance(result, dict) else getattr(result, "violations", ())
        raise LoopRuntimeError(code or fallback, message, details={"violations": list(violations or ())})

    def _index_record(self, view: _LedgerView, record: Dict[str, Any], reject_duplicates: bool) -> None:
        fingerprint = _canonical_text(record)
        tx_id = record["transaction_id"]
        tx_idem = record["idempotency_key"]
        overlaps = tx_id in view.transaction_by_id or tx_idem in view.transaction_by_idempotency
        for event in record["events"]:
            overlaps = overlaps or event["event_id"] in view.event_by_id or event["idempotency_key"] in view.event_by_idempotency
        if reject_duplicates and overlaps:
            raise LoopRuntimeError(
                "LM-EVENT-IDEMPOTENCY-CONFLICT",
                "Committed ledger contains duplicate transaction or event identities.",
            )
        view.transaction_by_id[tx_id] = (fingerprint, record)
        view.transaction_by_idempotency[tx_idem] = (fingerprint, record)
        for event in record["events"]:
            event_fingerprint = _canonical_text(event)
            view.event_by_id[event["event_id"]] = event_fingerprint
            view.event_by_idempotency[event["idempotency_key"]] = event_fingerprint
        view.records.append(record)
        view.revision = record["resulting_state_revision"]
        view.head_record_hash = record["record_hash"]
        last_event = record["events"][-1]
        view.head_event_id = last_event["event_id"]
        view.head_event_hash = last_event["event_hash"]
        view.last_event_sequence = last_event["event_sequence"]
        view.applied_event_count += len(record["events"])

    def _view_with_record(self, view: _LedgerView, record: Dict[str, Any]) -> _LedgerView:
        clone = copy.deepcopy(view)
        clone.raw = view.raw + _canonical_bytes(record) + b"\n"
        self._index_record(clone, copy.deepcopy(record), reject_duplicates=True)
        return clone

    def _idempotency_result(self, record: Dict[str, Any], view: _LedgerView) -> Optional[Dict[str, Any]]:
        tx_id = record.get("transaction_id")
        tx_idem = record.get("idempotency_key")
        tx_hits = [
            view.transaction_by_id.get(tx_id),
            view.transaction_by_idempotency.get(tx_idem),
        ]
        tx_hits = [item for item in tx_hits if item is not None]
        event_overlap = False
        for event in record.get("events", []) if isinstance(record.get("events"), list) else []:
            if event.get("event_id") in view.event_by_id or event.get("idempotency_key") in view.event_by_idempotency:
                event_overlap = True
                break
        if not tx_hits and not event_overlap:
            return None

        incoming = _canonical_text(record)
        if len(tx_hits) == 2 and tx_hits[0][0] == incoming and tx_hits[1][0] == incoming:
            # The stored record was fully validated during replay.  Equality of
            # the complete canonical record proves all nested IDs and hashes.
            return tx_hits[0][1]
        raise LoopRuntimeError(
            "LM-EVENT-IDEMPOTENCY-CONFLICT",
            "Transaction or event identity was reused with different canonical content.",
            details={"transaction_id": tx_id},
        )

    @staticmethod
    def _check_cas(view: _LedgerView, expected_revision: int, expected_head_hash: str) -> None:
        actual_head = view.head_event_hash or GENESIS
        require(
            expected_revision == view.revision and expected_head_hash == actual_head,
            "ERR_STATE_REVISION_STALE",
            "Expected revision or event head does not match the authoritative ledger.",
            retryable=True,
            expected_revision=expected_revision,
            actual_revision=view.revision,
            expected_head_hash=expected_head_hash,
            actual_head_hash=actual_head,
        )

    # ------------------------------------------------------------------
    # Deterministic snapshot reducer and cache publication
    # ------------------------------------------------------------------
    @staticmethod
    def _initial_snapshot(project_id: str, display_name: str, timestamp: str) -> Dict[str, Any]:
        return {
            "schema_version": "2.0",
            "artifact_type": "loop_marketing_project_state",
            "project_id": project_id,
            "project_ref": "project:%s" % project_id,
            "display_name": display_name,
            "state_revision": 0,
            "derived_from_revision": None,
            "created_at": timestamp,
            "updated_at": timestamp,
            "event_log": {
                "path": "events.jsonl",
                "head_event_id": None,
                "head_event_hash": None,
                "head_record_hash": None,
                "last_event_sequence": 0,
                "applied_event_count": 0,
                "committed_transaction_count": 0,
            },
            "state": {
                "active_cycle_id": None,
                "maturity": "unknown",
                "route_status": "needs_evidence",
                "accepted_bottleneck_ref": None,
                "decision_refs": [],
                "handoff_refs": [],
                "experiment_refs": [],
                "learning_refs": [],
                "known_gap_refs": [],
                "legacy_import_refs": [],
                "canonical_library": {
                    "baseline_commit": BASELINE_COMMIT,
                    "aggregate_sha256": LIBRARY_SHA256,
                    "prompt_count": 100,
                },
            },
        }

    def _identity(self, project_id: str, project_dir: Path, view: _LedgerView) -> Dict[str, str]:
        value = self._read_json_cache(project_dir / "identity.json")
        expected_keys = {
            "schema_version", "project_id", "project_ref", "display_name", "created_at",
        }
        if not (
            isinstance(value, dict)
            and set(value) == expected_keys
            and value.get("schema_version") == "1.0"
            and value.get("project_id") == project_id
            and value.get("project_ref") == "project:%s" % project_id
            and isinstance(value.get("display_name"), str)
            and bool(value.get("display_name"))
            and isinstance(value.get("created_at"), str)
            and bool(value.get("created_at"))
        ):
            raise LoopRuntimeError(
                "ERR_RECOVERY_REQUIRED",
                "Immutable project identity is missing or invalid; derived caches cannot replace it.",
                retryable=True,
                details={"project_id": project_id},
            )
        return {"display_name": value["display_name"], "created_at": value["created_at"]}

    def _snapshot_from_view(
        self,
        project_id: str,
        identity: Dict[str, str],
        view: _LedgerView,
    ) -> Dict[str, Any]:
        snapshot = self._initial_snapshot(project_id, identity["display_name"], identity["created_at"])
        state = snapshot["state"]
        for record in view.records:
            for event in record["events"]:
                self._apply_event(state, event)
        snapshot["state_revision"] = view.revision
        snapshot["derived_from_revision"] = view.revision - 1 if view.revision else None
        snapshot["updated_at"] = view.records[-1]["committed_at"] if view.records else identity["created_at"]
        snapshot["event_log"] = {
            "path": "events.jsonl",
            "head_event_id": view.head_event_id,
            "head_event_hash": view.head_event_hash,
            "head_record_hash": view.head_record_hash,
            "last_event_sequence": view.last_event_sequence,
            "applied_event_count": view.applied_event_count,
            "committed_transaction_count": view.revision,
        }
        if state["route_status"] == "ready" and state["accepted_bottleneck_ref"] is None:
            state["route_status"] = "needs_evidence"
        return snapshot

    @staticmethod
    def _append_unique(target: List[str], value: Any) -> None:
        if isinstance(value, str) and value and value not in target:
            target.append(value)

    def _apply_event(self, state: Dict[str, Any], event: Dict[str, Any]) -> None:
        event_type = event["event_type"]
        data = event.get("payload", {}).get("data", {})
        data = data if isinstance(data, dict) else {}
        state["active_cycle_id"] = event.get("cycle_id") or state["active_cycle_id"]
        if event_type == "maturity_classified" and data.get("maturity") in {
            "nascente", "em_desenvolvimento", "maduro", "avancado", "unknown",
        }:
            state["maturity"] = data["maturity"]
        elif event_type == "bottleneck_accepted":
            ref = data.get("bottleneck_ref") or data.get("accepted_bottleneck_ref") or event["event_id"]
            state["accepted_bottleneck_ref"] = ref
            state["route_status"] = "ready"
        elif event_type == "bottleneck_rejected":
            state["accepted_bottleneck_ref"] = None
            state["route_status"] = "needs_evidence"
        elif event_type == "route_plan_issued":
            status = data.get("route_status")
            if status in {"ready", "needs_evidence", "blocked", "rejected"}:
                state["route_status"] = status

        if event_type == "handoff_issued":
            self._append_unique(state["handoff_refs"], data.get("handoff_ref") or data.get("handoff_id") or event["event_id"])
        elif event_type.startswith("experiment_"):
            self._append_unique(state["experiment_refs"], data.get("experiment_ref") or data.get("experiment_id") or event["event_id"])
        elif event_type == "learning_recorded":
            self._append_unique(state["learning_refs"], data.get("learning_ref") or data.get("learning_id") or event["event_id"])
        elif event_type == "data_gap_reported":
            self._append_unique(state["known_gap_refs"], data.get("gap_ref") or data.get("gap_id") or event["event_id"])
        elif event.get("effect") == "integration":
            self._append_unique(state["decision_refs"], data.get("decision_ref") or event["event_id"])

    def _read_json_cache(self, path: Path) -> Optional[Dict[str, Any]]:
        if not path.exists():
            return None
        try:
            raw = self._safe_read_bytes(path)
            value = json.loads(raw.decode("utf-8"))
        except (LoopRuntimeError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _cache_status(self, project_dir: Path, expected: Dict[str, Any]) -> str:
        latest = self._read_json_cache(project_dir / "snapshots" / "latest.json")
        project = self._read_json_cache(project_dir / "project.json")
        for value in (latest, project):
            if isinstance(value, dict) and isinstance(value.get("state_revision"), int):
                if value["state_revision"] > expected["state_revision"]:
                    return "ahead"
        if latest == expected and project == expected:
            return "current"
        if latest is None and project is None:
            return "missing"
        return "stale"

    def _assert_cache_not_ahead(self, project_id: str, project_dir: Path, view: _LedgerView) -> None:
        identity = self._identity(project_id, project_dir, view)
        expected = self._snapshot_from_view(project_id, identity, view)
        if self._cache_status(project_dir, expected) == "ahead":
            raise LoopRuntimeError(
                "ERR_STATE_FABRICATION",
                "A derived cache is ahead of the authoritative ledger.",
                details={"project_id": project_id, "ledger_revision": view.revision},
            )

    def _publish_caches(self, project_dir: Path, snapshot: Dict[str, Any]) -> None:
        self._atomic_write_json(project_dir / "project.json", snapshot)
        self._atomic_write_json(project_dir / "snapshots" / "latest.json", snapshot)

    @staticmethod
    def _commit_result(record: Dict[str, Any], snapshot: Dict[str, Any], status: str) -> Dict[str, Any]:
        return {
            "status": status,
            "transaction_id": record["transaction_id"],
            "state_revision": record["resulting_state_revision"],
            "current_state_revision": snapshot["state_revision"],
            "head_event_hash": record["events"][-1]["event_hash"],
            "head_record_hash": record["record_hash"],
            "event_hashes": [event["event_hash"] for event in record["events"]],
            "snapshot": copy.deepcopy(snapshot),
        }

    def _noop_result(self, stored: Dict[str, Any], view: _LedgerView) -> Dict[str, Any]:
        project_id = stored["project_ref"].split(":", 1)[1]
        project_dir = self._project_dir(project_id, must_exist=True)
        identity = self._identity(project_id, project_dir, view)
        current = self._snapshot_from_view(project_id, identity, view)
        result = self._commit_result(stored, current, status="noop")
        result["current_state_revision"] = view.revision
        return result

    # ------------------------------------------------------------------
    # Recovery and quarantine
    # ------------------------------------------------------------------
    def _assert_writable(self, project_dir: Path) -> None:
        marker = self._read_recovery_marker(project_dir)
        if marker is not None:
            raise LoopRuntimeError(
                "ERR_RECOVERY_REQUIRED",
                "Project is degraded read-only until explicit recovery.",
                retryable=True,
                details=marker,
            )

    def _read_recovery_marker(self, project_dir: Path) -> Optional[Dict[str, Any]]:
        return self._read_json_cache(project_dir / "recovery-status.json")

    def _quarantine_ledger(
        self,
        project_id: str,
        project_dir: Path,
        corruption: _LedgerCorruption,
    ) -> Dict[str, Any]:
        self._ensure_roots()
        ledger = project_dir / "events.jsonl"
        try:
            raw = self._read_bytes_nofollow(ledger)
        except (LoopRuntimeError, OSError):
            raw = b""
        digest = _sha256(raw)
        quarantine = self._quarantine_dir / ("%s-events-%s.jsonl" % (project_id, digest))
        if not quarantine.exists():
            try:
                self._create_fsynced_file(quarantine, raw)
                self._fsync_dir(self._quarantine_dir)
            except FileExistsError:
                pass
        report = {
            "status": "degraded_read_only",
            "writable": False,
            "project_id": project_id,
            "ledger_status": "corrupt",
            "primary_code": corruption.code,
            "message": corruption.message,
            "ledger_sha256": digest,
            "quarantine_paths": [str(quarantine.relative_to(self.state_root))],
            "observed_at": _now(),
            "details": corruption.details,
        }
        self._atomic_write_json(project_dir / "recovery-status.json", report)
        return report

    # Test-only fault injection seam.  Production calls are a no-op.
    def _fault_hook(self, stage: str) -> None:
        del stage
