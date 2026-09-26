/* Canvas rendering and playback. No third-party runtime dependencies. */
(() => {
  'use strict';
  const C = TyphoonCore, $ = id => document.getElementById(id);
  const canvas = $('tracks'), ctx = canvas.getContext('2d'), base = $('base'), bg = base.getContext('2d');
  let data = window.TYPHOON_DATA, storms = [], selected = null, start = 0, end = 1, time = 0;
  let playing = false, lastFrame = 0, lastUI = 0, dirty = true, width = 0, height = 0, dpr = 1;
  let scale = 1, center = [138, 30], hits = [], drag = null;
  const JMA_TYPHOON_ROOT = 'https://www.jma.go.jp/bosai/typhoon/data';
  const merc = lat => Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)) * 180 / Math.PI;
  const unmerc = y => (2 * Math.atan(Math.exp(y * Math.PI / 180)) - Math.PI / 2) * 180 / Math.PI;
  const project = (lon, lat) => [(lon - center[0]) * scale + width / 2, (merc(center[1]) - merc(lat)) * scale + height / 2];
  const unproject = (x,y) => [center[0] + (x-width/2)/scale, unmerc(merc(center[1]) - (y-height/2)/scale)];
  const label = s => `${s.year} Typhoon ${s.number}`;
  const minText = s => Number.isFinite(C.minimum(s)) ? `${C.minimum(s)} hPa` : '気圧不明';
  function notice(text) { $('notice').textContent = text; $('notice').hidden = !text; }
  async function fetchJson(url) {
    const response = await fetch(url, {cache:'no-store'});
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return response.json();
  }
  async function fetchCurrentStorms() {
    const targets = await fetchJson(`${JMA_TYPHOON_ROOT}/targetTc.json`);
    const results = await Promise.all(targets.map(async target => {
      const specification = await fetchJson(`${JMA_TYPHOON_ROOT}/${target.tropicalCyclone}/specifications.json`);
      const title = specification.find(item => item.part === 'title') || {};
      const points = specification.flatMap(item => {
        const position = item.position?.deg, valid = item.validtime?.UTC;
        if (!position || !valid) return [];
        const wind = Number(item.maximumWind?.sustained?.kt);
        const pressure = Number(item.pressure);
        return [{t:Date.parse(valid),lat:Number(position[0]),lon:Number(position[1]),
          grade:target.category === 'TD' ? 2 : 5,pressure:Number.isFinite(pressure) ? pressure : null,
          wind:Number.isFinite(wind) ? wind : null,forecast:Number(item.advancedHours || 0) > 0,
          circleKm:Number(item.probabilityCircleRadius?.km) || null}];
      });
      if (!points.length) return null;
      const number = Number(String(target.typhoonNumber || target.tropicalCyclone).slice(-2));
      return {id:`${new Date(points[0].t).getUTCFullYear()}${String(number).padStart(2,'0')}`,
        year:new Date(points[0].t).getUTCFullYear(),number,name:title.name?.en || '',points,
        provisional:true,sourceId:target.tropicalCyclone};
    }));
    return results.filter(Boolean);
  }
  async function refreshLiveData() {
    const active = await fetchCurrentStorms();
    const ids = new Set(active.map(storm => storm.id));
    data = {...data,storms:data.storms.filter(storm => !ids.has(storm.id)).concat(active),liveUpdatedAt:new Date().toISOString()};
    return active;
  }
  function setPlaying(value) { playing = value; $('play').textContent = playing ? 'Ⅱ' : '▶'; $('play').setAttribute('aria-label', playing ? 'Pause' : 'Play'); $('play-state').textContent = playing ? 'Playing' : 'Stopped'; dirty = true; }
  function resetView() {
    center = [136, 29];
    scale = Math.min(width / (width < 650 ? 48 : 72), height / 60);
    drawBase(); dirty = true;
  }
  function resize() {
    width = innerWidth; height = innerHeight; dpr = Math.min(devicePixelRatio || 1, 2);
    for (const c of [base, canvas]) { c.width = Math.round(width*dpr); c.height = Math.round(height*dpr); c.getContext('2d').setTransform(dpr,0,0,dpr,0,0); }
    if (scale === 1) resetView(); else { drawBase(); dirty = true; }
  }
  function path(ring, context) { ring.forEach((p,i) => { const q = project(...p); if (i) context.lineTo(...q); else context.moveTo(...q); }); }
  function drawBase() {
    bg.clearRect(0,0,width,height); bg.fillStyle = '#070b14'; bg.fillRect(0,0,width,height);
    bg.strokeStyle = '#121d2c'; bg.lineWidth = 1; bg.fillStyle = '#3c4b63'; bg.font = '10px Segoe UI';
    for (let lon = 80; lon <= 190; lon += 5) { const [x] = project(lon,0); bg.beginPath(); bg.moveTo(x,0); bg.lineTo(x,height); bg.stroke(); if (x>0 && x<width) bg.fillText(`${lon}°E`,x+5,height-$('controls').offsetHeight-34); }
    for (let lat = -5; lat <= 65; lat += 5) { const [,y] = project(0,lat); bg.beginPath(); bg.moveTo(0,y); bg.lineTo(width,y); bg.stroke(); bg.fillText(`${lat}°N`,width-40,y-5); }
    for (const feature of window.MAP_DATA || []) {
      bg.fillStyle = feature.name === 'Japan' ? '#1d2a3d' : '#121b29'; bg.strokeStyle = feature.name === 'Japan' ? '#4c6385' : '#2a3a50'; bg.lineWidth = .8;
      for (const polygon of feature.polygons) { bg.beginPath(); for (const ring of polygon) { path(ring,bg); bg.closePath(); } bg.fill('evenodd'); bg.stroke(); }
    }
    const cities = [['Tokyo',139.69,35.68],['Osaka',135.5,34.69],['Fukuoka',130.4,33.59],['Sapporo',141.35,43.06],['Naha',127.68,26.21],['Taipei',121.56,25.03],['Manila',120.98,14.6]];
    bg.font = '11px "Yu Gothic UI",sans-serif';
    for (const [name,lon,lat] of cities) { const [x,y] = project(lon,lat); bg.fillStyle = '#7a8aa5'; bg.beginPath(); bg.arc(x,y,2,0,Math.PI*2); bg.fill(); bg.fillStyle = '#8999b1'; bg.fillText(name,x+6,y+4); }
    bg.fillStyle = '#26364e'; bg.font = '14px Segoe UI'; bg.textAlign = 'center';
    for (const [name,lon,lat] of [['P A C I F I C',150,24],['S E A  O F  J A P A N',135,40],['E A S T  C H I N A  S E A',124,29]]) { bg.fillText(name,...project(lon,lat)); }
    bg.textAlign = 'left';
  }
  function draw() {
    ctx.clearRect(0,0,width,height); hits = [];
    for (const storm of storms) {
      const focused = !selected || selected.id === storm.id, opacity = focused ? 1 : .16;
      const ps = storm.points, current = C.atTime(storm,time);
      if ($('full').checked) {
        ctx.beginPath(); path(ps.map(p => [p.lon,p.lat]),ctx); ctx.strokeStyle = `rgba(145,161,185,${focused ? .23 : .07})`; ctx.lineWidth = 1; ctx.setLineDash([3,5]); ctx.stroke(); ctx.setLineDash([]);
      }
      for (let i=1; i<ps.length && ps[i-1].t<=time; i++) {
        const a=ps[i-1], b=ps[i].t<=time ? ps[i] : current;
        if (!b) break;
        const q=project(a.lon,a.lat), r=project(b.lon,b.lat);
        ctx.globalAlpha = opacity * (current ? .85 : .42); ctx.strokeStyle=C.category(a).color; ctx.lineWidth=focused ? 2 : 1;
        if (b.forecast) ctx.setLineDash([6,5]);
        ctx.beginPath(); ctx.moveTo(...q); ctx.lineTo(...r); ctx.stroke(); ctx.setLineDash([]);
        if (focused) hits.push({storm,a:q,b:r,point:a});
        if (focused && (selected || scale>20)) { ctx.fillStyle=C.category(a).color; ctx.beginPath(); ctx.arc(...q,1.8,0,Math.PI*2); ctx.fill(); }
      }
      if (current) {
        const [x,y]=project(current.lon,current.lat), color=C.category(current).color;
        ctx.globalAlpha=opacity; ctx.strokeStyle=color; ctx.fillStyle=color;
        const pulse=playing && !matchMedia('(prefers-reduced-motion: reduce)').matches ? (performance.now()%1800)/1800 : .35;
        ctx.globalAlpha=opacity*(1-pulse)*.35; ctx.lineWidth=1; ctx.beginPath(); ctx.arc(x,y,9+pulse*18,0,Math.PI*2); ctx.stroke();
        ctx.globalAlpha=opacity; ctx.beginPath(); ctx.arc(x,y,7,0,Math.PI*2); ctx.fill(); ctx.fillStyle='#07101b'; ctx.beginPath(); ctx.arc(x,y,3,0,Math.PI*2); ctx.fill();
        if (current.forecast && current.circleKm) { ctx.globalAlpha=opacity*.55; ctx.strokeStyle=color; ctx.lineWidth=1; ctx.setLineDash([4,4]); ctx.beginPath(); ctx.arc(x,y,current.circleKm/111*scale,0,Math.PI*2); ctx.stroke();ctx.setLineDash([]); }
        if (focused) { ctx.font='12px "Segoe UI",sans-serif'; ctx.fillStyle='#070b14'; ctx.fillRect(x+12,y-21,118,23); ctx.fillStyle=color; ctx.fillText(`Typhoon ${storm.number} · ${current.pressure || '—'} hPa`,x+16,y-6); }
        hits.push({storm,a:[x,y],b:[x,y],point:current.observation});
      }
    }
    ctx.globalAlpha=1;
  }
  function populateYears(preferred) {
    const years = [...new Set(data.storms.filter(s=>s.year>=2000).map(s=>s.year))].sort((a,b)=>b-a);
    $('year').replaceChildren(...years.map(year=>new Option(String(year),year)));
    if (years.includes(Number(preferred))) $('year').value=preferred;
    $('coverage').textContent=`2000–${years[0]} / ${data.storms.length} storms`;
    $('fetched').textContent=C.formatTime(Date.parse(data.fetchedAt));
  }
  function filterStorms() {
    setPlaying(false); selected=null;
    storms=data.storms.filter(s=>s.year===Number($('year').value) && ($('region').value==='all' || C.nearJapan(s)));
    $('region-note').textContent=$('region').value==='all' ? 'JMA coverage: Western North Pacific and South China Sea' : 'Tracks entering 20–46°N / 120–155°E';
    $('count').textContent=`${storms.length} storms`;
    if (!storms.length) { start=Date.parse(`${$('year').value}-01-01T00:00:00+09:00`); end=start+86400000; time=start; notice('No storms match this selection. Try another area or year.'); }
    else {
      notice(''); start=Math.min(...storms.map(s=>s.points[0].t)); end=Math.max(...storms.map(s=>s.points.at(-1).t));
      const latest=storms.at(-1); time=latest.points.reduce((a,b)=>(b.pressure||2000)<(a.pressure||2000)?b:a).t;
    }
    $('from').value=C.dateJST(start); $('to').value=C.dateJST(end); $('play').disabled=!storms.length;
    renderList(); updateUI(); dirty=true;
  }
  function renderList() {
    $('storm-list').replaceChildren(...storms.slice().reverse().map(storm=>{
      const button=document.createElement('button'); button.className='storm'+(selected?.id===storm.id?' selected':''); button.setAttribute('aria-pressed',String(selected?.id===storm.id));
      const dot=document.createElement('span'); dot.className='dot'; dot.style.setProperty('--c',C.category(storm.points.reduce((a,b)=>(b.wind||0)>(a.wind||0)?b:a)).color);
      const text=document.createElement('span'), title=document.createElement('strong'), subtitle=document.createElement('small'), reading=document.createElement('span');
      title.textContent=`Typhoon ${storm.number} ${storm.name || ''}`; subtitle.textContent=`${C.dateJST(storm.points[0].t).slice(5)} — ${C.dateJST(storm.points.at(-1).t).slice(5)}${storm.provisional ? ' / Live update' : ''}`; reading.className='reading'; reading.textContent=minText(storm); text.append(title,subtitle); button.append(dot,text,reading);
      button.onclick=()=>selectStorm(storm); return button;
    }));
  }
  function selectStorm(storm) {
    selected=storm; setPlaying(false); start=storm.points[0].t; end=storm.points.at(-1).t;
    if (end<=start) end=start+C.HOUR;
    time=start; $('from').value=C.dateJST(start); $('to').value=C.dateJST(end);
    renderList(); updateUI(); dirty=true;
  }
  function updateUI() {
    $('clock').replaceChildren(document.createTextNode(C.formatTime(time)),Object.assign(document.createElement('small'),{textContent:'JST'}));
    $('seek').value=Math.round((time-start)/(end-start)*10000); $('seek').setAttribute('aria-valuetext',C.formatTime(time)+' JST');
    const s=selected || storms.filter(s=>C.atTime(s,time)).at(-1);
    $('detail-content').hidden=!s;
    if (!s) { $('detail-title').textContent='Select a typhoon'; $('detail-name').textContent='Choose a list item or track on the map'; return; }
    $('detail-title').textContent=label(s); $('detail-name').textContent=(s.name||'Unnamed')+(s.provisional?' / Live update':' / Best track');
    const current=C.atTime(s,time), p=current?.observation;
    $('phase').textContent=p ? `${s.provisional ? (p.forecast ? 'Forecast / ' : 'Analysis / ') : ''}${C.category(p).label}` : time<s.points[0].t?'Before record':'After record'; $('phase').style.color=p?C.category(p).color:'#91a1b9';
    $('pressure').textContent=p?.pressure || '—'; $('wind').textContent=p?.wind ? (p.wind*.514444).toFixed(1) : '—';
    $('observation').textContent=p ? C.formatTime(p.t)+' JST' : '—'; $('position').textContent=current?`${current.lat.toFixed(1)}°N ${current.lon.toFixed(1)}°E`:'—';
    $('minimum').textContent=minText(s); $('life').textContent=`${C.dateJST(s.points[0].t).slice(5)} to ${C.dateJST(s.points.at(-1).t).slice(5)}`;
    $('replay').onclick=()=>{selectStorm(s); setPlaying(true);};
  }
  function frame(now) {
    if (playing) { time+=Math.min((now-lastFrame)/1000,.1)*Number($('speed').value)*C.HOUR; if(time>=end){ if($('loop').checked) time=start; else {time=end;setPlaying(false);} } dirty=true; }
    lastFrame=now;
    if(dirty){draw();dirty=false;}
    if(now-lastUI>120){updateUI();lastUI=now;}
    requestAnimationFrame(frame);
  }
  function zoom(factor,x=width/2,y=height/2) {
    const anchor=unproject(x,y); scale=Math.max(3,Math.min(160,scale*factor));
    center=[anchor[0]-(x-width/2)/scale,unmerc(merc(anchor[1])+(y-height/2)/scale)]; drawBase();dirty=true;
  }
  function hit(x,y) {
    let best=null, distance=10;
    for(const h of hits){const [ax,ay]=h.a,[bx,by]=h.b,dx=bx-ax,dy=by-ay,f=Math.max(0,Math.min(1,((x-ax)*dx+(y-ay)*dy)/(dx*dx+dy*dy||1))),d=Math.hypot(x-ax-f*dx,y-ay-f*dy);if(d<distance){distance=d;best=h;}}
    return best;
  }
  canvas.addEventListener('wheel',e=>{e.preventDefault();zoom(Math.exp(-e.deltaY*.001),e.clientX,e.clientY);},{passive:false});
  canvas.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,center:[...center],moved:false};canvas.setPointerCapture(e.pointerId);canvas.classList.add('dragging');$('tip').hidden=true;});
  canvas.addEventListener('pointermove',e=>{
    if(drag){const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag.moved ||= Math.hypot(dx,dy)>4;center=[drag.center[0]-dx/scale,Math.max(-10,Math.min(65,unmerc(merc(drag.center[1])+dy/scale)))];drawBase();dirty=true;return;}
    const h=hit(e.clientX,e.clientY);$('tip').hidden=!h;
    if(h){$('tip').textContent=`${label(h.storm)} ${h.storm.name}\n${C.formatTime(h.point.t)} JST\n${h.point.pressure||'—'} hPa · ${h.point.wind?(h.point.wind*.514444).toFixed(1):'—'} m/s`;$('tip').style.left=Math.max(8,Math.min(width-245,e.clientX+14))+'px';$('tip').style.top=Math.min(height-100,e.clientY+14)+'px';}
  });
  canvas.addEventListener('pointerup',e=>{if(drag&&!drag.moved){const h=hit(e.clientX,e.clientY);if(h){selectStorm(h.storm);time=h.point.t;updateUI();}}drag=null;canvas.classList.remove('dragging');});
  canvas.addEventListener('pointercancel',()=>{drag=null;canvas.classList.remove('dragging');});
  canvas.addEventListener('pointerleave',()=>{$('tip').hidden=true;});
  $('zoom-in').onclick=()=>zoom(1.3);$('zoom-out').onclick=()=>zoom(1/1.3);$('home').onclick=resetView;
  $('play').onclick=()=>{if(!playing&&time>=end)time=start;setPlaying(!playing);};
  $('seek').oninput=()=>{time=start+(end-start)*Number($('seek').value)/10000;dirty=true;updateUI();};
  $('year').onchange=filterStorms;$('region').onchange=filterStorms;$('all').onclick=filterStorms;$('full').onchange=()=>{dirty=true;};
  for(const id of ['from','to']) $(id).onchange=()=>{try{[start,end]=C.parseRange($('from').value,$('to').value);time=Math.max(start,Math.min(end,time));notice('');dirty=true;}catch(e){notice(e.message);}};
  document.addEventListener('keydown',e=>{if(['INPUT','SELECT','BUTTON','TEXTAREA'].includes(e.target.tagName))return;if(e.code==='Space'){e.preventDefault();if(storms.length)$('play').click();}if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();time=Math.max(start,Math.min(end,time+(e.key==='ArrowRight'?1:-1)*6*C.HOUR));dirty=true;}if(e.key==='+')zoom(1.3);if(e.key==='-')zoom(1/1.3);});
  $('refresh').onclick=async()=>{
    $('refresh').disabled=true;notice('Checking JMA for the latest active typhoon data…');
    try{const active=await refreshLiveData();populateYears($('year').value);filterStorms();notice(active.length ? `Updated ${active.length} active storm${active.length === 1 ? '' : 's'}. Analysis is solid; forecasts are dashed.` : 'JMA has no active typhoons at this time.');}
    catch(e){notice(`Update failed. Displaying saved data. ${e.message}`);}
    finally{$('refresh').disabled=false;}
  };
  window.addEventListener('resize',resize);
  if(!data?.storms?.length){notice('No typhoon data is available. Run python tools/update_data.py.');$('play').disabled=true;resize();return;}
  data.storms=data.storms.filter(s=>s.year>=2000);populateYears();filterStorms();resize();requestAnimationFrame(frame);
})();
