from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.workers.queue import followup_job_id


def test_followup_job_ids_deduplicate_a_quarter_hour_without_blocking_next_run():
    tenant = uuid4()
    now = datetime(2026, 10, 24, 5, 0, tzinfo=UTC)
    assert followup_job_id(tenant, now) == followup_job_id(tenant, now + timedelta(minutes=14))
    assert followup_job_id(tenant, now) != followup_job_id(tenant, now + timedelta(minutes=15))
    assert followup_job_id(tenant, now) != followup_job_id(uuid4(), now)
