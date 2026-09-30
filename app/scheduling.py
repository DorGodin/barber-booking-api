"""The scheduling rules, as pure functions: no database, no HTTP, no clock.

Every instant here is an aware UTC datetime. Opening hours are local wall-clock
times, so a day is turned into its two UTC instants - local open, local close -
and slots are stepped in UTC between them. That is the whole DST story: stepping
the local clock instead would give the spring-forward day a slot at 02:30 that
does not exist, and the fall-back day one hour too few.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SLOT = timedelta(minutes=15)
MINUTES_PER_DAY = 24 * 60
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True)
class Interval:
    """Half-open [start, end). Back-to-back bookings touch and do not overlap."""

    start: datetime
    end: datetime

    def overlaps(self, other: Interval) -> bool:
        return self.start < other.end and other.start < self.end

    def contains(self, other: Interval) -> bool:
        return self.start <= other.start and other.end <= self.end


def parse_hhmm(value: str) -> int:
    """'09:30' -> 570. '24:00' is allowed as a closing time: the end of the day."""
    hours, minutes = value.split(":")
    total = int(hours) * 60 + int(minutes)
    if not 0 <= total <= MINUTES_PER_DAY or int(minutes) % 15:
        raise ValueError(f"{value!r} is not a time on a 15 minute boundary between 00:00 and 24:00")
    return total


def format_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def local_instant(day: date, minute_of_day: int, tz: ZoneInfo) -> datetime:
    """The UTC instant of a local wall-clock time. 24:00 is the next local midnight."""
    if minute_of_day == MINUTES_PER_DAY:
        day, minute_of_day = day + timedelta(days=1), 0
    wall = datetime.combine(day, time(minute_of_day // 60, minute_of_day % 60), tzinfo=tz)
    return wall.astimezone(UTC)


def working_window(day: date, hours: dict[str, list[str] | None], tz: ZoneInfo) -> Interval | None:
    """The barber's working interval on a local date, or None when closed."""
    opening = hours.get(WEEKDAYS[day.weekday()])
    if not opening:
        return None
    open_min, close_min = parse_hhmm(opening[0]), parse_hhmm(opening[1])
    return Interval(local_instant(day, open_min, tz), local_instant(day, close_min, tz))


def is_aligned(instant: datetime) -> bool:
    return instant.second == 0 and instant.microsecond == 0 and instant.minute % 15 == 0


def available_starts(
    window: Interval | None,
    duration: timedelta,
    busy: list[Interval],
    now: datetime,
    latest: datetime,
) -> list[datetime]:
    """Every slot start where a service of `duration` fits inside the window,
    touches no busy interval, starts after `now` and no later than `latest`."""
    if window is None:
        return []
    starts = []
    cursor = window.start
    while cursor + duration <= window.end:
        candidate = Interval(cursor, cursor + duration)
        if cursor > now and cursor <= latest and not any(candidate.overlaps(b) for b in busy):
            starts.append(cursor)
        cursor += SLOT
    return starts
