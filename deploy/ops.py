"""Single-purpose production backup/uptime process. Never prints credentials or provider errors."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import psycopg
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKUP_LOCK = 6406001


class OpsSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_file=".env.production")
    pghost: str = "postgres"
    pgport: int = 5432
    pguser: str = "munim"
    pgdatabase: str = "munim"
    pgpassword: SecretStr = SecretStr("")
    backup_bucket: str = ""
    backup_prefix: str = "munim"
    backup_endpoint_url: str = ""
    backup_sse: Literal["AES256", "aws:kms"] = "AES256"
    backup_kms_key_id: str = ""
    backup_hour_utc: int = Field(default=20, ge=0, le=23)
    backup_minute_utc: int = Field(default=30, ge=0, le=59)
    backup_work_dir: str = "/backups"
    backup_state_dir: str = "/backup-state"
    uploads_dir: str = "/data/uploads"
    health_url: str = "http://api:8000/ready"
    alert_webhook_url: SecretStr = SecretStr("")
    monitor_interval_s: int = Field(default=60, ge=10, le=3600)
    monitor_failures: int = Field(default=3, ge=1, le=20)
    backup_max_age_hours: int = Field(default=26, ge=1, le=168)

    @model_validator(mode="after")
    def safe_endpoints(self) -> "OpsSettings":
        for value in (self.backup_endpoint_url, self.alert_webhook_url.get_secret_value()):
            if value:
                parsed = urlparse(value)
                if (
                    parsed.scheme != "https"
                    or not parsed.hostname
                    or parsed.username
                    or parsed.password
                ):
                    raise ValueError(
                        "External operations endpoints must use HTTPS without userinfo"
                    )
        if self.backup_sse == "aws:kms" and not self.backup_kms_key_id:
            raise ValueError("KMS backups require BACKUP_KMS_KEY_ID")
        return self


def emit(event: str, **values: str | int) -> None:
    print(json.dumps({"event": event, **values}), flush=True)


def alert(settings: OpsSettings, event: str) -> None:
    emit(event)
    endpoint = settings.alert_webhook_url.get_secret_value()
    if endpoint:
        request = Request(
            endpoint,
            data=json.dumps({"event": event, "service": "munim"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:
                response.read(1024)
        except (URLError, TimeoutError, OSError):
            emit("alert_delivery_failed")


def upload_command(settings: OpsSettings, source: Path, key: str) -> list[str]:
    command = [
        "aws",
        "s3",
        "cp",
        str(source),
        f"s3://{settings.backup_bucket}/{key}",
        "--sse",
        settings.backup_sse,
        "--only-show-errors",
        "--no-progress",
    ]
    if settings.backup_sse == "aws:kms":
        command.extend(["--sse-kms-key-id", settings.backup_kms_key_id])
    if settings.backup_endpoint_url:
        command.extend(["--endpoint-url", settings.backup_endpoint_url])
    return command


def backup(settings: OpsSettings) -> None:
    if not settings.backup_bucket or not settings.pgpassword.get_secret_value():
        raise ValueError("Configure the private backup bucket and database credential")
    original_mask = os.umask(0o077)
    directory = Path(settings.backup_work_dir)
    directory.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="munim-backup-", dir=directory))
    environment = {
        **os.environ,
        "PGHOST": settings.pghost,
        "PGPORT": str(settings.pgport),
        "PGUSER": settings.pguser,
        "PGDATABASE": settings.pgdatabase,
        "PGPASSWORD": settings.pgpassword.get_secret_value(),
    }
    try:
        with psycopg.connect(
            host=settings.pghost,
            port=settings.pgport,
            user=settings.pguser,
            dbname=settings.pgdatabase,
            password=settings.pgpassword.get_secret_value(),
            connect_timeout=10,
            autocommit=True,
        ) as connection:
            connection.execute("SELECT pg_advisory_lock(%s)", (BACKUP_LOCK,))
            try:
                subprocess.run(
                    [
                        "pg_dump",
                        "--format=custom",
                        "--no-owner",
                        "--no-acl",
                        "--file",
                        str(work / "database.dump"),
                    ],
                    env=environment,
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    ["tar", "-czf", str(work / "uploads.tar.gz"), "-C", settings.uploads_dir, "."],
                    check=True,
                    capture_output=True,
                )
                with connection.cursor() as cursor:
                    with cursor.copy(
                        "COPY (SELECT tenant_id,customer_fingerprint,"
                        "channel_fingerprints,created_at "
                        "FROM privacy_erasures) TO STDOUT WITH CSV HEADER"
                    ) as copy:
                        with (work / "erasures.csv").open("wb") as ledger:
                            for block in copy:
                                ledger.write(bytes(block))
            finally:
                connection.execute("SELECT pg_advisory_unlock(%s)", (BACKUP_LOCK,))
        checksum = {}
        for path in work.iterdir():
            with path.open("rb") as source:
                checksum[path.name] = hashlib.file_digest(source, "sha256").hexdigest()
        manifest = {
            "created_at": datetime.now(UTC).isoformat(),
            "sha256": checksum,
            "complete": True,
        }
        (work / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        run = work.name.removeprefix("munim-backup-")
        prefix = (
            settings.backup_prefix.strip("/")
            + "/"
            + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + run
        )
        # Completion manifest is uploaded last. Never advertise a partial upload as a usable backup.
        for name in ["database.dump", "uploads.tar.gz", "erasures.csv", "manifest.json"]:
            subprocess.run(
                upload_command(settings, work / name, f"{prefix}/{name}"),
                check=True,
                capture_output=True,
            )
        state = Path(settings.backup_state_dir)
        state.mkdir(parents=True, exist_ok=True)
        temporary = state / "last_success.tmp"
        temporary.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
        temporary.replace(state / "last_success")
        emit("backup_complete")
    finally:
        # Only remove the private directory created by mkdtemp for this invocation.
        if work.resolve().parent == directory.resolve() and work.name.startswith("munim-backup-"):
            shutil.rmtree(work)
        os.umask(original_mask)


def next_backup(settings: OpsSettings, now: datetime) -> datetime:
    target = now.astimezone(UTC).replace(
        hour=settings.backup_hour_utc, minute=settings.backup_minute_utc, second=0, microsecond=0
    )
    return target if target > now else target + timedelta(days=1)


def healthy(settings: OpsSettings) -> bool:
    try:
        with urlopen(settings.health_url, timeout=5) as response:
            if response.status != 200 or json.loads(response.read(4096)).get("status") != "ready":
                return False
        timestamp = datetime.fromisoformat(
            (Path(settings.backup_state_dir) / "last_success").read_text(encoding="utf-8")
        )
        return datetime.now(UTC) - timestamp < timedelta(hours=settings.backup_max_age_hours)
    except (URLError, TimeoutError, OSError, ValueError, TypeError):
        return False


def run(mode: str, settings: OpsSettings) -> None:
    if mode == "backup":
        backup(settings)
        return
    if mode == "backup-loop":
        due = datetime.now(UTC)
        while True:
            if datetime.now(UTC) >= due:
                try:
                    backup(settings)
                    due = next_backup(settings, datetime.now(UTC))
                except (OSError, ValueError, psycopg.Error, subprocess.SubprocessError):
                    alert(settings, "backup_failed")
                    due = datetime.now(UTC) + timedelta(minutes=15)
            time.sleep(min(30, max(1, (due - datetime.now(UTC)).total_seconds())))
    elif mode == "monitor":
        failures = 0
        previous: bool | None = None
        while True:
            failures = 0 if healthy(settings) else failures + 1
            current = failures < settings.monitor_failures
            if current != previous:
                if not current:
                    alert(settings, "uptime_or_backup_unhealthy")
                elif previous is False:
                    alert(settings, "uptime_and_backup_recovered")
                previous = current
            time.sleep(settings.monitor_interval_s)
    else:
        raise ValueError("Choose backup, backup-loop or monitor")


if __name__ == "__main__":
    try:
        run(sys.argv[1] if len(sys.argv) > 1 else "backup-loop", OpsSettings())
    except (OSError, ValueError, psycopg.Error, subprocess.SubprocessError):
        emit("operations_failed")
        raise SystemExit(1) from None
