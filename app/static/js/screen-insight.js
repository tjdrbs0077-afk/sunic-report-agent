/* ⑥ 동향 인사이트 — SUNIC_Demo_index.html의 더미 데이터를 그대로 유지한다. */

/* ───────── 기사 목록 ───────── */
var ARTS = [
  ['news','도요타, 2027년 전고체 배터리 탑재 차량 양산 계획 재확인','닛케이 · 7/26', 0.94],
  ['pat','황화물계 고체 전해질의 대기 안정성 개선 조성물 (KR 출원)','특허청 · 7/21', 0.91],
  ['news','삼성SDI, 전고체 파일럿 "S라인" 샘플 고객사 평가 착수','전자신문 · 7/24', 0.89],
  ['news','QuantumScape, 리튬메탈 분리막 수율 개선 발표… 주가 급등','로이터 · 7/22', 0.84],
  ['pat','건식 전극 제조용 바인더 섬유화 공정 (US 등록)','USPTO · 7/15', 0.81],
  ['news','LG에너지솔루션, 건식 전극 공정 2028년 상용화 목표','한국경제 · 7/18', 0.78]
];
var al = document.getElementById('artList');
ARTS.forEach(function(a){
  al.insertAdjacentHTML('beforeend',
    '<div class="art"><div class="t">' + a[1] + '</div>' +
    '<div class="m"><span class="pill ' + a[0] + '">' + (a[0] === 'news' ? '뉴스' : '특허') + '</span>' +
    '<span>' + a[2] + '</span>' +
    '<span class="rel"><span class="relbar"><i style="width:' + (a[3]*100) + '%"></i></span>관련도 ' + a[3].toFixed(2) + '</span></div></div>');
});

/* ───────── 관계 그래프 (SVG) ───────── */
var NODES = [
  {id:'us',  x:260, y:180, r:34, c:'#ea002c', t:'우리 사업',      d:'배터리소재사업단 기획안'},
  {id:'ssdi',x:95,  y:75,  r:24, c:'#f47725', t:'삼성SDI',        d:'전고체 파일럿 S라인 운영'},
  {id:'toy', x:425, y:70,  r:24, c:'#f47725', t:'도요타',          d:'2027 양산 목표'},
  {id:'qs',  x:455, y:250, r:24, c:'#f47725', t:'QuantumScape',   d:'리튬메탈 분리막'},
  {id:'lg',  x:80,  y:280, r:24, c:'#f47725', t:'LG에너지솔루션', d:'건식 전극 2028 상용화'},
  {id:'sulf',x:250, y:60,  r:20, c:'#1baf7a', t:'황화물 전해질',   d:'특허 5건 · 기사 8건'},
  {id:'limt',x:400, y:160, r:20, c:'#1baf7a', t:'리튬메탈 음극',   d:'기사 6건'},
  {id:'dry', x:175, y:300, r:20, c:'#1baf7a', t:'건식 전극',       d:'특허 3건 · 기사 4건'}
];
var EDGES = [
  ['us','sulf','핵심 기술'], ['us','limt','검토 중'], ['us','dry','공정 검토'],
  ['ssdi','sulf','파일럿 적용'], ['toy','sulf','양산 개발'],
  ['qs','limt','상용화 선도'], ['lg','dry','공정 개발'], ['toy','limt','공동 연구']
];
var svg = document.getElementById('graph');
var NS = 'http://www.w3.org/2000/svg';
function nodeById(id){ for(var i=0;i<NODES.length;i++){ if(NODES[i].id===id) return NODES[i]; } }
EDGES.forEach(function(e){
  var a = nodeById(e[0]), b = nodeById(e[1]);
  var ln = document.createElementNS(NS,'line');
  ln.setAttribute('x1',a.x); ln.setAttribute('y1',a.y);
  ln.setAttribute('x2',b.x); ln.setAttribute('y2',b.y);
  ln.setAttribute('stroke','#c3c2b7'); ln.setAttribute('stroke-width','1.5');
  ln.dataset.a = e[0]; ln.dataset.b = e[1];
  svg.appendChild(ln);
  var mx = (a.x+b.x)/2, my = (a.y+b.y)/2;
  var lb = document.createElementNS(NS,'text');
  lb.setAttribute('x',mx); lb.setAttribute('y',my-4); lb.setAttribute('text-anchor','middle');
  lb.setAttribute('font-size','9'); lb.setAttribute('fill','#898781');
  lb.textContent = e[2];
  svg.appendChild(lb);
});
NODES.forEach(function(n){
  var g = document.createElementNS(NS,'g');
  g.style.cursor = 'default';
  var c = document.createElementNS(NS,'circle');
  c.setAttribute('cx',n.x); c.setAttribute('cy',n.y); c.setAttribute('r',n.r);
  c.setAttribute('fill',n.c);
  c.setAttribute('stroke','#fcfcfb'); c.setAttribute('stroke-width','2');
  g.appendChild(c);
  var t = document.createElementNS(NS,'text');
  t.setAttribute('x',n.x); t.setAttribute('y',n.y + n.r + 13); t.setAttribute('text-anchor','middle');
  t.setAttribute('font-size','11'); t.setAttribute('font-weight','600'); t.setAttribute('fill','#0b0b0b');
  t.textContent = n.t;
  g.appendChild(t);
  g.addEventListener('mousemove', function(ev){
    showTip(ev, '<b>' + n.t + '</b><br>' + n.d);
    svg.querySelectorAll('line').forEach(function(l){
      var hit = (l.dataset.a === n.id || l.dataset.b === n.id);
      l.setAttribute('stroke', hit ? '#ea002c' : '#e1e0d9');
      l.setAttribute('stroke-width', hit ? '2.5' : '1.5');
    });
  });
  g.addEventListener('mouseleave', function(){
    hideTip();
    svg.querySelectorAll('line').forEach(function(l){
      l.setAttribute('stroke','#c3c2b7'); l.setAttribute('stroke-width','1.5');
    });
  });
  svg.appendChild(g);
});

Screens.s6 = { load: function(){} };
