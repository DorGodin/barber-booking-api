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
| Settings | Brand, tagline, year and address come from `.env` (`SHOP_BRAND`, `SHOP_TAGLINE`, `SHOP_SINCE`, `SHOP_ADDRESS`), never hard-coded. The tab title is `TomGoldin Hair Design`, and the accessibility statement uses the same values. |

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
- **My bookings** (`התורים שלי`): one card per booking, `שינוי מועד` and `ביטול` under it; a
  cancelled one faded and struck through.
- **Changing a booking's time**: a banner `שינוי מועד לתור של …` with `השארת המועד הקיים`; the
  barber locked, the others dimmed; the button `אישור המועד החדש`; success `✓ המועד עודכן`;
  the 12-hour refusal `אפשר לשנות מועד עד 12 שעות לפני`.
- **Sign-in** (replaces username and password, and sign-up): `ברוכים הבאים`, `שם מלא`,
  `מספר טלפון` (digits only, written `0501234567`; spaces and dashes typed in are removed),
  the button `שולחים קוד`, and under it `קוד קצר ב־SMS, ואת/ה כבר בדרך לכיסא.` The first
  sign-in opens the account; there is no separate sign-up.
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
- **Refusal window**: a black band with the reason (`השעה כבר תפוסה`), the Hebrew sentence,
  and `בחירת שעה אחרת`.
- **Nothing booked**: a chair icon, `עוד אין תורים`, `הכיסא מחכה לך`.
- **Computer**: one screen split in two - the choice on the right, my bookings and the book
  button on the left.

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

## Kept as it is

Every `data-testid`, the radio-group times, `aria-busy`, `textContent` for every value from a
user, `isolate()` for names inside Hebrew, and the rules in `CLAUDE.md`.
