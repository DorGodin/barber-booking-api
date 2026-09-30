from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.scheduling import Interval, available_starts, is_aligned, parse_hhmm, working_window

TZ = ZoneInfo("Asia/Jerusalem")
ALL_DAY = dict.fromkeys(("mon", "tue", "wed", "thu", "fri", "sat", "sun"), ["00:00", "24:00"])
LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)
FAR_AHEAD = datetime(2100, 1, 1, tzinfo=UTC)


def slots(day, hours=ALL_DAY, duration=15, busy=()):
    return available_starts(
        working_window(day, hours, TZ), timedelta(minutes=duration), list(busy), LONG_AGO, FAR_AHEAD
    )


def test_a_normal_day_has_96_quarter_hours():
    assert len(slots(date(2026, 10, 12))) == 96


def test_the_spring_forward_day_is_23_hours_and_has_no_2_30():
    day = slots(date(2027, 3, 26))
    local = [s.astimezone(TZ).strftime("%H:%M") for s in day]

    assert len(day) == 92
    assert "02:30" not in local


def test_the_fall_back_day_is_25_hours_and_has_1_30_twice():
    day = slots(date(2026, 10, 25))
    local = [s.astimezone(TZ).strftime("%H:%M") for s in day]

    assert len(day) == 100
    assert local.count("01:30") == 2
    assert len(set(day)) == 100, "the repeated wall-clock hour is two different instants"


def test_opening_at_9_is_9_local_on_both_sides_of_the_change():
    before = slots(date(2026, 10, 22), hours={"thu": ["09:00", "19:00"]})[0]
    after = slots(date(2026, 10, 29), hours={"thu": ["09:00", "19:00"]})[0]

    assert before.astimezone(TZ).hour == after.astimezone(TZ).hour == 9
    assert before.hour == 6 and after.hour == 7, "the UTC instant moves by the offset"


def test_a_service_that_would_run_past_closing_is_not_offered():
    day = slots(date(2026, 10, 12), hours={"mon": ["09:00", "19:00"]}, duration=30)
    last = day[-1].astimezone(TZ).strftime("%H:%M")

    assert last == "18:30", "18:30 + 30 min ends exactly at closing and is allowed; 18:45 is not"


def test_back_to_back_is_allowed_and_overlap_is_not():
    window = working_window(date(2026, 10, 12), {"mon": ["09:00", "12:00"]}, TZ)
    booked = Interval(window.start + timedelta(hours=1), window.start + timedelta(hours=1, minutes=30))
    offered = available_starts(window, timedelta(minutes=30), [booked], LONG_AGO, FAR_AHEAD)
    local = [s.astimezone(TZ).strftime("%H:%M") for s in offered]

    assert "09:30" in local, "09:30-10:00 ends where the booking starts"
    assert "09:45" not in local and "10:00" not in local and "10:15" not in local
    assert "10:30" in local, "10:30 starts where the booking ends"


def test_a_closed_day_offers_nothing():
    assert slots(date(2026, 10, 17), hours={"sat": None}) == []


def test_nothing_in_the_past_or_beyond_the_window_is_offered():
    window = working_window(date(2026, 10, 12), {"mon": ["09:00", "10:00"]}, TZ)
    now = window.start + timedelta(minutes=20)
    latest = window.start + timedelta(minutes=45)

    offered = available_starts(window, timedelta(minutes=15), [], now, latest)

    assert [s - window.start for s in offered] == [timedelta(minutes=30), timedelta(minutes=45)]


@pytest.mark.parametrize("value", ["09:10", "25:00", "-01:00"])
def test_times_off_the_quarter_hour_or_outside_the_day_are_refused(value):
    with pytest.raises(ValueError):
        parse_hhmm(value)


def test_alignment_is_to_the_quarter_hour():
    assert is_aligned(datetime(2026, 10, 12, 7, 45, tzinfo=UTC))
    assert not is_aligned(datetime(2026, 10, 12, 7, 50, tzinfo=UTC))
