// Loads the Google Maps JavaScript API once. Rejects if there is no key, no network or the key is refused.
let pending = null;

export function loadGoogleMaps(key, timeoutMs = 10000) {
  if (window.google?.maps?.Map) return Promise.resolve(window.google.maps);
  if (!key) return Promise.reject(new Error("sin clave de Google Maps"));
  if (pending) return pending;
  pending = new Promise((resolve, reject) => {
    const fail = (why) => { pending = null; reject(new Error(why)); };
    const timer = setTimeout(() => fail("tiempo agotado"), timeoutMs);
    window.__familyGameMapsReady = () => { clearTimeout(timer); resolve(window.google.maps); };
    window.gm_authFailure = () => { clearTimeout(timer); fail("clave rechazada"); window.dispatchEvent(new Event("gmaps-auth-failure")); };
    const s = document.createElement("script");
    s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&v=weekly&callback=__familyGameMapsReady`;
    s.async = true;
    s.onerror = () => { clearTimeout(timer); fail("sin conexión"); };
    document.head.append(s);
  });
  return pending;
}

/** A round SVG pin in the given colour. */
export function pinIcon(maps, color, scale = 1) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="36" height="48" viewBox="0 0 36 48"><path d="M18 47C18 47 34 28 34 17A16 16 0 0 0 2 17C2 28 18 47 18 47Z" fill="${color}" stroke="#14151c" stroke-width="3"/><circle cx="18" cy="17" r="6" fill="#14151c"/></svg>`;
  return {
    url: "data:image/svg+xml;charset=UTF-8," + encodeURIComponent(svg),
    scaledSize: new maps.Size(36 * scale, 48 * scale),
    anchor: new maps.Point(18 * scale, 47 * scale),
  };
}

export const MAP_STYLE = { disableDefaultUI: true, zoomControl: true, gestureHandling: "greedy", clickableIcons: false };
