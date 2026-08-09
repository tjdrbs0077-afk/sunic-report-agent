/* ② 업로드 / ④ 다운로드 — 실제 업로드(XHR 진행률·드래그앤드롭) + 개별 생성·통합 병합
   + 양식 기준 직접 수정 · 기준 양식 PPTX 교체 */
Screens.s2 = (function(){
  var reports = [];
  var merging = false;
  var rules = null;
  var editingRules = false;

  var STEP_UPLOAD = 0, STEP_CHECK = 1, STEP_LAYOUT = 2, STEP_MERGE = 3;

  function $id(x){ return document.getElementById(x); }
  function steps(){ return document.querySelectorAll('#pipeSteps .step'); }
  function setStep(idx, state){
    var el = steps()[idx];
    el.classList.remove('done', 'now');
    if(state) el.classList.add(state);
  }
  function resetStepsFromReports(){
    if(reports.length){
      setStep(STEP_UPLOAD, 'done'); setStep(STEP_CHECK, 'done');
      setStep(STEP_LAYOUT, null); setStep(STEP_MERGE, null);
    }else{
      [0,1,2,3].forEach(function(i){ setStep(i, null); });
    }
  }
  function setProgress(pct, label){
    $id('mergeFill').style.width = pct + '%';
    var lab = $id('mergeLabel');
    lab.textContent = label;
    lab.style.color = ''; lab.style.fontWeight = '';
  }

  /* ── 양식 기준: 보기 모드 ── */
  function renderRuleView(){
    var levels = (rules.body_levels || []);
    var sizes = levels.map(function(l){ return l.size; }).join('/');
    var bullets = levels.map(function(l){ return esc((l.bullet || '').split(':').pop()); }).join('</code> → <code>');
    var t = rules.table || {}, f = rules.fonts || {}, fr = rules.frame || {};
    var rows = [
      ['글꼴', '영문 <code>' + esc(f.latin || '') + '</code> · 한글 <code>' + esc(f.korean || '') + '</code> · 제목 <code>' + esc(f.heading_korean || '') + '</code>'],
      ['제목', ((rules.title || {}).font_size) + 'pt' + ((rules.title || {}).bold ? ' Bold' : '')],
      ['본문', levels.length + '단계 ' + sizes + 'pt, 글머리 <code>' + bullets + '</code>'],
      ['표', '좌 ' + (t.x_in * 2.54).toFixed(2) + 'cm · 폭 ' + (t.width_in * 2.54).toFixed(2) + 'cm 고정, 헤더 <code>' + esc(t.header_fill || '') + '</code> ' + t.header_font_size + 'pt'],
      ['프레임', '헤더 <code>' + esc(fr.header_fill || '') + '</code> ' + fr.header_font_size + 'pt, 테두리 <code>' + esc(fr.border_color || '') + '</code>'],
      ['각주', ((rules.footnote || {}).font_size) + 'pt, 하단 고정'],
      ['정리', ((rules.cleanup || {}).remove_empty_textbox ? '빈 텍스트상자 제거' : '빈 상자 유지') + ' · ' +
               ((rules.cleanup || {}).collapse_spaces ? '연속 공백 1칸 축소' : '공백 유지')]
    ];
    $id('ruleList').innerHTML = rows.map(function(row){
      return '<li><span class="rk">' + row[0] + '</span><span>' + row[1] + '</span></li>';
    }).join('');
    $id('ruleList').style.display = '';
    $id('ruleEditor').style.display = 'none';
    $id('ruleEditBtn').textContent = '기준 직접 수정';
    editingRules = false;
  }

  /* ── 양식 기준: 편집 모드 ── */
  function field(label, id, value, type, extra){
    return '<label style="font-size:11px; color:var(--text-muted); display:block;">' + label +
      '<input class="ed-field" id="' + id + '" type="' + (type || 'text') + '" ' + (extra || '') +
      ' value="' + esc(value == null ? '' : value) + '"></label>';
  }
  function renderRuleEdit(){
    var f = rules.fonts || {}, t = rules.table || {}, fr = rules.frame || {};
    var levels = rules.body_levels || [];
    var html = '';
    html += '<div class="rule-fields">' +
      field('영문 글꼴', 'rfLatin', f.latin) +
      field('한글 글꼴', 'rfKorean', f.korean) +
      field('제목 한글 글꼴', 'rfHeading', f.heading_korean) +
      field('제목 크기(pt)', 'rfTitleSize', (rules.title || {}).font_size, 'number', 'step="0.5" min="5" max="60"') +
      '</div>';
    html += '<div style="font-size:11px; color:var(--text-muted); margin-bottom:6px;">본문 단계별 글자 크기(pt)</div>' +
      '<div class="rule-levels">' +
      levels.map(function(l, i){
        return '<label style="font-size:11px; color:var(--text-muted);">' + (i + 1) + '단계' +
          '<input class="ed-field" id="rfLv' + i + '" type="number" step="0.5" min="5" max="60" value="' + l.size + '"></label>';
      }).join('') + '</div>';
    html += '<div class="rule-fields">' +
      field('표 헤더 크기(pt)', 'rfTblHead', t.header_font_size, 'number', 'step="0.5" min="5" max="60"') +
      field('표 본문 크기(pt)', 'rfTblBody', t.body_font_size, 'number', 'step="0.5" min="5" max="60"') +
      field('각주 크기(pt)', 'rfFoot', (rules.footnote || {}).font_size, 'number', 'step="0.5" min="5" max="60"') +
      field('프레임 헤더 크기(pt)', 'rfFrameSize', fr.header_font_size, 'number', 'step="0.5" min="5" max="60"') +
      '</div>';
    html += '<div class="rule-colors">' +
      '<label style="font-size:11px; color:var(--text-muted);">표 헤더색<input class="ed-field" id="rfTblFill" type="color" style="padding:4px; height:38px;" value="' + esc(t.header_fill || '#DCE6F2') + '"></label>' +
      '<label style="font-size:11px; color:var(--text-muted);">프레임 헤더색<input class="ed-field" id="rfFrameFill" type="color" style="padding:4px; height:38px;" value="' + esc(fr.header_fill || '#B7D3EE') + '"></label>' +
      '<label style="font-size:11px; color:var(--text-muted);">테두리색<input class="ed-field" id="rfBorder" type="color" style="padding:4px; height:38px;" value="' + esc(fr.border_color || '#7F7F7F') + '"></label>' +
      '</div>';
    var c = rules.cleanup || {};
    html += '<div style="display:flex; gap:16px; flex-wrap:wrap; margin-bottom:12px;">' +
      '<label style="font-size:13px; display:flex; align-items:center; gap:7px;"><input type="checkbox" id="rfEmpty" ' + (c.remove_empty_textbox ? 'checked' : '') + ' style="accent-color:var(--accent); width:15px; height:15px;">빈 텍스트상자 제거</label>' +
      '<label style="font-size:13px; display:flex; align-items:center; gap:7px;"><input type="checkbox" id="rfSpace" ' + (c.collapse_spaces ? 'checked' : '') + ' style="accent-color:var(--accent); width:15px; height:15px;">연속 공백 축소</label>' +
      '</div>';
    html += '<div style="display:flex; gap:8px;"><button class="btn primary" id="rfSave">기준 저장</button>' +
      '<button class="btn ghost" id="rfCancel">취소</button></div>';

    $id('ruleEditor').innerHTML = html;
    $id('ruleEditor').style.display = '';
    $id('ruleList').style.display = 'none';
    $id('ruleEditBtn').textContent = '편집 닫기';
    editingRules = true;

    $id('rfSave').onclick = saveRules;
    $id('rfCancel').onclick = renderRuleView;
  }

  function num(id, fallback){
    var v = parseFloat($id(id).value);
    return isNaN(v) ? fallback : v;
  }
  function saveRules(){
    var next = JSON.parse(JSON.stringify(rules));
    next.fonts = next.fonts || {};
    next.fonts.latin = $id('rfLatin').value.trim();
    next.fonts.korean = $id('rfKorean').value.trim();
    next.fonts.heading_korean = $id('rfHeading').value.trim() || next.fonts.korean;
    next.title = next.title || {};
    next.title.font_size = num('rfTitleSize', 24);
    (next.body_levels || []).forEach(function(l, i){
      if($id('rfLv' + i)) l.size = num('rfLv' + i, l.size);
    });
    next.table = next.table || {};
    next.table.header_font_size = num('rfTblHead', 10.5);
    next.table.body_font_size = num('rfTblBody', 10);
    next.table.header_fill = $id('rfTblFill').value.toUpperCase();
    next.footnote = next.footnote || {};
    next.footnote.font_size = num('rfFoot', 8);
    next.frame = next.frame || {};
    next.frame.header_font_size = num('rfFrameSize', 14);
    next.frame.header_fill = $id('rfFrameFill').value.toUpperCase();
    next.frame.border_color = $id('rfBorder').value.toUpperCase();
    next.cleanup = next.cleanup || {};
    next.cleanup.remove_empty_textbox = $id('rfEmpty').checked;
    next.cleanup.collapse_spaces = $id('rfSpace').checked;

    $id('ruleStatus').textContent = '저장 중…';
    API.put('/api/rules', { rules: next }).then(function(res){
      rules = res.rules;
      renderRuleView();
      $id('ruleStatus').textContent = '양식 기준을 저장했습니다. 다음 검사와 PPT 생성부터 적용됩니다.';
    }).catch(function(e){
      $id('ruleStatus').textContent = '저장 실패: ' + e.message;
    });
  }

  function loadRules(){
    return Promise.all([API.get('/api/rules'), API.get('/api/template')]).then(function(res){
      rules = res[0];
      var tpl = res[1];
      $id('ruleSource').textContent = tpl.is_default
        ? 'standard_rules.yaml · 기본 양식' : 'standard_rules.yaml · ' + tpl.name;
      if(!editingRules) renderRuleView();
    });
  }

  function uploadTemplate(file){
    $id('ruleStatus').textContent = '양식 PPTX에서 기준을 추출하는 중…';
    var form = new FormData();
    form.append('file', file);
    fetch('/api/template/upload', { method: 'POST', body: form })
      .then(function(r){ return r.json().then(function(d){ if(!r.ok) throw new Error((d.detail && (d.detail.message || d.detail)) || '실패'); return d; }); })
      .then(function(d){
        rules = d.rules;
        renderRuleView();
        loadRules();
        $id('ruleStatus').textContent = '기준 양식을 ' + d.template + ' 로 교체했습니다.';
      })
      .catch(function(e){ $id('ruleStatus').textContent = '교체 실패: ' + e.message; });
  }

  /* ── 시연용 샘플 보고서 ── */
  function loadDemoUnits(){
    return API.get('/api/demo/units').then(function(d){
      var sel = $id('demoUnitSel');
      var keep = sel.value;
      sel.innerHTML = d.units.map(function(u){
        var mark = u.created || u.created_messy ? ' ✓' : '';
        return '<option value="' + u.id + '">' + esc(u.name) + mark + '</option>';
      }).join('');
      if(keep) sel.value = keep;
    }).catch(function(){});
  }

  function generateDemo(body){
    $id('demoStatus').textContent = '시연용 보고서를 만드는 중…';
    API.post('/api/demo/generate', body).then(function(res){
      var names = res.created.map(function(x){ return x.name + '(' + x.slide_count + 'p, 오류 ' + (x.issue_count || 0) + '건)'; });
      $id('demoStatus').textContent = '생성 완료 — ' + names.join(', ');
      loadDemoUnits();
      refresh();
    }).catch(function(e){
      $id('demoStatus').textContent = '생성 실패: ' + e.message;
    });
  }

  /* ── 파일 목록 ── */
  function renderFileList(){
    var list = $id('fileList');
    list.innerHTML = '';
    reports.forEach(function(r){
      var chip = r.issue_count > 0
        ? '<span class="chip err">오류 ' + r.issue_count + '건</span>'
        : '<span class="chip ok">통과</span>';
      list.insertAdjacentHTML('beforeend',
        '<div class="file-item">✅<span class="fname">' + esc(r.source_file || r.name) + '</span>' +
        '<span class="mini-track"><span class="mini-fill" style="width:100%"></span></span>' + chip +
        '<button class="btn ghost" style="padding:4px 10px; font-size:11.5px;" data-del="' + r.id + '">삭제</button></div>');
    });
    list.querySelectorAll('button[data-del]').forEach(function(b){
      b.onclick = function(){ API.del('/api/reports/' + b.dataset.del).then(refresh); };
    });
  }

  function startDownload(url, name){
    var link = document.createElement('a');
    link.href = encodeURI(url);
    link.download = name || '';
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  function renderIndividualDownloads(){
    var list = $id('individualDownloadList');
    if(!list) return;
    if(!reports.length){
      list.innerHTML = '<div class="individual-download-empty">다운로드할 보고서가 없습니다.<br>먼저 보고서를 업로드해 주세요.</div>';
      return;
    }
    list.innerHTML = reports.map(function(r){
      return '<div class="individual-download-item">' +
        '<div class="individual-download-info"><b>' + esc(r.name) + '</b>' +
        '<span class="individual-download-status">' + r.slide_count + '페이지 · 저장된 편집값 반영</span></div>' +
        '<button class="btn ghost" data-individual="' + esc(r.id) + '">다운로드</button></div>';
    }).join('');
    list.querySelectorAll('button[data-individual]').forEach(function(btn){
      btn.onclick = function(){
        if(btn.dataset.download){
          startDownload(btn.dataset.download, btn.dataset.filename);
          return;
        }
        var row = btn.closest('.individual-download-item');
        var status = row.querySelector('.individual-download-status');
        btn.disabled = true;
        btn.textContent = '준비 중…';
        status.textContent = '다운로드 파일을 준비하는 중입니다…';
        API.post('/api/generate', { report_id: btn.dataset.individual, edited_copy: true })
          .then(function(res){
            var name = decodeURIComponent(res.download.split('/').pop());
            btn.dataset.download = res.download;
            btn.dataset.filename = name;
            btn.textContent = '다시 다운로드';
            status.textContent = '다운로드 준비 완료 · ' + res.slide_count + '슬라이드';
            startDownload(res.download, name);
          })
          .catch(function(e){
            btn.textContent = '다시 시도';
            status.textContent = '다운로드 준비 실패: ' + e.message;
          })
          .then(function(){ btn.disabled = false; });
      };
    });
  }

  function setDownloadMode(mode){
    document.querySelectorAll('[data-download-mode]').forEach(function(btn){
      var active = btn.dataset.downloadMode === mode;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    document.querySelectorAll('[data-download-panel]').forEach(function(panel){
      var active = panel.dataset.downloadPanel === mode;
      panel.classList.toggle('active', active);
      panel.hidden = !active;
    });
  }

  function updateMergeReady(){
    var btn = $id('mergeBtn');
    if(reports.length >= 2 && !merging){
      btn.classList.remove('disabled');
      setProgress(0, '대기 중 — ' + reports.length + '개 보고서가 병합 준비되었습니다');
    }else{
      btn.classList.add('disabled');
      if(!reports.length) setProgress(0, '대기 중 — 보고서를 업로드해 주세요');
      else if(reports.length === 1) setProgress(0, '보고서 1건 등록됨 — 병합에는 2개 이상 필요합니다');
    }
  }

  function refresh(){
    return API.get('/api/reports').then(function(r){
      reports = r;
      renderFileList();
      renderIndividualDownloads();
      resetStepsFromReports();
      updateMergeReady();
    });
  }

  /* ── 업로드: 파일당 XHR 1개, onprogress로 진행률 표시 ── */
  function uploadOne(file){
    return new Promise(function(resolve){
      var list = $id('fileList');
      var el = document.createElement('div');
      el.className = 'file-item';
      el.innerHTML = '⏳<span class="fname">' + esc(file.name) + '</span>' +
        '<span class="mini-track"><span class="mini-fill"></span></span><span class="chip run">업로드 중</span>';
      list.prepend(el);
      var fill = el.querySelector('.mini-fill'), chip = el.querySelector('.chip');

      var xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/reports/upload');
      xhr.upload.onprogress = function(e){
        if(e.lengthComputable) fill.style.width = Math.round(e.loaded / e.total * 90) + '%';
      };
      xhr.upload.onload = function(){
        chip.textContent = '검사 중';
        setStep(STEP_UPLOAD, 'done'); setStep(STEP_CHECK, 'now');
      };
      xhr.onload = function(){
        fill.style.width = '100%';
        var ok = xhr.status >= 200 && xhr.status < 300;
        var data = {};
        try{ data = JSON.parse(xhr.responseText); }catch(err){}
        if(ok && data.created && data.created.length){
          var item = data.created[0];
          el.firstChild.textContent = '✅';
          chip.className = item.issue_count > 0 ? 'chip err' : 'chip ok';
          chip.textContent = item.issue_count > 0 ? '오류 ' + item.issue_count + '건' : '통과';
          setStep(STEP_CHECK, 'done');
        }else{
          var msg = (data.detail && (data.detail.message || data.detail)) || '실패';
          el.firstChild.textContent = '❌';
          chip.className = 'chip err';
          chip.textContent = typeof msg === 'string' ? msg.slice(0, 20) : '실패';
        }
        resolve();
      };
      xhr.onerror = function(){
        chip.className = 'chip err'; chip.textContent = '네트워크 오류';
        resolve();
      };
      var form = new FormData();
      form.append('files', file);
      xhr.send(form);
    });
  }

  function uploadFiles(files){
    var pptx = Array.prototype.filter.call(files, function(f){ return /\.pptx$/i.test(f.name); });
    if(!pptx.length) return;
    setStep(STEP_UPLOAD, 'now');
    var chain = Promise.resolve();
    pptx.forEach(function(f){ chain = chain.then(function(){ return uploadOne(f); }); });
    chain.then(refresh);
  }

  /* ── 통합본 생성 ── */
  function runMerge(){
    if(merging || reports.length < 2) return;
    merging = true;
    var btn = $id('mergeBtn'), dl = $id('dlBtn');
    btn.classList.add('disabled');
    dl.classList.add('disabled'); dl.classList.remove('primary'); dl.classList.add('ghost');
    setStep(STEP_LAYOUT, 'now');
    setProgress(15, '표준 양식 프로파일 로드 중…');
    var pct = 15;
    var timer = setInterval(function(){
      pct = Math.min(85, pct + 6);
      var label = pct < 45 ? reports.length + '개 보고서를 표준 양식으로 배열 중…'
                : '슬라이드 병합 중 (' + reports.length + '개 보고서, 업로드 순서)';
      if(pct >= 45){ setStep(STEP_LAYOUT, 'done'); setStep(STEP_MERGE, 'now'); }
      setProgress(pct, label);
    }, 700);

    API.post('/api/merge', {
      report_ids: reports.map(function(r){ return r.id; }),
      title: '사업단 통합 보고서',
      include_layout_edits: true
    }).then(function(d){
      clearInterval(timer);
      setStep(STEP_LAYOUT, 'done'); setStep(STEP_MERGE, 'done');
      var name = decodeURIComponent(d.download.split('/').pop());
      $id('mergeFill').style.width = '100%';
      var lab = $id('mergeLabel');
      lab.textContent = '✅ 통합본 생성 완료 — ' + name + ' (' + d.slide_count + '슬라이드)';
      lab.style.color = 'var(--good-text)'; lab.style.fontWeight = '600';
      dl.classList.remove('disabled', 'ghost'); dl.classList.add('primary');
      dl.onclick = function(){ window.location.href = encodeURI(d.download); };
    }).catch(function(e){
      clearInterval(timer);
      setStep(STEP_MERGE, null);
      setProgress(0, '병합 실패: ' + e.message);
    }).then(function(){
      merging = false;
      if(reports.length >= 2) btn.classList.remove('disabled');
    });
  }

  /* ── 이벤트 바인딩 (1회) ── */
  var bound = false;
  function bind(){
    if(bound) return; bound = true;
    var dz = $id('dz'), input = $id('fileInput');
    dz.onclick = function(){ input.click(); };
    input.onchange = function(){ uploadFiles(input.files); input.value = ''; };
    ['dragenter', 'dragover'].forEach(function(n){
      dz.addEventListener(n, function(e){ e.preventDefault(); dz.classList.add('drag'); });
    });
    ['dragleave', 'drop'].forEach(function(n){
      dz.addEventListener(n, function(e){ e.preventDefault(); dz.classList.remove('drag'); });
    });
    dz.addEventListener('drop', function(e){ uploadFiles(e.dataTransfer.files); });
    $id('mergeBtn').onclick = runMerge;
    document.querySelectorAll('[data-download-mode]').forEach(function(btn){
      btn.onclick = function(){ setDownloadMode(btn.dataset.downloadMode); };
    });

    $id('demoOneBtn').onclick = function(){
      generateDemo({ unit_ids: [$id('demoUnitSel').value], messy: $id('demoMessy').checked });
    };
    $id('demoAllBtn').onclick = function(){
      generateDemo({ all_units: true, messy: $id('demoMessy').checked });
    };

    $id('ruleEditBtn').onclick = function(){ editingRules ? renderRuleView() : renderRuleEdit(); };
    $id('ruleTplBtn').onclick = function(){ $id('ruleTplInput').click(); };
    $id('ruleTplInput').onchange = function(){
      if(this.files && this.files[0]) uploadTemplate(this.files[0]);
      this.value = '';
    };
    $id('ruleResetBtn').onclick = function(){
      $id('ruleStatus').textContent = '기본 양식으로 되돌리는 중…';
      API.post('/api/template/reset').then(function(d){
        rules = d.rules; renderRuleView(); loadRules();
        $id('ruleStatus').textContent = '기본 양식(' + d.template + ')으로 복원했습니다.';
      }).catch(function(e){ $id('ruleStatus').textContent = '복원 실패: ' + e.message; });
    };
  }

  return {
    load: function(){
      bind();
      loadRules();
      loadDemoUnits();
      refresh();
    },
    loadRulesOnly: function(){
      bind();
      loadRules();
    }
  };
})();

/* 업로드와 다운로드는 화면만 분리하고 같은 보고서 상태를 공유한다. */
Screens.s7 = Screens.s2;
Screens.s8 = { load: Screens.s2.loadRulesOnly };
