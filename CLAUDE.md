# Barber Booking API — working rules

A small, real appointment booking API for a barbershop. It is built to be tested **from the
outside**, by an independent framework (qa-api-starter) that knows only its URL. That is
the point of it, and most of these rules protect it.

## Never

- **Never add a test hook.** No `/_test/reset`, no endpoint that exists only so a test can
  cheat. A product with test hooks lets its test framework stay coupled to it, and the
  framework then fails on the next real product it meets. Tests create their own data
  through the real API — the owner can create a barber, set hours, add time off.
- **Never store or compare a naive datetime.** Every instant is aware UTC. `UTCDateTime` in
  `app/models.py` converts at the database boundary and refuses a naive value.
- **Never use a float for money.** `price_minor` is an integer in minor units (8000 = 80.00).

## Where things live

| File | Holds |
|---|---|
| `app/scheduling.py` | pure rules: slots, overlap, DST. No database, no HTTP, no clock |
| `app/booking_rules.py` | "is this bookable", used by BOTH the availability listing and the booking |
| `app/db.py` | the engine and `write_lock`, the BEGIN IMMEDIATE that prevents double booking |
| `app/routers/` | one file per area |
| `app/views.py` | how every entity looks on the wire, once |
| `app/static/index.html` | the booking page: one file, no build step, every value written as text |

**Availability and booking must never compute their rules separately.** If the listing and
the booking disagree, the listing offers a slot the booking refuses. Change the rule in
`booking_rules.py` and both follow.

## Concurrency

Any check-then-write that must not race runs inside `with write_lock(session):`. It ends
the request's earlier read transaction and begins a new one with `BEGIN IMMEDIATE`, which
takes SQLite's write lock at the start. Without that first step SQLAlchemy silently
ignores the option — `pytest.ini` turns that warning into an error. See `docs/pitfalls.md`.

A race is tested against a real server with two workers (`tests/test_concurrency.py`),
asserting **exactly one 201, every other a 409, and zero 5xx**. On SQLite the unlocked
version does not double book — it answers the losers with 500s — so "one booking exists"
alone would pass a broken server.

## Errors

Every refusal is `{"detail": "...", "code": "..."}`. Clients branch on `code`; the wording
of `detail` can change. Somebody else's booking is 404, not 403.

## Verifying

`make test`. A claim that something works comes with the output that shows it.

## The booking page

- **Times come from `start_local`, never from the browser's clock.** A customer abroad sees
  the shop's 10:30.
- **Every value from a user is set with `textContent`.** A display name is text, even when
  it looks like a tag.
- **`aria-busy` on the app section is true while the page fetches** and false once the
  screen is current. Screen readers use it, and so do the outside UI tests — keep it
  accurate when adding anything that fetches.
- **`[hidden] { display: none !important; }` stays.** Without it, any element with its own
  `display` rule ignores `hidden`.

### Hebrew, right to left

- **`<html lang="he" dir="rtl">`**, and times keep `direction: ltr` inside it: 10:30 never
  becomes 30:10.
- **A name from the server inside a Hebrew sentence is wrapped in `isolate()`** (FSI...PDI),
  so a Latin barber or service name cannot drag punctuation to the wrong side.
- **Write direction characters as escapes (`\u2068`), never as the characters.** They are
  invisible in review — the Trojan Source class. `tests/test_source_hygiene.py` fails on any.
- **The customer never sees the server's English.** Every error code has Hebrew words in
  `FRIENDLY`, and the fallback is Hebrew too. Adding a code on the server means adding it here.
- **Labels are tied with `for=`, never wrapped around a field.** A label around a `<select>`
  takes every option into the field's accessible name.
- **Prices and dates go through `Intl` with `he-IL`**, whatever the browser's own language.
- The seeded menu and accounts are Hebrew. Tests read the names from `app/seed.py`, so a
  rename there never breaks them.

### The seed and the popup

- **The seed obeys every rule the product enforces.** It builds bookings with the same
  scheduling functions the product uses, inside the shop's hours, in the future, and never
  with one customer in two chairs. `tests/test_seed.py` checks each of those.
- **Tests read seeded data from `app/seed.py`**, never repeat it, and take the seed
  passwords from the `passwords` fixture - importing them from `tests.conftest` runs that
  file a second time and the random passwords come out different.
- **The booking outcome is a `<dialog>` opened with `showModal()`**: focus goes to it,
  Escape closes it, the page behind it is inert. `show()` is not modal and is not
  acceptable here.
