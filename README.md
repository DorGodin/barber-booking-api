# Barber Booking API

A small, real appointment booking API for a barbershop: barbers, services, working hours,
availability, bookings and cancellations.

It exists to be tested **from the outside**. It has no test hooks — no reset endpoint, no
back door — so a test framework pointed at it has to work the way it would against any
real product. Its companion is [qa-api-starter](https://github.com/DorGodin/qa-api-starter).

[עברית למטה](#עברית)

---

## Start

```bash
cp .env.example .env
make install
make run
```

Open **http://127.0.0.1:8100** for the booking page — sign in as the seeded customer, pick a
barber, a service and a day, and book. The API's interactive docs are at
http://127.0.0.1:8100/docs.

The first start creates three accounts, with the passwords from `.env`:

| Username | Role | Can |
|---|---|---|
| `owner` | owner | everything: services, barbers, hours, time off, cancel any booking |
| `barber` | barber | see the bookings on their own schedule |
| `customer` | customer | book, see and cancel their own bookings |

Anyone can sign up as another customer with `POST /customers`.

---

## The rules

These are what makes a booking product hard to get right — and what is worth testing.

| Rule | Refused with |
|---|---|
| Two customers cannot book overlapping times with the same barber — even when they press "Book" in the same second | `409 slot_taken` |
| A customer cannot be in two chairs at once, even with two different barbers | `409 customer_overlap` |
| A booking must fit entirely inside the barber's working hours. Closing at 19:00, a 30 minute haircut can start at 18:30, not 18:45 | `422 outside_hours` |
| Back-to-back is allowed: 10:00–10:30 and 10:30–11:00 do not overlap | — |
| Bookings start on the quarter hour | `422 not_aligned` |
| A start time must carry a UTC offset. `10:00` alone means a different moment in every time zone | `422` |
| Not in the past, and at most 60 days ahead | `422 in_past` / `beyond_window` |
| Nothing on a barber's day off | `422 barber_off` |
| A customer can cancel up to 24 hours before. The owner can cancel any time | `409 late_cancellation` |
| A double tap with the same `Idempotency-Key` books once | the first booking, again |
| Changing a price does not change bookings already made | — |
| Somebody else's booking is *not found*, not *forbidden* — a 403 would confirm it exists | `404` |

Every refusal is `{"detail": "...", "code": "..."}`. Branch on `code`; the wording can change.

**Daylight saving is handled, not assumed.** Opening hours are local time, and slots are
computed as real UTC instants between local opening and closing. So the spring-forward day
has 23 hours and no 02:30, the fall-back day has 25 hours and 01:30 twice, and 09:00 opening
is 06:00 UTC in summer and 07:00 UTC in winter. Every booking shows both `start` (UTC) and
`start_local` (with its offset).

---

## Endpoints

| Method | Path | Who |
|---|---|---|
| POST | `/auth/token` | anyone |
| POST | `/customers` | anyone — sign up |
| GET | `/me` | signed in |
| GET | `/services` | signed in |
| POST / PATCH | `/services`, `/services/{id}` | owner |
| GET | `/barbers` | signed in |
| POST | `/barbers` | owner |
| GET / PUT | `/barbers/{id}/hours` | signed in / owner |
| POST / DELETE | `/barbers/{id}/time-off`, `/barbers/{id}/time-off/{date}` | owner |
| GET | `/barbers/{id}/availability?date=&service_id=` | signed in |
| POST | `/bookings` | customer |
| GET | `/bookings`, `/bookings/{id}` | signed in — each sees only their own |
| POST | `/bookings/{id}/cancel` | the customer who booked, or the owner |
| GET | `/shop` | anyone — the shop's time zone, today on its clock, the window and the cutoff |
| GET | `/` | anyone — the booking page |
| GET | `/health` | anyone |

---

## Tests

```bash
make test
```

The product's own tests: the scheduling rules including both DST transitions, the booking
rules through the API, and a **race against a real server running two worker processes** —
twelve customers booking one slot at once must produce exactly one booking, eleven clean
refusals, and not a single server error.

The deep QA suites live in qa-api-starter, which tests this API the way it would test any
product: through its URL, and nothing else.

---

## How it prevents double booking

A booking is check-then-insert: is the slot free? then take it. Two requests can both check,
both see it free, and both take it. So the check and the insert run inside one database
transaction that takes the write lock **at its start** (`BEGIN IMMEDIATE`). The second
request waits, and its check then sees the first request's booking.

A lock in Python memory would not do: it protects one process, and the server runs two.

---

<a id="עברית"></a>

## עברית

API קטן ואמיתי לקביעת תורים במספרה: ספרים, שירותים, שעות עבודה, זמינות, הזמנות וביטולים.

הוא קיים כדי שיבדקו אותו **מבחוץ**. אין בו שום "קיצור" לבדיקות — אין endpoint לאיפוס, אין
דלת אחורית — כך שתשתית בדיקות שמופנית אליו צריכה לעבוד בדיוק כמו מול כל מוצר אמיתי. התשתית
שבודקת אותו היא [qa-api-starter](https://github.com/DorGodin/qa-api-starter).

### הפעלה

```bash
cp .env.example .env
make install
make run
```

פותחים את **http://127.0.0.1:8100** כדי להגיע למסך ההזמנה — מתחברים כלקוח, בוחרים ספר, שירות
ויום, ומזמינים. התיעוד האינטראקטיבי של ה-API נמצא ב-http://127.0.0.1:8100/docs.

בהפעלה הראשונה נוצרים שלושה משתמשים, עם הסיסמאות מ-`.env`: `owner` (בעלים — הכל), `barber`
(ספר — רואה את התורים שלו) ו-`customer` (לקוח — מזמין, רואה ומבטל את התורים שלו). כל אחד יכול
להירשם כלקוח נוסף דרך `POST /customers`.

### החוקים

אלה הדברים שעושים מוצר של תורים לקשה — ושכדאי לבדוק:

| חוק | נדחה עם |
|---|---|
| שני לקוחות לא יכולים לקבוע זמנים חופפים אצל אותו ספר — גם כשהם לוחצים "הזמן" באותה שנייה | `409 slot_taken` |
| לקוח לא יכול לשבת בשני כיסאות בבת אחת, גם אצל שני ספרים שונים | `409 customer_overlap` |
| תור חייב להיכנס כולו לשעות העבודה. סוגרים ב-19:00? תספורת של 30 דקות מתחילה ב-18:30, לא ב-18:45 | `422 outside_hours` |
| תור צמוד לתור מותר: 10:00–10:30 ו-10:30–11:00 לא חופפים | — |
| תורים מתחילים ברבע שעה | `422 not_aligned` |
| שעת התחלה חייבת לכלול הפרש מ-UTC. "10:00" לבד זה רגע אחר בכל אזור זמן | `422` |
| לא בעבר, ולכל היותר 60 יום קדימה | `422 in_past` / `beyond_window` |
| שום תור ביום חופש של הספר | `422 barber_off` |
| לקוח יכול לבטל עד 24 שעות לפני. הבעלים יכול לבטל תמיד | `409 late_cancellation` |
| לחיצה כפולה עם אותו `Idempotency-Key` מזמינה פעם אחת | ההזמנה הראשונה, שוב |
| שינוי מחיר לא משנה הזמנות שכבר נעשו | — |
| הזמנה של מישהו אחר *לא נמצאה*, ולא *אסורה* — 403 היה מאשר שהיא קיימת | `404` |

כל דחייה מחזירה `{"detail": "...", "code": "..."}`. מחליטים לפי `code`; הניסוח יכול להשתנות.

**שעון קיץ מטופל, לא מנוחש.** שעות הפתיחה הן בשעון המקומי, והתורים מחושבים כרגעים אמיתיים
ב-UTC בין הפתיחה לסגירה. לכן ביום המעבר לשעון קיץ יש 23 שעות ואין 02:30, ביום החזרה יש 25
שעות ו-01:30 פעמיים, ופתיחה ב-09:00 היא 06:00 UTC בקיץ ו-07:00 UTC בחורף.

### בדיקות

```bash
make test
```

הבדיקות של המוצר עצמו: חוקי התזמון כולל שני ימי המעבר של שעון קיץ, חוקי ההזמנה דרך ה-API,
ו**מרוץ מול שרת אמיתי שרץ בשני תהליכים** — שנים עשר לקוחות שמזמינים את אותו תור באותו רגע
חייבים לקבל הזמנה אחת בדיוק, אחת עשרה דחיות נקיות, ואף לא שגיאת שרת אחת.

סוויטות ה-QA המעמיקות נמצאות ב-qa-api-starter, שבודק את ה-API הזה כמו שהוא בודק כל מוצר: דרך
הכתובת שלו, ותו לא.

### איך נמנעת הזמנה כפולה

הזמנה היא "בדוק ואז הכנס": האם התור פנוי? אם כן, קח אותו. שתי בקשות יכולות לבדוק יחד, לראות
שהוא פנוי, ולקחת אותו שתיהן. לכן הבדיקה וההכנסה רצות בתוך טרנזקציה אחת שנועלת את מסד הנתונים
**כבר בתחילתה** (`BEGIN IMMEDIATE`). הבקשה השנייה מחכה, והבדיקה שלה כבר רואה את ההזמנה של
הראשונה.

נעילה בזיכרון של פייתון לא הייתה מספיקה: היא מגינה על תהליך אחד, והשרת מריץ שניים.
