/* ⑤ 근거형 챗봇 — /api/chat 연동. 답변의 [p.N] 클릭 시 보고서 상세로 이동 */
Screens.s5 = (function(){
  var reports = [];
  var mode = 'easy';
  var MODES = [['brief', '간단히'], ['easy', '쉽게'], ['detail', '자세히']];

  function $id(x){ return document.getElementById(x); }
  function sel(){ return $id('chatReportSel'); }

  function renderModes(){
    $id('chatModes').innerHTML = MODES.map(function(m){
      var cls = m[0] === mode ? 'chip ok' : 'chip wait';
      return '<button class="' + cls + '" style="cursor:pointer; border:none; font:inherit; font-size:11.5px;" data-mode="' + m[0] + '">' + m[1] + '</button>';
    }).join('');
    $id('chatModes').querySelectorAll('button').forEach(function(b){
      b.onclick = function(){ mode = b.dataset.mode; renderModes(); };
    });
  }

  function bubble(role, html){
    var style = role === 'user'
      ? 'align-self:flex-end; background:var(--grad); color:#fff;'
      : 'align-self:flex-start; background:#f6f1ef; color:var(--text-primary);';
    $id('chatLog').insertAdjacentHTML('beforeend',
      '<div style="' + style + ' border-radius:13px; padding:10px 14px; max-width:78%; font-size:13.5px; line-height:1.55; white-space:pre-wrap;">' + html + '</div>');
    $id('chatLog').scrollTop = $id('chatLog').scrollHeight;
  }

  /* [p.3] · "3페이지" → 클릭 가능한 링크로 치환 */
  function linkifyPages(text){
    var link = function(n, label){
      return '<a style="color:var(--accent-deep); font-weight:700; cursor:pointer; text-decoration:underline;" data-page="' + n + '">' + label + '</a>';
    };
    return esc(text)
      .replace(/\[p\.(\d+)\]/g, function(_, n){ return link(n, '[p.' + n + ']'); })
      .replace(/(\d+)페이지/g, function(_, n){ return link(n, n + '페이지'); });
  }
  function bindPageLinks(){
    $id('chatLog').querySelectorAll('a[data-page]:not([data-bound])').forEach(function(a){
      a.dataset.bound = '1';
      a.onclick = function(){ Screens.s3.show(sel().value, +a.dataset.page); };
    });
  }

  function renderSources(sources){
    var box = $id('chatSources');
    if(!sources.length){
      box.innerHTML = '<div class="note">직접 관련된 근거를 찾지 못했습니다.</div>';
      return;
    }
    var max = Math.max.apply(null, sources.map(function(s){ return s.score; })) || 1;
    box.innerHTML = sources.map(function(s){
      var quotes = (s.evidence || []).slice(0, 2).map(function(e){
        return '<div style="font-size:12px; color:var(--text-secondary); margin-top:3px;">↳ “' + esc(e.quote) + '”</div>';
      }).join('');
      return '<div class="art"><div class="t">p.' + s.slide_number + ' · ' + esc(s.page_title) + '</div>' +
        '<div class="m"><span>' + esc(s.summary).slice(0, 60) + '…</span>' +
        '<span class="rel"><span class="relbar"><i style="width:' + Math.round(s.score / max * 100) + '%"></i></span>' + s.score.toFixed(3) + '</span></div>' +
        quotes + '</div>';
    }).join('');
  }

  function send(){
    var input = $id('chatInput');
    var q = input.value.trim();
    if(!q || !reports.length) return;
    input.value = '';
    bubble('user', esc(q));
    var btn = $id('chatSend');
    btn.classList.add('disabled');
    API.post('/api/chat', { report_id: sel().value, question: q, mode: mode }).then(function(d){
      bubble('ai', linkifyPages(d.answer));
      bindPageLinks();
      renderSources(d.sources || []);
    }).catch(function(e){
      bubble('ai', '오류: ' + esc(e.message));
    }).then(function(){
      btn.classList.remove('disabled');
    });
  }

  function clearConversation(){
    $id('chatLog').innerHTML = '';
    $id('chatSources').innerHTML = '';
    if(reports.length){
      bubble('ai', '업로드된 보고서에 대해 질문해 주세요. 답변에는 근거 페이지 번호가 함께 표시됩니다.');
    }
  }

  var bound = false;
  function bind(){
    if(bound) return; bound = true;
    $id('chatSend').onclick = send;
    $id('chatInput').addEventListener('keydown', function(e){ if(e.key === 'Enter') send(); });
    sel().onchange = clearConversation;
  }

  return {
    load: function(){
      bind();
      renderModes();
      var keep = sel().value;
      API.get('/api/reports').then(function(r){
        reports = r;
        sel().innerHTML = reports.map(function(x){
          return '<option value="' + x.id + '">' + esc(x.name) + ' (' + x.slide_count + 'p)</option>';
        }).join('');
        if(!reports.length){
          $id('chatLog').innerHTML = '';
          $id('chatSources').innerHTML = '';
          $id('chatLog').innerHTML = '<div class="note">업로드된 보고서가 없습니다. 업로드 · 취합 화면에서 PPT를 올려 주세요.</div>';
          return;
        }
        var changed = keep !== sel().value;
        if(keep && reports.some(function(x){ return x.id === keep; })){ sel().value = keep; changed = false; }
        if(changed || !$id('chatLog').childElementCount) clearConversation();
      });
    }
  };
})();
