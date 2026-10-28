import importlib.util
import json
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.core.config import Settings
from app.repositories.storage import BACKUP_LOCK

SPEC = importlib.util.spec_from_file_location(
    "munim_ops", Path(__file__).parents[3] / "deploy/ops.py"
)
OPS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = OPS
SPEC.loader.exec_module(OPS)


@pytest.mark.parametrize("failed_upload", [False, True])
def test_backup_uploads_manifest_last_and_only_after_complete_snapshot(
    monkeypatch, tmp_path, failed_upload
):
    locks = []
    commands = []

    class Connection:
        def execute(self, sql, args):
            locks.append((sql, args))

        @contextmanager
        def cursor(self):
            yield self

        @contextmanager
        def copy(self, sql):
            yield iter([b"tenant_id,customer_fingerprint\n"])

    @contextmanager
    def connect(**kwargs):
        yield Connection()

    monkeypatch.setattr(OPS.psycopg, "connect", connect)

    def run(command, **kwargs):
        commands.append(command)
        assert "synthetic-password" not in " ".join(command)
        if command[0] == "pg_dump":
            Path(command[-1]).write_bytes(b"PGDMP-synthetic")
        elif command[0] == "tar":
            Path(command[2]).write_bytes(b"synthetic-archive")
        elif command[0] == "aws" and failed_upload:
            raise subprocess.CalledProcessError(1, command)
        elif command[0] == "aws" and command[3].endswith("manifest.json"):
            manifest = json.loads(Path(command[3]).read_text(encoding="utf-8"))
            assert manifest["complete"] and len(manifest["sha256"]) == 3
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(OPS.subprocess, "run", run)
    settings = OPS.OpsSettings(
        _env_file=None,
        pgpassword="synthetic-password",
        backup_bucket="private-demo",
        backup_work_dir=str(tmp_path / "work"),
        backup_state_dir=str(tmp_path / "state"),
        uploads_dir=str(tmp_path / "uploads"),
    )
    if failed_upload:
        with pytest.raises(subprocess.CalledProcessError):
            OPS.backup(settings)
        assert not (tmp_path / "state/last_success").exists()
    else:
        OPS.backup(settings)
        assert commands[-1][3].endswith("manifest.json")
        assert (tmp_path / "state/last_success").is_file()
    assert locks[0][1] == (BACKUP_LOCK,) and "unlock" in locks[-1][0]
    assert all("AES256" in command for command in commands if command[0] == "aws")
    assert not list((tmp_path / "work").iterdir())


def test_monitor_requires_ready_api_and_recent_completed_backup(monkeypatch, tmp_path):
    class Response:
        status = 200

        def read(self, size):
            return b'{"status":"ready"}'

    @contextmanager
    def response(*args, **kwargs):
        yield Response()

    monkeypatch.setattr(OPS, "urlopen", response)
    settings = OPS.OpsSettings(_env_file=None, backup_state_dir=str(tmp_path))
    assert not OPS.healthy(settings)
    marker = tmp_path / "last_success"
    marker.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
    assert OPS.healthy(settings)
    marker.write_text("2026-01-01T00:00:00+00:00", encoding="utf-8")
    assert not OPS.healthy(settings)
    marker.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
    Response.status = 503
    assert not OPS.healthy(settings)


def test_operations_schedule_and_endpoint_validation():
    settings = OPS.OpsSettings(_env_file=None)
    assert (
        OPS.next_backup(settings, datetime(2026, 10, 28, 19, tzinfo=UTC)).isoformat()
        == "2026-10-28T20:30:00+00:00"
    )
    with pytest.raises(ValidationError):
        OPS.OpsSettings(_env_file=None, backup_endpoint_url="http://insecure.example")
    with pytest.raises(ValidationError):
        OPS.OpsSettings(_env_file=None, backup_sse="aws:kms")


def test_production_requires_https_limits_and_explicit_provider_setup():
    values = dict(
        _env_file=None,
        app_env="prod",
        secret_key="s" * 64,
        privacy_hash_key="p" * 64,
        credentials_encryption_key=Fernet.generate_key().decode(),
        public_api_url="https://demo.example",
        widget_script_url="https://demo.example/widget.js",
        cors_origins="https://demo.example",
        llm_provider="fake",
        embedding_provider="fake",
        allow_fake_models_in_prod=True,
    )
    assert Settings(**values).app_env == "prod"
    with pytest.raises(ValidationError):
        Settings(**{**values, "rate_limits_enabled": False})
    with pytest.raises(ValidationError):
        Settings(**{**values, "public_api_url": "http://demo.example"})
    with pytest.raises(ValidationError):
        Settings(**{**values, "allow_fake_models_in_prod": False})
