# Design: TomGoldin Hair Design

The look of the booking page and the owner's screen, as approved on 2026-10-02, with the
name and the sign-in changed on 2026-10-03. Not built
yet. Every Hebrew string below is the exact text on the screen.

## Identity

| What | Decision |
|---|---|
| Brand | `TomGoldin` large, `HAIR DESIGN` under it in small, widely spaced capitals. Marked `lang="en" dir="ltr"`. Shown, with the line under it, on **every** screen, sign-in and code included. |
| Under the brand | `מאז 1991 · שביט 8, נס ציונה` in dark gold `#8a6a1f`. |
| Divider | A dashed black line with small scissors at its start (the right edge). The scissors open and close gently. |
| Decoration | A turning barber pole (red `#a8323a`, white, blue `#2f4a7a`) down **both** sides of every screen, turning in opposite directions. 12px on a phone, 22px on a computer. |
| Settings | Brand, tagline, year and address come from `.env` (`SHOP_BRAND`, `SHOP_TAGLINE`, `SHOP_SINCE`, `SHOP_ADDRESS`), never hard-coded. The tab title is `TomGoldin Hair Design`, and the accessibility statement uses the same values. A value with spaces - the address - is set in the server's environment (`SHOP_ADDRESS='שביט 8, נס ציונה' make run`), not in `.env`, which `make` reads as shell. |

## Colour and type

- White background; black (`#111`) buttons and black for anything selected (barber, day, time).
- Greys for supporting text (`#6b655a`); taken or withdrawn items dashed and struck through.
- `מאושר` is a green chip (`#e6f2e8` / `#1f5a2c`).
- Headings and the brand: **Suez One**. Everything else: **Assistant**. Both are bundled with
  the page (OFL), never loaded from Google - the page's CSP stays `font-src 'self'`.
- Every pair passes WCAG 2.2 AA; light gold is never used for text.

## Motion

The poles and the scissors stop under `prefers-reduced-motion: reduce`. All decoration is
`aria-hidden`.

## Customer screens

- **Booking**: `כמו בפעם הקודמת?` (same service with the same barber, next free time, one tap
  `קביעה`) · barbers as pill buttons with the full name (`טום`, `גולדה`, `גולדין`, `וטר` -
  not initials: גולדה and גולדין share four letters) · days as a list with the number free
  (`מלא` when none) · times · a black `קביעת התור` bar fixed at the bottom with day, time and
  price.
- **Tabs** (approved 2026-10-04): on a customer's phone, two tabs fixed at the foot of the
  screen - `קביעת תור` and `התורים שלי` - one at a time instead of one long page. A new booking
  or a changed time shows its card, whose `התורים שלי` opens the list with the focus on it;
  `שינוי מועד` goes back to booking.
  A tab the customer presses wins over a focus still waiting for the list. A computer keeps the
  two side by side with no tabs; the owner and the barbers have no tabs.
- **My bookings** (`התורים שלי`): one card per booking, `שינוי מועד` and `ביטול` under it; a
  cancelled one faded and struck through. A cancelled booking is shown for twelve hours after
  the cancellation (approved 2026-10-05): one the customer cancelled leaves with the app -
  signing out, closing the tab - and one the shop cancelled stays the twelve hours however
  often they come back, since it is news to them (the booking says who cancelled it:
  `cancelled_by`, `customer` or `staff`). The line after cancelling is red.
- **Changing a booking's time**: a banner `שינוי מועד לתור של …` with `השארת המועד הקיים`; the
  barber locked, the others dimmed; the button `אישור המועד החדש`; success `✓ המועד עודכן`;
  the 12-hour refusal `אפשר לשנות מועד עד 12 שעות לפני`.
- **Sign-in** (replaces username and password, and sign-up): `ברוכים הבאים`, `שם מלא`,
  `מספר טלפון` (digits only, written `0501234567`; spaces and dashes typed in are removed),
  the button `שולחים קוד`, and under it `קוד קצר ב־SMS, ואת/ה כבר בדרך לכיסא.` The first
  sign-in opens the account; there is no separate sign-up.
- **The password form** (approved 2026-10-04): `כניסה עם שם משתמש וסיסמה`, folded under the
  code form, stays for the accounts that already have one - the owner, the barbers, the seeded
  and the test accounts. The `פעם ראשונה כאן?` form (name, username, password, `יצירת חשבון`)
  is gone from the page: a first-time customer signs in with a code. `POST /customers` stays in
  the API, with its limit of five accounts an hour from one address.
- **Verification code** (straight after sign-in): `קוד אימות`, `שלחנו קוד בן 4 ספרות למספר
  שמסתיים ב־4567` (the last four digits only), four boxes, the button `לכיסא` (read to a screen
  reader as `לכיסא, כניסה לחשבון`), `עוד קוד, בבקשה` with a countdown until it is allowed, and
  `החלפת מספר`.
