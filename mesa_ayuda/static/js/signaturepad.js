
function SignaturePadSimple(id){
  const c = document.getElementById(id), x = c.getContext('2d');
  const ratio = Math.max(window.devicePixelRatio || 1, 1);
  const w = c.width, h = c.height;
  c.width = w * ratio; c.height = h * ratio; c.style.width = w + 'px'; c.style.height = h + 'px';
  x.scale(ratio, ratio);
  x.fillStyle = '#fff'; x.fillRect(0, 0, w, h); x.fillStyle = '#000';
  let drawing=false, lx=0, ly=0, hasDrawn=false;
  x.lineWidth=2; x.lineCap='round'; x.strokeStyle='#111827';
  function pos(e){
    const r=c.getBoundingClientRect();
    if(e.touches && e.touches[0]) return {x:e.touches[0].clientX-r.left, y:e.touches[0].clientY-r.top};
    return {x:e.clientX-r.left, y:e.clientY-r.top};
  }
  function start(e){ drawing=true; const o=pos(e); lx=o.x; ly=o.y; }
  function move(e){ if(!drawing) return; const o=pos(e); x.beginPath(); x.moveTo(lx,ly); x.lineTo(o.x,o.y); x.stroke(); lx=o.x; ly=o.y; hasDrawn=true; }
  function end(){ drawing=false; }
  c.addEventListener('mousedown', start); c.addEventListener('mousemove', move); window.addEventListener('mouseup', end);
  c.addEventListener('touchstart', e=>{ e.preventDefault(); start(e); }, {passive:false});
  c.addEventListener('touchmove',  e=>{ e.preventDefault(); move(e);  }, {passive:false});
  c.addEventListener('touchend',   e=>{ e.preventDefault(); end();    }, {passive:false});
  return { toDataURL: () => c.toDataURL('image/png'), clear: () => { x.clearRect(0,0,w,h); x.fillStyle='#fff'; x.fillRect(0,0,w,h); x.fillStyle='#000'; hasDrawn=false; }, isBlank: () => !hasDrawn };
}
