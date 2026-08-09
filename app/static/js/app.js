/* 화면 전환·사이드바 접기·툴팁 — SUNIC_Demo_index.html <script> 이관.
   각 화면 모듈(screen-*.js)은 Screens[id] = { load: fn } 형태로 등록한다. */
var Screens = {};

function esc(s){
  return String(s == null ? '' : s).replace(/[&<>"']/g, function(m){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m];
  });
}
function activeScreenId(){
  var el = document.querySelector('.screen.active');
  return el ? el.id : null;
}

/* ───────── 화면 전환 ───────── */
function go(id, btn){
  document.querySelectorAll('.screen').forEach(function(s){ s.classList.remove('active'); });
  document.getElementById(id).classList.add('active');
  document.querySelectorAll('.nav button').forEach(function(b){ b.classList.remove('active'); });
  document.querySelectorAll('.nav-group').forEach(function(group){ group.classList.remove('child-active'); });
  if(btn){
    btn.classList.add('active');
    var group = btn.closest('.nav-group');
    if(group){
      group.classList.add('child-active', 'open');
      var parent = group.querySelector('.nav-parent');
      if(parent) parent.setAttribute('aria-expanded', 'true');
    }
  }
  if(Screens[id] && typeof Screens[id].load === 'function') Screens[id].load();
}
function goTo(id){
  var btn = document.querySelector('.nav button[data-s="' + id + '"]');
  go(id, btn);
}
function toggleNavGroup(name){
  var group = document.querySelector('.nav-group[data-group="' + name + '"]');
  if(!group) return;
  group.classList.toggle('open');
  var parent = group.querySelector('.nav-parent');
  if(parent) parent.setAttribute('aria-expanded', group.classList.contains('open') ? 'true' : 'false');
}
function toggleSide(){
  var sb = document.querySelector('.sidebar');
  sb.classList.toggle('collapsed');
  document.getElementById('cbtn').textContent = sb.classList.contains('collapsed') ? '▶' : '◀';
}

/* ───────── 툴팁 ───────── */
var tip = document.getElementById('tip');
function showTip(e, html){ tip.innerHTML = html; tip.style.opacity = 1;
  tip.style.left = (e.clientX + 14) + 'px'; tip.style.top = (e.clientY + 10) + 'px'; }
function hideTip(){ tip.style.opacity = 0; }
