// The page's service worker: it only shows a notification when the server says there is news.
// Nothing about a booking travels in the message, so the words are fixed here, by role.
const role = new URL(self.location).searchParams.get("role");
const WORDS = {
  customer: ["עדכון על התור שלך", "פתחו את האפליקציה לפרטים."],
  barber: ["עדכון ביומן", "תור חדש, בקשה או ביטול - פתחו את היומן."],
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

// With no connection, the shop on a home screen would open on the phone's own error. The worker keeps a page of the
// shop's for that, with its letters, and gives it for any page it cannot fetch. Only that: the shop's pages and its
// answers always come from the server, never from a copy.
const OFFLINE_CACHE = "offline-1";
const OFFLINE_FILES = ["/offline.html", "/fonts/rubik-hebrew.woff2", "/fonts/rubik-latin.woff2"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(OFFLINE_CACHE).then((cache) => cache.addAll(OFFLINE_FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(names.filter((name) => name !== OFFLINE_CACHE).map((name) => caches.delete(name))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  if (event.request.mode === "navigate") {
    event.respondWith(fetch(event.request).catch(() => caches.match("/offline.html")));
  } else if (OFFLINE_FILES.includes(new URL(event.request.url).pathname)) {
    event.respondWith(fetch(event.request).catch(() => caches.match(event.request)));
  }
});

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
