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

**One way in on the page: a mobile, and the code sent to it** (`/auth/otp`). Whose phone it is
decides what opens - the owner's is `OWNER_PHONE`, set on every start by `give_owner_phone` and
refused when it is not a mobile or is somebody else's account; a barber's is given by the owner
(`PATCH /barbers/{id}` with `phone`, `_staff_phone`), unique across every account, shown to the
owner alone. **Never let a name decide a role** - anyone can type one. The password sign-in
(`/auth/token`) is the API's only, for scripts and tests; the page has no form for it.

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
- **A course is a card whose button opens WhatsApp** (`/courses`, `app/routers/courses.py`); the
  owner keeps them and uploads their pictures. A picture is accepted by its bytes and gets a name
  the server makes; `/media` serves only the identity pictures and the ones a course holds.
- **A review is the customer's, once, after the booking is over** (`reviews`, `app/routers/bookings.py`):
  stars at a tap, words optional and changeable, never for a cancelled or declined booking.
- **A customer who cancelled or moved three times in 90 days waits for the barber on every booking**
  (`is_flagged`, `booking_moves`): never shown to anyone, never approved by silence, counting only
  the customer's own cancellations and moves.
- **A service ticked `any_time` ignores the barber's hours and days off, and nothing else**
  (`day_window(any_time=...)`, used by the listing and by the booking): their bookings still take its
  times, and the booking window still ends it.
- **A notification carries no booking** (`app/push.py`): a signed header and no body, the words fixed in
  `/sw.js` by role. The server posts only to a push service's own host (`PUSH_HOSTS`, plus
  `PUSH_EXTRA_HOSTS` for development) - a subscription address is typed by a customer, and trusting it is
  a server-side request forgery. Never send a name, a time or a service through it.
- **The shop's app on a phone is notified through Firebase** (`app/native_push.py`, `push_devices`): the app registers
  its token (`POST /push/devices`, removed on sign-out with `/push/devices/remove`), and `PushHub.tell` tells every
  phone of those people too. Firebase hands an iPhone's message to Apple's APNs, so the server speaks to one
  service. As with Web Push, a phone is told only the fixed words of its person's role - never a name, a time or
  a service. The server posts only to Firebase's fixed address; the token travels in the body. A device Firebase
  says is gone is forgotten. `FCM_CREDENTIALS` unset: no phone notifications.
- **A customer is asked for notifications only after booking, for 24 hours** (`pushCard`, `PUSH_ASK_HOURS`): a
  booking ahead that stands and was made that lately. Moving or cancelling is no reason to ask; the row that
  turns them off stays for whoever said yes.
- **A customer deletes their own account in the app** (`DELETE /me`, `app/routers/accounts.py`; the "איזור אישי" tab,
  the fifth on a phone), as both stores require: one dialog asks, then the bookings ahead are cancelled and the
  staff told as of any customer's cancellation; the name, the phone, the staff's note, the notifications and
  any waiting code go. The row stays, emptied and closed (`deleted_at`), so the bookings that are over keep
  their place in the diary and the counts - `customer_deleted`, shown as "לקוח שנמחק" - and the reviews stay.
  The same phone signs up again as someone new. The staff are not deleted here; the owner manages them.
- **A request that fails for the connection or the server opens the trouble popup** (`trouble()`, in `api()`): no
  connection, no answer within `API_WAIT_MS`, or a 5xx. It names which, shows the customer's next booking when
  offline, and offers the shop's WhatsApp; "חזרה" closes it (the caller then gets a refusal like any other) and
  it stays closed until the person's next tap. When the connection returns the same request is sent again - a
  booking with the same Idempotency-Key, so never twice.
