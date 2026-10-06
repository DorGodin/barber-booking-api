# Barber Booking API

[![ci](https://github.com/DorGodin/barber-booking-api/actions/workflows/ci.yml/badge.svg)](https://github.com/DorGodin/barber-booking-api/actions/workflows/ci.yml)

A small, real appointment booking system for a barbershop: an API and a booking page in Hebrew,
for a phone as much as a desktop. Customers book and cancel; the owner runs the shop — barbers,
working hours, days off, services and prices. It has no test hooks and no back door, so it is
tested from the outside, by [qa-api-starter](https://github.com/DorGodin/qa-api-starter),
exactly as a real product would be.

![Two customers go for the same free time; the first is booked, the second is told it has just gone](docs/media/race.gif)

[עברית למטה](#עברית)

---

## Start

1. Copy the settings and install:

   ```bash
   cp .env.example .env
   make install
   ```

2. Run it:

   ```bash
   make run
   ```

3. Open **http://127.0.0.1:8100** and sign in. The first start creates the shop, with the
   passwords from `.env`:

   | Username | Who |
   |---|---|
   | `owner` | the owner — the same page becomes the management screen |
   | `barber`, `barber.yossi`, `barber.moran`, `barber.ron` | four barbers, each on their own days |
   | `customer`, `yael` | two customers, nothing booked |

   Try it: sign in as `customer` in one window and `yael` in another, pick the same time in
   both, and press book in each — one is booked, the other is told the time has just gone.

The API's interactive docs are at http://127.0.0.1:8100/docs.

## The main rules

- The shop is open Sunday to Thursday, 10:00–19:00; a booking fits inside a barber's hours.
- No two customers in one chair at once — even when they press book in the same second.
- A customer holds at most two bookings ahead, moves one to another free time and cancels
  up to 12 hours before (inside that, the page links to the shop's WhatsApp). The owner can always move and cancel.
- A barber who leaves is made inactive by the owner: offered to no one and signed in nowhere,
  with their bookings kept for the owner to cancel.
- The owner also books, by name, someone who phoned or walked in - into the same diary, under
  the same rules.
- Sign-in is limited after repeated wrong passwords; one address makes at most five accounts an hour.

Every refusal answers with a stable `code`, and the page shows it in Hebrew.

## Tests

```bash
make test
```

The product's own tests, including races against a real server with two worker processes.
The outside suites — API, pages on three screens, journeys, load — are in
[qa-api-starter](https://github.com/DorGodin/qa-api-starter). They run against a second copy,
so they never touch yours:

```bash
make run-test     # http://127.0.0.1:8101, with its own database
```

`make reset-db` empties your copy and `make reset-test-db` the test copy — each only while its
server is stopped.

## Backups

```bash
make backup                  # a copy of your database - safe while the server runs
make restore from=<file>     # put one back; stop the server first. Without from=, lists them
```

A copy is also taken by itself before an upgrade changes the database. They are kept in
`backups/` next to the database, the newest ten.

## Before going live

Set these in `.env`:

- `SECRET_KEY` — a new random value of at least 32 characters.
- `FORWARDED_ALLOW_IPS` — the address of the proxy in front of the server, so the limits count
  each client's own address.
- `ACCESSIBILITY_*` — the shop's real contact and premises for the accessibility statement at
  `/accessibility`.
- Copy `backups/` off the machine regularly — a backup on the same disk is lost with it.

`CLAUDE.md` holds the rules the code follows, and `docs/pitfalls.md` the mistakes behind them.

---

<a id="עברית"></a>

## עברית

מערכת קטנה ואמיתית לקביעת תורים במספרה: API ומסך הזמנה בעברית, לטלפון בדיוק כמו למחשב. לקוחות קובעים
ומבטלים; בעל המספרה מנהל את המספרה — ספרים, שעות עבודה, ימי חופש, שירותים ומחירים. אין בה "קיצורים"
לבדיקות ואין דלת אחורית, ולכן בודקים אותה מבחוץ, עם [qa-api-starter](https://github.com/DorGodin/qa-api-starter),
בדיוק כמו מוצר אמיתי.

### איך מתחילים

1. מעתיקים את ההגדרות ומתקינים:

   ```bash
   cp .env.example .env
   make install
   ```

2. מפעילים:

   ```bash
   make run
   ```

3. פותחים את **http://127.0.0.1:8100** ומתחברים. בהפעלה הראשונה נוצרת המספרה, עם הסיסמאות מ-`.env`:

   | שם משתמש | מי |
   |---|---|
   | `owner` | בעל המספרה — אותו מסך הופך למסך הניהול |
   | `barber`, `barber.yossi`, `barber.moran`, `barber.ron` | ארבעה ספרים, כל אחד בימים שלו |
   | `customer`, `yael` | שתי לקוחות, בלי תורים |

   נסו: מתחברים כ-`customer` בחלון אחד וכ-`yael` בחלון אחר, בוחרים את אותה שעה בשניהם ולוחצים "קביעת
   התור" בכל אחד — אחת מקבלת את התור, והשנייה הודעה שהשעה בדיוק נתפסה.

התיעוד האינטראקטיבי של ה-API נמצא ב-http://127.0.0.1:8100/docs.

### החוקים העיקריים

- המספרה פתוחה בימים א׳–ה׳, 10:00–19:00; תור חייב להיכנס בשעות העבודה של הספר.
- אין שני לקוחות באותו כיסא באותו זמן — גם כשהם לוחצים באותה שנייה.
- לקוח מחזיק לכל היותר שני תורים קדימה, יכול להזיז תור לשעה פנויה אחרת ולבטל עד 12 שעות
  לפני (אחרי זה הדף מפנה לוואטסאפ של המספרה). בעל המספרה יכול להזיז ולבטל תמיד.
- ספר שעזב מסומן כלא פעיל: הוא לא מוצע לאף אחד ולא יכול להתחבר, והתורים שלו נשארים לבעל המספרה לטפל בהם.
- בעל המספרה קובע גם תור בשם, למי שהתקשר או נכנס מהרחוב - לאותו יומן ובאותם חוקים.
- הכניסה נחסמת אחרי סיסמאות שגויות חוזרות; מכתובת אחת נפתחים לכל היותר חמישה חשבונות בשעה.

כל סירוב מחזיר `code` קבוע, והמסך מציג אותו בעברית.

### בדיקות

```bash
make test
```

הבדיקות של המוצר עצמו, כולל מרוצים מול שרת אמיתי עם שני תהליכים. הסוויטות החיצוניות — API, מסכים בשלושה
מכשירים, מסעות מקצה לקצה ועומס — נמצאות ב-[qa-api-starter](https://github.com/DorGodin/qa-api-starter).
הן רצות מול עותק שני, כך שהן אף פעם לא נוגעות בשלכם:

```bash
make run-test     # http://127.0.0.1:8101, עם מסד נתונים משלו
```

`make reset-db` מרוקן את העותק שלכם ו-`make reset-test-db` את עותק הבדיקות — כל אחד רק כשהשרת שלו כבוי.

### גיבויים

```bash
make backup                  # עותק של מסד הנתונים שלכם - בטוח גם כשהשרת רץ
make restore from=<file>     # מחזיר עותק; קודם עוצרים את השרת. בלי from= מוצגת רשימת העותקים
```

עותק נלקח גם לבד, לפני ששדרוג משנה את מסד הנתונים. העותקים נשמרים ב-`backups/` ליד מסד הנתונים, עשרת
האחרונים.

### לפני שעולים לאוויר

מגדירים ב-`.env`:

- `SECRET_KEY` — ערך אקראי חדש, באורך 32 תווים לפחות.
- `FORWARDED_ALLOW_IPS` — הכתובת של ה-proxy שלפני השרת, כדי שההגבלות יספרו את הכתובת של כל לקוח.
- `ACCESSIBILITY_*` — פרטי הקשר ותיאור המקום האמיתיים של המספרה, להצהרת הנגישות ב-`/accessibility`.
- מעתיקים את `backups/` למקום אחר באופן קבוע — גיבוי על אותו דיסק הולך לאיבוד יחד איתו.

`CLAUDE.md` מחזיק את הכללים שהקוד עוקב אחריהם, ו-`docs/pitfalls.md` את הטעויות שמאחוריהם.
