/* Control room wiring: load state.json and review.json from beside the page, subscribe to the
   store (decisions, answers, pull request events, labels), switch tabs and follow anchors. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var state = null, review = null, db = null, sample = null;
  var live = { db: 'pending', questions: [], answers: {}, events: {}, labels: {} };
  var pending = location.hash ? location.hash.slice(1) : null;
  var current = null, activeTab = null;
  var draft = {}, said = {}, qdraft = {};
  var TAB_KEY = 'control-room-tab';

  function remember(tab) { try { localStorage.setItem(TAB_KEY, tab); } catch (e) { /* storage may be blocked */ } }
  function remembered() { try { return localStorage.getItem(TAB_KEY); } catch (e) { return null; } }

  /* ---------- tabs and anchors ---------- */

  function showTab(tab, keepFocus) {
    if (CR.TABS.indexOf(tab) < 0 || (tab === 'review' && !review)) tab = 'needs';
    activeTab = tab;
    CR.TABS.forEach(function (t) {
      var on = t === tab;
      $('tab-' + t).setAttribute('aria-selected', String(on));
      $('tab-' + t).tabIndex = on ? 0 : -1;
      $(t).hidden = !on;
    });
    remember(tab);
    if (!keepFocus) window.scrollTo({ top: 0 });
  }
  function reveal(id) {
    var el = $(id);
    if (!el) return false;
    if (/^item-/.test(id)) { select(id.slice(5)); el = $(id); }
    for (var p = el.parentElement; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true;
    if (el.tagName === 'DETAILS') el.open = true;
    // Mark first: the flash class carries the scroll margin that keeps the target clear of the tab bar.
    el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');
    el.scrollIntoView({ block: 'start' });
    return true;
  }
  function follow(hash) {
    var r = CR.route(hash, { review: review, live: live });
    if (!r) return false;
    showTab(r.tab, !!r.target);
    if (r.target && !reveal(r.target)) pending = r.target; else pending = null;
    return true;
  }
  function setHash(h) { try { history.replaceState(null, '', '#' + h); } catch (e) { /* not allowed in every frame */ } }

  $('tablist').addEventListener('click', function (e) {
    var a = e.target.closest('a.tab'); if (!a) return;
    e.preventDefault();
    var tab = a.id.slice(4);
    showTab(tab); setHash(tab);
  });
  $('tablist').addEventListener('keydown', function (e) {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    var tabs = CR.TABS.filter(function (t) { return !$('tab-' + t).hidden; });
    var i = tabs.indexOf(activeTab) + (e.key === 'ArrowRight' ? 1 : -1);
    var next = tabs[(i + tabs.length) % tabs.length];
    showTab(next); setHash(next); $('tab-' + next).focus();
  });
  document.addEventListener('click', function (e) {
    var a = e.target.closest('a[href^="#"]');
    if (!a || a.classList.contains('tab')) return;
    var h = a.getAttribute('href').slice(1);
    if (follow(h)) { e.preventDefault(); setHash(h); }
  });
  window.addEventListener('hashchange', function () { follow(location.hash); });

  /* ---------- rendering ---------- */

  function keepDecisionDrafts() {
    document.querySelectorAll('#needs .q').forEach(function (el) {
      var id = el.id.slice(2);
      var picked = el.querySelector('input[type=radio]:checked');
      var note = el.querySelector('textarea');
      qdraft[id] = { choice: picked ? picked.value : null, note: note ? note.value : '' };
    });
  }
  function restoreDecisionDrafts() {
    Object.keys(qdraft).forEach(function (id) {
      var el = $('q-' + id); if (!el || !el.closest('#needs')) return;
      var d = qdraft[id];
      el.querySelectorAll('input[type=radio]').forEach(function (r) { r.checked = r.value === d.choice; });
      var note = el.querySelector('textarea'); if (note) note.value = d.note || '';
    });
  }
  function renderLive() {
    if (!state) return;
    var focused = document.activeElement && document.activeElement.closest && document.activeElement.closest('#needs .q');
    var focusId = focused ? document.activeElement.id : null;
    keepDecisionDrafts();
    $('needs').innerHTML = CR.renderNeeds(state, live);
    restoreDecisionDrafts();
    if (focusId && $(focusId)) $(focusId).focus();
    var opened = Array.prototype.map.call(document.querySelectorAll('#records details[open]'), function (d) { return d.id; });
    $('records').innerHTML = CR.renderRecords(state, live);
    opened.forEach(function (id) { if (id && $(id)) $(id).open = true; });
    var n = CR.needsCount(state, live);
    $('badge-needs').hidden = !n; $('badge-needs').textContent = n;
    // A decision or pull request anchor waits for the store; try it once when the store answers.
    if (pending && /^(q-|pr-)/.test(pending) && live.db !== 'pending') {
      var p = pending; pending = null;
      if ($(p)) follow('#' + p);
    }
  }
  function renderStatic() {
    $('fresh').textContent = CR.freshness(state);
    $('lanes').innerHTML = CR.renderLanes(state);
    $('findings').innerHTML = CR.renderFindings(state);
  }
  $('needs').addEventListener('click', function (e) {
    var b = e.target.closest('button[data-save]'); if (b) saveDecision(b.getAttribute('data-save'));
  });
  // One write at a time per document: a second click or Enter while a save is in flight does nothing.
  var saving = {};
  async function saveDecision(qid) {
    var card = $('q-' + qid); if (!card || saving['answers/' + qid]) return;
    var picked = card.querySelector('input[type=radio]:checked');
    var note = (card.querySelector('textarea').value || '').trim();
    var st = card.querySelector('.status');
    if (!picked) { st.textContent = 'Pick an option first.'; return; }
    if (!db) { st.textContent = 'Not saved: this view cannot reach the store.'; return; }
    st.textContent = 'Saving.';
    saving['answers/' + qid] = true;
    card.querySelector('button[data-save]').disabled = true;
    try {
      var body = { choice: picked.value, note: note, updated: new Date().toISOString() };
      await db.doc('answers/' + qid).set(body);
      live.answers[qid] = body; delete qdraft[qid];
      delete saving['answers/' + qid];
      renderLive();
    } catch (err) {
      delete saving['answers/' + qid];
      var c = $('q-' + qid);
      if (c) { c.querySelector('button[data-save]').disabled = false; c.querySelector('.status').textContent = 'Not saved (' + (err && err.code || 'error') + '). Try again.'; }
    }
  }

  /* ---------- review bench ---------- */

  function renderReviewList() {
    if (!review) return;
    $('list').innerHTML = CR.reviewList(review, live.labels, current);
    var p = CR.reviewProgress(review, live.labels);
    $('progressText').textContent = p.text;
    $('progressBar').style.width = (p.total ? 100 * p.done / p.total : 0) + '%';
    var left = p.total - p.done;
    $('badge-review').hidden = !left; $('badge-review').textContent = left;
  }
  function renderReviewDetail() {
    if (!review) return;
    var r = (review.rows || []).filter(function (x) { return x.id === current; })[0];
    var l = live.labels[current] || {};
    var value = draft[current] != null ? draft[current] : (l.goal || '');
    $('detail').innerHTML = CR.reviewDetail(review, r, l, value, CR.usedLabels(live.labels), said[current]);
    if (!r) return;
    var input = $('goal');
    input.addEventListener('input', function () { draft[r.id] = input.value; });
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); saveLabel(r.id); } });
    $('detail').querySelectorAll('button[data-goal]').forEach(function (b) {
      b.addEventListener('click', function () { input.value = b.getAttribute('data-goal'); draft[r.id] = input.value; input.focus(); });
    });
    $('save').addEventListener('click', function () { saveLabel(r.id); });
    $('skip').addEventListener('click', function () { next(r.id); });
    if ($('clear')) $('clear').addEventListener('click', function () { clearLabel(r.id); });
    if (sample && review.assist) {
      $('assist').hidden = false;
      $('said').addEventListener('input', function () { said[r.id] = $('said').value; });
      $('suggest').addEventListener('click', function () { suggest(r); });
    }
  }
  function select(id) {
    if (!review || !(review.rows || []).some(function (r) { return r.id === id; })) return;
    current = id; renderReviewList(); renderReviewDetail();
    var el = document.querySelector('.row.active'); if (el) el.scrollIntoView({ block: 'nearest' });
  }
  function next(id) {
    var rows = review.rows || [];
    var i = rows.findIndex(function (x) { return x.id === id; });
    var after = rows.slice(i + 1).concat(rows.slice(0, i));
    var target = after.filter(function (x) { return !(live.labels[x.id] && live.labels[x.id].goal); })[0] || after[0];
    if (target) select(target.id);
  }
  async function saveLabel(id) {
    if (saving['labels/' + id]) return;
    var goal = ($('goal').value || '').trim().toLowerCase().replace(/\s+/g, '-');
    var st = $('ls');
    if (!goal) { st.textContent = 'Type something first.'; return; }
    if (!db) { st.textContent = 'Not saved: this view cannot reach the store.'; return; }
    st.textContent = 'Saving.';
    saving['labels/' + id] = true; $('save').disabled = true;
    try {
      var body = { goal: goal, updated: new Date().toISOString() };
      if (said[id]) body.said = said[id];
      await db.doc('labels/' + id).set(body);
      delete saving['labels/' + id];
      live.labels[id] = body; delete draft[id];
      next(id); renderReviewList();
    } catch (err) {
      delete saving['labels/' + id];
      if (current === id && $('save')) { $('save').disabled = false; $('ls').textContent = 'Not saved (' + (err && err.code || 'error') + '). Try again.'; }
    }
  }
  async function clearLabel(id) {
    if (!db || saving['labels/' + id]) return;
    saving['labels/' + id] = true;
    try { await db.doc('labels/' + id).delete(); delete live.labels[id]; delete draft[id]; delete saving['labels/' + id]; renderReviewList(); renderReviewDetail(); }
    catch (err) { delete saving['labels/' + id]; if ($('ls')) $('ls').textContent = 'Not cleared. Try again.'; }
  }
  async function suggest(r) {
    var out = $('suggestion'), btn = $('suggest');
    btn.disabled = true; out.textContent = 'Thinking.';
    var used = CR.usedLabels(live.labels).map(function (u) { return u[0]; });
    var prompt = review.assist + '\n\nLabels already in use (reuse one when it fits, exactly as written): ' + (used.length ? used.join(', ') : 'none yet') + '.'
      + '\n\nWhat the person says they wanted: ' + (($('said').value || '').trim() || '(nothing said)')
      + '\n\nHow the item starts:\n' + (r.turns || []).map(function (t) { return t.who + ': ' + t.text; }).join('\n\n').slice(0, 4000)
      + '\n\nAnswer with JSON only: {"label": "<lowercase, 1 to 3 words joined by hyphens>", "reason": "<one short sentence>"}';
    try {
      var v = await sample.json(prompt, { modelTier: 'quick' });
      var label = String(v && v.label || '').trim().toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^-+|-+$/g, '');
      if (!label) throw new Error('empty');
      $('goal').value = label; draft[r.id] = label;
      out.innerHTML = 'Suggested <b>' + CR.esc(label) + '</b>' + (v.reason ? ': ' + CR.esc(v.reason) : '') + '. Edit it if it is not right, then save.';
    } catch (err) {
      out.textContent = err && err.code === 'not_granted' ? 'Suggestions are off for this page.' : 'No suggestion this time. Type your own.';
    }
    btn.disabled = false;
  }
  $('review').addEventListener('click', function (e) { var row = e.target.closest('.row[data-item]'); if (row) select(row.getAttribute('data-item')); });
  $('review').addEventListener('keydown', function (e) {
    var row = e.target.closest('.row[data-item]');
    if (row && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); select(row.getAttribute('data-item')); }
  });

  /* ---------- loading ---------- */

  function fail(msg) {
    $('fresh').textContent = msg;
    ['needs', 'lanes', 'findings', 'records'].forEach(function (t) {
      $(t).innerHTML = '<p class="note warn">' + CR.esc(msg) + '</p>';
    });
  }
  var stateLoad = fetch('state.json', { cache: 'no-store' }).then(function (r) {
    if (!r.ok) throw new Error('state.json answered ' + r.status);
    return r.json();
  });
  var reviewLoad = fetch('review.json', { cache: 'no-store' }).then(function (r) {
    if (r.status === 404 || !r.ok) return null; // no review round published: the tab stays hidden
    return r.json();
  }).catch(function () { return null; });

  Promise.all([stateLoad, reviewLoad]).then(function (both) {
    state = both[0]; review = both[1] && (both[1].rows || []).length ? both[1] : null;
    if (review) {
      $('tab-review').hidden = false;
      $('review').innerHTML = CR.reviewShell(review);
      var wanted = pending && /^item-/.test(pending) ? pending.slice(5) : null;
      current = wanted && review.rows.some(function (r) { return r.id === wanted; }) ? wanted : review.rows[0].id;
      renderReviewList(); renderReviewDetail();
    }
    renderStatic(); renderLive();
    if (!(pending && follow('#' + pending))) showTab(remembered() || 'needs', true);
    connect();
  }).catch(function (err) {
    fail('The control room could not load its state file (' + (err && err.message || 'unknown error') + '). Publish state.json beside the page.');
  });

  async function connect() {
    db = window.claude && window.claude.use ? await window.claude.use('db') : null;
    if (!db) {
      live.db = 'off'; renderLive();
      if (review) $('review-conn').textContent = 'Not connected: labels cannot be saved in this view. Open the control room from claude.ai while signed in.';
      return;
    }
    // Each collection has its own status. Decisions count as loaded once both questions and
    // answers have delivered a first snapshot, and as unreachable only when one of those two fails.
    var status = { questions: 'pending', answers: 'pending', events: 'pending', labels: 'pending' };
    function decisionsStatus() {
      if (status.questions === 'off' || status.answers === 'off') return 'off';
      return status.questions === 'on' && status.answers === 'on' ? 'on' : 'pending';
    }
    function subscribe(name, onDocs, retried) {
      db.collection(name).onSnapshot(function (s) {
        status[name] = 'on'; live.db = decisionsStatus(); onDocs(s.docs);
      }, function (e) {
        console.warn('store', name, e && e.code);
        if (e && e.code === 'unavailable' && !retried) { subscribe(name, onDocs, true); return; }  // the bridge died: one fresh try
        status[name] = 'off'; live.db = decisionsStatus();
        if (name === 'labels' && review) $('review-conn').textContent = 'Labels stopped updating. Reload the page to reconnect.';
        renderLive();
      });
    }
    subscribe('questions', function (docs) {
      live.questions = docs.map(function (d) { return Object.assign({ id: d.id }, d.data()); })
        .sort(function (a, b) { return (a.order || 0) - (b.order || 0); });
      renderLive();
    });
    subscribe('answers', function (docs) {
      var a = {}; docs.forEach(function (d) { a[d.id] = d.data(); }); live.answers = a; renderLive();
    });
    subscribe('events', function (docs) {
      var ev = {}; docs.forEach(function (d) { if (/^pr-\d+$/.test(d.id)) ev[d.id] = d.data(); }); live.events = ev; renderLive();
    });
    if (review) {
      $('review-conn').textContent = '';
      subscribe('labels', function (docs) {
        var l = {}; docs.forEach(function (d) { l[d.id] = d.data(); }); live.labels = l;
        renderReviewList();
        var f = document.activeElement && document.activeElement.id;
        if (f !== 'goal' && f !== 'said') renderReviewDetail();
      });
      if (review.assist && window.claude.use) { sample = await window.claude.use('sample'); if (sample) renderReviewDetail(); }
    }
  }
})();
