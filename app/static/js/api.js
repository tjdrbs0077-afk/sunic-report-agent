/* fetch 래퍼 — 모든 화면이 이 모듈로만 서버와 통신한다. */
var API = {
  get: function(url){
    return fetch(url).then(API._json);
  },
  post: function(url, body){
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(API._json);
  },
  put: function(url, body){
    return fetch(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(API._json);
  },
  patch: function(url, body){
    return fetch(url, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(API._json);
  },
  del: function(url){
    return fetch(url, { method: 'DELETE' }).then(API._json);
  },
  upload: function(url, files){
    var form = new FormData();
    for(var i = 0; i < files.length; i++) form.append('files', files[i]);
    return fetch(url, { method: 'POST', body: form }).then(API._json);
  },
  _json: function(res){
    return res.json().catch(function(){ return {}; }).then(function(data){
      if(!res.ok){
        var detail = data && data.detail;
        var msg = typeof detail === 'string' ? detail
          : (detail && detail.message) ? detail.message
          : '요청이 실패했습니다 (' + res.status + ')';
        throw new Error(msg);
      }
      return data;
    });
  }
};
