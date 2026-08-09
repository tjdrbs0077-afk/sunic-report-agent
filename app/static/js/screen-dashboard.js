/* ① 현황 대시보드 — /api/stats + /api/reports 실데이터 렌더링 */
Screens.s1 = (function(){
  var activeReports = [];
  var archivedReports = [];
  var currentView = 'active';

  function fmtTime(iso){
    if(!iso) return '—';
    var d = new Date(iso);
    if(isNaN(d)) return '—';
    var mm = String(d.getMinutes()).padStart(2,'0');
    return (d.getMonth()+1) + '/' + d.getDate() + ' ' + d.getHours() + ':' + mm;
  }
  function fmtAvg(sec){
    if(!sec) return '—';
    if(sec < 60) return sec.toFixed(1) + '<small>초</small>';
    return Math.floor(sec/60) + '<small>분</small> ' + Math.round(sec%60) + '<small>초</small>';
  }

  function renderTiles(stats){
    var empty = stats.report_count === 0;
    document.getElementById('stReports').innerHTML = empty ? '—' : String(stats.report_count) + '<small> 건</small>';
    document.getElementById('stReportsSub').textContent = empty
      ? (stats.archived_count ? '보관함 ' + stats.archived_count + '건' : '업로드된 보고서가 없습니다')
      : (stats.archived_count ? '보관함 ' + stats.archived_count + '건' : '현재 작업 중인 보고서');
    document.getElementById('stDone').innerHTML = empty ? '—' : stats.done_count + '<small> / ' + stats.report_count + '건</small>';
    document.getElementById('stDoneSub').textContent = empty ? '업로드된 보고서가 없습니다' : (stats.report_count - stats.done_count) + '건 처리 중';
    document.getElementById('stIssues').innerHTML = empty ? '—' : String(stats.issue_total) + '<small> 건</small>';
    document.getElementById('stIssuesSub').textContent = empty ? '업로드된 보고서가 없습니다'
      : '보고서당 평균 ' + (stats.issue_total / stats.report_count).toFixed(1) + '건';
    document.getElementById('stAvg').innerHTML = empty ? '—' : fmtAvg(stats.avg_processing_seconds);
    document.getElementById('stAvgSub').textContent = empty ? '업로드된 보고서가 없습니다' : '업로드 → 추출 · 양식 검사 기준';
  }

  function renderTable(reports, archived){
    var tb = document.getElementById('dashTable');
    var emptyBox = document.getElementById('dashEmpty');
    document.getElementById('dashProjectTitle').textContent = archived ? '보관된 프로젝트' : '현재 프로젝트';
    document.getElementById('dashDateHead').textContent = archived ? '보관 시각' : '등록 시각';
    tb.innerHTML = '';
    if(!reports.length){
      emptyBox.style.display = '';
      document.getElementById('dashEmptyText').textContent = archived
        ? '보관된 프로젝트가 없습니다.' : '현재 프로젝트가 없습니다.';
      document.getElementById('dashEmptyAction').style.display = archived ? 'none' : '';
      return;
    }
    emptyBox.style.display = 'none';
    reports.forEach(function(r){
      var stateChip = archived ? '<span class="chip wait">보관됨</span>'
        : (r.status === 'done' ? '<span class="chip ok">완료</span>' : '<span class="chip run">처리 중</span>');
      var action = archived
        ? '<button class="btn ghost dashboard-row-action" data-unarchive="' + esc(r.id) + '">복구</button>'
        : '<button class="btn ghost dashboard-row-action" data-archive="' + esc(r.id) + '" ' + (r.status === 'done' ? '' : 'disabled') + '>보관</button>';
      tb.insertAdjacentHTML('beforeend',
        '<tr class="rowhover"><td><b>' + esc(r.name) + '</b></td>' +
        '<td>' + stateChip + '</td>' +
        '<td class="num">' + (r.issue_count || 0) + '건</td>' +
        '<td class="num" style="color:var(--text-muted)">' + fmtTime(archived ? r.archived_at : r.uploaded_at) + '</td>' +
        '<td class="num">' + action + '</td></tr>');
    });
    tb.querySelectorAll('button[data-archive]').forEach(function(btn){
      btn.onclick = function(){ changeArchived(btn.dataset.archive, true, btn); };
    });
    tb.querySelectorAll('button[data-unarchive]').forEach(function(btn){
      btn.onclick = function(){ changeArchived(btn.dataset.unarchive, false, btn); };
    });
  }

  function setView(view){
    currentView = view;
    document.querySelectorAll('[data-dashboard-view]').forEach(function(btn){
      var active = btn.dataset.dashboardView === view;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    renderTable(view === 'archived' ? archivedReports : activeReports, view === 'archived');
  }

  function changeArchived(reportId, archived, btn){
    btn.disabled = true;
    btn.textContent = archived ? '보관 중…' : '복구 중…';
    API.post('/api/reports/' + reportId + '/' + (archived ? 'archive' : 'unarchive'))
      .then(loadData)
      .catch(function(e){
        btn.disabled = false;
        btn.textContent = archived ? '보관' : '복구';
        showTip({ clientX: 24, clientY: 24 }, '처리 실패: ' + esc(e.message));
        setTimeout(hideTip, 2400);
      });
  }

  function renderErrChart(stats){
    var box = document.getElementById('errChart');
    box.innerHTML = '';
    document.getElementById('dashErrTotal').textContent = stats.issue_total ? '전체 ' + stats.issue_total + '건' : '';
    if(!stats.issues_by_category.length){
      box.innerHTML = '<div class="note">' + (stats.report_count ? '발견된 양식 오류가 없습니다. ✓' : '업로드된 보고서가 없습니다.') + '</div>';
      return;
    }
    var max = stats.issues_by_category[0].count || 1;
    stats.issues_by_category.forEach(function(e){
      box.insertAdjacentHTML('beforeend',
        '<div class="bar-row" data-d="' + esc(e.category) + ' 위반"><span class="bl">' + esc(e.category) + '</span>' +
        '<span class="bar-track"><span class="bar-fill" data-w="' + (e.count / max * 100) + '"></span></span>' +
        '<span class="bv">' + e.count + '</span></div>');
    });
    box.querySelectorAll('.bar-row').forEach(function(row){
      row.addEventListener('mousemove', function(ev){
        showTip(ev, '<b>' + row.querySelector('.bl').textContent + ' · ' +
          row.querySelector('.bv').textContent + '건</b><br>' + row.dataset.d);
      });
      row.addEventListener('mouseleave', hideTip);
    });
    requestAnimationFrame(function(){
      box.querySelectorAll('.bar-fill').forEach(function(f){ f.style.width = f.dataset.w + '%'; });
    });
  }

  function renderDonut(stats){
    var circumference = 276.5;
    var arc = document.getElementById('donutArc');
    var pctEl = document.getElementById('donutPct');
    var subEl = document.getElementById('donutSub');
    var legend = document.getElementById('donutLegend');
    if(!stats.report_count){
      arc.setAttribute('stroke-dasharray', '0 ' + circumference);
      pctEl.textContent = '—';
      subEl.textContent = '';
      legend.innerHTML = '<span style="color:var(--text-muted); font-size:12px;">업로드된 보고서가 없습니다</span>';
      return;
    }
    var pct = Math.round(stats.done_count / stats.report_count * 100);
    arc.setAttribute('stroke-dasharray', (pct / 100 * circumference).toFixed(1) + ' ' + circumference);
    pctEl.textContent = pct + '%';
    subEl.textContent = stats.done_count + ' / ' + stats.report_count + '건';
    legend.innerHTML =
      '<span><i class="lg-dot" style="background:#ea002c"></i>처리 완료 ' + stats.done_count + '건</span>' +
      '<span><i class="lg-dot" style="background:#e1e0d9"></i>처리 중 ' + (stats.report_count - stats.done_count) + '건</span>';
  }

  function loadData(){
    return Promise.all([
      API.get('/api/stats'),
      API.get('/api/reports'),
      API.get('/api/reports?archived=true')
    ]).then(function(res){
        var stats = res[0];
        // API 응답이 섞여 오더라도 보관 여부를 기준으로 화면 목록을 분리한다.
        activeReports = res[1].filter(function (report) {
          return report.archived !== true;
        });
        archivedReports = res[2].filter(function (report) {
          return report.archived === true;
        });
        renderTiles(stats);
        document.getElementById('dashArchiveCount').textContent = archivedReports.length;
        setView(currentView);
        renderErrChart(stats);
        renderDonut(stats);
      }).catch(function(e){
        document.getElementById('dashTable').innerHTML =
          '<tr><td colspan="5" style="color:var(--text-muted)">불러오기 실패: ' + esc(e.message) + '</td></tr>';
      });
  }

  var bound = false;
  function bind(){
    if(bound) return;
    bound = true;
    document.querySelectorAll('[data-dashboard-view]').forEach(function(btn){
      btn.onclick = function(){ setView(btn.dataset.dashboardView); };
    });
  }

  return {
    load: function(){
      bind();
      loadData();
    }
  };
})();
