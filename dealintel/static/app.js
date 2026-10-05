(() => {
  const svg = document.getElementById('priceChart');
  if (!svg) return;
  let series = [];
  try { series = JSON.parse(svg.dataset.series || '[]'); } catch (_) { return; }
  const ns = 'http://www.w3.org/2000/svg';
  const add = (tag, attrs, text) => {
    const el = document.createElementNS(ns, tag);
    Object.entries(attrs || {}).forEach(([k, v]) => el.setAttribute(k, String(v)));
    if (text != null) el.textContent = text;
    svg.appendChild(el); return el;
  };
  if (!series.length) {
    add('text', {x:450,y:150,'text-anchor':'middle',fill:'#718096','font-size':14}, 'No price history yet');
    return;
  }
  const W=900,H=300,pad={l:55,r:20,t:20,b:35};
  const vals=series.map(x=>Number(x.p)).filter(Number.isFinite);
  let min=Math.min(...vals), max=Math.max(...vals);
  if (min===max){min*=.95;max*=1.05}
  const span=Math.max(1,max-min);
  min=Math.max(0,min-span*.12);max=max+span*.12;
  const x=i=>pad.l+(W-pad.l-pad.r)*(series.length===1?.5:i/(series.length-1));
  const y=v=>pad.t+(H-pad.t-pad.b)*(1-(v-min)/(max-min));
  for(let i=0;i<4;i++){
    const yy=pad.t+(H-pad.t-pad.b)*i/3;
    const value=max-(max-min)*i/3;
    add('line',{x1:pad.l,x2:W-pad.r,y1:yy,y2:yy,stroke:'#26303d','stroke-width':1});
    add('text',{x:pad.l-8,y:yy+4,'text-anchor':'end',fill:'#708095','font-size':10},'$'+value.toFixed(0));
  }
  const points=series.map((d,i)=>`${x(i)},${y(Number(d.p))}`).join(' ');
  add('polyline',{points,fill:'none',stroke:'#9cff57','stroke-width':3,'stroke-linecap':'round','stroke-linejoin':'round'});
  series.forEach((d,i)=>add('circle',{cx:x(i),cy:y(Number(d.p)),r:series.length<30?3:1.8,fill:d.available?'#9cff57':'#ff6b78'}));
  const first=new Date(series[0].t), last=new Date(series[series.length-1].t);
  add('text',{x:pad.l,y:H-10,fill:'#708095','font-size':10},first.toLocaleDateString());
  add('text',{x:W-pad.r,y:H-10,'text-anchor':'end',fill:'#708095','font-size':10},last.toLocaleDateString());
})();
