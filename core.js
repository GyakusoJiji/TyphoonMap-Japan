(function (root) {
  'use strict';
  const HOUR = 3600000;
  const nearJapan = s => s.points.some(p => p.lat >= 20 && p.lat <= 46 && p.lon >= 120 && p.lon <= 155);
  function category(p) {
    if (p.grade === 2) return {label:'Tropical Depression', color:'#8294b1'};
    if (p.grade === 6) return {label:'Extratropical Cyclone', color:'#8294b1'};
    if (!p.wind) return {label:'Typhoon (wind unknown)', color:'#5ad1c9'};
    if (p.wind >= 105) return {label:'Violent Typhoon', color:'#e67ca8'};
    if (p.wind >= 85) return {label:'Very Strong Typhoon', color:'#ff895a'};
    if (p.wind >= 64) return {label:'Strong Typhoon', color:'#ffca70'};
    return {label:'Typhoon', color:'#5ad1c9'};
  }
  function atTime(storm, t) {
    const ps = storm.points;
    if (t < ps[0].t || t > ps[ps.length - 1].t) return null;
    let lo = 0, hi = ps.length;
    while (lo < hi) { const m = (lo + hi) >>> 1; if (ps[m].t <= t) lo = m + 1; else hi = m; }
    const index = lo - 1, a = ps[index], b = ps[index + 1];
    if (!b) return {...a, index, observation:a};
    const f = (t - a.t) / (b.t - a.t);
    let delta = b.lon - a.lon;
    if (delta > 180) delta -= 360;
    if (delta < -180) delta += 360;
    return {...a, lat:a.lat + (b.lat - a.lat) * f, lon:a.lon + delta * f, index, observation:a};
  }
  const minimum = s => Math.min(...s.points.map(p => p.pressure).filter(p => p !== null));
  const dateJST = t => new Date(t + 9 * HOUR).toISOString().slice(0, 10);
  const formatTime = t => new Date(t + 9 * HOUR).toISOString().slice(0,16).replace('T',' ');
  function parseRange(from, to) {
    const start = Date.parse(from + 'T00:00:00+09:00');
    const end = Date.parse(to + 'T23:59:59.999+09:00');
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) throw new Error('Check the start and end dates.');
    return [start, end];
  }
  const api = {HOUR, nearJapan, category, atTime, minimum, dateJST, formatTime, parseRange};
  if (typeof module !== 'undefined') module.exports = api;
  root.TyphoonCore = api;
})(typeof window !== 'undefined' ? window : globalThis);
