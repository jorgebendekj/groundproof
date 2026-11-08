import * as Cesium from 'cesium';
// eoAlerts: clearing alerts as pulsing markers (pattern of the FIRMS / perimeters layers).
export function createEoAlertsLayer({ fetchImpl = (...a) => globalThis.fetch(...a) } = {}) {
  let viewer = null, ds = null;
  const colour = (a) => (a.state === 'confirmed' ? '#e5484d' : a.confidence >= 0.8 ? '#ff7a45' : '#f5a623');
  return {
    id: 'eoAlerts',
    async enable(v) {
      viewer = v;
      const r = await fetchImpl('/api/eo/alerts'); if (!r.ok) return;
      ds = new Cesium.CustomDataSource('eoAlerts');
      for (const a of await r.json()) {
        const c = Cesium.Cartesian3.fromDegrees(...centroid(a.geometry));
        ds.entities.add({ id: `eo-alert:${a.id}`, position: c, point: { pixelSize: 12, color: Cesium.Color.fromCssColorString(colour(a)), outlineColor: Cesium.Color.WHITE, outlineWidth: 2 },
          description: `Alert #${a.id} ${a.type}<br>confidence ${a.confidence}<br>first seen ${a.first_seen.slice(0, 10)}<br>~${a.details.clearing_ha} ha` });
      }
      await viewer.dataSources.add(ds);
    },
    disable() { if (ds) viewer.dataSources.remove(ds, true); ds = null; },
  };
}
function centroid(g) { const ring = g.type === 'Polygon' ? g.coordinates[0] : g.type === 'Point' ? [g.coordinates] : g.coordinates[0][0];
  return [ring.reduce((s, p) => s + p[0], 0) / ring.length, ring.reduce((s, p) => s + p[1], 0) / ring.length]; }
