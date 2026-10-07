// The page's service worker: it only shows a notification when the server says there is news.
// Nothing about a booking travels in the message, so the words are fixed here, by role.
const role = new URL(self.location).searchParams.get("role");
const WORDS = {
  customer: ["עדכון על התור שלך", "פתחו את האפליקציה לפרטים."],
  barber: ["בקשה חדשה ביומן", "יש בקשה שמחכה לאישור שלך."],
};

// The push itself carries no words. When the shop left some for this browser - a reminder - they are
// fetched, with this browser's own push address as the proof of who is asking, and given once; otherwise the
// fixed wording above is shown.
async function words() {
  const [title, body] = WORDS[role] || WORDS.customer;
  try {
    const subscription = await self.registration.pushManager.getSubscription();
    if (subscription) {
      const answer = await fetch("/push/notice", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ endpoint: subscription.endpoint }),
      });
      const notice = answer.ok ? await answer.json() : null;
      if (notice && notice.title) return [notice.title, notice.body];
    }
  } catch {}
  return [title, body];
}

self.addEventListener("push", (event) => {
  event.waitUntil(
    words().then(([title, body]) => self.registration.showNotification(title, { body, lang: "he", dir: "rtl", tag: role || "customer" })),
  );
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
