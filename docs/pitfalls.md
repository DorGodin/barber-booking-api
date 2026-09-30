# Pitfalls

Mistakes made while building this, and the rule that prevents each one.

## 2026-09-30 — The booking lock did nothing, and every in-process test passed

`write_lock` asked for `BEGIN IMMEDIATE` through `session.connection(execution_options=...)`.
By then the authentication dependency had already loaded the user through the same
session, so the connection was established with an ordinary `BEGIN`. SQLAlchemy ignores
execution options on an established connection and says so only in a warning. 26 tests
passed. Against a real two-worker server, 10 of 12 customers racing for one slot got a 500.

**Rule:** `write_lock` ends any open transaction before taking the lock, and `pytest.ini`
turns `SAWarning` into an error so an ignored option fails the run. A concurrency property
is tested against a real multi-process server, never only in-process — `TestClient` runs
one request at a time and cannot race.

## 2026-09-30 — On SQLite, a missing lock looks like 500s, not double bookings

Without `BEGIN IMMEDIATE`, five concurrent requests for one slot produced **one** booking —
and four `database is locked` errors. The deferred transaction's read lock cannot be
upgraded to a write lock while another writer waits, so SQLite refuses instead of
serialising. On Postgres the same code would double book.

**Rule:** a race test asserts exactly one success, every other a clean 409, and no 5xx.
"One booking exists" alone passes a server that crashes for everyone who lost.

## 2026-09-30 — A fixed UTC offset instead of the time zone

Computing slots as "local time minus two hours" is right for half the year in Israel. The
spring-forward day has 23 hours and no 02:30; the fall-back day has 25 hours and 01:30
twice; and 09:00 local is 06:00 UTC in summer but 07:00 in winter.

**Rule:** a day is turned into the UTC instants of its local opening and closing, through
`zoneinfo`, and slots are stepped in UTC between them. `tests/test_scheduling.py` checks
both transition days; a fixed-offset mutant fails five of its tests.
