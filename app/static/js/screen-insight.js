/* ⑥ 동향 인사이트 — 보고서 키워드 뉴스 + 기업·기술 지식맵.
   - /api/reports/{id}/news : 보고서 키워드 기반 6시간 캐시 뉴스 (그래프 포함)
   지식맵은 이 보고서 뉴스 그래프만 사용한다.
   챗봇 질문·조사 이력과는 연동하지 않는다 (팀 결정). */
Screens.s6 = (function(){
  var NS = 'http://www.w3.org/2000/svg';
  var VIEW_W = 720, VIEW_H = 500;
  var CX = VIEW_W / 2, CY = 235;
  var RING = { tech: 132, company: 214 };
  var COLORS = { biz: '#ea002c', company: '#f47725', tech: '#1baf7a' };
  /* 지식맵이 기사에서 기술·기관을 직접 뽑게 되면서 노드가 30개 안팎으로 늘었다.
     한 화면에 담을 수 있는 만큼 올려 잡고, 나머지는 '더 보기'로 넘긴다. */
  var MAX_VISIBLE = 28;
  /* 기사 수집 범위 — 서버(news.LOOKBACK_DAYS)와 같은 값을 쓴다.
     정확순은 이 기간 전체를 대상으로 일치율을 따진다. */
  var LOOKBACK_DAYS = 30;
  /* 지식맵을 만들 기사 수 — 서버(news.GRAPH_ARTICLES)와 같은 값.
     목록에 보이는 기사와 지식맵 재료를 1:1 로 맞춰야 상호 하이라이트가 어긋나지 않는다. */
  var GRAPH_ARTICLES = 10;

  var reports = [];
  var loadedOnce = false;
  var reportGraph = null;
  var graphData = { nodes:[], edges:[] };
  var pendingFocusIds = [];
  var selectedId = null;
  var showAll = false;
  var articleSort = 'accuracy';
  var articleItems = [];
  var articleNote = '';
  var articleContext = null;
  var graphContextLabel = '';
  var graphBasis = 'accuracy';
  /* 기사 ↔ 지식맵 양방향 연결
     nodeIdMap : 서버 노드 id('t:자율제조') → 화면 노드 id('tech:자율제조')
     activeArticle : 사용자가 고른 기사 인덱스 (그 기사의 노드를 강조)
     selectedId 가 있으면 기사 목록을 그 노드의 기사로 좁힌다. */
  var nodeIdMap = {};
  var activeArticle = null;

  /* ── 뷰(줌·팬) 상태 — viewBox 를 직접 조작한다 ── */
  var vb = null;          /* 현재 viewBox {x,y,w,h} */
  var homeVB = null;      /* '전체 보기' 기준 프레임 */
  var userView = false;   /* 사용자가 줌·팬을 조작했는지 (재렌더 시 시점 유지) */
  var panning = null;

  function $id(x){ return document.getElementById(x); }
  function setVB(x, y, w, h){
    vb = {x:x, y:y, w:w, h:h};
    $id('graph').setAttribute('viewBox', x + ' ' + y + ' ' + w + ' ' + h);
  }
  function zoomAt(factor, relX, relY){
    if(!vb) return;
    var w = Math.max(150, Math.min(4200, vb.w * factor));
    if(w === vb.w) return;
    userView = true;
    var k = w / vb.w, h = vb.h * k;
    var wx = vb.x + relX * vb.w, wy = vb.y + relY * vb.h;
    setVB(wx - relX * w, wy - relY * h, w, h);
  }
  function relPoint(e){
    var r = $id('graph').getBoundingClientRect();
    return { x:(e.clientX - r.left) / Math.max(r.width, 1),
             y:(e.clientY - r.top) / Math.max(r.height, 1) };
  }
  function fitView(nodes, pos, labels){
    var minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
    nodes.forEach(function(n){
      var r = nodeRadius(n), p = pos[n.id];
      minX = Math.min(minX, p.x - r); maxX = Math.max(maxX, p.x + r);
      minY = Math.min(minY, p.y - r); maxY = Math.max(maxY, p.y + r);
    });
    (labels || []).forEach(function(l){
      minX = Math.min(minX, l.x - l.w / 2); maxX = Math.max(maxX, l.x + l.w / 2);
      minY = Math.min(minY, l.y - l.h / 2); maxY = Math.max(maxY, l.y + l.h / 2);
    });
    if(minX > maxX){ minX = 0; minY = 0; maxX = VIEW_W; maxY = VIEW_H; }
    var pad = 28;
    homeVB = { x:minX - pad, y:minY - pad, w:maxX - minX + pad * 2, h:maxY - minY + pad * 2 };
    if(!userView) setVB(homeVB.x, homeVB.y, homeVB.w, homeVB.h);
  }
  function reducedMotion(){
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }
  function cleanId(value){
    return String(value || '').toLowerCase().replace(/\s+/g, '-').replace(/[^0-9a-z가-힣:_-]/g, '');
  }
  function canonicalId(type, label){
    return type + ':' + (cleanId(label) || 'unknown');
  }

  /* ── 보고서 뉴스 ──
     정렬은 서버가 이미 끝내서 보내 준다. 여기서 다시 정렬하지 않는다.
     예전에는 화면에서 한 번 더 정렬했는데, 날짜 표기가 '오늘 14:30' 처럼
     시각까지 붙도록 바뀐 뒤로 이 파서가 전부 0 을 돌려주면서
     서버 정렬 결과를 뒤엎고 있었다. articleTime 은 표시용 보조로만 남긴다. */
  function articleTime(a){
    if(a.published_at){
      var parsed = Date.parse(a.published_at);
      if(!isNaN(parsed)) return parsed;
    }
    var label = String(a.date || '').trim();
    var now = new Date();
    /* 서버 표기: '오늘 14:30' · '어제 09:05' · '3일 전 18:20' · '2026.08.10' */
    if(/^오늘/.test(label)) return now.getTime();
    if(/^어제/.test(label)) return now.getTime() - 86400000;
    var days = label.match(/^(\d+)일 전/);
    if(days) return now.getTime() - Number(days[1]) * 86400000;
    var ymd = label.match(/^(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})$/);
    if(ymd) return new Date(Number(ymd[1]), Number(ymd[2]) - 1, Number(ymd[3])).getTime();
    var monthDay = label.match(/^(\d{1,2})[/.](\d{1,2})$/);   /* 구버전 캐시 */
    if(monthDay){
      var guess = new Date(now.getFullYear(), Number(monthDay[1]) - 1, Number(monthDay[2]));
      if(guess > now) guess.setFullYear(now.getFullYear() - 1);
      return guess.getTime();
    }
    return 0;
  }

  function sortedArticles(){
    return articleItems.slice();
  }

  function updateSortButtons(){
    document.querySelectorAll('[data-news-sort]').forEach(function(button){
      var active = button.dataset.newsSort === articleSort;
      button.classList.toggle('active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
    });
  }

  /* 선택된 노드에 걸린 기사만 남긴다. 원래 순서(=서버 정렬)는 유지한다. */
  function filteredArticles(){
    var items = sortedArticles();
    if(!selectedId) return items.map(function(a, i){ return {item:a, idx:i}; });
    var node = graphData.nodes.filter(function(n){ return n.id === selectedId; })[0];
    var keep = {};
    ((node && node.articles_idx) || []).forEach(function(i){ keep[i] = 1; });
    return items.map(function(a, i){ return {item:a, idx:i}; })
                .filter(function(row){ return keep[row.idx]; });
  }

  function selectedLabel(){
    var node = graphData.nodes.filter(function(n){ return n.id === selectedId; })[0];
    return node ? node.label : '';
  }

  function drawArticles(){
    var box = $id('artList');
    var rows = filteredArticles();
    updateSortButtons();
    var banner = '';
    if(selectedId){
      banner = '<div class="note" id="artFilterNote" style="display:flex; align-items:center; gap:8px; justify-content:space-between;">' +
        '<span>지식맵 <b>' + esc(selectedLabel()) + '</b> 노드에 걸린 기사 ' + rows.length + '건</span>' +
        '<button type="button" class="btn ghost" id="artFilterClear">전체 기사 보기</button></div>';
    }
    if(!rows.length){
      box.innerHTML = banner + '<div class="note">' +
        esc(selectedId ? '이 노드에 연결된 기사가 목록에 없습니다.' : (articleNote || '검색 결과가 없습니다.')) + '</div>';
      bindArticleEvents(box);
      return;
    }
    box.innerHTML = banner + rows.map(function(row){
      var a = row.item;
      var url = a.link || a.url || '';
      var link = url
        ? '<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer" style="color:inherit; text-decoration:none;">' + esc(a.title) + '</a>'
        : esc(a.title);
      var score = typeof a.score === 'number' ? a.score : null;
      var on = activeArticle === row.idx;
      return '<div class="art' + (on ? ' active' : '') + '" data-art="' + row.idx + '"' +
        (on ? ' aria-current="true"' : '') + '><div class="t">' + link + '</div>' +
        '<div class="m"><span class="pill news">뉴스</span>' +
        '<span>' + esc(a.source || '뉴스') + (a.date ? ' · ' + esc(a.date) : '') + '</span>' +
        (a.keyword ? '<span style="color:var(--accent-deep); font-weight:600;">' + esc(a.keyword) + '</span>' : '') +
        (score == null ? '' : '<span class="rel"><span class="relbar"><i style="width:' + Math.round(score * 100) + '%"></i></span>정확도 ' + Math.round(score * 100) + '%</span>') +
        '</div></div>';
    }).join('');
    bindArticleEvents(box);
  }

  /* 기사를 클릭하면 그 기사에서 뽑힌 기업·기술 노드를 지식맵에서 강조한다.
     제목 링크 클릭은 그대로 기사 원문으로 보낸다. */
  function bindArticleEvents(box){
    var clear = $id('artFilterClear');
    if(clear) clear.onclick = function(){ selectNode(selectedId); };
    box.querySelectorAll('[data-art]').forEach(function(el){
      el.onclick = function(ev){
        if(ev.target.closest('a')) return;
        var idx = Number(el.dataset.art);
        activeArticle = activeArticle === idx ? null : idx;
        drawArticles();
        renderGraph();
      };
    });
  }

  /* 지금 강조해야 할 노드 = 선택한 기사가 가리키는 노드들 (화면 id 로 변환) */
  function activeArticleNodes(){
    if(activeArticle == null) return {};
    var a = articleItems[activeArticle];
    var out = {};
    ((a && a.node_ids) || []).forEach(function(serverId){
      var id = nodeIdMap[serverId];
      if(id) out[id] = 1;
    });
    return out;
  }

  function renderArticles(items, note){
    articleItems = Array.isArray(items) ? items : [];
    articleNote = note || '';
    activeArticle = null;
    drawArticles();
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

  function renderFetchInfo(d){
    var info = $id('insFetchInfo');
    if(!d || !d.fetched_at){ info.textContent = ''; return; }
    var when = new Date(d.fetched_at);
    var mm = String(when.getMinutes()).padStart(2, '0');
    var stamp = (when.getMonth() + 1) + '/' + when.getDate() + ' ' + when.getHours() + ':' + mm;
    var age = d.age_minutes == null ? '' :
      (d.age_minutes < 60 ? d.age_minutes + '분 전' : Math.floor(d.age_minutes / 60) + '시간 전');
    info.textContent = '마지막 수집: ' + stamp + (age ? ' (' + age + ')' : '') +
      ' · 최근 ' + rangeLabel(d) + ' 기사 수집' +
      ' · ' + d.refresh_hours + '시간마다 자동 갱신' + (d.from_cache ? ' · 저장된 결과' : ' · 방금 수집함');
  }

  /* 수집 범위를 사람이 읽는 말로 (30일 → '1개월') */
  function rangeLabel(d){
    var days = (d && Number(d.lookback_days)) || LOOKBACK_DAYS;
    if(days % 30 === 0) return (days / 30) + '개월';
    if(days % 7 === 0) return (days / 7) + '주';
    return days + '일';
  }
  function sortSubLabel(d){
    return articleSort === 'latest'
      ? '최신 발행 기사 우선'
      : '최근 ' + rangeLabel(d) + ' 중 검색어 일치율 우선';
  }

  function loading(msg){
    /* 새 결과를 부르면 기사 색인이 전부 바뀌므로 이전 선택은 여기서 버린다 */
    selectedId = null;
    activeArticle = null;
    $id('nodeDetail').style.display = 'none';
    $id('artList').innerHTML = '<div class="note">' + esc(msg) + '</div>';
  }
  function loadForReport(id, force){
    if(!id) return;
    articleContext = { type:'report', id:id };
    loading(force ? '최근 ' + rangeLabel(null) + ' 기사를 새로 수집하는 중…'
                  : '보고서 키워드로 최근 ' + rangeLabel(null) + ' 뉴스를 불러오는 중…');
    $id('insArtSub').textContent = sortSubLabel(null);
    API.get('/api/reports/' + id + '/news?limit=' + GRAPH_ARTICLES + '&days=' + LOOKBACK_DAYS + '&sort=' + articleSort +
            (force ? '&force=true' : '')).then(function(d){
      renderReportKeywords(d.keywords);
      renderArticles(d.items, d.reason || '관련 기사를 찾지 못했습니다.');
      renderFetchInfo(d);
      $id('insArtSub').textContent = sortSubLabel(d);
      reportGraph = d.graph || null;
      graphContextLabel = d.unit || '';
      graphBasis = d.graph_basis || articleSort;
      rebuildGraph();
      $id('insKwSub').textContent = (d.unit || '') + ' 보고서에서 자동 추출 · 클릭하면 해당 키워드로 검색';
    }).catch(function(e){
      renderArticles([], '뉴스를 불러오지 못했습니다: ' + e.message);
    });
  }
  function searchDirect(q){
    q = (q || $id('insQuery').value || '').trim();
    if(!q) return;
    articleContext = { type:'query', query:q };
    $id('insQuery').value = q;
    loading('‘' + q + '’ · 최근 ' + rangeLabel(null) + ' 기사 검색 중…');
    $id('insArtSub').textContent = '‘' + q + '’ · ' + sortSubLabel(null);
    API.get('/api/news?q=' + encodeURIComponent(q) + '&limit=' + GRAPH_ARTICLES + '&days=' + LOOKBACK_DAYS +
            '&sort=' + articleSort).then(function(d){
      renderArticles(d.items, d.reason || '검색 결과가 없습니다.');
      $id('insArtSub').textContent = '‘' + q + '’ · ' + sortSubLabel(d);
      reportGraph = d.graph || null;
      graphContextLabel = q + ' 검색';
      graphBasis = d.graph_basis || articleSort;
      rebuildGraph();
    }).catch(function(e){
      renderArticles([], '검색 실패: ' + e.message);
    });
  }

  /* ── 두 그래프 스키마 통합 ── */
  /* "01_사업단" 같은 파일 정렬용 접두 번호만 떼어 낸다.
     구분자를 +(하나 이상)로 둔 것이 핵심 — *(0개 이상)이면 "1팀_AI데이터센터" 의
     앞 숫자까지 먹어 "팀_AI데이터센터" 가 된다. 숫자가 이름의 일부인 경우다. */
  function stripIndexPrefix(name){
    return String(name || '').replace(/^\d+[_.\s-]+/, '');
  }
  function currentBizLabel(){
    if(graphContextLabel) return stripIndexPrefix(graphContextLabel);
    /* 중앙 노드 라벨 = 선택된 사업단명 */
    var sel = $id('insReportSel');
    var rep = reports.filter(function(r){ return r.id === sel.value; })[0];
    return rep ? stripIndexPrefix(rep.name) : '사업단';
  }
  function rebuildGraph(){
    var byId = {}, edges = [];
    var BIZ_ID = 'biz:main';                 /* 중앙 노드는 항상 하나로 통일 */
    var bizLabel = currentBizLabel();
    function addNode(node){
      var current = byId[node.id];
      if(!current){ byId[node.id] = node; return; }
      current.weight = Math.max(current.weight || 0, node.weight || 0);
      current.article_count = Math.max(current.article_count || 0, node.article_count || 0);
      current.touch_count = Math.max(current.touch_count || 0, node.touch_count || 0);
      current.query_count = Math.max(current.query_count || 0, node.query_count || 0);
      current.kind = current.kind || node.kind || '';
      current.articles = (current.articles || []).concat(node.articles || []).slice(0, 5);
      /* 같은 화면 id 로 합쳐지는 노드는 기사 색인도 합집합으로 모은다 */
      var seen = {};
      current.articles_idx = (current.articles_idx || []).concat(node.articles_idx || [])
        .filter(function(i){ if(seen[i]) return false; seen[i] = 1; return true; });
    }
    var reportIdMap = {};
    (reportGraph && reportGraph.nodes || []).forEach(function(n){
      var type = n.type === 'us' ? 'biz' : n.type;
      var id = type === 'biz' ? BIZ_ID : canonicalId(type, n.label);
      reportIdMap[n.id] = id;
      addNode({id:id, label:type === 'biz' ? bizLabel : n.label, type:type, weight:n.weight || 1,
               kind:n.kind || '', article_count:n.weight || 0, touch_count:0, query_count:0,
               articles:n.articles || [], articles_idx:n.articles_idx || [],
               search_queries:[], seed:false});
    });
    (reportGraph && reportGraph.links || []).forEach(function(l){
      if(!reportIdMap[l.source] || !reportIdMap[l.target]) return;
      /* relation_type 을 그대로 넘겨야 동시등장(점선)·약한 연결(옅은 선)이 구분돼 보인다 */
      edges.push({a:reportIdMap[l.source], b:reportIdMap[l.target], label:l.label || '기사 근거',
                  weight:l.weight || 1, relation_type:l.relation_type || 'extracted',
                  articles:l.articles || []});
    });
    nodeIdMap = reportIdMap;   /* 기사의 node_ids 를 화면 노드 id 로 옮길 때 쓴다 */
    graphData = { nodes:Object.keys(byId).map(function(id){ return byId[id]; }), edges:edges };
    /* 그래프가 새로 만들어지면 예전 선택은 무효 — 사라진 노드를 가리키지 않도록 */
    if(selectedId && !byId[selectedId]){ selectedId = null; $id('nodeDetail').style.display = 'none'; }
    renderGraph();
    drawArticles();
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
    /* 노드 수에 비례해 링 반지름을 넓혀 겹침을 막는다 (라벨 폭 감안 호 간격) */
    var rTech = Math.max(RING.tech, rings.tech.length * 86 / (2 * Math.PI));
    var rComp = Math.max(RING.company, rings.company.length * 108 / (2 * Math.PI), rTech + 92);
    var radii = { tech:rTech, company:rComp };
    Object.keys(rings).forEach(function(type){
      rings[type].forEach(function(n, i){
        var a = Math.PI * 2 * i / Math.max(rings[type].length, 1) - Math.PI / 2 + (type === 'company' ? 0.35 : 0);
        pos[n.id] = {x:CX + radii[type] * Math.cos(a), y:CY + radii[type] * Math.sin(a)};
      });
    });
    return pos;
  }
  function nodeRadius(n){
    if(n.type === 'biz'){
      /* 중앙 노드는 사업단명이 원 안에 들어가도록 반지름을 라벨 크기에 맞춘다 */
      var lines = wrapLabel(n.label, 7);
      var longest = lines.reduce(function(m, l){ return Math.max(m, l.length); }, 0);
      return Math.max(40, Math.min(60, longest * 5.8 + 10));
    }
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
    /* biz 는 사업단명을 원 안에 흰 글자로 그린다 */
    if(n.type === 'biz'){
      var bizLines = wrapLabel(n.label, 7);
      return {id:n.id, x:p.x, y:p.y, w:r * 2, h:r * 2, lines:bizLines, biz:true};
    }
    var lines = wrapLabel(n.label, 13);
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
        /* 월드 좌표는 줌·핏으로 감싸므로 넉넉한 범위로만 제한한다 */
        l.x = Math.max(CX - 1100, Math.min(CX + 1100, l.x));
        l.y = Math.max(CY - 900, Math.min(CY + 900, l.y));
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
      userView = false;
      setVB(0, 0, VIEW_W, VIEW_H);
      var empty = document.createElementNS(NS, 'text');
      empty.setAttribute('x', CX); empty.setAttribute('y', CY); empty.setAttribute('text-anchor', 'middle');
      empty.setAttribute('font-size', '12'); empty.setAttribute('fill', '#898781');
      empty.textContent = '표시할 조사 관계가 없습니다.';
      svg.appendChild(empty); return;
    }
    var nodes = visibleNodes(), byId = {}, pos = layout(nodes), labels = [];
    nodes.forEach(function(n){ byId[n.id] = n; });
    var fromArticle = activeArticleNodes();
    var hasArticleFocus = Object.keys(fromArticle).length > 0;
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
    function setDim(centerId){
      /* 호버한 노드와 이웃만 남기고 나머지는 흐리게 — 관계가 한눈에 읽힌다 */
      var nb = centerId ? neighborsOf(centerId) : null;
      svg.querySelectorAll('g.graph-node, g.graph-node-label').forEach(function(el){
        var id = el.dataset.node;
        var on = !centerId || id === centerId || (nb && nb[id]);
        el.setAttribute('opacity', on ? '1' : '0.28');
      });
      svg.querySelectorAll('.graph-label-guide').forEach(function(gl){
        var id = gl.dataset.node;
        var on = !centerId || id === centerId || (nb && nb[id]);
        gl.setAttribute('opacity', on ? '.8' : '.15');
      });
    }
    function bindInteraction(el, n){
      el.style.cursor = 'pointer';
      el.addEventListener('mousemove', function(ev){
        var details = '<b>' + esc(n.label) + '</b>' + (n.kind ? ' · ' + esc(n.kind) : '') +
          '<br>관련 기사 ' + (n.article_count || n.weight || 0) + '건';
        showTip(ev, details);
        setDim(n.id);
        svg.querySelectorAll('.graph-edge').forEach(function(line){
          var active = line.dataset.a === n.id || line.dataset.b === n.id;
          line.setAttribute('stroke', active ? '#ea002c' : '#e1e0d9');
          line.setAttribute('opacity', active ? '1' : '.2');
        });
      });
      el.addEventListener('mouseleave', function(){ hideTip(); resetEdges(); setDim(null); });
      el.addEventListener('click', function(){ selectNode(n.id); });
    }
    nodes.forEach(function(n){
      var p = pos[n.id], r = nodeRadius(n), label = labelsById[n.id], g = document.createElementNS(NS, 'g');
      g.setAttribute('class', 'graph-node');
      g.dataset.node = n.id;
      var title = document.createElementNS(NS, 'title');
      title.textContent = n.label; g.appendChild(title);
      if(!label.biz){
        var guide = document.createElementNS(NS, 'line');
        guide.setAttribute('x1', p.x); guide.setAttribute('y1', p.y);
        guide.setAttribute('x2', label.x); guide.setAttribute('y2', label.y);
        guide.setAttribute('class', 'graph-label-guide');
        guide.dataset.node = n.id;
        guideLayer.appendChild(guide);
      }
      var c = document.createElementNS(NS, 'circle');
      var marked = n.id === selectedId || fromArticle[n.id];
      c.setAttribute('cx', p.x); c.setAttribute('cy', p.y); c.setAttribute('r', r);
      c.setAttribute('fill', COLORS[n.type] || COLORS.company);
      c.setAttribute('stroke', marked ? '#ea002c' : '#fcfcfb');
      c.setAttribute('stroke-width', marked ? 3 : 2); c.dataset.node = n.id;
      if(n.seed && !n.touch_count) c.setAttribute('opacity', '0.55');
      g.appendChild(c);
      /* 기사를 고른 상태면 그 기사와 무관한 노드는 흐리게 — 어느 기사에서 나온 노드인지 보인다 */
      if(hasArticleFocus && !fromArticle[n.id] && n.type !== 'biz') g.setAttribute('opacity', '0.3');
      bindInteraction(g, n);
      nodeLayer.appendChild(g);
      var lg = document.createElementNS(NS, 'g');
      lg.setAttribute('class', 'graph-node-label' + (label.biz ? ' biz' : ''));
      lg.dataset.node = n.id;
      if(!label.biz){
        var rect = document.createElementNS(NS, 'rect');
        rect.setAttribute('x', label.x - label.w / 2); rect.setAttribute('y', label.y - label.h / 2);
        rect.setAttribute('width', label.w); rect.setAttribute('height', label.h);
        rect.setAttribute('rx', 8); lg.appendChild(rect);
      }
      var t = document.createElementNS(NS, 'text');
      t.setAttribute('x', label.x); t.setAttribute('text-anchor', 'middle');
      var lineH = label.biz ? 13 : 14;
      var startY = label.y - ((label.lines.length - 1) * lineH) / 2 + 4;
      label.lines.forEach(function(line, idx){
        var span = document.createElementNS(NS, 'tspan');
        span.setAttribute('x', label.x); span.setAttribute('y', startY + idx * lineH);
        span.textContent = line; t.appendChild(span);
      });
      lg.appendChild(t);
      if(hasArticleFocus && !fromArticle[n.id] && n.type !== 'biz') lg.setAttribute('opacity', '0.3');
      bindInteraction(lg, n);
      labelLayer.appendChild(lg);
    });
    $id('insGraphSub').textContent = (graphBasis === 'latest' ? '최신순' : '정확순') +
      ' 상위 ' + GRAPH_ARTICLES + '개 기사 · 노드 ' + graphData.nodes.length +
      '개 · 관계 ' + graphData.edges.length + '개' +
      (hasArticleFocus ? ' · 선택한 기사의 노드 강조 중' : ' · 노드를 누르면 그 기사만 봅니다');
    fitView(nodes, pos, labels);
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
  /* 노드를 고르면 왼쪽 기사 목록이 그 노드의 근거 기사만 남는다 (다시 누르면 해제). */
  function selectNode(id){
    selectedId = selectedId === id ? null : id;
    activeArticle = null;
    var box = $id('nodeDetail');
    if(!selectedId){ box.style.display = 'none'; renderGraph(); drawArticles(); return; }
    var n = graphData.nodes.filter(function(x){ return x.id === id; })[0];
    var question = (ASK[n.type] || ASK.tech).replace('{label}', n.label);
    var linked = (n.articles_idx || []).length;
    var evidence = (n.articles || []).slice(0, 3);
    var evidenceHtml = evidence.length
      ? '<div class="graph-evidence"><b>연결된 기사</b>' + evidence.map(function(title){
          return '<div>• ' + esc(title) + '</div>';
        }).join('') + '</div>'
      : '';
    box.innerHTML = '<b>' + esc(n.label) + '</b>' + (n.kind ? ' · ' + esc(n.kind) : '') +
      '<div style="margin-top:4px; color:var(--text-secondary);">관련 기사 ' + (n.article_count || n.weight || 0) + '건' +
      (linked ? ' · 왼쪽 목록을 이 노드의 ' + linked + '건으로 좁혔습니다' : '') + '</div>' +
      evidenceHtml +
      '<button class="btn primary" style="margin-top:8px;">챗봇에 물어보기</button>' +
      '<span style="font-size:12px; color:var(--text-muted); margin-left:8px;">질문은 입력만 되며 전송은 직접 확정합니다</span>';
    box.style.display = '';
    box.querySelector('button').onclick = function(){ goTo('s5'); if(Screens.s5 && Screens.s5.ask) Screens.s5.ask(question); };
    renderGraph();
    drawArticles();
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

  var bound = false;
  function bind(){
    if(bound) return; bound = true;
    $id('insSearchBtn').onclick = function(){ searchDirect(); };
    $id('insQuery').addEventListener('keydown', function(e){ if(e.key === 'Enter') searchDirect(); });
    $id('insReportSel').onchange = function(){ loadForReport(this.value); };
    $id('insRefreshBtn').onclick = function(){ loadForReport($id('insReportSel').value, true); };
    document.querySelectorAll('[data-news-sort]').forEach(function(button){
      button.onclick = function(){
        articleSort = button.dataset.newsSort === 'latest' ? 'latest' : 'accuracy';
        updateSortButtons();
        if(articleContext && articleContext.type === 'query') searchDirect(articleContext.query);
        else loadForReport((articleContext && articleContext.id) || $id('insReportSel').value, false);
      };
    });

    /* ── 지식맵 단독 줌·팬 ── */
    var svg = $id('graph');
    $id('gzIn').onclick = function(){ zoomAt(0.78, 0.5, 0.5); };
    $id('gzOut').onclick = function(){ zoomAt(1.28, 0.5, 0.5); };
    $id('gzFit').onclick = function(){
      userView = false;
      if(homeVB) setVB(homeVB.x, homeVB.y, homeVB.w, homeVB.h);
    };
    svg.addEventListener('wheel', function(e){
      e.preventDefault();
      var p = relPoint(e);
      zoomAt(e.deltaY > 0 ? 1.16 : 0.86, p.x, p.y);
    }, { passive:false });
    svg.addEventListener('dblclick', function(e){
      var p = relPoint(e);
      zoomAt(0.6, p.x, p.y);
    });
    svg.addEventListener('mousedown', function(e){
      /* 노드·라벨 위에서는 팬을 시작하지 않는다 — 클릭 선택과 충돌 방지 */
      if(e.target.closest && e.target.closest('.graph-node, .graph-node-label')) return;
      panning = { x:e.clientX, y:e.clientY };
      svg.classList.add('grabbing');
      e.preventDefault();
    });
    window.addEventListener('mousemove', function(e){
      if(!panning || !vb) return;
      var r = svg.getBoundingClientRect();
      var dx = (e.clientX - panning.x) / Math.max(r.width, 1) * vb.w;
      var dy = (e.clientY - panning.y) / Math.max(r.height, 1) * vb.h;
      panning = { x:e.clientX, y:e.clientY };
      userView = true;
      setVB(vb.x - dx, vb.y - dy, vb.w, vb.h);
    });
    window.addEventListener('mouseup', function(){
      panning = null;
      svg.classList.remove('grabbing');
    });
  }

  return {
    focus:focus,
    load:function(){
      bind();
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
