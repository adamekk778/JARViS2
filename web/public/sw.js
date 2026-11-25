// 3.18 JARVIS on the iPhone home screen (and any browser): JARVIS's notices as notifications (Web Push). The page
// subscribes once; the PC encrypts each notice for this device only. Nothing else is cached or intercepted here.
self.addEventListener("push", (event) => {
  let d = {};
  try { d = event.data ? event.data.json() : {}; } catch { d = { title: "JARVIS", body: event.data ? event.data.text() : "" }; }
  event.waitUntil(self.registration.showNotification(d.title || "JARVIS", {
    body: d.body || "", icon: "icons/jarvis-256.png", badge: "icons/jarvis-256.png", data: { url: d.url || "./mobile" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "./mobile";
  event.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const c of all) { if ("focus" in c) return c.focus(); }
    return self.clients.openWindow(url);
  })());
});
