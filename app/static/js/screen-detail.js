/* ③ 보고서 상세 — 원본/교정본 비교 + 양식 검사 내역 + AI 내용 피드백 */
Screens.s3 = (function(){
  var reports = [];
  var payload = null;
  var validation = null;
  var slideNo = 1;
  var activeReviewPanel = 'changes';
  var fbCache = {};   // report_id → fb 렌더링 HTML
  var BAD_BULLETS = '▶▷◆◇■□※✓√●○◎☞▸»*·◦▪';
  var STD_BULLETS = ['1.', '1)', '❑', '–', '•'];

  function sel(){ return document.getElementById('detReportSel'); }

  function fillSelect(keepId){
    sel().innerHTML = reports.map(function(r){
      return '<option value="' + r.id + '">' + esc(r.name) + ' — 오류 ' + (r.issue_count || 0) + '건</option>';
    }).join('');
    if(keepId && reports.some(function(r){ return r.id === keepId; })) sel().value = keepId;
  }

  function slideIssues(n){
    if(!validation) return [];
    return validation.issues.filter(function(i){ return i.slide_no === n; });
  }

  function renderNav(){
    var nav = document.getElementById('detSlideNav');
    nav.innerHTML = payload.slides.map(function(s){
      var cls = s.slide_number === slideNo ? 'btn primary' : 'btn ghost';
      return '<button class="' + cls + '" style="padding:4px 10px; font-size:11.5px;" data-n="' + s.slide_number + '">' + s.slide_number + '</button>';
    }).join('');
    nav.querySelectorAll('button').forEach(function(b){
      b.onclick = function(){ slideNo = +b.dataset.n; renderSlide(); renderNav(); };
    });
  }

  function bulletSpanOrig(text){
    var head = text.charAt(0);
    if(BAD_BULLETS.indexOf(head) >= 0){
      return '<span class="badpt">' + esc(head) + '</span> ' + esc(text.slice(1).trim());
    }
    return esc(text);
  }

  function miniTable(spec){
    if(!spec) return '';
    return '<table style="font-size:9px; margin-top:6px;"><thead><tr>' +
      spec.headers.map(function(h){ return '<th style="padding:2px 6px;">' + esc(h) + '</th>'; }).join('') +
      '</tr></thead><tbody>' +
      spec.rows.slice(0, 3).map(function(row){
        return '<tr>' + row.map(function(c){ return '<td style="padding:2px 6px;">' + esc(c) + '</td>'; }).join('') + '</tr>';
      }).join('') + '</tbody></table>';
  }

  function renderSlide(){
    var s = payload.slides[slideNo - 1];
    var issues = slideIssues(slideNo);
    document.getElementById('detOrigLabel').textContent = '제출된 슬라이드 ' + slideNo + ' / ' + payload.slides.length +
      (issues.length ? ' · 위반 ' + issues.length + '건' : '');

    /* 좌: 원본 (추출 데이터 기준) */
    var left = '<div class="stitle">' + esc(s.page_title) + '</div><ul>';
    s.body.forEach(function(item){
      left += '<li style="margin-left:' + (item.level * 14) + 'px;' + (item.bold ? 'font-weight:700;' : '') + '">' +
        bulletSpanOrig(item.text) + '</li>';
    });
    left += '</ul>';
    left += miniTable(s.table1);
    if(issues.length){
      var first = issues[0];
      left += '<div style="position:absolute; left:8%; right:8%; bottom:6%; font-size:10px; color:#a52e2e;">' +
        '<span class="badpt">' + esc(first.category) + '</span> ' + esc(first.message) +
        (issues.length > 1 ? ' 외 ' + (issues.length - 1) + '건' : '') + '</div>';
    }
    document.getElementById('detOrig').innerHTML = left;

    /* 우: 표준 양식 적용본 */
    var counters = [0, 0];
    var right = '<div class="stitle">' + esc(s.page_title) + '</div><ul>';
    s.body.forEach(function(item, idx){
      var lv = Math.min(item.level, 4);
      var bullet;
      if(lv === 0){ counters[0]++; counters[1] = 0; bullet = counters[0] + '.'; }
      else if(lv === 1){ counters[1]++; bullet = counters[1] + ')'; }
      else bullet = STD_BULLETS[lv];
      var wasBad = BAD_BULLETS.indexOf(item.text.charAt(0)) >= 0;
      var text = wasBad ? item.text.slice(1).trim() : item.text;
      var mt = idx === 0 ? 0 : (lv <= 1 ? 7 : 4);   /* 샘플 spc_before 비율 축소판 */
      right += '<li style="margin-left:' + (lv * 14) + 'px;margin-top:' + mt + 'px;' + (lv === 0 ? 'font-weight:700;' : '') + '">' +
        (wasBad ? '<span class="fixedpt">' + bullet + '</span>' : bullet) + ' ' + esc(text) + '</li>';
    });
    right += '</ul>';
    right += miniTable(s.table1);
    if(issues.length){
      right += '<div style="position:absolute; left:8%; right:8%; bottom:6%; font-size:10px; color:#0a7a0a;">' +
        '<span class="fixedpt">교정</span> 표준 양식 이관 시 ' + issues.length + '건 자동 반영</div>';
    }
    document.getElementById('detFixed').innerHTML = right;
  }

  function renderFixList(){
    var listEl = document.getElementById('detFixList');
    document.getElementById('detFixCount').textContent = validation.total + '건';
    if(!validation.by_category.length){
      listEl.innerHTML = '<li><span class="fico">✓</span><span>양식 위반이 발견되지 않았습니다.</span></li>';
      return;
    }
    listEl.innerHTML = validation.by_category.map(function(c){
      var rep = validation.issues.filter(function(i){ return i.category === c.category; })[0];
      return '<li><span class="fico">' + esc(c.category.charAt(0)) + '</span>' +
        '<span>' + esc(rep ? rep.message : c.category) + '</span>' +
        '<span class="cnt">' + c.count + '건</span></li>';
    }).join('');
  }

  function severityForSlide(n){
    var count = slideIssues(n).length;
    return count >= 5 ? 'high' : count >= 1 ? 'mid' : 'low';
  }

  function renderFeedback(){
    var box = document.getElementById('detFbList');
    var id = payload.unit.id;
    if(fbCache[id]){ box.innerHTML = fbCache[id]; bindFb(box); return; }
    box.innerHTML = '<div class="note">보고서 내용을 기반으로 피드백을 생성하고 있습니다…</div>';

    /* 위반이 많은 슬라이드 상위 3개 → /api/chat 근거형 요약 */
    var ranked = payload.slides.slice().sort(function(a, b){
      return slideIssues(b.slide_number).length - slideIssues(a.slide_number).length;
    }).slice(0, 3);

    var chain = Promise.resolve([]);
    ranked.forEach(function(s){
      chain = chain.then(function(acc){
        return API.post('/api/chat', {
          report_id: id,
          question: s.page_title + ' 내용의 핵심 근거는?',
          mode: 'brief'
        }).then(function(d){ acc.push({ slide: s, answer: d.answer }); return acc; })
          .catch(function(){ acc.push({ slide: s, answer: s.summary }); return acc; });
      });
    });
    chain.then(function(items){
      var html = items.map(function(it, k){
        var sev = severityForSlide(it.slide.slide_number);
        var sevLabel = sev === 'high' ? '중요' : sev === 'mid' ? '권장' : '참고';
        var checked = sev === 'high';
        var fid = 'fb_' + id + '_' + k;
        return '<label class="fb-item' + (checked ? ' sel' : '') + '" for="' + fid + '">' +
          '<input type="checkbox" id="' + fid + '"' + (checked ? ' checked' : '') + '>' +
          '<span class="fbt"><b>p.' + it.slide.slide_number + ' ' + esc(it.slide.page_title) +
          ' · 양식 위반 ' + slideIssues(it.slide.slide_number).length + '건</b>' + esc(it.answer) + '</span>' +
          '<span class="sev ' + sev + '">' + sevLabel + '</span></label>';
      }).join('');
      fbCache[id] = html;
      box.innerHTML = html;
      bindFb(box);
    });
  }

  function setCompareView(view){
    var grid = document.getElementById('detCompareGrid');
    if(!grid) return;
    grid.dataset.view = view;
    document.querySelectorAll('.detail-view-switch button').forEach(function(btn){
      btn.classList.toggle('active', btn.dataset.view === view);
    });
  }

  function setReviewPanel(panel){
    activeReviewPanel = panel;
    document.querySelectorAll('.detail-review-tabs button').forEach(function(btn){
      var active = btn.dataset.panel === panel;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    var changes = document.getElementById('detPanelChanges');
    var feedback = document.getElementById('detPanelFeedback');
    changes.hidden = panel !== 'changes';
    feedback.hidden = panel !== 'feedback';
    changes.classList.toggle('active', panel === 'changes');
    feedback.classList.toggle('active', panel === 'feedback');
    if(panel === 'feedback' && payload) renderFeedback();
  }

  function bindFb(box){
    box.querySelectorAll('input').forEach(function(cb){
      cb.addEventListener('change', function(){
        cb.closest('.fb-item').classList.toggle('sel', cb.checked);
      });
    });
  }

  function choose(id){
    return Promise.all([
      API.get('/api/reports/' + id),
      API.get('/api/reports/' + id + '/rules')
    ]).then(function(res){
      payload = res[0]; validation = res[1];
      slideNo = 1;
      var chip = document.getElementById('detChip');
      if(validation.total > 0){
        chip.className = 'chip err'; chip.textContent = '양식 오류 ' + validation.total + '건';
      }else{
        chip.className = 'chip ok'; chip.textContent = '양식 통과';
      }
      renderNav();
      renderSlide();
      renderFixList();
      if(activeReviewPanel === 'feedback') renderFeedback();
    });
  }

  function clearAll(){
    document.getElementById('detSlideNav').innerHTML = '';
    document.getElementById('detOrig').innerHTML = '';
    document.getElementById('detFixed').innerHTML = '';
    document.getElementById('detFixList').innerHTML = '';
    document.getElementById('detFbList').innerHTML = '<div class="note">업로드된 보고서가 없습니다. 보고서 업로드 화면에서 PPT를 올려 주세요.</div>';
    document.getElementById('detFixCount').textContent = '';
    var chip = document.getElementById('detChip');
    chip.className = 'chip wait'; chip.textContent = '보고서 없음';
  }

  var bound = false;
  function bind(){
    if(bound) return; bound = true;
    sel().onchange = function(){ choose(sel().value); };
    document.querySelectorAll('.detail-view-switch button').forEach(function(btn){
      btn.onclick = function(){ setCompareView(btn.dataset.view); };
    });
    document.querySelectorAll('.detail-review-tabs button').forEach(function(btn){
      btn.onclick = function(){ setReviewPanel(btn.dataset.panel); };
    });
  }

  return {
    load: function(){
      bind();
      var keep = sel().value;
      API.get('/api/reports').then(function(r){
        reports = r;
        if(!reports.length){ fillSelect(); clearAll(); return; }
        fillSelect(keep);
        choose(sel().value);
      });
    },
    /* 챗봇 [p.N] 클릭 → 해당 보고서·페이지로 이동 */
    show: function(reportId, n){
      goTo('s3');
      API.get('/api/reports').then(function(r){
        reports = r;
        fillSelect(reportId);
        choose(reportId).then(function(){
          if(n >= 1 && n <= payload.slides.length){ slideNo = n; renderSlide(); renderNav(); }
        });
      });
    }
  };
})();
