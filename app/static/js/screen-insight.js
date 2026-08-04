/* ⑥ 동향 인사이트 — 보고서 키워드로 실제 뉴스를 수집하고,
   그 기사에서 기업–기술 관계 그래프를 그린다. 수집 주기는 6시간. */
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

  function renderFetchInfo(d){
    var info = $id('insFetchInfo');
    if(!d.fetched_at){ info.textContent = ''; return; }
    var when = new Date(d.fetched_at);
    var mm = String(when.getMinutes()).padStart(2, '0');
    var stamp = (when.getMonth() + 1) + '/' + when.getDate() + ' ' + when.getHours() + ':' + mm;
    var age = d.age_minutes == null ? '' :
      (d.age_minutes < 60 ? d.age_minutes + '분 전' : Math.floor(d.age_minutes / 60) + '시간 전');
    info.textContent = '마지막 수집: ' + stamp + (age ? ' (' + age + ')' : '') +
      ' · ' + d.refresh_hours + '시간마다 자동 갱신' + (d.from_cache ? ' · 저장된 결과' : ' · 방금 수집함');
  }

  /* ── 관계 그래프 (수집한 기사에서 추출) ── */
  var NS = 'http://www.w3.org/2000/svg';
  var COLORS = { us: '#ea002c', company: '#f47725', tech: '#1baf7a' };

  function layout(nodes){
    // 우리 사업을 가운데, 기술은 안쪽 원, 기업은 바깥 원에 배치
    var cx = 260, cy = 180;
    var techs = nodes.filter(function(n){ return n.type === 'tech'; });
    var companies = nodes.filter(function(n){ return n.type === 'company'; });
    var placed = {};
    nodes.forEach(function(n){ if(n.type === 'us') placed[n.id] = { x: cx, y: cy }; });
    techs.forEach(function(n, i){
      var a = (Math.PI * 2 * i / Math.max(techs.length, 1)) - Math.PI / 2;
      placed[n.id] = { x: cx + Math.cos(a) * 92, y: cy + Math.sin(a) * 74 };
    });
    companies.forEach(function(n, i){
      var a = (Math.PI * 2 * i / Math.max(companies.length, 1)) - Math.PI / 2 + 0.35;
      placed[n.id] = { x: cx + Math.cos(a) * 196, y: cy + Math.sin(a) * 130 };
    });
    return placed;
  }

  function renderGraph(graph){
    var svg = $id('graph');
    while(svg.firstChild) svg.removeChild(svg.firstChild);
    var sub = $id('insGraphSub');
    if(!graph || !graph.nodes || graph.nodes.length <= 1){
      sub.textContent = '추출된 관계 없음';
      var t = document.createElementNS(NS, 'text');
      t.setAttribute('x', 260); t.setAttribute('y', 180); t.setAttribute('text-anchor', 'middle');
      t.setAttribute('font-size', '12'); t.setAttribute('fill', '#898781');
      t.textContent = '관계를 추출할 기사가 없습니다.';
      svg.appendChild(t);
      return;
    }
    var companies = graph.nodes.filter(function(n){ return n.type === 'company'; }).length;
    var techs = graph.nodes.filter(function(n){ return n.type === 'tech'; }).length;
    sub.textContent = '기업·기관 ' + companies + ' · 기술 ' + techs + ' · 기사에서 추출';

    var pos = layout(graph.nodes);
    var maxW = Math.max.apply(null, graph.links.map(function(l){ return l.weight || 1; }).concat([1]));

    graph.links.forEach(function(l){
      var a = pos[l.source], b = pos[l.target];
      if(!a || !b) return;
      var ln = document.createElementNS(NS, 'line');
      ln.setAttribute('x1', a.x); ln.setAttribute('y1', a.y);
      ln.setAttribute('x2', b.x); ln.setAttribute('y2', b.y);
      ln.setAttribute('stroke', '#c3c2b7');
      ln.setAttribute('stroke-width', String(1 + (l.weight || 1) / maxW * 2.5));
      ln.dataset.a = l.source; ln.dataset.b = l.target;
      svg.appendChild(ln);
    });

    graph.nodes.forEach(function(n){
      var p = pos[n.id];
      if(!p) return;
      var r = n.type === 'us' ? 30 : Math.min(26, 13 + (n.weight || 1) * 2.5);
      var g = document.createElementNS(NS, 'g');
      g.style.cursor = 'default';
      var c = document.createElementNS(NS, 'circle');
      c.setAttribute('cx', p.x); c.setAttribute('cy', p.y); c.setAttribute('r', r);
      c.setAttribute('fill', COLORS[n.type] || '#898781');
      c.setAttribute('stroke', '#fcfcfb'); c.setAttribute('stroke-width', '2');
      g.appendChild(c);
      var t = document.createElementNS(NS, 'text');
      t.setAttribute('x', p.x); t.setAttribute('y', p.y + r + 12); t.setAttribute('text-anchor', 'middle');
      t.setAttribute('font-size', '10.5'); t.setAttribute('font-weight', '600'); t.setAttribute('fill', '#0b0b0b');
      t.textContent = n.label;
      g.appendChild(t);

      g.addEventListener('mousemove', function(ev){
        var head = '<b>' + esc(n.label) + '</b>' +
          (n.type === 'us' ? '' : '<br>기사 ' + (n.weight || 0) + '건');
        var body = (n.articles || []).slice(0, 2).map(function(a){
          return '<br>· ' + esc(String(a).slice(0, 34));
        }).join('');
        showTip(ev, head + body);
        svg.querySelectorAll('line').forEach(function(l){
          var hit = (l.dataset.a === n.id || l.dataset.b === n.id);
          l.setAttribute('stroke', hit ? '#ea002c' : '#e1e0d9');
        });
      });
      g.addEventListener('mouseleave', function(){
        hideTip();
        svg.querySelectorAll('line').forEach(function(l){ l.setAttribute('stroke', '#c3c2b7'); });
      });
      svg.appendChild(g);
    });
  }

  function loading(msg){
    $id('artList').innerHTML = '<div class="note">' + esc(msg) + '</div>';
  }

  function loadForReport(id, force){
    if(!id) return;
    loading(force ? '뉴스를 새로 수집하는 중…' : '보고서 키워드로 뉴스를 불러오는 중…');
    $id('insArtSub').textContent = '관련도순 정렬';
    API.get('/api/reports/' + id + '/news?limit=12' + (force ? '&force=true' : '')).then(function(d){
      renderKeywords(d.keywords);
      renderArticles(d.items, d.reason || '관련 기사를 찾지 못했습니다.');
      renderGraph(d.graph);
      renderFetchInfo(d);
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
    $id('insRefreshBtn').onclick = function(){ loadForReport($id('insReportSel').value, true); };
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
          renderGraph(null);
          $id('insFetchInfo').textContent = '';
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
