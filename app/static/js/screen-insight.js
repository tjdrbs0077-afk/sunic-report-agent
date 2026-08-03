/* ⑥ 동향 인사이트 — /api/insight/graph 기반 조사 지식맵.
   챗봇(⑤) 지식·동향 모드의 조사 활동이 누적된 그래프를 그린다.

   선 스타일 = 신뢰도 구분:
     extracted     실선   (근거 문장을 동반한 추출 관계 — 2차)
     co_occurrence 점선   (같은 기사에 함께 언급 — 관계 미확정)
     seed          흐린 선 (예시 데이터)

   표시 정책: 저장은 전체, 화면은 중요도(touch_count) 상위 MAX_VISIBLE개
   + 선택·강조 노드의 이웃. 나머지는 "더 보기"로 전체 표시. */
Screens.s6 = (function(){
  var NS = 'http://www.w3.org/2000/svg';
  var CX = 260, CY = 180;            /* viewBox 520×360 중심 */
  var RING = { tech: 90, company: 150 };
  var COLOR = { biz: '#ea002c', company: '#f47725', tech: '#1baf7a' };
  var MAX_VISIBLE = 20;
  var MAX_LABEL = 10;

  var graphData = null;
  var graphLoaded = false;
  var pendingFocusIds = [];
  var showAll = false;
  var selectedId = null;

  function $id(x){ return document.getElementById(x); }
  function reducedMotion(){
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  /* ── 표시 대상 선정 ── */
  function neighborsOf(id){
    var out = {};
    (graphData.edges || []).forEach(function(e){
      if(e.a === id) out[e.b] = 1;
      if(e.b === id) out[e.a] = 1;
    });
    return out;
  }
  function visibleNodes(){
    var nodes = graphData.nodes.slice();
    nodes.sort(function(a, b){
      return (b.touch_count - a.touch_count) || (b.article_count - a.article_count) ||
             (a.seed === b.seed ? 0 : (a.seed ? 1 : -1));
    });
    if(showAll || nodes.length <= MAX_VISIBLE) return nodes;
    var keep = {};
    nodes.slice(0, MAX_VISIBLE).forEach(function(n){ keep[n.id] = 1; });
    /* 선택·강조 노드와 그 이웃은 순위와 무관하게 표시 */
    [selectedId].concat(pendingFocusIds).forEach(function(id){
      if(!id) return;
      keep[id] = 1;
      Object.keys(neighborsOf(id)).forEach(function(nid){ keep[nid] = 1; });
    });
    return nodes.filter(function(n){ return keep[n.id]; });
  }

  /* ── 배치: biz 중앙 고정, tech 안쪽 링, company 바깥 링 ── */
  function layout(nodes){
    var pos = {};
    var rings = { tech: [], company: [] };
    nodes.forEach(function(n){
      if(n.type === 'biz'){ pos[n.id] = { x: CX, y: CY }; }
      else (rings[n.type] || rings.company).push(n);
    });
    Object.keys(rings).forEach(function(type){
      var list = rings[type], r = RING[type];
      list.forEach(function(n, i){
        var angle = (2 * Math.PI * i / Math.max(list.length, 1)) - Math.PI / 2 + (type === 'company' ? 0.35 : 0);
        pos[n.id] = { x: CX + r * Math.cos(angle), y: CY + r * Math.sin(angle) };
      });
    });
    return pos;
  }
  function radius(n){
    if(n.type === 'biz') return 30;
    return Math.min(34, 13 + Math.sqrt(n.touch_count || 0) * 4);
  }
  function shortLabel(s){
    return s.length > MAX_LABEL ? s.slice(0, MAX_LABEL - 1) + '…' : s;
  }
  function edgeStyle(e){
    if(e.relation_type === 'seed') return { stroke: '#c3c2b7', dash: '', opacity: 0.45 };
    if(e.relation_type === 'co_occurrence') return { stroke: '#c3c2b7', dash: '4 3', opacity: 1 };
    return { stroke: '#a29699', dash: '', opacity: 1 };  /* extracted */
  }

  /* ── 렌더 ── */
  function render(){
    var svg = $id('graph');
    svg.innerHTML = '';
    var nodes = visibleNodes();
    var byId = {};
    nodes.forEach(function(n){ byId[n.id] = n; });
    var pos = layout(nodes);

    (graphData.edges || []).forEach(function(e){
      if(!byId[e.a] || !byId[e.b]) return;
      var st = edgeStyle(e);
      var ln = document.createElementNS(NS, 'line');
      ln.setAttribute('x1', pos[e.a].x); ln.setAttribute('y1', pos[e.a].y);
      ln.setAttribute('x2', pos[e.b].x); ln.setAttribute('y2', pos[e.b].y);
      ln.setAttribute('stroke', st.stroke);
      ln.setAttribute('stroke-width', Math.min(1.5 + (e.weight - 1) * 0.5, 3.5));
      if(st.dash) ln.setAttribute('stroke-dasharray', st.dash);
      ln.setAttribute('opacity', st.opacity);
      ln.dataset.a = e.a; ln.dataset.b = e.b;
      svg.appendChild(ln);

      var lb = document.createElementNS(NS, 'text');
      lb.setAttribute('x', (pos[e.a].x + pos[e.b].x) / 2);
      lb.setAttribute('y', (pos[e.a].y + pos[e.b].y) / 2 - 4);
      lb.setAttribute('text-anchor', 'middle');
      lb.setAttribute('font-size', '9'); lb.setAttribute('fill', '#898781');
      lb.textContent = e.label + (e.weight > 1 ? ' ×' + e.weight : '');
      svg.appendChild(lb);
    });

    nodes.forEach(function(n){
      var p = pos[n.id], r = radius(n);
      var g = document.createElementNS(NS, 'g');
      g.style.cursor = 'pointer';

      var c = document.createElementNS(NS, 'circle');
      c.setAttribute('cx', p.x); c.setAttribute('cy', p.y); c.setAttribute('r', r);
      c.setAttribute('fill', COLOR[n.type] || COLOR.company);
      c.setAttribute('stroke', n.id === selectedId ? '#ea002c' : '#fcfcfb');
      c.setAttribute('stroke-width', n.id === selectedId ? 3 : 2);
      if(n.seed && !n.touch_count) c.setAttribute('opacity', '0.55');  /* 예시 데이터 */
      c.dataset.node = n.id;
      g.appendChild(c);

      var t = document.createElementNS(NS, 'text');
      t.setAttribute('x', p.x); t.setAttribute('y', p.y + r + 13);
      t.setAttribute('text-anchor', 'middle');
      t.setAttribute('font-size', '11'); t.setAttribute('font-weight', '600');
      t.setAttribute('fill', '#0b0b0b');
      if(n.seed && !n.touch_count) t.setAttribute('opacity', '0.6');
      t.textContent = shortLabel(n.label);
      g.appendChild(t);

      g.addEventListener('mousemove', function(ev){
        showTip(ev, tipHtml(n));
        svg.querySelectorAll('line').forEach(function(l){
          var hit = (l.dataset.a === n.id || l.dataset.b === n.id);
          l.setAttribute('stroke', hit ? '#ea002c' : edgeStyleById(l).stroke);
          l.setAttribute('stroke-width', hit ? 2.5 : 1.5);
        });
      });
      g.addEventListener('mouseleave', function(){
        hideTip();
        svg.querySelectorAll('line').forEach(function(l){
          l.setAttribute('stroke', edgeStyleById(l).stroke);
          l.setAttribute('stroke-width', 1.5);
        });
      });
      g.addEventListener('click', function(){ select(n.id); });
      svg.appendChild(g);
    });

    renderMore(nodes.length);
    applyFocus();
  }

  function edgeStyleById(lineEl){
    var e = (graphData.edges || []).filter(function(x){
      return x.a === lineEl.dataset.a && x.b === lineEl.dataset.b;
    })[0];
    return e ? edgeStyle(e) : { stroke: '#c3c2b7' };
  }

  function tipHtml(n){
    var html = '<b>' + esc(n.label) + '</b>';
    if(n.seed && !n.touch_count) html += ' <span style="color:#a29699;">· 예시</span>';
    if(n.desc) html += '<br>' + esc(n.desc);
    if(n.touch_count){
      html += '<br>조사 ' + n.query_count + '회 · 기사 ' + n.article_count + '건';
      if((n.search_queries || []).length){
        html += '<br>검색어: ' + esc(n.search_queries.slice(-3).join(', '));
      }
    }
    return html;
  }

  function renderMore(shownCount){
    var box = $id('graphMore');
    var total = graphData.nodes.length;
    if(showAll && total > MAX_VISIBLE){
      box.innerHTML = '<button class="btn ghost" style="margin-top:8px;">상위 ' + MAX_VISIBLE + '개만 보기</button>';
      box.querySelector('button').onclick = function(){ showAll = false; render(); };
    } else if(total > shownCount){
      box.innerHTML = '<button class="btn ghost" style="margin-top:8px;">관련 노드 ' + (total - shownCount) + '개 더 보기</button>';
      box.querySelector('button').onclick = function(){ showAll = true; render(); };
    } else {
      box.innerHTML = '';
    }
  }

  /* ── 노드 선택 → 상세 + 챗봇 프리필 ── */
  var ASK_TEMPLATES = {
    company: '{label}의 최근 기술 개발과 사업 동향을 알려줘',
    tech: '{label}의 최근 산업 동향과 주요 기업을 알려줘',
    biz: '{label}과 연관된 최근 외부 동향을 알려줘'
  };
  function select(id){
    selectedId = (selectedId === id) ? null : id;
    var box = $id('nodeDetail');
    if(!selectedId){ box.style.display = 'none'; render(); return; }
    var n = graphData.nodes.filter(function(x){ return x.id === id; })[0];
    var question = (ASK_TEMPLATES[n.type] || ASK_TEMPLATES.tech).replace('{label}', n.label);
    var meta = n.touch_count
      ? '조사 ' + n.query_count + '회 · 기사 ' + n.article_count + '건 · 최근 ' + (n.last_seen || '—')
      : '예시 데이터 — 아직 조사되지 않았습니다';
    box.innerHTML = '<b>' + esc(n.label) + '</b>' +
      (n.desc ? ' · ' + esc(n.desc) : '') +
      '<div style="margin-top:4px; color:var(--text-secondary);">' + esc(meta) + '</div>' +
      '<button class="btn primary" style="margin-top:8px;">챗봇에 물어보기</button>' +
      '<span style="font-size:12px; color:var(--text-muted); margin-left:8px;">질문이 입력만 되며, 전송은 직접 확정합니다</span>';
    box.style.display = '';
    box.querySelector('button').onclick = function(){
      goTo('s5');
      if(Screens.s5 && Screens.s5.ask) Screens.s5.ask(question);
    };
    render();
  }

  /* ── 챗봇에서 넘어온 강조 — 로딩 전 호출 대비 보류 큐 ── */
  function focus(ids){
    pendingFocusIds = ids || [];
    if(graphLoaded) render();
  }
  function applyFocus(){
    if(!pendingFocusIds.length) return;
    var svg = $id('graph');
    pendingFocusIds.forEach(function(id){
      var c = svg.querySelector('circle[data-node="' + id + '"]');
      if(!c) return;
      c.setAttribute('stroke', '#ea002c');
      c.setAttribute('stroke-width', 3.5);
      if(!reducedMotion()){
        var base = +c.getAttribute('r');
        var anim = document.createElementNS(NS, 'animate');
        anim.setAttribute('attributeName', 'r');
        anim.setAttribute('values', base + ';' + (base + 4) + ';' + base);
        anim.setAttribute('dur', '1.1s');
        anim.setAttribute('repeatCount', '3');
        c.appendChild(anim);
      }
    });
    pendingFocusIds = [];
  }

  /* ── 조사된 주제 · 기사 목록 ── */
  function renderKeywords(){
    var box = $id('kwList');
    var researched = graphData.nodes.filter(function(n){ return n.touch_count > 0; })
      .sort(function(a, b){ return b.query_count - a.query_count || b.touch_count - a.touch_count; })
      .slice(0, 8);
    if(!researched.length){
      box.innerHTML = '<div class="note">아직 조사 이력이 없습니다. ‘근거형 챗봇 → 지식 · 동향’ 모드로 질문하면 이곳에 쌓입니다.</div>';
      return;
    }
    box.innerHTML = researched.map(function(n){
      return '<span class="kw"><b>' + esc(n.label) + '</b><span class="n">조사 ' + n.query_count + '회 · 기사 ' + n.article_count + '</span></span>';
    }).join('');
  }
  function renderArticles(){
    var box = $id('artList');
    var arts = Object.keys(graphData.articles || {}).map(function(h){ return graphData.articles[h]; });
    arts.sort(function(a, b){ return (b.date || '').localeCompare(a.date || ''); });
    if(!arts.length){
      box.innerHTML = '<div class="note">수집된 기사가 없습니다. 챗봇 조사가 진행되면 이곳에 공개 기사가 쌓입니다.</div>';
      return;
    }
    box.innerHTML = arts.slice(0, 8).map(function(a){
      var title = a.url
        ? '<a href="' + esc(a.url) + '" target="_blank" rel="noopener noreferrer" style="color:inherit; text-decoration:none;">' + esc(a.title) + '</a>'
        : esc(a.title);
      return '<div class="art"><div class="t">' + title + '</div>' +
        '<div class="m"><span class="pill news">' + esc(a.source || '뉴스') + '</span>' +
        '<span>' + esc(a.date || '날짜 미상') + '</span></div></div>';
    }).join('');
  }

  return {
    focus: focus,
    load: function(){
      API.get('/api/insight/graph').then(function(g){
        graphData = g;
        graphLoaded = true;
        renderKeywords();
        renderArticles();
        render();
      }).catch(function(e){
        $id('kwList').innerHTML = '<div class="note">그래프를 불러오지 못했습니다 — ' + esc(e.message) + '</div>';
      });
    }
  };
})();
