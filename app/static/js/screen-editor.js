/* ④ 페이지 편집 — _ref/report_ai_prototype/static/app.js 캔버스 편집기 이식 + Undo/Redo 추가 */
Screens.s4 = (function(){
  var W = 10.833333, H = 7.5;
  var LABELS = {
    frame: '전체 프레임', title: '상단 제목', sidebar: '좌측 사업단명', body: '본문',
    table_type1: '협의 경과 표', table_type3_top: '상단 표', table_type3_bottom: '하단 표',
    timeline: '타임라인', footnote: '각주'
  };
  var STD_BULLETS = ['1.', '1)', '❑', '–', '•'];

  var reports = [], profile = null, payload = null, validation = null;
  var curSlide = 1, selectedKey = 'title';
  var overrides = { global: {}, slides: {} };
  var undoStack = [], redoStack = [], editingField = false;

  function $id(x){ return document.getElementById(x); }
  function clone(x){ return JSON.parse(JSON.stringify(x)); }
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
    var t = payload.slides[curSlide - 1].template_type;
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
    if(key === 'body'){ def('font_size', (c.level_sizes || [14])[0]); def('bold', true); }
    return c;
  }
  function pctX(x){ return x / W * 100; }
  function pctY(y){ return y / H * 100; }
  function fontPx(pt, canvas){ return Math.max(6, pt * canvas.clientWidth / (W * 72)); }

  /* ── Undo / Redo (스택 50단계) ── */
  function pushUndo(){
    undoStack.push(clone(overrides));
    if(undoStack.length > 50) undoStack.shift();
    redoStack = [];
  }
  function undo(){
    if(!undoStack.length) return;
    redoStack.push(clone(overrides));
    overrides = undoStack.pop();
    renderAll();
    $id('edStatus').textContent = '실행 취소 (남은 기록 ' + undoStack.length + '단계)';
  }
  function redo(){
    if(!redoStack.length) return;
    undoStack.push(clone(overrides));
    overrides = redoStack.pop();
    renderAll();
    $id('edStatus').textContent = '다시 실행';
  }

  /* ── 렌더링 ── */
  function renderNav(){
    var nav = $id('edSlideNav');
    nav.innerHTML = payload.slides.map(function(s){
      var cls = s.slide_number === curSlide ? 'btn primary' : 'btn ghost';
      return '<button class="' + cls + '" style="padding:3px 8px; font-size:11px;" data-n="' + s.slide_number + '">' + s.slide_number + '</button>';
    }).join('');
    nav.querySelectorAll('button').forEach(function(b){
      b.onclick = function(){ curSlide = +b.dataset.n; renderAll(); };
    });
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
      b.onclick = function(){ selectedKey = b.dataset.key; renderAll(); };
    });
  }
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
  function renderCanvas(){
    var canvas = $id('edCanvas');
    var s = payload.slides[curSlide - 1];
    var c = effective();
    var html = '';
    var f = normalizeCfg('frame', c.frame);
    var sidePct = f.sidebar_w / f.w * 100, headPct = f.header_h / f.h * 100;
    html += objHtml('frame', f,
      '<div style="height:' + headPct + '%;display:grid;grid-template-columns:' + sidePct + '% 1fr;align-items:center;text-align:center;background:' + f.fill + ';color:' + (f.header_text_color || '#000') + ';font-weight:700;border:1px solid ' + (f.border_color || '#7F7F7F') + ';"><div>구 분</div><div>주요 내용</div></div>' +
      '<div style="position:absolute;top:' + headPct + '%;bottom:0;left:0;right:0;border:1px solid ' + (f.border_color || '#7F7F7F') + ';border-top:none;"></div>' +
      '<div style="position:absolute;top:0;bottom:0;left:' + sidePct + '%;width:1px;background:' + (f.border_color || '#7F7F7F') + ';"></div>', 1);
    html += objHtml('title', c.title, esc(s.page_title), 5);
    html += objHtml('sidebar', c.sidebar,
      '<div style="height:100%;display:flex;align-items:center;justify-content:center;text-align:center;white-space:pre-line;">' + esc(s.sidebar) + '</div>', 4);
    html += objHtml('body', c.body,
      s.body.map(function(x){
        var lv = Math.min(x.level, 4);
        return '<div style="margin-left:' + (lv * 8) + '%;">' + STD_BULLETS[lv] + ' ' + esc(x.text) + '</div>';
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
    html += objHtml('footnote', c.footnote, esc(s.footnote), 6);
    canvas.innerHTML = html;
    canvas.querySelectorAll('.ed-obj').forEach(function(el){
      el.addEventListener('pointerdown', function(e){
        if(el.dataset.key !== selectedKey){
          selectedKey = el.dataset.key;
          renderObjectList(); renderCanvas(); loadProps();
        }
      });
      attachDrag(el);
      var pt = +el.dataset.pt || 12;
      el.style.fontSize = fontPx(pt, canvas) + 'px';
    });
  }
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
      if(e.target === handle) return;
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
  function loadProps(){
    var cfg = normalizeCfg(selectedKey, effective()[selectedKey]);
    $id('edSelLabel').textContent = LABELS[selectedKey] || selectedKey;
    $id('edX').value = (+cfg.x || 0).toFixed(3);
    $id('edY').value = (+cfg.y || 0).toFixed(3);
    $id('edW').value = (+cfg.w || 0).toFixed(3);
    $id('edH').value = (+cfg.h || 0).toFixed(3);
    $id('edFont').value = cfg.font_ea || '나눔스퀘어';
    $id('edSize').value = cfg.font_size || 12;
    $id('edFill').value = (cfg.fill && cfg.fill !== 'transparent') ? cfg.fill : (cfg.header_fill || '#ffffff');
    $id('edText').value = cfg.text_color || cfg.header_text_color || '#000000';
    $id('edBold').checked = !!cfg.bold;
  }
  function renderBadge(){
    var badge = $id('edValidBadge');
    if(!validation){ badge.className = 'chip wait'; badge.textContent = '검사 전'; return; }
    if(validation.total > 0){
      badge.className = 'chip err'; badge.textContent = '양식 위반 ' + validation.total + '건';
    }else{
      badge.className = 'chip ok'; badge.textContent = '양식 통과';
    }
  }
  function renderAll(){
    var s = payload.slides[curSlide - 1];
    $id('edPageInfo').textContent = 'p.' + s.slide_number + ' · ' + s.page_title + ' · 템플릿 유형 ' + s.template_type;
    renderNav(); renderObjectList(); renderCanvas(); loadProps(); renderBadge();
  }

  /* ── 속성 입력 ── */
  function beforeFieldEdit(){
    if(!editingField){ pushUndo(); editingField = true; }
  }
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
    $id('edBold').onchange = function(){
      pushUndo();
      objectPatch().bold = this.checked;
      renderCanvas();
    };
    $id('edScope').onchange = loadProps;
  }

  /* ── 저장 · 초기화 ── */
  function bindActions(){
    $id('edSaveBtn').onclick = function(){
      API.post('/api/layouts', { report_id: payload.unit.id, layout_overrides: overrides }).then(function(){
        $id('edStatus').textContent = '편집값을 저장했습니다. 표준 양식 생성과 병합에 반영됩니다.';
      }).catch(function(e){
        $id('edStatus').textContent = '저장 실패: ' + e.message;
      });
    };
    $id('edResetPageBtn').onclick = function(){
      pushUndo();
      if(overrides.slides) delete overrides.slides[String(curSlide)];
      renderAll();
      $id('edStatus').textContent = '현재 페이지 편집값을 초기화했습니다.';
    };
    $id('edResetAllBtn').onclick = function(){
      pushUndo();
      overrides = { global: {}, slides: {} };
      API.del('/api/layouts/' + payload.unit.id).then(function(){
        renderAll();
        $id('edStatus').textContent = '모든 편집값을 초기화했습니다.';
      });
    };
    document.addEventListener('keydown', function(e){
      if(activeScreenId() !== 's4' || !payload) return;
      if((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z'){ e.preventDefault(); undo(); }
      else if((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'y' || (e.shiftKey && e.key.toLowerCase() === 'z'))){ e.preventDefault(); redo(); }
    });
  }

  function choose(id){
    return Promise.all([
      API.get('/api/reports/' + id),
      API.get('/api/layouts/' + id),
      API.get('/api/reports/' + id + '/rules')
    ]).then(function(res){
      payload = res[0];
      overrides = res[1].layout_overrides || { global: {}, slides: {} };
      overrides.global = overrides.global || {};
      overrides.slides = overrides.slides || {};
      validation = res[2];
      curSlide = 1; selectedKey = 'title';
      undoStack = []; redoStack = [];
      $id('edStatus').textContent = '';
      renderAll();
    });
  }

  function clearAll(){
    payload = null; validation = null;
    $id('edSlideNav').innerHTML = '';
    $id('edObjectList').innerHTML = '';
    $id('edCanvas').innerHTML = '<div class="note" style="margin:20px;">업로드된 보고서가 없습니다. 업로드 · 취합 화면에서 PPT를 올려 주세요.</div>';
    $id('edPageInfo').textContent = '';
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
      Promise.all([API.get('/api/reports'), profile ? Promise.resolve(profile) : API.get('/api/profile')]).then(function(res){
        reports = res[0]; profile = res[1];
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
