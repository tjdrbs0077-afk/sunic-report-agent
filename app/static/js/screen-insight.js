/* ⑥ 동향 인사이트 — 보고서 키워드로 실제 뉴스 기사를 검색한다.
   관계 그래프는 아직 더미 데이터(LLM 엔티티 추출 연동 예정). */
Screens.s6 = (function(){
  var reports = [];
  var loadedOnce = false;

  function $id(x){ return document.getElementById(x); }

  function renderArticles(items, note){
    var box = $id('artList');
    if(!items.length){
      box.innerHTML = '<div class="note">' + esc(note || '검색 결과가 없습니다.') + '</div>';
      return;
    }
    box.innerHTML = items.map(function(a){
      var link = a.link
        ? '<a href="' + esc(a.link) + '" target="_blank" rel="noopener noreferrer" style="color:inherit; text-decoration:none;">' + esc(a.title) + '</a>'
        : esc(a.title);
      return '<div class="art"><div class="t">' + link + '</div>' +
        '<div class="m"><span class="pill news">뉴스</span>' +
        '<span>' + esc(a.source) + (a.date ? ' · ' + esc(a.date) : '') + '</span>' +
        (a.keyword ? '<span style="color:var(--accent-deep); font-weight:600;">' + esc(a.keyword) + '</span>' : '') +
        '<span class="rel"><span class="relbar"><i style="width:' + Math.round(a.score * 100) + '%"></i></span>관련도 ' + a.score.toFixed(2) + '</span>' +
        '</div></div>';
    }).join('');
  }

  function renderKeywords(list){
    var box = $id('insKeywords');
    if(!list || !list.length){
      box.innerHTML = '<span style="font-size:12.5px; color:var(--text-muted);">추출된 키워드가 없습니다.</span>';
      return;
    }
    box.innerHTML = list.map(function(k){
      return '<span class="kw" data-kw="' + esc(k.keyword) + '" style="cursor:pointer;"><b>' + esc(k.keyword) + '</b>' +
        '<span class="n">기사 ' + k.count + '</span></span>';
    }).join('');
    box.querySelectorAll('[data-kw]').forEach(function(el){
      el.onclick = function(){
        $id('insQuery').value = el.dataset.kw;
        searchDirect(el.dataset.kw);
      };
    });
  }

  function loading(msg){
    $id('artList').innerHTML = '<div class="note">' + esc(msg) + '</div>';
  }

  function loadForReport(id){
    if(!id) return;
    loading('보고서 키워드로 뉴스를 검색하는 중…');
    $id('insArtSub').textContent = '관련도순 정렬';
    API.get('/api/reports/' + id + '/news?limit=12').then(function(d){
      renderKeywords(d.keywords);
      renderArticles(d.items, d.reason || '관련 기사를 찾지 못했습니다.');
      $id('insKwSub').textContent = (d.unit || '') + ' 보고서에서 자동 추출 · 클릭하면 해당 키워드로 검색';
    }).catch(function(e){
      renderArticles([], '뉴스를 불러오지 못했습니다: ' + e.message);
    });
  }

  function searchDirect(q){
    q = (q || $id('insQuery').value || '').trim();
    if(!q) return;
    loading('‘' + q + '’ 검색 중…');
    $id('insArtSub').textContent = '‘' + q + '’ 검색 결과';
    API.get('/api/news?q=' + encodeURIComponent(q) + '&limit=12').then(function(d){
      renderArticles(d.items, d.reason || '검색 결과가 없습니다.');
    }).catch(function(e){
      renderArticles([], '검색 실패: ' + e.message);
    });
  }

  var bound = false;
  function bind(){
    if(bound) return; bound = true;
    $id('insSearchBtn').onclick = function(){ searchDirect(); };
    $id('insQuery').addEventListener('keydown', function(e){ if(e.key === 'Enter') searchDirect(); });
    $id('insReportSel').onchange = function(){ loadForReport(this.value); };
  }

  return {
    load: function(){
      bind();
      var sel = $id('insReportSel');
      var keep = sel.value;
      API.get('/api/reports').then(function(r){
        reports = r;
        sel.innerHTML = reports.map(function(x){
          return '<option value="' + x.id + '">' + esc(x.name) + '</option>';
        }).join('');
        if(!reports.length){
          renderKeywords([]);
          renderArticles([], '업로드된 보고서가 없습니다. 위 검색창에 키워드를 직접 입력해 검색할 수 있습니다.');
          return;
        }
        if(keep && reports.some(function(x){ return x.id === keep; })){
          sel.value = keep;
          if(loadedOnce) return;
        }
        loadedOnce = true;
        loadForReport(sel.value);
      });
    }
  };
})();

/* ───────── 관계 그래프 (SVG) — 더미 데이터 유지 ───────── */
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
