// The page's service worker: it only shows a notification when the server says there is news.
// Nothing about a booking travels in the message, so the words are fixed here, by role.
const role = new URL(self.location).searchParams.get("role");
const WORDS = {
  customer: ["עדכון על התור שלך", "פתחו את האפליקציה לפרטים."],
  barber: ["בקשה חדשה ביומן", "יש בקשה שמחכה לאישור שלך."],
};

self.addEventListener("push", (event) => {
  const [title, body] = WORDS[role] || WORDS.customer;
  event.waitUntil(self.registration.showNotification(title, { body, lang: "he", dir: "rtl", tag: role || "customer" }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((open) => {
      const page = open.find((w) => new URL(w.url).pathname === "/");
      return page ? page.focus() : self.clients.openWindow("/");
    }),
  );
});
