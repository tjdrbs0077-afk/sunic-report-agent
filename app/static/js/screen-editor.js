/* ④ 페이지 편집 — v4 캔버스 편집기 이식 + Undo/Redo
   + 양식 오류 자동 수정(4) + 슬라이드 내용 직접 편집(5) */
Screens.s4 = (function(){
  var W = 10.833333, H = 7.5;
  var LABELS = {
    frame: '전체 프레임', title: '상단 제목', sidebar: '좌측 사업단명', body: '본문',
    table_type1: '협의 경과 표', table_type3_top: '상단 표', table_type3_bottom: '하단 표',
    timeline: '타임라인', footnote: '각주'
  };
  var STD_BULLETS = ['1.', '1)', '❑', '–', '•'];

  var reports = [], profile = null, payload = null, issues = null, fonts = null;
  var curSlide = 1, selectedKey = 'title';
  var overrides = { global: {}, slides: {} };
  var undoStack = [], redoStack = [], editingField = false;

  function $id(x){ return document.getElementById(x); }
  function clone(x){ return JSON.parse(JSON.stringify(x)); }
  function slide(){ return payload.slides[curSlide - 1]; }
  function deepMerge(a, b){
    var o = clone(a);
    Object.keys(b || {}).forEach(function(k){
      var v = b[k];
      o[k] = (v && typeof v === 'object' && !Array.isArray(v) && o[k] && typeof o[k] === 'object')
        ? deepMerge(o[k], v) : clone(v);
    });
    return o;
  }
  function effective(){
    return deepMerge(deepMerge(profile, overrides.global || {}), (overrides.slides || {})[String(curSlide)] || {});
  }
  function scope(){ return $id('edScope').value; }
  function ensurePatch(){
    if(scope() === 'global' || selectedKey === 'frame') return overrides.global || (overrides.global = {});
    overrides.slides || (overrides.slides = {});
    var key = String(curSlide);
    return overrides.slides[key] || (overrides.slides[key] = {});
  }
  function objectPatch(){
    var root = ensurePatch();
    return root[selectedKey] || (root[selectedKey] = {});
  }
  function activeKeys(){
    var t = slide().template_type;
    var out = ['frame', 'title', 'sidebar', 'body'];
    if(t === 1) out.push('table_type1', 'timeline');
    if(t === 3) out.push('table_type3_top', 'table_type3_bottom');
    out.push('footnote');
    return out;
  }
  function normalizeCfg(key, cfg){
    var c = clone(cfg || {});
    function def(k, v){ if(c[k] === undefined || c[k] === null) c[k] = v; }
    if(key === 'timeline'){ def('x', 2.7); def('y', 6.25); def('w', 7.65); def('h', .8); def('font_size', 9); def('fill', 'transparent'); def('text_color', '#000000'); def('font_ea', '나눔스퀘어'); }
    if(key === 'frame'){ def('font_size', c.header_font_size || 14); def('fill', c.header_fill || '#B7D3EE'); def('text_color', c.header_text_color || '#000000'); def('font_ea', c.header_font_ea || '나눔스퀘어 ExtraBold'); c.bold = true; }
    if(key.indexOf('table_') === 0){ def('font_size', c.body_font_size || 10); def('fill', c.header_fill || '#DCE6F2'); def('text_color', '#000000'); def('font_ea', '나눔스퀘어'); c.bold = false; }
    if(key === 'body'){ def('font_size', (c.level_sizes || [14])[0]); def('bold', false); }
    return c;
  }
  function pctX(x){ return x / W * 100; }
  function pctY(y){ return y / H * 100; }
  function fontPx(pt, canvas){ return Math.max(6, pt * canvas.clientWidth / (W * 72)); }

  /* ── Undo / Redo (스택 50단계) — 좌표·서식(layout)과 글 내용(content) 모두 ── */
  function snapLayout(){ return { kind: 'layout', overrides: clone(overrides) }; }
  function snapContent(){ return { kind: 'content', slides: clone(payload.slides) }; }

  function pushUndo(){
    undoStack.push(snapLayout());
    if(undoStack.length > 50) undoStack.shift();
    redoStack = [];
  }
  function pushUndoContent(){
    if(!payload) return;
    undoStack.push(snapContent());
    if(undoStack.length > 50) undoStack.shift();
    redoStack = [];
  }

  function applySnapshot(entry){
    if(entry.kind === 'layout'){
      overrides = entry.overrides;
      renderAll();
      return Promise.resolve();
    }
    payload.slides = entry.slides;
    return API.put('/api/reports/' + payload.unit.id + '/slides', { slides: entry.slides })
      .then(function(res){ issues = res.issues; renderAll(); })
      .catch(function(e){ $id('edStatus').textContent = '되돌리기 저장 실패: ' + e.message; });
  }

  function undo(){
    if(!undoStack.length) return;
    var entry = undoStack.pop();
    redoStack.push(entry.kind === 'layout' ? snapLayout() : snapContent());
    var label = entry.kind === 'layout' ? '좌표·서식' : '글 내용';
    applySnapshot(entry).then(function(){
      $id('edStatus').textContent = '실행 취소 — ' + label + ' (남은 기록 ' + undoStack.length + '단계)';
    });
  }
  function redo(){
    if(!redoStack.length) return;
    var entry = redoStack.pop();
    undoStack.push(entry.kind === 'layout' ? snapLayout() : snapContent());
    applySnapshot(entry).then(function(){
      $id('edStatus').textContent = '다시 실행 — ' + (entry.kind === 'layout' ? '좌표·서식' : '글 내용');
    });
  }

  /* ── 좌측: 페이지 · 개체 목록 ── */
  function moveSlide(delta){
    if(!payload || !payload.slides || !payload.slides.length) return;
    var next = Math.max(1, Math.min(payload.slides.length, curSlide + delta));
    if(next === curSlide) return;
    curSlide = next;
    renderAll();
  }
  function renderPageStepper(){
    var total = payload && payload.slides ? payload.slides.length : 0;
    $id('edPageCounter').textContent = total ? curSlide + ' / ' + total : '0 / 0';
    $id('edPrevSlide').disabled = !total || curSlide <= 1;
    $id('edNextSlide').disabled = !total || curSlide >= total;
  }
  function renderNav(){
    var nav = $id('edSlideNav');
    nav.innerHTML = payload.slides.map(function(s){
      var cls = s.slide_number === curSlide ? 'btn primary' : 'btn ghost';
      var bad = issues && issues.issues.some(function(i){ return i.slide_no === s.slide_number; });
      return '<button class="' + cls + '" style="padding:3px 8px; font-size:11px;" data-n="' + s.slide_number + '">' +
        s.slide_number + (bad ? ' ⚠' : '') + '</button>';
    }).join('');
    nav.querySelectorAll('button').forEach(function(b){
      b.onclick = function(){ curSlide = +b.dataset.n; renderAll(); };
    });
    renderPageStepper();
  }
  function renderObjectList(){
    var keys = activeKeys();
    if(keys.indexOf(selectedKey) < 0) selectedKey = keys[0];
    var box = $id('edObjectList');
    box.innerHTML = keys.map(function(k){
      var cls = k === selectedKey ? 'btn primary' : 'btn ghost';
      return '<button class="' + cls + '" style="padding:8px 12px; font-size:12.5px;" data-key="' + k + '">' + LABELS[k] + '</button>';
    }).join('');
    box.querySelectorAll('button').forEach(function(b){
      b.onclick = function(){ selectedKey = b.dataset.key; renderObjectList(); renderCanvas(); loadProps(); renderTextPanel(); };
    });
  }

  /* ── 캔버스 ── */
  function miniTable(spec){
    if(!spec) return '';
    return '<table style="font-size:8px; width:100%; border-collapse:collapse;"><thead><tr>' +
      spec.headers.map(function(h){ return '<th style="padding:1px 4px; border-bottom:1px solid var(--grid);">' + esc(h) + '</th>'; }).join('') +
      '</tr></thead><tbody>' +
      spec.rows.slice(0, 5).map(function(row){
        return '<tr>' + row.map(function(c){ return '<td style="padding:1px 4px; border-bottom:1px solid var(--grid);">' + esc(c) + '</td>'; }).join('') + '</tr>';
      }).join('') + '</tbody></table>';
  }
  function objHtml(key, cfg, content, z){
    var c = normalizeCfg(key, cfg);
    var fill = key === 'frame' ? 'transparent' : (c.fill && c.fill !== 'transparent' ? c.fill : 'transparent');
    return '<div class="ed-obj' + (key === 'frame' ? ' frame' : '') + (key === selectedKey ? ' selected' : '') + '"' +
      ' data-key="' + key + '" data-pt="' + (c.font_size || 12) + '"' +
      ' style="left:' + pctX(c.x) + '%;top:' + pctY(c.y) + '%;width:' + pctX(c.w) + '%;height:' + pctY(c.h) + '%;' +
      'z-index:' + z + ';color:' + (c.text_color || '#000') + ';background:' + fill + ';' +
      'font-weight:' + (c.bold ? '700' : '400') + ';">' + content + '<span class="ed-handle"></span></div>';
  }
  /* 편집 가능한 텍스트 조각 — 더블클릭하면 그 자리에서 수정 */
  function editable(field, index, text){
    return '<span class="ed-line" data-field="' + field + '"' +
      (index == null ? '' : ' data-index="' + index + '"') + '>' + esc(text) + '</span>';
  }
  function renderCanvas(){
    var canvas = $id('edCanvas');
    var s = slide(), c = effective();
    var html = '';
    var f = normalizeCfg('frame', c.frame);
    var sidePct = f.sidebar_w / f.w * 100, headPct = f.header_h / f.h * 100;
    html += objHtml('frame', f,
      '<div style="height:' + headPct + '%;display:grid;grid-template-columns:' + sidePct + '% 1fr;align-items:center;text-align:center;background:' + f.fill + ';color:' + (f.header_text_color || '#000') + ';font-weight:700;border:1px solid ' + (f.border_color || '#7F7F7F') + ';"><div>구 분</div><div>주요 내용</div></div>' +
      '<div style="position:absolute;top:' + headPct + '%;bottom:0;left:0;right:0;border:1px solid ' + (f.border_color || '#7F7F7F') + ';border-top:none;"></div>' +
      '<div style="position:absolute;top:0;bottom:0;left:' + sidePct + '%;width:1px;background:' + (f.border_color || '#7F7F7F') + ';"></div>', 1);
    html += objHtml('title', c.title, editable('page_title', null, s.page_title), 5);
    html += objHtml('sidebar', c.sidebar,
      '<div style="height:100%;display:flex;align-items:center;justify-content:center;text-align:center;white-space:pre-line;">' +
      editable('sidebar', null, s.sidebar) + '</div>', 4);
    /* 번호는 파워포인트처럼 증가시킨다 — 1. 2. 3. / 1) 2), 하위 단계가 나오면 하위 카운터 리셋.
       들여쓰기·크기·볼드는 standard_rules 실측값(marL EMU)을 본문 폭 비율로 환산해 그대로 따른다. */
    var bulletCounters = [0, 0];
    var STD_MARL_EMU = [265113, 538163, 714375, 892175, 1081088];
    var STD_SPC_BEFORE = [10, 10, 5, 5, 5];   /* 단락 앞 간격 pt — 샘플 실측 */
    var lvSizes = (c.body && c.body.level_sizes) || [14, 13, 12, 11, 10];
    var bodyW = (c.body && c.body.w) || 7.5;
    html += objHtml('body', c.body,
      s.body.map(function(x, i){
        var lv = Math.min(x.level, 4);
        var bullet;
        if(lv === 0){ bulletCounters[0]++; bulletCounters[1] = 0; bullet = bulletCounters[0] + '.'; }
        else if(lv === 1){ bulletCounters[1]++; bullet = bulletCounters[1] + ')'; }
        else bullet = STD_BULLETS[lv];
        var mPct = (STD_MARL_EMU[lv] / 914400) / bodyW * 100;
        var mtEm = i === 0 ? 0 : (STD_SPC_BEFORE[lv] / lvSizes[lv]);
        var stl = 'margin-left:' + mPct.toFixed(2) + '%;' +
          'margin-top:' + mtEm.toFixed(2) + 'em;' +
          'font-size:' + Math.round(lvSizes[lv] / lvSizes[0] * 100) + '%;' +
          'font-weight:' + (lv === 0 ? '700' : '400') + ';';
        return '<div style="' + stl + '">' + bullet + ' ' + editable('body', i, x.text) + '</div>';
      }).join(''), 4);
    if(s.template_type === 1){
      html += objHtml('table_type1', c.table_type1, miniTable(s.table1), 5);
      html += objHtml('timeline', c.timeline,
        '<div style="height:100%;display:flex;align-items:center;">' +
        (s.timeline || []).map(function(d, i){
          return '<span style="flex:1;text-align:center;font-size:75%;">' + esc(d) + '<br>' + esc((s.timeline_note || [])[i] || '') + '</span>';
        }).join('') + '</div>', 4);
    }
    if(s.template_type === 3){
      html += objHtml('table_type3_top', c.table_type3_top, miniTable(s.table1), 5);
      html += objHtml('table_type3_bottom', c.table_type3_bottom, miniTable(s.table2), 5);
    }
    html += objHtml('footnote', c.footnote, editable('footnote', null, s.footnote), 6);
    canvas.innerHTML = html;

    canvas.querySelectorAll('.ed-obj').forEach(function(el){
      el.addEventListener('pointerdown', function(){
        if(el.dataset.key !== selectedKey){
          selectedKey = el.dataset.key;
          renderObjectList(); renderCanvas(); loadProps(); renderTextPanel();
        }
      });
      attachDrag(el);
      el.style.fontSize = fontPx(+el.dataset.pt || 12, canvas) + 'px';
    });
    canvas.querySelectorAll('.ed-line').forEach(function(el){
      // 드래그와 충돌하지 않도록 텍스트 조각에서 시작한 포인터는 캔버스로 넘기지 않는다.
      el.addEventListener('pointerdown', function(e){ e.stopPropagation(); });
      el.addEventListener('dblclick', function(e){ e.stopPropagation(); startInline(el); });
    });
  }

  /* ── 캔버스 내 직접 텍스트 수정 ── */
  function startInline(el){
    if(el.isContentEditable) return;
    var before = el.textContent;
    el.contentEditable = 'true';
    el.classList.add('editing');
    el.focus();
    var range = document.createRange();
    range.selectNodeContents(el);
    window.getSelection().removeAllRanges();
    window.getSelection().addRange(range);

    function finish(commit){
      el.contentEditable = 'false';
      el.classList.remove('editing');
      var text = el.textContent.trim();
      if(!commit || text === before.trim()){ el.textContent = before; return; }
      applyText(el.dataset.field, el.dataset.index === undefined ? null : +el.dataset.index, text);
    }
    el.addEventListener('blur', function(){ finish(true); }, { once: true });
    el.addEventListener('keydown', function(e){
      if(e.key === 'Enter'){ e.preventDefault(); el.blur(); }
      else if(e.key === 'Escape'){ e.preventDefault(); el.textContent = before; el.blur(); }
    });
  }

  /* ── 내용 저장 (서버 반영) ── */
  function applyText(field, index, text){
    var s = slide();
    var body;
    if(field === 'body'){
      body = clone(s.body);
      body[index].text = text;
    }
    var patch = field === 'body' ? { body: body } : {};
    if(field !== 'body') patch[field] = text;

    pushUndoContent();
    $id('edStatus').textContent = '내용 저장 중…';
    API.patch('/api/reports/' + payload.unit.id + '/slides/' + curSlide, patch).then(function(res){
      payload.slides[curSlide - 1] = res.slide;
      return API.get('/api/reports/' + payload.unit.id + '/issues');
    }).then(function(v){
      issues = v;
      renderAll();
      $id('edStatus').textContent = '내용을 저장했습니다 (Ctrl+Z로 되돌리기).';
    }).catch(function(e){
      $id('edStatus').textContent = '저장 실패: ' + e.message;
      renderCanvas();
    });
  }

  function changeLevel(index, delta){
    var body = clone(slide().body);
    body[index].level = Math.max(0, Math.min(4, (body[index].level || 0) + delta));
    saveBody(body);
  }
  function removeLine(index){
    var body = clone(slide().body);
    if(body.length <= 1){ $id('edStatus').textContent = '본문은 최소 한 줄이 있어야 합니다.'; return; }
    body.splice(index, 1);
    saveBody(body);
  }
  function addLine(){
    var body = clone(slide().body);
    body.push({ text: '새 문단', level: 2, bold: null });
    saveBody(body);
  }
  function saveBody(body){
    pushUndoContent();
    $id('edStatus').textContent = '내용 저장 중…';
    API.patch('/api/reports/' + payload.unit.id + '/slides/' + curSlide, { body: body }).then(function(res){
      payload.slides[curSlide - 1] = res.slide;
      return API.get('/api/reports/' + payload.unit.id + '/issues');
    }).then(function(v){
      issues = v; renderAll();
      $id('edStatus').textContent = '내용을 저장했습니다.';
    }).catch(function(e){ $id('edStatus').textContent = '저장 실패: ' + e.message; });
  }

  /* ── 우측: 내용 편집 패널 ── */
  function renderTextPanel(){
    var box = $id('edTextPanel'), s = slide();
    var key = selectedKey;
    $id('edTextLabel').textContent = LABELS[key] || key;

    if(key === 'body'){
      box.innerHTML = s.body.map(function(item, i){
        return '<div style="display:flex; gap:5px; align-items:flex-start; margin-bottom:6px;">' +
          '<span style="font-size:10.5px; color:var(--text-muted); width:16px; padding-top:11px; flex:none;">' + (item.level + 1) + '</span>' +
          '<textarea class="ed-field" data-i="' + i + '" rows="2" style="resize:vertical; font-weight:400; font-size:12px; margin-top:0;">' + esc(item.text) + '</textarea>' +
          '<span style="display:flex; flex-direction:column; gap:2px; flex:none;">' +
          '<button class="btn ghost" data-up="' + i + '" title="단계 올리기" style="padding:1px 6px; font-size:11px;">◂</button>' +
          '<button class="btn ghost" data-down="' + i + '" title="단계 내리기" style="padding:1px 6px; font-size:11px;">▸</button>' +
          '<button class="btn ghost" data-del="' + i + '" title="줄 삭제" style="padding:1px 6px; font-size:11px;">×</button>' +
          '</span></div>';
      }).join('') + '<button class="btn ghost" id="edAddLine" style="width:100%; padding:7px; font-size:12px;">+ 문단 추가</button>';

      box.querySelectorAll('textarea').forEach(function(ta){
        ta.addEventListener('blur', function(){
          var i = +ta.dataset.i, text = ta.value.trim();
          if(text && text !== s.body[i].text) applyText('body', i, text);
        });
      });
      box.querySelectorAll('[data-up]').forEach(function(b){ b.onclick = function(){ changeLevel(+b.dataset.up, -1); }; });
      box.querySelectorAll('[data-down]').forEach(function(b){ b.onclick = function(){ changeLevel(+b.dataset.down, 1); }; });
      box.querySelectorAll('[data-del]').forEach(function(b){ b.onclick = function(){ removeLine(+b.dataset.del); }; });
      $id('edAddLine').onclick = addLine;
      return;
    }

    var simple = { title: ['page_title', '페이지 제목'], sidebar: ['sidebar', '좌측 라벨'], footnote: ['footnote', '각주'] }[key];
    if(simple){
      box.innerHTML = '<textarea class="ed-field" id="edSimpleText" rows="3" style="resize:vertical; font-weight:400; font-size:12px;">' +
        esc(s[simple[0]]) + '</textarea>' +
        '<div class="note" style="margin-top:8px;">캔버스에서 글자를 더블클릭해도 바로 수정할 수 있습니다.</div>';
      $id('edSimpleText').addEventListener('blur', function(){
        var text = this.value.trim();
        if(text && text !== s[simple[0]]) applyText(simple[0], null, text);
      });
      return;
    }
    box.innerHTML = '<div class="note">' + (LABELS[key] || key) + '은(는) 좌표·서식만 조정합니다. 텍스트 수정은 제목·본문·각주에서 가능합니다.</div>';
  }

  /* ── 양식 오류 목록 · 자동 수정 ── */
  function slideIssues(){
    if(!issues) return [];
    return issues.issues.filter(function(i){ return i.slide_no === curSlide; });
  }
  function renderIssues(){
    var list = $id('edIssueList'), mine = slideIssues();
    $id('edIssueCount').textContent = issues
      ? (mine.length ? mine.length + '건 · 전체 ' + issues.total + '건' : '전체 ' + issues.total + '건')
      : '';
    if(!mine.length){
      list.innerHTML = '<li><span class="fico">✓</span><span>이 페이지에서 고칠 양식 오류가 없습니다.</span></li>';
    }else{
      list.innerHTML = mine.map(function(i){
        return '<li><span class="fico">' + esc(i.category.charAt(0)) + '</span>' +
          '<span>' + esc(i.message) + '<br><span style="color:var(--text-muted); font-size:12px;">' + esc(i.detail) + '</span></span>' +
          '<span class="cnt">' + (i.severity === 'high' ? '중요' : i.severity === 'mid' ? '권장' : '참고') + '</span></li>';
      }).join('');
    }
    $id('edFixPageBtn').classList.toggle('disabled', !mine.length);
    $id('edFixAllBtn').classList.toggle('disabled', !issues || !issues.total);
  }
  /* 자동 수정: 먼저 무엇이 바뀌는지 보여주고, 확인을 받은 뒤 적용한다 */
  var pendingFixScope = null;

  function showFixPreview(onlyPage){
    if(!payload) return;
    var url = '/api/reports/' + payload.unit.id + '/autofix/preview' + (onlyPage ? '?slide_no=' + curSlide : '');
    $id('edStatus').textContent = '바뀔 내용을 확인하는 중…';
    API.get(url).then(function(res){
      if(!res.count){
        $id('edPreviewBox').style.display = 'none';
        $id('edStatus').textContent = onlyPage ? '이 페이지는 고칠 내용이 없습니다.' : '고칠 내용이 없습니다.';
        return;
      }
      pendingFixScope = onlyPage;
      $id('edPreviewCount').textContent = res.count + '곳';
      $id('edPreviewList').innerHTML = res.changes.map(function(c){
        var after = c.removed
          ? '<span class="badpt">삭제됨</span>'
          : '<span class="fixedpt">' + esc(c.after) + '</span>';
        var level = (c.before_level != null && c.after_level != null && c.before_level !== c.after_level)
          ? ' <span class="sub">단계 ' + (c.before_level + 1) + ' → ' + (c.after_level + 1) + '</span>' : '';
        return '<div style="padding:8px 0; border-bottom:1px solid var(--grid); font-size:12.5px;">' +
          '<div style="color:var(--text-muted); font-size:11px; margin-bottom:3px;">p.' + c.slide_no + ' · ' + esc(c.field) + level + '</div>' +
          '<div><span class="badpt">' + esc(c.before) + '</span></div>' +
          '<div style="margin-top:2px;">' + after + '</div></div>';
      }).join('');
      $id('edPreviewBox').style.display = '';
      $id('edStatus').textContent = '아래 내용을 확인하고 적용하세요.';
    }).catch(function(e){ $id('edStatus').textContent = '미리보기 실패: ' + e.message; });
  }

  function applyFix(){
    var onlyPage = pendingFixScope;
    var url = '/api/reports/' + payload.unit.id + '/autofix' + (onlyPage ? '?slide_no=' + curSlide : '');
    $id('edStatus').textContent = '자동 수정 적용 중…';
    pushUndoContent();
    API.post(url).then(function(res){
      issues = res.issues;
      return API.get('/api/reports/' + payload.unit.id);
    }).then(function(p){
      payload = p;
      $id('edPreviewBox').style.display = 'none';
      renderAll();
      $id('edStatus').textContent = '자동 수정을 적용했습니다 — 남은 오류 ' + issues.total + '건 (Ctrl+Z로 되돌리기)';
    }).catch(function(e){ $id('edStatus').textContent = '자동 수정 실패: ' + e.message; });
  }

  /* 원문 복원 — 업로드 직후 내용으로. 레이아웃 편집값은 건드리지 않는다 */
  function restore(onlyPage){
    if(!payload) return;
    var url = '/api/reports/' + payload.unit.id + '/restore' + (onlyPage ? '?slide_no=' + curSlide : '');
    $id('edStatus').textContent = '원문으로 되돌리는 중…';
    pushUndoContent();
    API.post(url).then(function(res){
      payload.slides = res.slides;
      issues = res.issues;
      $id('edPreviewBox').style.display = 'none';
      renderAll();
      $id('edStatus').textContent = res.restored
        ? (onlyPage ? '이 페이지를 원문으로 되돌렸습니다.' : res.restored + '개 페이지를 원문으로 되돌렸습니다.') + ' (레이아웃은 그대로)'
        : '이미 원문과 같습니다.';
    }).catch(function(e){ $id('edStatus').textContent = '복원 실패: ' + e.message; });
  }

  /* ── 드래그 · 속성 ── */
  function attachDrag(el){
    var mode = null, start = null;
    var handle = el.querySelector('.ed-handle');
    function begin(e, m){
      if(el.dataset.key === 'frame' && m === 'move' && scope() !== 'global') return;
      e.preventDefault(); e.stopPropagation();
      selectedKey = el.dataset.key;
      mode = m;
      pushUndo();
      start = { x: e.clientX, y: e.clientY, cfg: normalizeCfg(selectedKey, effective()[selectedKey]) };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', end, { once: true });
    }
    el.addEventListener('pointerdown', function(e){
      if(e.target === handle || e.target.classList.contains('ed-line')) return;
      begin(e, 'move');
    });
    handle.addEventListener('pointerdown', function(e){ begin(e, 'resize'); });
    function move(e){
      if(!mode) return;
      var rect = $id('edCanvas').getBoundingClientRect();
      var dx = (e.clientX - start.x) / rect.width * W;
      var dy = (e.clientY - start.y) / rect.height * H;
      var p = objectPatch();
      if(mode === 'move'){
        p.x = Math.max(0, +(start.cfg.x + dx).toFixed(3));
        p.y = Math.max(0, +(start.cfg.y + dy).toFixed(3));
      }else{
        p.w = Math.max(.2, +(start.cfg.w + dx).toFixed(3));
        p.h = Math.max(.15, +(start.cfg.h + dy).toFixed(3));
      }
      renderCanvas(); loadProps();
    }
    function end(){
      mode = null;
      window.removeEventListener('pointermove', move);
    }
  }
  /* 글꼴 드롭다운은 양식 기준(standard_rules.yaml) 값으로 채운다 */
  function fillFontSelects(){
    if(!fonts) return;
    function options(list, current){
      var all = list.slice();
      if(current && all.indexOf(current) < 0) all.unshift(current);
      return all.map(function(f){
        var mark = fonts.checked && fonts.installed[f] === false ? ' (미설치)' : '';
        return '<option value="' + esc(f) + '">' + esc(f) + mark + '</option>';
      }).join('');
    }
    var cfg = normalizeCfg(selectedKey, effective()[selectedKey]);
    $id('edFont').innerHTML = options(fonts.options.korean, cfg.font_ea);
    $id('edFontLatin').innerHTML = options(fonts.options.latin, cfg.font_latin || fonts.rule.latin);
  }
  function renderFontNote(){
    var note = $id('edFontNote');
    if(!fonts || !fonts.checked){ note.style.display = 'none'; return; }
    var missing = Object.keys(fonts.installed).filter(function(f){
      return fonts.installed[f] === false &&
        (f === fonts.rule.latin || f === fonts.rule.korean || f === fonts.rule.heading_korean);
    });
    if(!missing.length){ note.style.display = 'none'; return; }
    note.style.display = '';
    note.innerHTML = '⚠️ <b>' + esc(missing.join(', ')) + '</b> 글꼴이 이 PC에 없습니다. ' +
      '생성되는 PPT에는 정상으로 지정되지만, 이 PC에서 열면 다른 글꼴로 보입니다.<br>' +
      '설치 파일: <code>app/assets/fonts/</code> — TTF를 오른쪽 클릭 → 설치';
  }

  function loadProps(){
    var cfg = normalizeCfg(selectedKey, effective()[selectedKey]);
    $id('edSelLabel').textContent = LABELS[selectedKey] || selectedKey;
    $id('edX').value = (+cfg.x || 0).toFixed(3);
    $id('edY').value = (+cfg.y || 0).toFixed(3);
    $id('edW').value = (+cfg.w || 0).toFixed(3);
    $id('edH').value = (+cfg.h || 0).toFixed(3);
    fillFontSelects();
    $id('edFont').value = cfg.font_ea || (fonts ? fonts.rule.korean : '나눔스퀘어');
    $id('edFontLatin').value = cfg.font_latin || (fonts ? fonts.rule.latin : 'Corbel');
    $id('edSize').value = cfg.font_size || 12;
    $id('edFill').value = (cfg.fill && cfg.fill !== 'transparent') ? cfg.fill : (cfg.header_fill || '#ffffff');
    $id('edText').value = cfg.text_color || cfg.header_text_color || '#000000';
    $id('edBold').checked = !!cfg.bold;
  }
  function renderBadge(){
    var badge = $id('edValidBadge');
    if(!issues){ badge.className = 'chip wait'; badge.textContent = '검사 전'; return; }
    if(issues.total > 0){
      badge.className = 'chip err'; badge.textContent = '고칠 양식 오류 ' + issues.total + '건';
    }else{
      badge.className = 'chip ok'; badge.textContent = '양식 통과';
    }
  }
  function renderAll(){
    var s = slide();
    $id('edPageInfo').textContent = 'p.' + s.slide_number + ' · ' + s.page_title + ' · 템플릿 유형 ' + s.template_type;
    renderNav(); renderObjectList(); renderCanvas(); loadProps();
    renderTextPanel(); renderIssues(); renderBadge();
  }

  function beforeFieldEdit(){ if(!editingField){ pushUndo(); editingField = true; } }
  function bindProps(){
    [['edX', 'x'], ['edY', 'y'], ['edW', 'w'], ['edH', 'h']].forEach(function(pair){
      var input = $id(pair[0]);
      input.addEventListener('input', function(){
        beforeFieldEdit();
        objectPatch()[pair[1]] = +(+input.value).toFixed(3);
        renderCanvas();
      });
      input.addEventListener('blur', function(){ editingField = false; });
    });
    $id('edFont').onchange = function(){
      pushUndo();
      var p = objectPatch();
      if(selectedKey === 'frame') p.header_font_ea = this.value; else p.font_ea = this.value;
      if(selectedKey === 'body') p.level_ea_fonts = [this.value, this.value, this.value, this.value, this.value];
      renderCanvas();
    };
    $id('edFontLatin').onchange = function(){
      pushUndo();
      var p = objectPatch();
      if(selectedKey === 'frame') p.header_font_latin = this.value; else p.font_latin = this.value;
      renderCanvas();
    };
    $id('edSize').addEventListener('input', function(){
      beforeFieldEdit();
      var v = +this.value, p = objectPatch();
      if(selectedKey === 'body'){
        p.level_sizes = [v, Math.max(6, v - 1), Math.max(6, v - 2), Math.max(6, v - 3), Math.max(6, v - 4)];
      }else if(selectedKey === 'frame'){
        p.header_font_size = v;
      }else if(selectedKey.indexOf('table_') === 0){
        p.body_font_size = v; p.header_font_size = v + .5;
      }else{
        p.font_size = v;
      }
      renderCanvas();
    });
    $id('edSize').addEventListener('blur', function(){ editingField = false; });
    $id('edFill').addEventListener('input', function(){
      beforeFieldEdit();
      var p = objectPatch();
      if(selectedKey === 'frame' || selectedKey.indexOf('table_') === 0) p.header_fill = this.value;
      else p.fill = this.value;
      renderCanvas();
    });
    $id('edFill').addEventListener('change', function(){ editingField = false; });
    $id('edText').addEventListener('input', function(){
      beforeFieldEdit();
      var p = objectPatch();
      if(selectedKey === 'frame') p.header_text_color = this.value;
      else p.text_color = this.value;
      renderCanvas();
    });
    $id('edText').addEventListener('change', function(){ editingField = false; });
    $id('edBold').onchange = function(){ pushUndo(); objectPatch().bold = this.checked; renderCanvas(); };
    $id('edScope').onchange = loadProps;
  }

  function bindActions(){
    $id('edPrevSlide').onclick = function(){ moveSlide(-1); };
    $id('edNextSlide').onclick = function(){ moveSlide(1); };
    $id('edSaveBtn').onclick = function(){
      API.post('/api/layouts', { report_id: payload.unit.id, layout_overrides: overrides }).then(function(){
        $id('edStatus').textContent = '편집값을 저장했습니다. 표준 양식 생성과 병합에 반영됩니다.';
      }).catch(function(e){ $id('edStatus').textContent = '저장 실패: ' + e.message; });
    };
    $id('edResetPageBtn').onclick = function(){
      pushUndo();
      if(overrides.slides) delete overrides.slides[String(curSlide)];
      renderAll();
      $id('edStatus').textContent = '현재 페이지의 좌표·서식을 초기화했습니다. (글 내용은 원문 복원 버튼)';
    };
    $id('edResetAllBtn').onclick = function(){
      pushUndo();
      overrides = { global: {}, slides: {} };
      API.del('/api/layouts/' + payload.unit.id).then(function(){
        renderAll();
        $id('edStatus').textContent = '모든 편집값을 초기화했습니다.';
      });
    };
    $id('edFixPageBtn').onclick = function(){ showFixPreview(true); };
    $id('edFixAllBtn').onclick = function(){ showFixPreview(false); };
    $id('edApplyFixBtn').onclick = applyFix;
    $id('edCancelFixBtn').onclick = function(){
      $id('edPreviewBox').style.display = 'none';
      $id('edStatus').textContent = '자동 수정을 취소했습니다.';
    };
    $id('edRestorePageBtn').onclick = function(){ restore(true); };
    $id('edRestoreAllBtn').onclick = function(){ restore(false); };
    document.addEventListener('keydown', function(e){
      if(activeScreenId() !== 's4' || !payload) return;
      var tag = (e.target.tagName || '').toLowerCase();
      if(tag === 'input' || tag === 'textarea' || e.target.isContentEditable) return;
      if((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z'){ e.preventDefault(); undo(); }
      else if((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'y' || (e.shiftKey && e.key.toLowerCase() === 'z'))){ e.preventDefault(); redo(); }
    });
  }

  function choose(id){
    return Promise.all([
      API.get('/api/reports/' + id),
      API.get('/api/layouts/' + id),
      API.get('/api/reports/' + id + '/issues')
    ]).then(function(res){
      payload = res[0];
      overrides = res[1].layout_overrides || { global: {}, slides: {} };
      overrides.global = overrides.global || {};
      overrides.slides = overrides.slides || {};
      issues = res[2];
      curSlide = 1; selectedKey = 'title';
      undoStack = []; redoStack = [];
      $id('edStatus').textContent = '캔버스의 글자를 더블클릭하면 그 자리에서 수정할 수 있습니다.';
      renderAll();
    });
  }

  function clearAll(){
    payload = null; issues = null;
    $id('edSlideNav').innerHTML = '';
    $id('edObjectList').innerHTML = '';
    $id('edCanvas').innerHTML = '<div class="note" style="margin:20px;">업로드된 보고서가 없습니다. 업로드 · 취합 화면에서 PPT를 올려 주세요.</div>';
    $id('edPageInfo').textContent = '';
    $id('edTextPanel').innerHTML = '';
    $id('edIssueList').innerHTML = '';
    $id('edPageCounter').textContent = '0 / 0';
    $id('edPrevSlide').disabled = true;
    $id('edNextSlide').disabled = true;
    var badge = $id('edValidBadge');
    badge.className = 'chip wait'; badge.textContent = '보고서 없음';
  }

  var bound = false;
  function bind(){
    if(bound) return; bound = true;
    bindProps(); bindActions();
    $id('edReportSel').onchange = function(){ choose(this.value); };
  }

  return {
    load: function(){
      bind();
      var keep = $id('edReportSel').value;
      Promise.all([
        API.get('/api/reports'),
        profile ? Promise.resolve(profile) : API.get('/api/profile'),
        API.get('/api/fonts')
      ]).then(function(res){
        reports = res[0]; profile = res[1]; fonts = res[2];
        renderFontNote();
        var sel = $id('edReportSel');
        sel.innerHTML = reports.map(function(r){
          return '<option value="' + r.id + '">' + esc(r.name) + ' (' + r.slide_count + 'p)</option>';
        }).join('');
        if(!reports.length){ clearAll(); return; }
        if(keep && reports.some(function(r){ return r.id === keep; })) sel.value = keep;
        choose(sel.value);
      });
    }
  };
})();
