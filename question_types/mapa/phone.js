// Phone side of the map question: tap to drop a pin, then confirm.
import { loadGoogleMaps, pinIcon, MAP_STYLE } from "./gmaps.js";

export function renderPhone(canvas, q, ctx) {
  const { h } = ctx;
  const box = h("div.qt-map-box", h("p.qt-map-msg", "Cargando mapa…"));
  const confirm = h("button.btn.primary.block", { type: "button", disabled: true }, "Confirmar punto");
  canvas.append(h("div.qt-map-phone", box, h("p.qt-map-tip", "Toca el mapa para poner tu marca"), confirm));
  let point = null;
  let marker = null;
  let maps = null;
  let map = null;
  let locked = false;

  const giveUp = (why) => {
    if (locked) return;
    locked = true;
    box.replaceChildren(h("p.qt-map-msg", `No se puede cargar el mapa (${why}). Esta pregunta no te cuenta.`));
    confirm.hidden = true;
    ctx.unavailable(why);
  };
  window.addEventListener("gmaps-auth-failure", () => giveUp("clave rechazada"), { once: true });

  loadGoogleMaps(ctx.mapsKey).then((m) => {
    if (locked) return;
    maps = m;
    box.replaceChildren();
    map = new maps.Map(box, { ...MAP_STYLE, center: { lat: q.data.view.lat, lng: q.data.view.lng }, zoom: q.data.view.zoom });
    map.addListener("click", (ev) => {
      if (locked) return;
      point = { lat: ev.latLng.lat(), lng: ev.latLng.lng() };
      if (!marker) marker = new maps.Marker({ map, icon: pinIcon(maps, ctx.me?.color || "#ffcf5a") });
      marker.setPosition(point);
      confirm.disabled = false;
    });
  }).catch((err) => giveUp(err.message));

  confirm.addEventListener("click", () => {
    if (locked || !point) return;
    locked = true;
    confirm.disabled = true;
    canvas.classList.add("is-locked");
    ctx.submit(point);
  });

  return {
    lock() { locked = true; confirm.disabled = true; canvas.classList.add("is-locked"); },
    reveal(reveal) {
      locked = true;
      confirm.hidden = true;
      const s = reveal.solution;
      if (!maps || !map) return;
      new maps.Marker({ map, position: s.point, icon: pinIcon(maps, "#51cf66", 1.2) });
      if (s.zone.length) new maps.Polygon({ map, paths: s.zone, strokeColor: "#51cf66", fillColor: "#51cf66", fillOpacity: 0.25 });
      else new maps.Circle({ map, center: s.point, radius: s.radius, strokeColor: "#51cf66", fillColor: "#51cf66", fillOpacity: 0.2 });
      const bounds = new maps.LatLngBounds(s.point);
      if (point) bounds.extend(point);
      map.fitBounds(bounds, 40);
    },
    destroy() {},
  };
}
