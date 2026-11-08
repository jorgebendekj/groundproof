import * as Cesium from 'cesium';
// eoImagery: before/after previews draped on the globe (pattern of recentImagery). In STAC mode, point the
// template at TiTiler (EO_TITILER_URL) instead of the preview endpoint.
export function createEoImageryLayer() {
  let viewer = null, layers = [];
  return {
    id: 'eoImagery',
    async show(v, alert, which = 'after') {
      viewer = v; this.clear();
      const ring = (alert.geometry.type === 'Polygon' ? alert.geometry.coordinates[0] : alert.geometry.coordinates[0][0]);
      const xs = ring.map((p) => p[0]), ys = ring.map((p) => p[1]);
      const rect = Cesium.Rectangle.fromDegrees(Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys));
      const provider = await Cesium.SingleTileImageryProvider.fromUrl(`/api/eo/alerts/${alert.id}/preview/${which}`, { rectangle: rect });
      layers.push(viewer.imageryLayers.addImageryProvider(provider));
    },
    clear() { layers.forEach((l) => viewer.imageryLayers.remove(l)); layers = []; },
  };
}
