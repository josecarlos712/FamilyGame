// TV side of the map question: during the question a hint; at reveal, the answer and every pin.
import { loadGoogleMaps, pinIcon, MAP_STYLE } from "./gmaps.js";

export function renderTV(canvas, q, ctx) {
  const { h, avatar } = ctx;
  const box = h("div.qt-map-box.qt-map-tv", h("p.qt-map-msg", "📍 Señalad el sitio en el mapa de vuestro móvil"));
  const legend = h("div.qt-map-legend");
  canvas.append(h("div.qt-map-wrap", box, legend));

  return {
    async reveal(reveal, players) {
      const s = reveal.solution;
      for (const [pid] of Object.entries(reveal.answers)) {
        const player = players.find((p) => p.id === pid);
        const res = reveal.results[pid];
        if (player) legend.append(h("div.qt-map-row", { class: res?.correct ? "is-good" : "" }, avatar(player, 44), h("span", res?.detail || "")));
      }
      let maps;
      try {
        maps = await loadGoogleMaps(ctx.mapsKey);
      } catch {
        box.replaceChildren(h("p.qt-map-msg", "Mapa no disponible en la tele"));
        return;
      }
      box.replaceChildren();
      const map = new maps.Map(box, { ...MAP_STYLE, zoomControl: false, center: s.point, zoom: q.data.view.zoom });
      new maps.Marker({ map, position: s.point, icon: pinIcon(maps, "#51cf66", 1.4) });
      if (s.zone.length) new maps.Polygon({ map, paths: s.zone, strokeColor: "#51cf66", fillColor: "#51cf66", fillOpacity: 0.25 });
      else new maps.Circle({ map, center: s.point, radius: s.radius, strokeColor: "#51cf66", fillColor: "#51cf66", fillOpacity: 0.2 });
      const bounds = new maps.LatLngBounds(s.point);
      for (const [pid, pos] of Object.entries(reveal.answers)) {
        const player = players.find((p) => p.id === pid);
        if (!player) continue;
        new maps.Marker({ map, position: pos, icon: pinIcon(maps, player.color, 1.2), title: player.name });
        bounds.extend(pos);
      }
      map.fitBounds(bounds, 80);
    },
    destroy() {},
  };
}
