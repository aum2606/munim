from datetime import UTC, datetime

from app.core.inbox import holding_message, outside_hours


def test_business_hours_and_localized_holding():
    now = datetime(2026, 10, 26, 5, 0, tzinfo=UTC)  # Monday 10:30 IST
    assert not outside_hours({}, "Asia/Kolkata", now)
    assert not outside_hours({"monday": ["09:00", "18:00"]}, "Asia/Kolkata", now)
    assert outside_hours({"monday": ["11:00", "18:00"]}, "Asia/Kolkata", now)
    assert outside_hours({"tuesday": ["09:00", "18:00"]}, "Asia/Kolkata", now)
    assert outside_hours({"monday": ["bad", "time"]}, "Asia/Kolkata", now)
    assert not outside_hours({"monday": ["18:00", "11:00"]}, "Asia/Kolkata", now)
    for language in ["en", "hi", "gu", "hinglish", "gujlish", "other"]:
        assert holding_message(language, True) != holding_message(language, False)