- **Wrong code**: the boxes red, `הקוד לא נכון. נשארו 2 ניסיונות.`, and `לכיסא` disabled -
  with `מתקנים ספרה, והכפתור חוזר לפעול` under it - while the boxes hold the code just
  refused; it comes back the moment a digit changes. After the third wrong code it stays
  disabled until a new code is sent. The disabled state is announced, with the reason.
- **Code rules**: 4 digits, valid 5 minutes, 3 attempts per code, a new code at most once a
  minute, and a cap per phone and per address so nobody can run up the SMS bill. Sent through
  a configurable provider; a fake provider outside the product serves development and the
  tests until a real one is chosen.
- **Refusal window** (approved 2026-10-05, replaces the red band): a small white card, modal, with
  a red mark, a title, the reason in grey, and the way on. Too many bookings - `נראה שכבר קבעת
  מספיק`, `אפשר להחזיק עד 2 תורים קדימה. כדי לפנות מקום, אפשר לבטל אחד מהם.` - a black
  `התורים שלי` over a grey `סגירה`. A taken time - `מישהו הקדים אותך`, `14:00 נתפסה לפני
  רגע. אפשר לבחור שעה אחרת.` - one black button, `בחירת שעה אחרת`. A reason the page knows
  but has no title of its own for keeps `לא הצלחנו לקבוע את התור`; one nobody planned for is
  `אוי, משהו השתבש`, `לא הצלחנו להשלים את הפעולה. אפשר לנסות שוב בעוד רגע.` The wording is
  neutral between a man and a woman, as the rest of the page is. The reason is not repeated
  in red behind the card.
- **Nothing booked**: a chair icon, `עוד אין תורים`, `הכיסא מחכה לך`.
- **The month's calendar** (approved 2026-10-03, replaces the date field): one month, Sunday
  first, with the previous and next month buttons - only inside the booking window. A day with
  a free time is framed and has a gold dot; a day with none - full, not worked, or outside the
  window - is grey (approved 2026-10-04), and its name tells a screen reader which. Only a free day can be chosen; the chosen day
  is black. A screen reader hears each day's date and its state - `7 שעות פנויות`, `מלא`,
  `הספר לא עובד ביום הזה`, `לא ניתן לקבוע`. The keyboard follows the WAI-ARIA date picker
  (arrows, left is the next day; Page Up/Down a month; Enter or Space chooses). The screen
  opens on the first free day of the month when today has none. Counts come from
  `GET /barbers/{id}/days?month=YYYY-MM&service_id=…`, computed by the same rule as the day's
  own times, so a day called free always has a time.
  The same holds after a change of barber or service: a chosen day with no time with the new
  choice gives way to the first free day of the month shown (approved 2026-10-04).
- **How far ahead** (approved 2026-10-03): a month at most - `BOOKING_WINDOW_DAYS=30` - and
  never a day already over; the calendar neither offers nor turns to either.
- **Friday** (approved 2026-10-03): the shop opens Friday ten to two. A new barber starts on
  Sunday to Thursday 10:00-19:00 and Friday 10:00-14:00; the owner changes it per barber. An
  existing database keeps each barber's saved hours - the owner opens Friday from the hours
  table.
- **Barbers** (built 2026-10-04): pills by full name, a radio group - one Tab stop, the
  arrows move and choose. Black when chosen; in the owner's list a barber who left is dashed
  and marked `(לא פעיל)`. Locked while a booking's time is being changed.
- **Times** (approved 2026-10-04): pills, five to a row and 36px tall on a phone - below
  Apple's 44px for a finger, above WCAG 2.5.8's 24px, chosen so a day's times fit the screen.
- **Greeting** (approved 2026-10-03): a customer is greeted `שלום` and their first name; the
  account keeps the full name. The staff keep their name and role (`· בעלים`, `· ספר`).
- **Signing out** (approved 2026-10-05): `יציאה` is a small, faded pill beside the greeting - a
  light grey `#f1efea` with the page's muted text colour (5.0:1), no border, 13px - not a framed
  button. It is painted 34px tall inside a 44px target, so it is quiet to look at and still a
  finger's size to press. The same for the owner and the barbers.
- **Booked** (approved 2026-10-05, replaces the popup): a card in the booking panel in place of
  the form - a green tick, `התור נקבע` (`המועד עודכן` for a moved time), the day and time, the
  service with the barber and the price, and two buttons: `התורים שלי` (black) and `קביעת תור
  נוסף` (grey). The focus goes to its heading. The card alone announces it - no second line
  `נקבע: …` under the list (approved 2026-10-03). A refusal still answers in a modal popup, red;
  so does the owner's booking for a caller.
- **Computer**: one screen split in two - the choice on the right, my bookings and the book
  button on the left.
- **The foot of the page** (approved 2026-10-04): the cut line, the shop's contact buttons and
  the links `הצהרת נגישות` and `מדיניות פרטיות` stand at the bottom of the screen when the page
  is shorter than the screen, never in the middle of it; on a longer page they follow the
  content. On a customer's phone, signed in (approved 2026-10-05), the two links are not shown
  on either tab: the shop's contact buttons, if the owner set any, stay at the foot of
  `קביעת תור`, and with none the foot is gone. `התורים שלי` has no foot at all, the tab bar
  standing under a short list. A computer and the signed-out screens keep the links - the
  statement and the policy are one step away from the sign-in screen.

