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
