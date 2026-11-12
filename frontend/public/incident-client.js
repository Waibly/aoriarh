/* Technical metadata only. No user text, original request body or credentials persisted. */
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
  // Credentials live only in memory for the event that supplied them.
  var eventTokens = new Map();
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
      location: safeLocation(), visitor_id: visitor, occurred_at: Date.now(),
      online: navigator.onLine === true,
      visibility: document.visibilityState === 'hidden' ? 'hidden' : 'visible' };
    var operation = requestOperation(options.request_path);
    if (operation) event.operation = operation;
    if (['GET','POST','PUT','PATCH','DELETE','OPTIONS','HEAD'].indexOf(options.method) >= 0) event.method = options.method;
    ['elapsed_ms','timeout_ms'].forEach(function (key) {
      if (Number.isFinite(options[key]) && options[key] >= 0 && options[key] <= 86400000) {
        event[key] = Math.round(options[key]);
      }
    });
    if (['provider_quota_exhausted','provider_rate_limited','server_error',
      'resource_next_script','resource_next_stylesheet','resource_turnstile',
      'resource_analytics','resource_image','resource_stylesheet','resource_script',
      'resource_frame','resource_other'].indexOf(options.reason) >= 0) event.reason = options.reason;
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
      if (typeof options.token === 'string' && options.token) eventTokens.set(event.id, options.token);
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
          var headers = {'Content-Type':'application/json'};
          if (eventTokens.has(item.event.id)) headers.Authorization = 'Bearer ' + eventTokens.get(item.event.id);
          var response = await nativeFetch(endpoint, {method:'POST', credentials:'omit',
            headers:headers, body:JSON.stringify(item.event),
            keepalive:true, signal:AbortSignal.timeout(8000)});
          if (response.status !== 202) break;
          queue.splice(queue.indexOf(item), 1);
          eventTokens.delete(item.event.id);
          persist();
        } catch (_) { break; }
      }
    } finally { flushing = false; }
  }
  window.aoriaReportIncident = report;
  function requestOperation(path) {
    // Closed technical categories; no path parameter, query or arbitrary URL is stored.
    if (typeof path !== 'string') return null;
    var routes = [
      [/^\/api\/v1\/users\/me\/?$/, 'users.me'],
      [/^\/api\/v1\/billing\/quota\/?$/, 'billing.quota'],
      [/^\/api\/v1\/organisations\/?$/, 'organisations.list'],
      [/^\/api\/v1\/conventions\/organisations\/[^/]+\/?$/, 'conventions.organisation'],
      [/^\/api\/v1\/conversations\/?$/, 'conversations.list'],
      [/^\/api\/v1\/conversations\/[^/]+\/messages\/?$/, 'conversations.messages'],
      [/^\/api\/v1\/conversations\/[^/]+\/?$/, 'conversations.read'],
      [/^\/api\/v1\/dossiers\/?$/, 'dossiers.list'],
      [/^\/api\/auth\/session\/?$/, 'auth.session'],
      [/^\/api\/v1\/auth\//, 'auth'],
      [/^\/api\/v1\/documents(?:\/|$)/, 'documents'],
      [/^\/api\/v1\/billing(?:\/|$)/, 'billing'],
      [/^\/api\/v1\/admin(?:\/|$)/, 'admin'],
      [/^\/api\/v1\//, 'api.other']
    ];
    for (var i=0; i<routes.length; i++) if (routes[i][0].test(path)) return routes[i][1];
    return 'frontend.other';
  }
  function resourceReason(target) {
    // Classify locally. Never transmit URLs, query strings, filenames, or DOM text.
    var tag = String(target.tagName || '').toLowerCase();
    try {
      var url = new URL(target.currentSrc || target.src || target.href, location.href);
      if (url.hostname === 'challenges.cloudflare.com') return 'resource_turnstile';
      if (url.hostname === 'www.googletagmanager.com') return 'resource_analytics';
      if (url.origin === location.origin && url.pathname.indexOf('/_next/static/') === 0) {
        if (tag === 'script') return 'resource_next_script';
        if (tag === 'link' && target.rel === 'stylesheet') return 'resource_next_stylesheet';
      }
    } catch (_) {}
    if (tag === 'img') return 'resource_image';
    if (tag === 'script') return 'resource_script';
    if (tag === 'link' && target.rel === 'stylesheet') return 'resource_stylesheet';
    if (tag === 'iframe') return 'resource_frame';
    return 'resource_other';
  }
  window.addEventListener('error', function (event) {
    var resource = event.target && event.target !== window;
    report(resource ? 'resource_error' : 'javascript_error',
      resource ? {reason: resourceReason(event.target)} : {});
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
    var started = performance.now();
    var requestHeaders = new Headers((init && init.headers) || (typeof input === 'object' && input.headers) || {});
    var metadata = {request_path:url.pathname, method:String((init && init.method) || (typeof input === 'object' && input.method) || 'GET').toUpperCase(),
      request_id:requestHeaders.get('X-Aoria-Request-ID')};
    var authorization = requestHeaders.get('Authorization');
    if (url.origin === 'https://api.aoriarh.fr' && authorization && /^Bearer /i.test(authorization)) metadata.token = authorization.slice(7);
    try {
      var response = await nativeFetch(input, init);
      metadata.elapsed_ms = Math.round(performance.now() - started);
      var managed401 = response.status === 401 && requestHeaders.get('X-Aoria-Auth-Retry') === 'managed';
      if (!response.ok && !managed401) report('http_error', Object.assign({}, metadata, {status:response.status, request_id:response.headers.get('X-Request-ID') || metadata.request_id}));
      return response;
    } catch (error) {
      var signal = (init && init.signal) || (typeof input === 'object' && input.signal);
      // Explicit cancellation is not an application failure. Timeout remains an error.
      if (!(signal && signal.aborted && signal.reason && signal.reason.name === 'AbortError')) {
        metadata.elapsed_ms = Math.round(performance.now() - started);
        report(error && error.name === 'TimeoutError' ? 'request_timeout' : 'network_error', metadata);
      }
      throw error;
    }
  };
  void flush();
})();