## From the shop's Calmark page (approved 2026-10-03)

1. **Business header** on the customer's booking screen: a cover photo of the shop, a round
   profile picture over its edge, the brand, the line under it, and five round action buttons
   - WhatsApp, phone, Instagram, TikTok, Waze. Every link, number and image comes from the
   owner's settings; a button with no value is not shown. Each button has a Hebrew name for a
   screen reader (`וואטסאפ`, `התקשרות`, `אינסטגרם`, `טיקטוק`, `ניווט ב־Waze`). The images are the
   shop's own, supplied by the owner - never copied from the old page.
   Scrolled, the header shrinks to a **slim bar** at the top - 52px, white as the page, with no
   line under it, the brand alone - so the round picture slides under it instead of being cut in
   half. It slides in and out; it never fades, and it stands still for reduced motion. The owner's
   sticky menu stands under it (approved 2026-10-03; a black top band and a fully sticky header
   were both turned down - the second took two thirds of the screen above the keyboard).
2. **Services in categories** (`תספורות`, `זקן וגילוח`, `מיוחדים` - the owner names them), as
   pill tabs; each service a card with its name, a short description, its length and its price,
   or `החל מ־` before a price that can grow. The selected one has a black frame.
3. **A month calendar** for the day: days with room circled in black, full or closed days grey,
   the chosen day filled black; the month changes with arrows; under it the chosen day's times.
   It needs the number of free times per day from the server, in one request for the month.

The rest of the booking screen is as below. All in Hebrew - including what the old page left in
English (`Next`, `Select services`, `Starting from`, English dates).

## Barber screen

`היומן שלי` with `היום` / `מחר` / `השבוע`; each booking shows the time, the customer's name and
the service, a guest marked `(בטלפון)`. Read only, as now.

## Owner screen

- Barbers as pills at the top, one who left dashed `וטר · לא פעיל`, and `+ ספר חדש`.
- Three columns: `קביעת תור בשם` · `היומן של <barber>` with each booking's time, customer and
  service, a guest marked `(בלי חשבון)`, and a day total (`4 תורים · 320 ₪`) · the barber's
  hours with switches, `שמירת השעות`, `+ יום חופש`, and `הוצאה מהפעילות`.
- Services as cards (name, minutes, price, an active switch); a withdrawn one faded.
- On a phone the same sections stack, with the sticky menu `תורים` / `שעות` / `שירותים`.

## New behaviour that comes with it

1. **Customer names in the diary**: the booking view gains the customer's display name, for the
   owner and that booking's barber only - never for another customer.
2. **Barber diary filter**: today / tomorrow / this week.
3. **Owner's day total**: the count and the sum of the confirmed bookings shown.
4. **Like last time**: the customer's latest booking's service and barber, and the next free
   time with them.
5. **Seed barbers** become טום, גולדה, גולדין, וטר (usernames in English, e.g. `barber.tom`).

## The barber's yes for the afternoon (2026-10-06)

A customer's booking that starts from 14:00 up to 16:00 (not including it; shop time) waits for
its barber. The rule is by the hour only, not by service, and is a setting (`APPROVAL_FROM`,
`APPROVAL_UNTIL`, `APPROVAL_WAIT_MINUTES`).

- **The chair is held at once.** The booking is `confirmed` and `approval` is `pending`; nobody
  else can take the time while the barber decides, and it counts toward the two bookings ahead.
- **No answer, a yes.** After two hours - or when the booking starts, if that is sooner - a
  pending booking reads `approved`. Computed when it is read: no background job.
- **The barber says yes or no** on the booking row (`אישור` / `דחייה`), the owner for any
  barber. `POST /bookings/{id}/approve` and `/decline`. A no cancels the booking, `cancelled_by`
  is `staff`, and the time is free again. A yes after the wait, or a no after it, is refused.
- **Moving** into those hours makes a customer's booking wait again; out of them ends the wait.
  The owner moving or booking a guest decides it: no wait.
- **The customer is told in the app, not by text message.** The booking card says
  `הבקשה נשלחה`, with an amber note and the time it stands by itself; the list says
  `ממתין לאישור של <barber>`. When the answer comes - the list is read again every 45 seconds
  while one waits, and when the app comes back to the front - a popup says `<barber> אישר את
  התור` or `<barber> לא יכול בשעה הזו`, with `בחירת שעה אחרת`. What the customer last saw waiting
  is kept on the device, so an answer that came while the app was shut is told on opening.
  A push notification to a closed app is a separate step (service worker, VAPID keys, HTTPS).

## Kept as it is

Every `data-testid`, the radio-group times, `aria-busy`, `textContent` for every value from a
user, `isolate()` for names inside Hebrew, and the rules in `CLAUDE.md`.
