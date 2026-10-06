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
| `app/backup.py` | copies of the database and putting one back - `make backup`, `make restore` |
| `app/migrate.py`, `app/migrations/versions/` | how the tables reach the shape `app/models.py` describes, one migration per change |
| `app/routers/` | one file per area |
| `app/views.py` | how every entity looks on the wire, once |
| `app/static/index.html` | the booking page: one file, no build step, every value written as text |

**A barber who leaves is inactive, never deleted** (`PATCH /barbers/{id}`). Everything that
books asks `bookable_barber_or_error`; everything that only manages - hours, days off, the
owner's list and diary - still finds them. Their bookings are not cancelled by the system:
the owner decides about each. An inactive user's token stops working at once, and
`account_inactive` is told only after the right password.

**A booking is a customer's or a guest's, never both, never neither** - the database's own
check holds it. A guest (`POST /bookings/guest`, the owner only) has a name and no account:
the chair is checked, the customer is not, and the limit on bookings ahead does not apply.
Every clash check goes through `_refuse_clashes` in `routers/bookings.py`; asked about "no
customer", `busy()` returns every booking in the shop.

**A move is the same booking at another time** - one request under the write lock, so the old
time is held until the new one is taken. The listing for a move passes `moving=<id>`, and both
leave that booking out of `busy()` the same way.

**Availability and booking must never compute their rules separately.** If the listing and
the booking disagree, the listing offers a slot the booking refuses. Change the rule in
`booking_rules.py` and both follow.

## Concurrency

**Every write in a route runs inside `with write_lock(session):`** - not only a
check-then-write that must not race. A request reads first (authentication loads the user),
and two workers that each read and then write deadlock in SQLite: one is answered "database
is locked", a 500. Sign-in, sign-out and the owner's saves all did, under concurrent load,
until they took the lock; `tests/test_source_hygiene.py` fails on a `session.commit()` in a
route. `write_lock` ends
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
- **The shop's header is written into the page by the server** (`app/identity.py`), escaped:
  the brand, the line under it, a button for each way to reach the shop that is set, and the
  shop's own cover and profile pictures, served from `/media` - only those two files. A link
  must be `https://` and a phone Israeli, or the server refuses to start, naming the setting.
- **The contact buttons stand at the foot of the page**, above the links to the accessibility
  statement and the privacy policy (`/privacy`). The policy says only what the code does - what
  is kept, why, for how long (codes a day, failed sign-ins a quarter hour, sign-ups an hour) -
  so a change to what is stored or for how long changes `app/static/privacy.html` too.
- **The poles, the scissors and every icon are decoration**: `aria-hidden`, and still under
  `prefers-reduced-motion`. Each contact button has a Hebrew name of its own.
- **A new screen starts at its top**, and on a phone nothing the page scrolls to may land under
  the owner's menu (`scroll-padding-top`, WCAG 2.4.11). The booking card is the one answer
  that may start below the fold, under the shop's tall header: it is brought up until all of it shows.
- **The owner books from the same panel, with a name field** (`guest-field`); a barber gets
  no booking panel. **The service choice offers active services only** - the owner's list
  holds withdrawn ones to manage, and offering one made the times fail and replace the
  owner's message.
- **A booking's names come from the booking** (`barber_name`, `service_name`), never from the
  shop's current lists: a customer's list has no barber who left, and their booking with
  that barber must still say who. The owner's list has them, marked, and the panel offers no
  times for one - asked, the server refuses and the refusal would replace the owner's message.
- **A customer's booking in the afternoon hours waits for the barber** (`approval`, `decide_by`;
  `app/booking_rules.py`). It holds the chair from the start; silence for the wait is a yes,
  read at the time and never by a job. The customer is told in the page, not by text message.
  **When it asks is the owner's** (`/approval-rules`, `shop_settings`): a switch, and per day the
  hours. The settings `APPROVAL_*` only say what it is until the owner saves.
