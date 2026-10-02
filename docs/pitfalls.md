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

## 2026-09-30 — The overlap rule lived in two places

The listing decided overlap with `Interval.overlaps`; the booking decided it with a SQL
predicate in `busy()`. Both said "strictly overlapping", so both were right — until one
changes. An outside suite broke only the Python side and watched the listing stop offering
the slot right after a booking, while the booking would still have accepted it. The rule
this repository's CLAUDE.md names first — availability and booking must never compute their
rules separately — was broken by its own author.

**Rule:** SQL fetches candidates, `Interval.overlaps` decides. `busy()` now returns bookings
touching the window as well, and every caller asks `clashes()`. A rule that must agree in
two places lives in one.

## 2026-09-30 — Signed in, and the sign-in form stayed on screen

The page hid the sign-in section with the `hidden` attribute after a successful login. The
section also had `display: grid` in the stylesheet, and an element's own display rule beats
the browser's `[hidden] { display: none }`. Every request succeeded; the form simply never
went away. The confirmation bar, `display: flex`, had the same bug and showed before any
time was chosen. Found by looking at the page, not by a test — so there is now a test.

**Rule:** `[hidden] { display: none !important; }` in the page's stylesheet, and UI tests
assert visibility (`to_be_hidden`, which reads the computed style), never the attribute.

## 2026-09-30 — A label wrapped around a select named the field after every option

`<label>ספר <select>…</select></label>` gives the select an accessible name made of the
label AND the text of every option inside it. A screen reader would announce the barber
field as the whole list of barbers. It hid in English because the outside tests looked the
label up by substring; the Hebrew rewrite looked it up exactly, and found nothing.

**Rule:** tie a label to its field with `for=`. Look labels up exactly in tests — a
substring match forgives exactly this.

## 2026-09-30 — Invisible direction characters in the page's source

The isolate helper was written with the actual U+2068 and U+2069 characters. They are
invisible: a reviewer sees an empty template literal, an editor can drop them without a
trace, and GitHub flags the file — the same characters are how "Trojan Source" hides code.

**Rule:** write them as `\u2068` escapes. `tests/test_source_hygiene.py` scans every source
file and fails on any such character; it was proven by putting one back.

## 2026-09-30 — The tests depended on the seeded menu's English names

Renaming the seeded services to Hebrew would have broken 23 references to "Haircut" and
"Beard trim" across the tests. They now read the names from `app/seed.py`, so the seed can
change without touching a test.

**Rule:** a test that needs seeded data reads it from the seed, never repeats it.

## 2026-09-30 — A red test run was committed and pushed

The commit was chained as `pytest -q | tail -1 && git commit`. A pipeline's exit status is
its last command's, so `tail` succeeded, `&&` saw success, and a run with one failing test
was committed and pushed. The failure itself was the source-hygiene guard catching a hidden
direction character in this very file.

**Rule:** gate a commit on the test command's own exit code, never on a pipeline's:
`pytest -q > out.txt; code=$?` — then commit only if `code` is 0.

## 2026-09-30 — Importing a fixture's data re-ran conftest and changed the passwords

`from tests.conftest import PASSWORDS` in a new test returned different passwords from the
ones the `client` fixture had seeded: pytest had already imported the file as `conftest`,
the test imported it again as `tests.conftest`, and its module-level `secrets.token_urlsafe`
ran a second time. Every login in the new test failed with 401.

**Rule:** share test data through a fixture (`passwords`), never by importing a conftest's
module-level values - especially random ones.

## 2026-09-30 — The local database was reset seconds after a booking was made in it

To load the new seed, the local database was deleted while the running page was in use:
the server's log showed a booking created a minute earlier, and it went with the rest. The
data was disposable, but nobody had said so.

**Rule:** before resetting a database someone may be using, read the server's log or ask.
Stop the server first, then reset, then start - never reset under a running server.

## 2026-10-01 — A worker died on every fresh start, and the supervisor hid it

Starting with several workers on an empty database, every worker ran the startup at once,
and all but one died on "database is locked". uvicorn restarted them, the restarted ones
found the database ready, and everything looked fine - CI included. It surfaced only when a
load test started a fresh copy and its log said "Child process died".

The cause was not where it first looked. Locking the seed's check-then-insert was worth
doing - two workers could otherwise both see an empty database and both seed it - but the
crash was `PRAGMA journal_mode=WAL` on connect. Switching to WAL needs an exclusive lock,
and when the conflict could deadlock SQLite refuses at once, `busy_timeout` or not.

**Rule:** a connection asks `PRAGMA journal_mode` first and switches only if the file is not
already in WAL, retrying briefly while the first worker does it. Read the traceback for the
line that failed before fixing the line you suspect. A crash a supervisor restarts is still
a crash: `tests/test_startup.py` reads the server's own log for one.

## 2026-10-01 — The database was reset under a running server, twice in one day

`make reset-db && make run` deleted the database while `make run` was still serving it in
another tab. The old server kept running on a file that no longer existed, and the new one
failed with "address already in use". Both times the instruction had said to stop the
server first; an instruction is not a guard.

**Rule:** `reset-db` and `reset-test-db` refuse while a server is listening on their port,
and say what to do. Proven both ways: refused with the test copy running, ran with the
port free.

## 2026-10-01 — Sign-in, sign-out and the owner's saves answered 500 under concurrent load

An owner signing in while a customer on the same page signed out got a 500. The sign-in
limits and the server-side sign-out had added writes to two routes, and neither took the write
lock: each request read first, then tried to write, and two workers doing that at once
deadlock in SQLite - one is refused at once with "database is locked". Reproduced with thirty
requests at once against two workers: most of them 500, on every run. The owner's saves -
hours, days off, services, barbers - had the same flaw from the start; a save during bookings
failed the same way.

**Rule:** every write in a route goes through `write_lock`, not only a check-then-write; a
source test fails on a plain `session.commit()` in a route. Found by a failing page test whose
sign-in step now says why it was refused - "500" - instead of "the screen never came".

## 2026-10-02 — The test for an old database built it from today's models

The test for "a database from before migrations keeps its data" made that database with
`create_all` from `app/models.py`. It passed - until a second migration added a column:
the "old" database already had it, and the upgrade failed on a duplicate column. The test
described a database that never existed.

**Rule:** a database from the past is built from the migrations at that point
(`upgrade` to the revision, as it was), never from the current models - they keep moving
and the past does not. When a test passes on the first run, break the code it guards and
watch it fail; then add a later change and watch it still pass.
