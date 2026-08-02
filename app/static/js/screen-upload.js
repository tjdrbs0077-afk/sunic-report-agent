/* ② 업로드 · 취합 — 실제 업로드(XHR 진행률·드래그앤드롭) + /api/merge 연동 */
Screens.s2 = (function(){
  var rulesLoaded = false;
  var reports = [];
  var merging = false;

  var STEP_UPLOAD = 0, STEP_CHECK = 1, STEP_LAYOUT = 2, STEP_MERGE = 3;

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
    document.getElementById('mergeFill').style.width = pct + '%';
    var lab = document.getElementById('mergeLabel');
    lab.textContent = label;
    lab.style.color = ''; lab.style.fontWeight = '';
  }

  /* ── 양식 기준 카드: standard_rules.yaml 렌더링 ── */
  function renderRules(){
    if(rulesLoaded) return;
    API.get('/api/rules').then(function(r){
      var levels = (r.body_levels || []).map(function(l){ return l.size; }).join('/');
      var bullets = (r.body_levels || []).map(function(l){ return (l.bullet || '').split(':').pop(); }).join('</code> → <code>');
      var t = r.table || {}, f = r.fonts || {};
      var rows = [
        ['글꼴', '영문 <code>' + esc(f.latin || '') + '</code> · 한글 <code>' + esc(f.korean || '') + '</code> · 제목 <code>' + esc(f.heading_korean || '') + '</code>'],
        ['제목', (r.title && r.title.font_size) + 'pt Bold, 좌상단 고정 좌표'],
        ['본문', '5단계 ' + levels + 'pt, 글머리 <code>' + bullets + '</code>'],
        ['표', '좌 ' + (t.x_in * 2.54).toFixed(2) + 'cm · 폭 ' + (t.width_in * 2.54).toFixed(2) + 'cm 고정, 헤더 <code>' + esc(t.header_fill || '') + '</code> ' + t.header_font_size + 'pt'],
        ['각주', ((r.footnote || {}).font_size) + 'pt, 하단 고정'],
        ['정리', '빈 텍스트상자 제거 · 연속 공백 1칸 축소'],
        ['이어지는 장', esc((r.continuation || {}).rule || '')]
      ];
      document.getElementById('ruleList').innerHTML = rows.map(function(row){
        return '<li><span class="rk">' + row[0] + '</span><span>' + row[1] + '</span></li>';
      }).join('');
      rulesLoaded = true;
    }).catch(function(){});
  }

  /* ── 파일 목록 ── */
  function renderFileList(){
    var list = document.getElementById('fileList');
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
      b.onclick = function(){
        API.del('/api/reports/' + b.dataset.del).then(refresh);
      };
    });
  }

  function updateMergeReady(){
    var btn = document.getElementById('mergeBtn');
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
      resetStepsFromReports();
      updateMergeReady();
    });
  }

  /* ── 업로드: 파일당 XHR 1개, onprogress로 진행률 표시 ── */
  function uploadOne(file){
    return new Promise(function(resolve){
      var list = document.getElementById('fileList');
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

  /* ── 통합 생성 ── */
  function runMerge(){
    if(merging || reports.length < 2) return;
    merging = true;
    var btn = document.getElementById('mergeBtn');
    var dl = document.getElementById('dlBtn');
    btn.classList.add('disabled');
    dl.classList.add('disabled'); dl.classList.remove('primary'); dl.classList.add('ghost');
    setStep(STEP_LAYOUT, 'now');
    setProgress(15, '표준 양식 프로파일 로드 중… (보고양식_Sample_4팀.pptx)');
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
      document.getElementById('mergeFill').style.width = '100%';
      var lab = document.getElementById('mergeLabel');
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
    var dz = document.getElementById('dz');
    var input = document.getElementById('fileInput');
    dz.onclick = function(){ input.click(); };
    input.onchange = function(){ uploadFiles(input.files); input.value = ''; };
    ['dragenter', 'dragover'].forEach(function(n){
      dz.addEventListener(n, function(e){ e.preventDefault(); dz.classList.add('drag'); });
    });
    ['dragleave', 'drop'].forEach(function(n){
      dz.addEventListener(n, function(e){ e.preventDefault(); dz.classList.remove('drag'); });
    });
    dz.addEventListener('drop', function(e){ uploadFiles(e.dataTransfer.files); });
    document.getElementById('mergeBtn').onclick = runMerge;
  }

  return {
    load: function(){
      bind();
      renderRules();
      refresh();
    }
  };
})();