- **Inside the shop's app the page runs under the phone's clock and home bar** (`viewport-fit=cover`):
  `--safe-top`/`--safe-bottom` (env(), or Capacitor's `--safe-area-inset-*` on an older Android WebView) keep the
  content, the slim bar, the owner's menu, the tabs and the floating message clear of them; a white band stays
  behind the clock with the poles above it. In a browser they are 0 and nothing moves.
- **A customer's screen has no bar on top**: the name, the phone and signing out are in the personal area, with
  a copy of the page's foot (the ways to reach the shop, the statement, the policy) that a signed-in phone does
  not show otherwise. The staff keep the bar.
- **A sign-up takes a name of up to 25 characters and a mobile of ten digits starting 05.** Every phone field - the
  sign-in, a barber's and a new barber's (`PHONE_FIELDS`) - keeps to ten digits (a pasted +972 becomes them), says
  "המספר חייב להתחיל ב־05" under the field as soon as the start is wrong and holds its button, and says
  "המספר חייב להכיל 10 ספרות" when a short one is sent. The server checks again.
- **The shop is offered for the home screen by a band of its own under the bookings** (`renderInstall`, the owner's
  choice of 2026-10-14): the shop's black, its icon, and on an iPhone - whose Safari sends no notifications outside
  the home screen - Safari's two taps; where Chrome offers its own install (`beforeinstallprompt`), a button for it.
  A customer for a day after each booking - "not now" waits for the next booking - the staff until they add it,
  "not now" resting a day. On a phone it shows under "my bookings" only. One offer at a time: while it shows, the
  notifications card does not.
- **What a phone shows of the shop from its home screen is drawn from the profile picture** (`app/home_screen.py`,
  Pillow): the icons the manifest names (a maskable one keeps the logo whole inside Android's circle), the
  `apple-touch-icon`, and an iPhone's splash - black, the logo, the brand, the address - one picture per screen it is
  told of, drawn when first asked and kept in memory. Android draws its own splash from `background_color` and the
  maskable icon. Hebrew is drawn without a shaping engine: `_visual` puts it in drawing order, and each run takes
  the font file that holds it.
- **A service is chosen from the page's own list, which opens under its field** (`drawPicker`, `openPicker`; the owner's
  choice of 2026-10-15): an iPhone opened its own list upward when the field was low and folded a long line in two. The
  `<select>` stays, hidden, as the value the page reads and sets - whoever sets its value, options or `disabled` calls
  `drawPicker`. The field and every row say the name, and beside it the minutes and the price; a long name is cut, never
  them. Both are round (2026-10-18): a pill for the field, the chosen service a black pill, a thin line between the
  others, one line each - smaller letters on the narrowest phone. The list is a `listbox` worked by the keyboard too
  (arrows, Home, End, Enter, Escape). **A tab pressed clears the
  message** of the last screen.
- **A product is kept for a booking, never sold here** (`/products`, `app/routers/products.py`, `booking_products`):
  the owner keeps the shelf and marks what ran out - nothing is counted, nothing is paid. A customer's button
  appears only with a booking ahead and keeps the product for the nearest one; the booking names what is kept
  (`products` in its view) for the customer's list and the barber's diary. A picture is a course's picture: by
  its bytes, under the server's own name.
  **A kept product has a number, one to nine, that is set and never added** (`KeepIn`): fewer of a product
  that ran out may be kept, never more. The booking's row says what is kept, the same words for the customer and in the
  diary; it is changed on the shelf only. The shelf's buttons are 36px by the owner's choice. The buttons under a booking are 32px and centred, also the owner's (2026-10-14). With no booking ahead the shelf says to book first.
- **Booking for two is told at a glance** (`drawCompanion`, the owner's choice of 2026-10-15): a "2 אנשים" badge beside
  the title, and the second person's card in the shop's gold, headed "תור נוסף" and then "התור של" their name as it is
  typed (isolated, set as text), over "מיד אחרי התור שלך, אצל אותו ספר"; its service field is "השירות של" that name.
  **The second person is offered once the first person's time is chosen** (`showCompanionField`, the owner's choice of
  2026-10-18), under the times. Adding, removing or changing them keeps that time when both still fit in it
  (`keepingTime`); when they do not, the times are where both fit and the customer is told why theirs went. The card
  shows the second time, from the first's end by the shop's clock (`laterClock`), and the button books both.
- **A group booking is all or none, in one step under the write lock** (`/bookings/group`): the
  listing for two (`also=`) and the booking must agree, so a time offered for two always books. It counts
  as one toward the limit; afterwards each booking is its own.
- **A reminder is claimed before it is sent** (`app/reminders.py`, `reminded_at`): several workers look at once, and
  the claim is one write step - so a booking is reminded once, and a push that fails is not repeated.
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

### How it feels

- **The letters are Rubik, served by this server** (`/fonts`, two files and nothing else; `font-src 'self'`).
  The page asks no other site for anything - a font from someone else's server would be a request to them
  for every visitor. The same `@font-face` is in the page, the privacy policy and the accessibility statement.
- **A list that is slow to arrive is drawn in grey first** (`loading(id)`, `SHAPES`): only after
  `SKELETON_AFTER`, so a fast answer never flickers; only when the list is on the screen; hidden from a
  screen reader; and gone - the list shown again - before `aria-busy` goes false. A new list that loads
  gets its `loading()` and its shape.
- **A barber is chosen by their face** (`fillBarberChoice`): the owner's picture (`PUT /barbers/{id}/photo`,
  served under `/media` like a course's) or the first letter on a colour of its own, drawn by CSS from
  `data-initial` so the pill's words stay the name alone. The face is `aria-hidden`.
- **What the page says floats** (`say()`): a dark pill over the foot of the screen that fades after `SAY_FOR`.
  Faded, never removed, and never `display:none` even when empty - a live region a screen reader cannot
  find when its words arrive is not read out. Its mark (`✓`, `!`) has empty alternative text.
- **The staff's day sits above the diary** (`renderToday`, `drawTimeline`): four cards and today by its hours,
  read from the list the diary already holds. A summary only - the list under it keeps every booking and its
  buttons; the timeline is `aria-hidden`, and a tap on a block takes the eye to the row. The staff see who is
  coming: `customer_name` in a booking's view (a customer only ever sees their own).
- **Motion is extra, all of it inside `@media (prefers-reduced-motion: no-preference)`**, and the confetti
  checks the same in script. Nothing waits for an animation to end, and nothing is shown only by one.
  The outside page tests run without motion; `test_fresh_look.py` asks for it.

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
