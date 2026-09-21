/* WoazeWeather: kleiner Dienst (Service Worker).
   Er tut absichtlich fast nichts: Jede Anfrage geht direkt ins Netz, es wird NICHTS
   zwischengespeichert. So zeigt die App immer den aktuellen Stand, und es gibt keine
   veralteten Wetterdaten. Er ist nur da, weil Chrome auf Android eine Seite erst dann
   als "App" zum Installieren anbietet, wenn ein solcher Dienst angemeldet ist.
   Zustaendig nur fuer handy.html und handy-app.html (Bereich wird beim Anmelden gesetzt). */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", event => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", event => {
  event.respondWith(
    fetch(event.request).catch(() => new Response("Keine Verbindung. Bitte später erneut öffnen.",
      { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8" } }))
  );
});
