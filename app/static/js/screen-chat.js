/* ⑤ 챗봇 — 단일 통합 챗봇 (v2).
   보고서를 선택하면 보고서 근거([p.N])와 외부 뉴스([기사 N])를 한 답변에서 다룬다.
   전송 내역(disclosure)은 매 답변마다 그대로 표시한다.
   API 키가 없으면 서버가 오프라인 발췌 답변으로 폴백한다. */
Screens.s5 = (function(){
  var reports = [];
  var mode = 'easy';
  var sending = false;
  var typingTimer = null;
  var caps = { llm_enabled:false, llm_model:null };

  var MODES = [
    ['brief', '간단히', '핵심만 짧게'],
    ['easy', '보통', '핵심 근거와 설명을 균형 있게'],
    ['detail', '자세히', '근거와 맥락까지']
  ];

  function $id(x){ return document.getElementById(x); }
  function sel(){ return $id('chatReportSel'); }
  function hasReport(){ return !!sel().value; }

  function renderModes(){
    $id('chatModes').innerHTML = MODES.map(function(m){
      var active = m[0] === mode;
      return '<button type="button" class="chat-mode-btn' + (active ? ' active' : '') + '"' +
        ' data-mode="' + m[0] + '" aria-pressed="' + active + '" title="' + m[2] + '">' + m[1] + '</button>';
    }).join('');
    $id('chatModes').querySelectorAll('button').forEach(function(b){
      b.onclick = function(){ mode = b.dataset.mode; renderModes(); };
    });
  }

  function renderStatus(){
    var note = '';
    if(caps.llm_enabled){
      note = '🔎 통합 답변 사용 중 (모델: ' + esc(caps.llm_model || '') + ') — 답변 생성 시 선택한 보고서 전문과 질문이 '
        + 'Claude API로 전송됩니다(모델 학습에는 사용되지 않음). 전송 내역은 매 답변 아래에 그대로 표시됩니다.';
    }
    var status = $id('chatScopeNote');
    status.innerHTML = note;
    status.hidden = !note;
  }

  function bubble(role, html){
    $id('chatLog').insertAdjacentHTML('beforeend',
      '<div class="chat-bubble ' + (role === 'user' ? 'user' : 'ai') + '">' + html + '</div>');
    $id('chatLog').scrollTop = $id('chatLog').scrollHeight;
  }

  function showTyping(){
    hideTyping();
    $id('chatLog').insertAdjacentHTML('beforeend',
      '<div class="chat-bubble ai chat-typing" id="chatTyping" role="status">' +
      '<span class="chat-typing-label">보고서 근거를 찾고 있어요</span>' +
      '<span class="chat-typing-dots" aria-hidden="true"><i></i><i></i><i></i></span></div>');
    $id('chatLog').scrollTop = $id('chatLog').scrollHeight;
    typingTimer = setTimeout(function(){
      var label = document.querySelector('#chatTyping .chat-typing-label');
      if(label) label.textContent = '근거를 종합해 답변을 작성하고 있어요';
    }, 1200);
  }

  function hideTyping(){
    if(typingTimer){ clearTimeout(typingTimer); typingTimer = null; }
    var el = $id('chatTyping');
    if(el) el.remove();
  }

  /* [p.3]·"3페이지" → 보고서 상세 링크, [기사 N] → 우측 기사 번호 강조 */
  function linkify(text){
    var html = esc(text)
      .replace(/^#{1,3}\s+(.+)$/gm, '<strong class="chat-answer-heading">$1</strong>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\[기사\s*(\d{1,2})\]/g, function(_, n){
        return '<span style="color:var(--accent-deep); font-weight:700;">[기사 ' + n + ']</span>';
      });
    if(hasReport()){
      var link = function(n, label){
        return '<a style="color:var(--accent-deep); font-weight:700; cursor:pointer; text-decoration:underline;" data-page="' + n + '">' + label + '</a>';
      };
      html = html
        .replace(/\[p\.(\d+)\]/g, function(_, n){ return link(n, '[p.' + n + ']'); })
        .replace(/(\d+)페이지/g, function(_, n){ return link(n, n + '페이지'); });
    }
    return html;
  }

  function bindPageLinks(){
    $id('chatLog').querySelectorAll('a[data-page]:not([data-bound])').forEach(function(a){
      a.dataset.bound = '1';
      a.onclick = function(){ Screens.s3.show(sel().value, +a.dataset.page); };
    });
  }

  /* 근거 페이지 + 참고 기사를 한 패널에 함께 표시 */
  function renderSources(d){
    var box = $id('chatSources');
    var html = '';
    var sources = d.sources || [], articles = d.articles || [];

    if(sources.length){
      var max = Math.max.apply(null, sources.map(function(s){ return s.score; })) || 1;
      html += '<section class="chat-source-section"><div class="chat-section-label">' +
        '<span>보고서 근거</span><b>' + sources.length + '개 페이지</b></div>';
      html += sources.map(function(s){
        var quotes = (s.evidence || []).slice(0, 2).map(function(e){
          return '<span class="chat-source-quote">“' + esc(e.quote) + '”</span>';
        }).join('');
        var pct = Math.max(4, Math.round(s.score / max * 100));
        return '<button type="button" class="chat-source-item" data-source-page="' + s.slide_number + '">' +
          '<span class="chat-source-head"><span class="chat-page-badge">p.' + s.slide_number + '</span>' +
          '<span class="chat-source-title">' + esc(s.page_title) + '</span></span>' +
          '<span class="chat-source-summary">' + esc(s.summary) + '</span>' + quotes +
          '<span class="chat-score"><span class="chat-score-track"><i style="width:' + pct + '%"></i></span>' +
          '<span>관련도 ' + s.score.toFixed(3) + '</span></span></button>';
      }).join('') + '</section>';
    }
    if(articles.length){
      html += '<section class="chat-source-section"><div class="chat-section-label">' +
        '<span>참고 기사</span><b>' + articles.length + '건</b></div>';
      html += articles.map(function(a, i){
        var title = a.url
          ? '<a href="' + esc(a.url) + '" target="_blank" rel="noopener noreferrer">' + esc(a.title) + '</a>'
          : esc(a.title);
        return '<div class="chat-article-item"><div class="chat-article-title">[' + (i + 1) + '] ' + title + '</div>' +
          '<div class="chat-article-meta"><span class="pill news">' + esc(a.source || '뉴스') + '</span>' +
          '<span>' + esc(a.date || '날짜 미상') + '</span></div></div>';
      }).join('') + '</section>';
    }
    box.innerHTML = html || '<div class="chat-empty-state">이번 답변에 연결된 근거가 없습니다.</div>';
  }

  /* 전송 내역 — 무엇이 외부로 나갔는지 매 답변마다 표시 */
  function renderDisclosure(d, notice){
    var box = $id('chatDisclosure');
    if(!d){ box.innerHTML = ''; return; }
    var chip = d.external_call ? 'chip run' : 'chip ok';
    var html = '<section class="chat-disclosure-card"><div class="chat-section-label">' +
      '<span>외부 전송 내역</span><span class="' + chip + '">' +
      (d.external_call ? '외부 호출 있음' : '외부 호출 없음') + '</span></div>' +
      '<p class="chat-disclosure-label">' + esc(d.label) + '</p>';
    if(d.sent_text){
      html += '<div class="chat-sent-text"><b>전송한 범위</b><span>' + esc(d.sent_text) + '</span></div>';
    }
    if(notice){
      html += '<div class="note chat-notice">' + esc(notice) + '</div>';
    }
    box.innerHTML = html + '</section>';
  }

  /* 답변 메타 — 왜 이 답이 나왔는지 (경로·질문 유형·근거 충분성·폴백 사유) */
  function renderMeta(m){
    if(!m) return;
    var box = $id('chatDisclosure');
    var SUFF = { sufficient: ['근거 충분', 'chip ok'], partial: ['근거 부분적', 'chip wait'],
                 insufficient: ['근거 부족', 'chip err'] };
    var chips = '<span class="chip ' + (m.path === 'llm' ? 'ok' : 'wait') + '">' +
      (m.path === 'llm' ? 'Claude 답변' : '오프라인 답변') + '</span> ' +
      '<span class="chip wait">' + esc(m.intent_label || '') + '</span>';
    if(m.sufficiency && SUFF[m.sufficiency]){
      chips += ' <span class="' + SUFF[m.sufficiency][1] + '">' + SUFF[m.sufficiency][0] + '</span>';
    }
    var detail = [];
    if(m.path === 'llm' && m.model) detail.push('모델 ' + esc(m.model));
    if(m.evidence_scope) detail.push('근거 ' + esc(m.evidence_scope));
    if(m.matched_terms && m.matched_terms.length) detail.push('일치 토큰: ' + esc(m.matched_terms.join(', ')));
    if(m.fallback_reason) detail.push('폴백 사유: ' + esc(m.fallback_reason));
    box.insertAdjacentHTML('beforeend',
      '<section class="chat-meta-card"><div class="chat-section-label"><span>답변 생성 정보</span></div>' +
      '<div class="chat-meta-chips">' + chips + '</div>' +
      (detail.length ? '<div class="chat-meta-detail">' + detail.join(' · ') + '</div>' : '') +
      '</section>');
  }

  /* 오프라인 폴백 안내 버튼 (LLM 미설정 시 서버가 제안을 보낼 수 있음) */
  function renderSuggestion(s){
    if(!s || !s.question) return;
    var btnId = 'chatSuggest' + Date.now();
    $id('chatLog').insertAdjacentHTML('beforeend',
      '<div style="align-self:flex-start;"><button id="' + btnId + '" class="btn ghost" style="font-size:12.5px;">' +
      '이어서 질문하기</button></div>');
    $id('chatLog').scrollTop = $id('chatLog').scrollHeight;
    $id(btnId).onclick = function(){ ask(s.question); };
  }

  /* ⑥ 동향 그래프 반영 결과 */
  function renderGraphDelta(delta){
    if(!delta) return;
    var box = $id('chatDisclosure');
    var added = delta.added_node_ids || [];
    var updated = delta.updated_node_ids || [];
    var labels = delta.labels || {};
    var name = function(id){ return '<b>' + esc(labels[id] || id.split(':')[1] || id) + '</b>'; };

    if(!added.length && !updated.length){
      if(!(delta.warnings || []).length) return;
      box.insertAdjacentHTML('beforeend',
        '<div style="font-size:12px; color:var(--text-muted); margin-top:8px;">' +
        '답변은 생성했지만 이번 결과는 동향 그래프에 반영하지 못했습니다.</div>');
      return;
    }
    var parts = [];
    if(added.length) parts.push(added.map(name).join(', ') + ' 추가');
    if(updated.length) parts.push(updated.map(name).join(', ') + ' 관계 갱신');
    box.insertAdjacentHTML('beforeend',
      '<div style="margin-top:10px; font-size:12.5px;">📈 동향 그래프에 ' + parts.join(' · ') +
      ' <a id="chatGraphLink" style="color:var(--accent-deep); font-weight:700; cursor:pointer; text-decoration:underline;">그래프에서 보기</a></div>');
    $id('chatGraphLink').onclick = function(){
      if(Screens.s6 && Screens.s6.focus) Screens.s6.focus(added.concat(updated));
      goTo('s6');
    };
  }

  function send(){
    var input = $id('chatInput');
    var q = input.value.trim();
    if(!q || sending) return;

    sending = true;
    input.value = '';
    bubble('user', esc(q));
    var btn = $id('chatSend');
    btn.disabled = true;
    input.disabled = true;
    $id('chatLog').setAttribute('aria-busy', 'true');
    showTyping();

    var body = { question: q, mode: mode };
    if(hasReport()) body.report_id = sel().value;

    API.post('/api/chat', body).then(function(d){
      hideTyping();
      bubble('ai', linkify(d.answer));
      bindPageLinks();
      renderSources(d);
      renderDisclosure(d.disclosure, d.notice);
      renderMeta(d.answer_meta);
      renderSuggestion(d.suggestion);
      renderGraphDelta(d.graph_delta);
    }).catch(function(e){
      hideTyping();
      bubble('ai', '오류: ' + esc(e.message));
    }).then(function(){
      sending = false;
      btn.disabled = false;
      input.disabled = false;
      $id('chatLog').setAttribute('aria-busy', 'false');
      input.focus();
    });
  }

  function clearConversation(){
    hideTyping();
    $id('chatLog').innerHTML = '';
    $id('chatSources').innerHTML = '';
    $id('chatDisclosure').innerHTML = '';
    bubble('ai', hasReport()
      ? '선택한 보고서에 대해 무엇이든 물어보세요. 보고서 근거는 [p.N], 외부 뉴스는 [기사 N]으로 출처가 붙습니다.'
      : '보고서를 선택하면 보고서 근거 답변이, 선택하지 않으면 뉴스·일반 지식 답변이 제공됩니다.');
  }

  /* ⑥ 그래프에서 넘어온 질문 프리필 — 전송은 사용자가 확정 */
  function ask(question){
    var input = $id('chatInput');
    input.value = question || '';
    input.focus();
  }

  var bound = false;
  function bind(){
    if(bound) return; bound = true;
    $id('chatSend').onclick = send;
    $id('chatInput').addEventListener('keydown', function(e){
      if(e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); send(); }
    });
    $id('chatSources').addEventListener('click', function(e){
      var item = e.target.closest('[data-source-page]');
      if(item && hasReport()) Screens.s3.show(sel().value, +item.dataset.sourcePage);
    });
    sel().onchange = clearConversation;
  }

  return {
    ask: ask,
    load: function(){
      bind();
      renderModes();
      API.get('/api/chat/capabilities').then(function(c){ caps = c; renderStatus(); })
                                       .catch(renderStatus);

      var keep = sel().value;
      API.get('/api/reports').then(function(r){
        reports = r;
        sel().innerHTML = '<option value="">— 보고서 선택 안 함 —</option>' + reports.map(function(x){
          return '<option value="' + x.id + '">' + esc(x.name) + ' (' + x.slide_count + 'p)</option>';
        }).join('');
        var changed = keep !== sel().value;
        if(keep && reports.some(function(x){ return x.id === keep; })){ sel().value = keep; changed = false; }
        else if(reports.length){ sel().value = reports[0].id; changed = true; }
        if(changed || !$id('chatLog').childElementCount) clearConversation();
      });
    }
  };
})();
