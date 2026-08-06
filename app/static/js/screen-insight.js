/* ⑥ 동향 인사이트 — 보고서 뉴스 검색 + 챗봇 조사 지식맵.
   - /api/reports/{id}/news : 보고서 키워드 기반 6시간 캐시 뉴스
   - /api/insight/graph     : 챗봇 질문으로 누적된 노드·관계
   두 결과를 하나의 기업·기술 그래프로 통합해 보여준다. */
Screens.s6 = (function(){
  var NS = 'http://www.w3.org/2000/svg';
  var VIEW_W = 720, VIEW_H = 500;
  var CX = VIEW_W / 2, CY = 235;
  var RING = { tech: 132, company: 214 };
  var COLORS = { biz: '#ea002c', company: '#f47725', tech: '#1baf7a' };
  var MAX_VISIBLE = 20;

  var reports = [];
  var loadedOnce = false;
  var knowledgeGraph = null;
  var reportGraph = null;
  var graphData = { nodes:[], edges:[] };
  var pendingFocusIds = [];
  var selectedId = null;
  var showAll = false;

  function $id(x){ return document.getElementById(x); }
  function reducedMotion(){
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }
  function cleanId(value){
    return String(value || '').toLowerCase().replace(/\s+/g, '-').replace(/[^0-9a-z가-힣:_-]/g, '');
  }
  function canonicalId(type, label){
    return type + ':' + (cleanId(label) || 'unknown');
  }

  /* ── 보고서 뉴스 ── */
  function renderArticles(items, note){
    var box = $id('artList');
    if(!items || !items.length){
      box.innerHTML = '<div class="note">' + esc(note || '검색 결과가 없습니다.') + '</div>';
      return;
    }
    box.innerHTML = items.map(function(a){
      var url = a.link || a.url || '';
      var link = url
        ? '<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer" style="color:inherit; text-decoration:none;">' + esc(a.title) + '</a>'
        : esc(a.title);
      var score = typeof a.score === 'number' ? a.score : null;
      return '<div class="art"><div class="t">' + link + '</div>' +
        '<div class="m"><span class="pill news">뉴스</span>' +
        '<span>' + esc(a.source || '뉴스') + (a.date ? ' · ' + esc(a.date) : '') + '</span>' +
        (a.keyword ? '<span style="color:var(--accent-deep); font-weight:600;">' + esc(a.keyword) + '</span>' : '') +
        (score == null ? '' : '<span class="rel"><span class="relbar"><i style="width:' + Math.round(score * 100) + '%"></i></span>관련도 ' + score.toFixed(2) + '</span>') +
        '</div></div>';
    }).join('');
  }

  function renderReportKeywords(list){
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

  function renderResearchKeywords(){
    var box = $id('kwList');
    var nodes = knowledgeGraph && knowledgeGraph.nodes ? knowledgeGraph.nodes : [];
    var researched = nodes.filter(function(n){ return (n.touch_count || 0) > 0; })
      .sort(function(a, b){ return (b.query_count || 0) - (a.query_count || 0) || (b.touch_count || 0) - (a.touch_count || 0); })
      .slice(0, 8);
    if(!researched.length){
      box.innerHTML = '<span style="font-size:12.5px; color:var(--text-muted);">아직 챗봇 조사 이력이 없습니다. 지식·동향 질문을 하면 여기에 쌓입니다.</span>';
      return;
    }
    box.innerHTML = researched.map(function(n){
      return '<span class="kw"><b>' + esc(n.label) + '</b><span class="n">조사 ' + (n.query_count || 0) + '회 · 기사 ' + (n.article_count || 0) + '</span></span>';
    }).join('');
  }

  function renderFetchInfo(d){
    var info = $id('insFetchInfo');
    if(!d || !d.fetched_at){ info.textContent = ''; return; }
    var when = new Date(d.fetched_at);
    var mm = String(when.getMinutes()).padStart(2, '0');
    var stamp = (when.getMonth() + 1) + '/' + when.getDate() + ' ' + when.getHours() + ':' + mm;
    var age = d.age_minutes == null ? '' :
      (d.age_minutes < 60 ? d.age_minutes + '분 전' : Math.floor(d.age_minutes / 60) + '시간 전');
    info.textContent = '마지막 수집: ' + stamp + (age ? ' (' + age + ')' : '') +
      ' · ' + d.refresh_hours + '시간마다 자동 갱신' + (d.from_cache ? ' · 저장된 결과' : ' · 방금 수집함');
  }

  function loading(msg){
    $id('artList').innerHTML = '<div class="note">' + esc(msg) + '</div>';
  }
  function loadForReport(id, force){
    if(!id) return;
    loading(force ? '뉴스를 새로 수집하는 중…' : '보고서 키워드로 뉴스를 불러오는 중…');
    $id('insArtSub').textContent = '관련도순 정렬';
    API.get('/api/reports/' + id + '/news?limit=12' + (force ? '&force=true' : '')).then(function(d){
      renderReportKeywords(d.keywords);
      renderArticles(d.items, d.reason || '관련 기사를 찾지 못했습니다.');
      renderFetchInfo(d);
      reportGraph = d.graph || null;
      rebuildGraph();
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

  /* ── 두 그래프 스키마 통합 ── */
  function rebuildGraph(){
    var byId = {}, edges = [];
    function addNode(node){
      var current = byId[node.id];
      if(!current){ byId[node.id] = node; return; }
      current.weight = Math.max(current.weight || 0, node.weight || 0);
      current.article_count = Math.max(current.article_count || 0, node.article_count || 0);
      current.touch_count = Math.max(current.touch_count || 0, node.touch_count || 0);
      current.query_count = Math.max(current.query_count || 0, node.query_count || 0);
      current.articles = (current.articles || []).concat(node.articles || []).slice(0, 5);
    }
    (knowledgeGraph && knowledgeGraph.nodes || []).forEach(function(n){
      addNode({
        id:n.id, label:n.label, type:n.type === 'biz' ? 'biz' : n.type,
        desc:n.desc || '', seed:!!n.seed, touch_count:n.touch_count || 0,
        query_count:n.query_count || 0, article_count:n.article_count || 0,
        weight:n.touch_count || n.article_count || 1, search_queries:n.search_queries || [],
        last_seen:n.last_seen || '', articles:[]
      });
    });
    (knowledgeGraph && knowledgeGraph.edges || []).forEach(function(e){
      edges.push({a:e.a, b:e.b, label:e.label || '함께 언급', weight:e.weight || 1,
                  relation_type:e.relation_type || 'co_occurrence', articles:e.articles || []});
    });

    var reportIdMap = {};
    (reportGraph && reportGraph.nodes || []).forEach(function(n){
      var type = n.type === 'us' ? 'biz' : n.type;
      var id = type === 'biz' ? canonicalId('biz', n.label || '우리 사업') : canonicalId(type, n.label);
      reportIdMap[n.id] = id;
      addNode({id:id, label:n.label, type:type, weight:n.weight || 1,
               article_count:n.weight || 0, touch_count:0, query_count:0,
               articles:n.articles || [], search_queries:[], seed:false});
    });
    (reportGraph && reportGraph.links || []).forEach(function(l){
      if(!reportIdMap[l.source] || !reportIdMap[l.target]) return;
      edges.push({a:reportIdMap[l.source], b:reportIdMap[l.target], label:l.label || '기사 근거',
                  weight:l.weight || 1, relation_type:'extracted', articles:l.articles || []});
    });
    graphData = { nodes:Object.keys(byId).map(function(id){ return byId[id]; }), edges:edges };
    renderGraph();
  }

  function neighborsOf(id){
    var out = {};
    graphData.edges.forEach(function(e){
      if(e.a === id) out[e.b] = 1;
      if(e.b === id) out[e.a] = 1;
    });
    return out;
  }
  function visibleNodes(){
    var nodes = graphData.nodes.slice().sort(function(a, b){
      return (b.touch_count || b.weight || 0) - (a.touch_count || a.weight || 0);
    });
    if(showAll || nodes.length <= MAX_VISIBLE) return nodes;
    var keep = {};
    nodes.slice(0, MAX_VISIBLE).forEach(function(n){ keep[n.id] = 1; });
    [selectedId].concat(pendingFocusIds).forEach(function(id){
      if(!id) return;
      keep[id] = 1;
      Object.keys(neighborsOf(id)).forEach(function(nid){ keep[nid] = 1; });
    });
    return nodes.filter(function(n){ return keep[n.id]; });
  }
  function layout(nodes){
    var pos = {}, rings = {tech:[], company:[]};
    nodes.forEach(function(n){
      if(n.type === 'biz') pos[n.id] = {x:CX, y:CY};
      else (rings[n.type] || rings.company).push(n);
    });
    Object.keys(rings).forEach(function(type){
      rings[type].forEach(function(n, i){
        var a = Math.PI * 2 * i / Math.max(rings[type].length, 1) - Math.PI / 2 + (type === 'company' ? 0.35 : 0);
        pos[n.id] = {x:CX + RING[type] * Math.cos(a), y:CY + RING[type] * Math.sin(a)};
      });
    });
    return pos;
  }
  function nodeRadius(n){
    if(n.type === 'biz') return 39;
    return Math.min(29, 14 + Math.sqrt(n.touch_count || n.weight || 1) * 3.2);
  }
  function wrapLabel(value, maxChars){
    var text = String(value || ''), words = text.split(/([\s_-]+)/).filter(Boolean);
    var lines = [], line = '';
    words.forEach(function(word){
      if(word.length > maxChars && !/[\s_-]/.test(word)){
        if(line){ lines.push(line); line = ''; }
        while(word.length > maxChars){ lines.push(word.slice(0, maxChars)); word = word.slice(maxChars); }
        line = word;
      }else if((line + word).length > maxChars && line.trim()){
        lines.push(line.trim()); line = word.replace(/^[\s_-]+/, '');
      }else line += word;
    });
    if(line.trim()) lines.push(line.trim());
    if(lines.length > 3){ lines = lines.slice(0, 3); lines[2] = lines[2].slice(0, Math.max(1, maxChars - 1)) + '…'; }
    return lines.length ? lines : ['이름 없음'];
  }
  function labelMetrics(n, p, r){
    var lines = wrapLabel(n.label, n.type === 'biz' ? 9 : 13);
    if(n.type === 'biz') return {id:n.id, x:p.x, y:p.y, w:70, h:lines.length * 12, lines:lines, biz:true};
    var longest = lines.reduce(function(m, line){ return Math.max(m, line.length); }, 0);
    var w = Math.max(58, Math.min(150, longest * 7.2 + 20));
    var h = lines.length * 14 + 10;
    var dx = p.x - CX, dy = p.y - CY, len = Math.sqrt(dx * dx + dy * dy) || 1;
    var ux = dx / len, uy = dy / len, x, y;
    if(Math.abs(ux) > .68){
      x = p.x + ux * (r + 11 + w / 2); y = p.y;
    }else{
      x = p.x; y = p.y + uy * (r + 11 + h / 2);
    }
    return {id:n.id, x:x, y:y, w:w, h:h, lines:lines, biz:false};
  }
  function boxesOverlap(a, b, pad){
    return Math.abs(a.x - b.x) < (a.w + b.w) / 2 + pad &&
           Math.abs(a.y - b.y) < (a.h + b.h) / 2 + pad;
  }
  function relaxLabels(labels, nodes, pos){
    var movable = labels.filter(function(l){ return !l.biz; });
    var nodeBoxes = nodes.map(function(n){
      var r = nodeRadius(n);
      return {id:n.id, x:pos[n.id].x, y:pos[n.id].y, w:r * 2, h:r * 2};
    });
    for(var step=0; step<32; step++){
      var moved = false;
      for(var i=0; i<movable.length; i++){
        for(var j=i+1; j<movable.length; j++){
          var a = movable[i], b = movable[j];
          if(!boxesOverlap(a, b, 5)) continue;
          var dx = a.x - b.x, dy = a.y - b.y;
          if(Math.abs(dx) > Math.abs(dy)){
            var sx = dx >= 0 ? 2.4 : -2.4; a.x += sx; b.x -= sx;
          }else{
            var sy = dy >= 0 ? 2.4 : -2.4; a.y += sy; b.y -= sy;
          }
          moved = true;
        }
      }
      movable.forEach(function(l){
        nodeBoxes.forEach(function(node){
          if(node.id === l.id || !boxesOverlap(l, node, 7)) return;
          var dx = l.x - node.x, dy = l.y - node.y;
          if(Math.abs(dx) > Math.abs(dy)) l.x += dx >= 0 ? 3.2 : -3.2;
          else l.y += dy >= 0 ? 3.2 : -3.2;
          moved = true;
        });
      });
      movable.forEach(function(l){
        l.x = Math.max(l.w / 2 + 9, Math.min(VIEW_W - l.w / 2 - 9, l.x));
        l.y = Math.max(l.h / 2 + 9, Math.min(VIEW_H - l.h / 2 - 9, l.y));
      });
      if(!moved) break;
    }
  }
  function edgeStyle(e){
    if(e.relation_type === 'seed') return {stroke:'#c3c2b7', dash:'', opacity:0.45};
    if(e.relation_type === 'co_occurrence') return {stroke:'#c3c2b7', dash:'4 3', opacity:1};
    return {stroke:'#a29699', dash:'', opacity:1};
  }

  function renderGraph(){
    var svg = $id('graph');
    svg.innerHTML = '';
    if(!graphData.nodes.length){
      var empty = document.createElementNS(NS, 'text');
      empty.setAttribute('x', CX); empty.setAttribute('y', CY); empty.setAttribute('text-anchor', 'middle');
      empty.setAttribute('font-size', '12'); empty.setAttribute('fill', '#898781');
      empty.textContent = '표시할 조사 관계가 없습니다.';
      svg.appendChild(empty); return;
    }
    var nodes = visibleNodes(), byId = {}, pos = layout(nodes), labels = [];
    nodes.forEach(function(n){ byId[n.id] = n; });
    var edgeLayer = document.createElementNS(NS, 'g');
    var guideLayer = document.createElementNS(NS, 'g');
    var nodeLayer = document.createElementNS(NS, 'g');
    var labelLayer = document.createElementNS(NS, 'g');
    edgeLayer.setAttribute('class', 'graph-edge-layer');
    guideLayer.setAttribute('class', 'graph-guide-layer');
    nodeLayer.setAttribute('class', 'graph-node-layer');
    labelLayer.setAttribute('class', 'graph-label-layer');
    svg.appendChild(edgeLayer); svg.appendChild(guideLayer); svg.appendChild(nodeLayer); svg.appendChild(labelLayer);
    graphData.edges.forEach(function(e){
      if(!byId[e.a] || !byId[e.b]) return;
      var st = edgeStyle(e), ln = document.createElementNS(NS, 'line');
      ln.setAttribute('x1', pos[e.a].x); ln.setAttribute('y1', pos[e.a].y);
      ln.setAttribute('x2', pos[e.b].x); ln.setAttribute('y2', pos[e.b].y);
      ln.setAttribute('stroke', st.stroke); ln.setAttribute('opacity', st.opacity);
      ln.setAttribute('stroke-width', Math.min(1.5 + (e.weight - 1) * 0.45, 3.5));
      if(st.dash) ln.setAttribute('stroke-dasharray', st.dash);
      ln.setAttribute('class', 'graph-edge');
      ln.dataset.stroke = st.stroke; ln.dataset.opacity = st.opacity;
      ln.dataset.a = e.a; ln.dataset.b = e.b;
      edgeLayer.appendChild(ln);
    });
    nodes.forEach(function(n){ labels.push(labelMetrics(n, pos[n.id], nodeRadius(n))); });
    relaxLabels(labels, nodes, pos);
    var labelsById = {};
    labels.forEach(function(l){ labelsById[l.id] = l; });
    function resetEdges(){
      svg.querySelectorAll('.graph-edge').forEach(function(line){
        line.setAttribute('stroke', line.dataset.stroke);
        line.setAttribute('opacity', line.dataset.opacity);
      });
    }
    function bindInteraction(el, n){
      el.style.cursor = 'pointer';
      el.addEventListener('mousemove', function(ev){
        var details = '<b>' + esc(n.label) + '</b><br>조사 ' + (n.query_count || 0) + '회 · 기사 ' + (n.article_count || n.weight || 0) + '건';
        showTip(ev, details);
        svg.querySelectorAll('.graph-edge').forEach(function(line){
          var active = line.dataset.a === n.id || line.dataset.b === n.id;
          line.setAttribute('stroke', active ? '#ea002c' : '#e1e0d9');
          line.setAttribute('opacity', active ? '1' : '.34');
        });
      });
      el.addEventListener('mouseleave', function(){ hideTip(); resetEdges(); });
      el.addEventListener('click', function(){ selectNode(n.id); });
    }
    nodes.forEach(function(n){
      var p = pos[n.id], r = nodeRadius(n), label = labelsById[n.id], g = document.createElementNS(NS, 'g');
      g.setAttribute('class', 'graph-node');
      var title = document.createElementNS(NS, 'title');
      title.textContent = n.label; g.appendChild(title);
      if(!label.biz){
        var guide = document.createElementNS(NS, 'line');
        guide.setAttribute('x1', p.x); guide.setAttribute('y1', p.y);
        guide.setAttribute('x2', label.x); guide.setAttribute('y2', label.y);
        guide.setAttribute('class', 'graph-label-guide'); guideLayer.appendChild(guide);
      }
      var c = document.createElementNS(NS, 'circle');
      c.setAttribute('cx', p.x); c.setAttribute('cy', p.y); c.setAttribute('r', r);
      c.setAttribute('fill', COLORS[n.type] || COLORS.company);
      c.setAttribute('stroke', n.id === selectedId ? '#ea002c' : '#fcfcfb');
      c.setAttribute('stroke-width', n.id === selectedId ? 3 : 2); c.dataset.node = n.id;
      if(n.seed && !n.touch_count) c.setAttribute('opacity', '0.55');
      g.appendChild(c);
      var lg = document.createElementNS(NS, 'g');
      lg.setAttribute('class', 'graph-node-label' + (label.biz ? ' biz' : ''));
      if(!label.biz){
        var rect = document.createElementNS(NS, 'rect');
        rect.setAttribute('x', label.x - label.w / 2); rect.setAttribute('y', label.y - label.h / 2);
        rect.setAttribute('width', label.w); rect.setAttribute('height', label.h);
        rect.setAttribute('rx', 8); lg.appendChild(rect);
      }
      var t = document.createElementNS(NS, 'text');
      t.setAttribute('x', label.x); t.setAttribute('text-anchor', 'middle');
      var lineH = label.biz ? 12 : 14;
      var startY = label.y - ((label.lines.length - 1) * lineH) / 2 + 4;
      label.lines.forEach(function(line, idx){
        var span = document.createElementNS(NS, 'tspan');
        span.setAttribute('x', label.x); span.setAttribute('y', startY + idx * lineH);
        span.textContent = line; t.appendChild(span);
      });
      lg.appendChild(t);
      bindInteraction(g, n); bindInteraction(lg, n);
      nodeLayer.appendChild(g); labelLayer.appendChild(lg);
    });
    $id('insGraphSub').textContent = '노드 ' + graphData.nodes.length + '개 · 관계 ' + graphData.edges.length + '개';
    renderMore(nodes.length);
    applyFocus();
  }

  function renderMore(shown){
    var box = $id('graphMore'), total = graphData.nodes.length;
    if(showAll && total > MAX_VISIBLE){
      box.innerHTML = '<button class="btn ghost" style="margin-top:8px;">상위 ' + MAX_VISIBLE + '개만 보기</button>';
      box.querySelector('button').onclick = function(){ showAll = false; renderGraph(); };
    }else if(total > shown){
      box.innerHTML = '<button class="btn ghost" style="margin-top:8px;">관련 노드 ' + (total - shown) + '개 더 보기</button>';
      box.querySelector('button').onclick = function(){ showAll = true; renderGraph(); };
    }else box.innerHTML = '';
  }

  var ASK = {
    company:'{label}의 최근 기술 개발과 사업 동향을 알려줘',
    tech:'{label}의 최근 산업 동향과 주요 기업을 알려줘',
    biz:'{label}과 연관된 최근 외부 동향을 알려줘'
  };
  function selectNode(id){
    selectedId = selectedId === id ? null : id;
    var box = $id('nodeDetail');
    if(!selectedId){ box.style.display = 'none'; renderGraph(); return; }
    var n = graphData.nodes.filter(function(x){ return x.id === id; })[0];
    var question = (ASK[n.type] || ASK.tech).replace('{label}', n.label);
    box.innerHTML = '<b>' + esc(n.label) + '</b>' + (n.desc ? ' · ' + esc(n.desc) : '') +
      '<div style="margin-top:4px; color:var(--text-secondary);">조사 ' + (n.query_count || 0) + '회 · 기사 ' + (n.article_count || n.weight || 0) + '건</div>' +
      '<button class="btn primary" style="margin-top:8px;">챗봇에 물어보기</button>' +
      '<span style="font-size:12px; color:var(--text-muted); margin-left:8px;">질문은 입력만 되며 전송은 직접 확정합니다</span>';
    box.style.display = '';
    box.querySelector('button').onclick = function(){ goTo('s5'); if(Screens.s5 && Screens.s5.ask) Screens.s5.ask(question); };
    renderGraph();
  }
  function focus(ids){ pendingFocusIds = ids || []; if(graphData.nodes.length) renderGraph(); }
  function applyFocus(){
    if(!pendingFocusIds.length) return;
    var svg = $id('graph');
    pendingFocusIds.forEach(function(id){
      var c = svg.querySelector('circle[data-node="' + id + '"]');
      if(!c) return;
      c.setAttribute('stroke', '#ea002c'); c.setAttribute('stroke-width', 3.5);
      if(!reducedMotion()){
        var anim = document.createElementNS(NS, 'animate'), base = +c.getAttribute('r');
        anim.setAttribute('attributeName', 'r'); anim.setAttribute('values', base + ';' + (base + 4) + ';' + base);
        anim.setAttribute('dur', '1.1s'); anim.setAttribute('repeatCount', '3'); c.appendChild(anim);
      }
    });
    pendingFocusIds = [];
  }

  function loadKnowledgeGraph(){
    return API.get('/api/insight/graph').then(function(g){
      knowledgeGraph = g; renderResearchKeywords(); rebuildGraph();
    }).catch(function(e){
      knowledgeGraph = {nodes:[], edges:[], articles:{}};
      $id('kwList').innerHTML = '<span style="font-size:12.5px; color:var(--text-muted);">챗봇 조사 이력을 불러오지 못했습니다: ' + esc(e.message) + '</span>';
      rebuildGraph();
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
    focus:focus,
    load:function(){
      bind();
      loadKnowledgeGraph();
      var sel = $id('insReportSel'), keep = sel.value;
      API.get('/api/reports').then(function(r){
        reports = r;
        sel.innerHTML = reports.map(function(x){ return '<option value="' + x.id + '">' + esc(x.name) + '</option>'; }).join('');
        if(!reports.length){
          renderReportKeywords([]);
          renderArticles([], '업로드된 보고서가 없습니다. 위 검색창에 키워드를 직접 입력하세요.');
          reportGraph = null; rebuildGraph(); return;
        }
        if(keep && reports.some(function(x){ return x.id === keep; })){
          sel.value = keep;
          if(loadedOnce) return;
        }
        loadedOnce = true; loadForReport(sel.value);
      });
    }
  };
})();
