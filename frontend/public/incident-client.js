/* AORIA technical incidents. No text, query string, request body or credentials. */
(function () {
  'use strict';
  if (window.aoriaReportIncident) return;
  var host = location.hostname;
  if (host !== 'aoriarh.fr' && host !== 'www.aoriarh.fr' && host !== 'app.aoriarh.fr') return;
  var source = host === 'app.aoriarh.fr' ? 'app' : 'site';
  var endpoint = 'https://api.aoriarh.fr/api/v1/telemetry/incidents';
  var nativeFetch = window.fetch.bind(window);
  var storageKey = 'aoria-technical-incidents-v1';
  var queue = [];
  var flushing = false;
  var visitor = crypto.randomUUID();
  try {
    visitor = sessionStorage.getItem('aoria-incident-visitor') || visitor;
    sessionStorage.setItem('aoria-incident-visitor', visitor);
    queue = JSON.parse(sessionStorage.getItem(storageKey) || '[]');
    if (!Array.isArray(queue)) queue = [];
    queue = queue.filter(function (item) { return item && Date.now() - item.at < 86400000; });
  } catch (_) { queue = []; }
  function persist() {
    try { sessionStorage.setItem(storageKey, JSON.stringify(queue)); } catch (_) {}
  }
  function safeLocation() {
    // Report the functional area, never path parameters (invitation tokens, IDs).
    var parts = location.pathname.split('/').filter(Boolean);
    var allowed = ['demo','chat','documents','dossiers','recherche','fiches','billing','account','team',
      'organisation','login','register','invite','promo','admin','outils','fonctionnalites',
      'dossiers','veille','pour','confidentialite','securite','a-propos','glossaire'];
    return parts.length === 0 ? '/' : (allowed.indexOf(parts[0]) >= 0 ? '/' + parts[0] : '/other');
  }
  function report(code, options) {
    options = options || {};
    var event = { id: options.id || crypto.randomUUID(), source: source, code: code,
      location: safeLocation(), visitor_id: visitor };
    if (options.request_id) event.request_id = options.request_id;
    if (options.status >= 400 && options.status <= 599) event.status = options.status;
    // No event sampling. Bound browser memory; disclose overflow as its own incident.
    if (queue.length >= 500) {
      if (!queue.some(function (x) { return x.event.location === 'telemetry_queue_overflow'; })) {
        queue.push({event: {id:crypto.randomUUID(),source:source,code:'ui_error',location:'telemetry_queue_overflow'},at:Date.now(),tries:0});
      }
      return;
    }
    if (!queue.some(function (x) { return x.event.id === event.id; })) {
      queue.push({event:event,at:Date.now(),tries:0});
      persist();
    }
    void flush();
  }
  async function flush() {
    if (flushing || !navigator.onLine) return;
    flushing = true;
    try {
      while (queue.length) {
        var item = queue.find(function (candidate) { return candidate.tries < 8; });
        if (!item) break; // retained for diagnosis; never retry without bound
        item.tries++;
        persist();
        try {
          var response = await nativeFetch(endpoint, {method:'POST', credentials:'omit',
            headers:{'Content-Type':'application/json'}, body:JSON.stringify(item.event),
            keepalive:true, signal:AbortSignal.timeout(8000)});
          if (response.status !== 202) break;
          queue.splice(queue.indexOf(item), 1);
          persist();
        } catch (_) { break; }
      }
    } finally { flushing = false; }
  }
  window.aoriaReportIncident = report;
  window.addEventListener('error', function (event) {
    report(event.target && event.target !== window ? 'resource_error' : 'javascript_error');
  }, true);
  window.addEventListener('unhandledrejection', function () { report('unhandled_rejection'); });
  document.addEventListener('invalid', function () { report('form_invalid'); }, true);
  window.addEventListener('online', flush);
  window.setInterval(flush, 30000);
  window.fetch = async function (input, init) {
    var url;
    try { url = new URL(typeof input === 'string' || input instanceof URL ? String(input) : input.url, location.href); }
    catch (_) { return nativeFetch(input, init); }
    // Observe product requests only; no advertising/analytics traffic.
    var owned = url.origin === location.origin || url.origin === 'https://api.aoriarh.fr';
    if (!owned || url.pathname === '/api/v1/telemetry/incidents') return nativeFetch(input, init);
    try {
      var response = await nativeFetch(input, init);
      if (!response.ok) report('http_error', {status:response.status, request_id:response.headers.get('X-Request-ID')});
      return response;
    } catch (error) {
      var signal = (init && init.signal) || (typeof input === 'object' && input.signal);
      // Explicit cancellation is not an application failure. Timeout remains an error.
      if (!(signal && signal.aborted && signal.reason && signal.reason.name === 'AbortError')) {
        report(error && error.name === 'TimeoutError' ? 'request_timeout' : 'network_error');
      }
      throw error;
    }
  };
  void flush();
})();
