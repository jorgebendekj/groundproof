import * as Cesium from 'cesium';
// eoPlots: plot polygons coloured by EUDR status. Follows GEV's layer shape (source -> render -> lifecycle).
export const STATUS_COLOURS = {
  compliant: '#2ecc71', at_risk: '#f5a623', cleared_after_2020: '#e5484d', undetermined: '#8e9aaf', unchecked: '#3b4a66',
};
export function createEoPlotsSource({ fetchImpl = (...a) => globalThis.fetch(...a) } = {}) {
  return { async getSnapshot() { const r = await fetchImpl('/api/eo/plots.geojson'); if (!r.ok) throw new Error('eo_plots_unavailable'); return r.json(); } };
}
export function createEoPlotsLayer({ source }) {
  let viewer = null, ds = null, enabled = false;
  async function refresh() {
    const snap = await source.getSnapshot();
    const next = await Cesium.GeoJsonDataSource.load(snap, { clampToGround: true });
    for (const e of next.entities.values) {
      const c = Cesium.Color.fromCssColorString(STATUS_COLOURS[e.properties.status?.getValue()] ?? STATUS_COLOURS.unchecked);
      if (e.polygon) { e.polygon.material = c.withAlpha(0.55); e.polygon.outline = true; e.polygon.outlineColor = c; }
    }
    if (ds) viewer.dataSources.remove(ds, true);
    ds = next; await viewer.dataSources.add(ds);
  }
  return {
    id: 'eoPlots',
    async enable(v) { viewer = v; enabled = true; await refresh(); },
    disable() { enabled = false; if (ds) { viewer.dataSources.remove(ds, true); ds = null; } },
    refresh, isEnabled: () => enabled,
  };
}