- **One `refused()` shows every refusal** - booking, guest booking, move. A new way to book
  uses it rather than a copy.
- **Moving a booking is the booking panel with the barber and the service locked** to the
  booking's own, the times listed with `moving=`, and the book button sending the move.
  `stopMoving()` puts the panel back, on every way out - moved, stopped, signed out.
- **Before pushing a change to `app/`, run `make mutate-check` in qa-api-starter.** Its
  catalogue anchors on lines of this code; a line that changes or appears twice breaks its
  nightly run. It takes seconds.
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
- **A booking that goes through is answered by a card in the booking panel**
  (`booking-done`), in place of the form: the focus goes to its heading, its two buttons
  lead to the list and back to the form, and the booking tab pressed again shows the form.
  **A refusal, and the owner's booking for a caller, are answered by a `<dialog>` opened
  with `showModal()`**: focus goes to it, Escape closes it, the page behind it is inert.
  `show()` is not modal and is not acceptable here.

### The owner's screen

- **Shekels become agorot in whole numbers** (`parseShekels`), never `parseFloat(x) * 100`:
  92.55 * 100 is 9254.999999999998. Up to two decimals; anything else is refused.
- **The page checks hours before sending them** - on the quarter hour, closing after
  opening - so the owner gets a Hebrew sentence about the day that is wrong, not a 422. The
  server checks again; the page is a courtesy, not the rule.
- **Everything the owner changes is part of `refresh()`**, so the bookings, the hours and the
  services on screen are always the selected barber's current ones.

## Changing a table

**Every change to `app/models.py` comes with a migration, in the same commit.** The server
applies the migrations a database has not had when it starts; it never runs `create_all`,
which skips a table that exists - a new column reached fresh databases and no running shop.

1. Change the model.
2. `make migration m="add phone to users"` writes the migration into
   `app/migrations/versions/`. With the models unchanged it writes nothing.
3. **Read it.** Autogenerate misses renames (it writes drop-and-add, which loses the
   column's data), misses CHECK constraints entirely (write them by hand, and a test that the
   database refuses the row), and cannot fill a new non-null column on rows that exist - give
   it a `server_default`, or add it nullable, fill it, then tighten it.
   A downgrade that would delete people's data refuses instead (see `0002_guest_bookings.py`).
4. `make test`. `tests/test_migrations.py` fails if the models and the migrations disagree.

- **A migration never imports `app.models`.** The models keep changing after the migration is
  written; `UTCDateTime` is rendered as `sa.DateTime()` for that reason.
- **A migration that is in `main` is never edited** - a shop that already ran it will not run
  it again. A fix is a new migration.
- **SQLite alters a column by copying the table**, so foreign keys are off while migrations
  run, `PRAGMA foreign_key_check` must come back empty before they commit, and they are on
  again before the connection serves a request.
- A database from before migrations has the baseline's tables and no version; it is stamped
  at `0001` and continues from there, with its data.

## Backups

- **A copy is made with SQLite's backup, never by copying the file.** In WAL mode the latest
  writes may still be in `barber.db-wal`; a copied file misses them or comes out torn.
- **Every copy passes `PRAGMA integrity_check` before it counts**, and a file that does not is
  never restored.
- **The database is backed up before a migration changes it, and a backup that cannot be made
  stops the migration.** Changing a shop's tables with nothing to go back to is not allowed.
- **A restore backs up what it replaces first**, so restoring the wrong file can be undone.
- `tests/test_backup.py` restores and reads the data back. A backup nobody has restored is not
  known to be one.

### Starting several workers on an empty database

Every worker runs the startup at once. `prepare_database` migrates the tables and seeds the
shop under the write lock, with the emptiness check inside it, and the connect handler sets
`busy_timeout` and then asks whether the file is already in WAL mode before switching it -
the switch needs an exclusive lock that SQLite refuses at once rather than waits for.
`tests/test_startup.py` starts four workers on an empty database and fails on a crash.
