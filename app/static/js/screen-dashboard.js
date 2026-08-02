/* ① 현황 대시보드 — /api/stats + /api/reports 실데이터 렌더링 */
Screens.s1 = (function(){

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
    document.getElementById('stReportsSub').textContent = empty ? '업로드된 보고서가 없습니다' : '표준양식 PPT ' + stats.generated_count + '건 생성됨';
    document.getElementById('stDone').innerHTML = empty ? '—' : stats.done_count + '<small> / ' + stats.report_count + '건</small>';
    document.getElementById('stDoneSub').textContent = empty ? '업로드된 보고서가 없습니다' : (stats.report_count - stats.done_count) + '건 처리 중';
    document.getElementById('stIssues').innerHTML = empty ? '—' : String(stats.issue_total) + '<small> 건</small>';
    document.getElementById('stIssuesSub').textContent = empty ? '업로드된 보고서가 없습니다'
      : '보고서당 평균 ' + (stats.issue_total / stats.report_count).toFixed(1) + '건';
    document.getElementById('stAvg').innerHTML = empty ? '—' : fmtAvg(stats.avg_processing_seconds);
    document.getElementById('stAvgSub').textContent = empty ? '업로드된 보고서가 없습니다' : '업로드 → 추출 · 양식 검사 기준';
  }

  function renderTable(reports){
    var tb = document.getElementById('dashTable');
    var emptyBox = document.getElementById('dashEmpty');
    tb.innerHTML = '';
    if(!reports.length){
      emptyBox.style.display = '';
      return;
    }
    emptyBox.style.display = 'none';
    reports.forEach(function(r){
      var stateChip = r.status === 'done' ? '<span class="chip ok">완료</span>' : '<span class="chip run">처리 중</span>';
      tb.insertAdjacentHTML('beforeend',
        '<tr class="rowhover"><td><b>' + esc(r.name) + '</b></td>' +
        '<td><span class="chip ok">제출</span></td>' +
        '<td>' + stateChip + '</td>' +
        '<td class="num">' + (r.issue_count || 0) + '건</td>' +
        '<td class="num" style="color:var(--text-muted)">' + fmtTime(r.uploaded_at) + '</td></tr>');
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

  return {
    load: function(){
      Promise.all([API.get('/api/stats'), API.get('/api/reports')]).then(function(res){
        var stats = res[0], reports = res[1];
        renderTiles(stats);
        renderTable(reports);
        renderErrChart(stats);
        renderDonut(stats);
      }).catch(function(e){
        document.getElementById('dashTable').innerHTML =
          '<tr><td colspan="5" style="color:var(--text-muted)">불러오기 실패: ' + esc(e.message) + '</td></tr>';
      });
    }
  };
})();
