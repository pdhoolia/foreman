/* Control room rendering: pure functions from (state, live store data, review) to HTML strings.
   No DOM access here, so scripts/control-room/check.cjs runs the same code under node. */
var CR = (function () {
  'use strict';
  var DONE = { done: 1, accepted: 1, complete: 1, dropped: 1 };
  var STATE_CLASS = { planned: 'muted', active: 'accent', blocked: 'crit', review: 'warn', done: 'good', accepted: 'good', complete: 'good', dropped: 'muted', draft: 'muted' };
  var TABS = ['needs', 'lanes', 'findings', 'review', 'records'];
  var METRIC_NAMES = { ari: 'ARI', coverage: 'coverage' };
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function safeId(s) { return String(s == null ? '' : s).replace(/[^A-Za-z0-9_.~-]/g, '-'); }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }
  function joinAnd(parts) {
    if (parts.length < 2) return parts.join('');
    return parts.slice(0, -1).join(', ') + ' and ' + parts[parts.length - 1];
  }
  function fmtTime(iso) {
    var d = new Date(iso);
    if (!iso || isNaN(d.getTime())) return '';
    var p = function (n) { return (n < 10 ? '0' : '') + n; };
    return d.getUTCDate() + ' ' + MONTHS[d.getUTCMonth()] + ' ' + d.getUTCFullYear() + ', ' + p(d.getUTCHours()) + ':' + p(d.getUTCMinutes()) + ' UTC';
  }
  function fmtDate(iso) { var t = fmtTime(iso); return t ? t.split(',')[0] : ''; }
  function href(state, path) {
    if (!path) return null;
    if (/^https:\/\//.test(path)) return path;
    var base = state.project && state.project.blob_base;
    return base && !/^[a-z]+:/i.test(path) ? base + String(path).replace(/^\/+/, '') : null;
  }
  function link(state, path, text, cls) {
    var h = href(state, path);
    if (!h) return esc(text);
    return '<a href="' + esc(h) + '" target="_blank" rel="noopener"' + (cls ? ' class="' + cls + '"' : '') + '>' + esc(text) + '</a>';
  }
  function paras(text) {
    return String(text || '').split(/\n\s*\n/).filter(function (p) { return p.trim(); })
      .map(function (p) { return '<p>' + esc(p.trim()) + '</p>'; }).join('');
  }
  function pill(stateWord) {
    var s = String(stateWord || 'unknown');
    return '<span class="pill ' + (STATE_CLASS[s] || 'muted') + '">' + esc(s) + '</span>';
  }
  function taskIndex(state) {
    var by = {};
    (state.tasks || []).forEach(function (t) { by[t.anchor] = t; if (!by['id:' + t.id]) by['id:' + t.id] = t; });
    return by;
  }
  function taskLink(state, idOrAnchor) {
    var by = taskIndex(state);
    // The anchor form first: an active track's task owns `task-<id>`, a finished track's copy does not.
    var t = by[idOrAnchor] || by['task-' + safeId(idOrAnchor)] || by['id:' + idOrAnchor];
    return t ? '<a href="#' + esc(t.anchor) + '">' + esc(t.id) + '</a>' : esc(idOrAnchor);
  }

  /* ---------- live store data ---------- */

  function openDecisions(live) {
    return (live.questions || []).filter(function (q) { var a = live.answers[q.id]; return !(a && a.choice); });
  }
  function answeredDecisions(live) {
    return (live.questions || []).filter(function (q) { var a = live.answers[q.id]; return a && a.choice; });
  }
  // Pull requests: the state file's list, then each `events/pr-<n>` document on top. An event
  // older than the state file loses to it (the state file was fetched from GitHub later).
  function livePrs(state, events) {
    var rows = {};
    var built = Date.parse(state.generated_at || '') || 0;
    (state.prs || []).forEach(function (p) { rows[p.number] = Object.assign({}, p); });
    Object.keys(events || {}).forEach(function (k) {
      var ev = events[k] || {};
      var n = Number(ev.number);
      if (!n || n !== Math.floor(n)) return;
      var when = Date.parse(ev.updated || '') || 0;
      if (state.prs_included && when && when < built) return;
      if (ev.state === 'merged' || ev.state === 'closed') { delete rows[n]; return; }
      var base = rows[n] || { number: n };
      rows[n] = Object.assign({}, base, {
        title: typeof ev.title === 'string' ? ev.title : base.title,
        url: typeof ev.url === 'string' && /^https:\/\//.test(ev.url) ? ev.url : base.url,
        state: ev.state === 'ready' ? 'ready' : 'open', updated: ev.updated || base.updated, live: true,
      });
    });
    return Object.keys(rows).map(function (k) { return rows[k]; }).sort(function (a, b) { return a.number - b.number; });
  }
  function needsCount(state, live) {
    var prs = livePrs(state, live.events).filter(function (p) { return p.state === 'ready'; }).length;
    return openDecisions(live).length + prs + (state.needs || []).length;
  }

  /* ---------- Needs you ---------- */

  function decisionCard(state, q) {
    var opts = (q.options || []).map(function (o) {
      var oid = safeId(o.id);
      return '<label class="opt" for="opt-' + esc(safeId(q.id)) + '-' + esc(oid) + '"><input type="radio" name="q-' + esc(q.id) + '" id="opt-' + esc(safeId(q.id)) + '-' + esc(oid) + '" value="' + esc(o.id) + '">'
        + '<span>' + esc(o.label) + (q.recommended === o.id ? '<span class="rec-tag">PM recommends</span>' : '')
        + (o.detail ? '<small>' + esc(o.detail) + '</small>' : '') + '</span></label>';
    }).join('');
    return '<article class="q" id="q-' + esc(q.id) + '">'
      + '<div class="q-for">' + (q.task ? 'Decision for ' + taskLink(state, q.task) : 'Decision') + '</div>'
      + '<h3>' + esc(q.title) + '</h3>'
      + '<div class="q-body">' + paras(q.body) + '</div>'
      + '<fieldset class="opts"><legend class="sr">Options</legend>' + opts + '</fieldset>'
      + (q.why ? '<p class="why"><b>Why the PM recommends it:</b> ' + esc(q.why) + '</p>' : '')
      + '<label class="sr" for="note-' + esc(safeId(q.id)) + '">A note for the PM</label>'
      + '<textarea id="note-' + esc(safeId(q.id)) + '" placeholder="A note for the PM (optional)"></textarea>'
      + '<div class="actions"><button class="primary" type="button" data-save="' + esc(q.id) + '">Save decision</button>'
      + '<span class="status" id="qs-' + esc(safeId(q.id)) + '" role="status"></span></div>'
      + '</article>';
  }
  function prRow(state, p) {
    var title = p.url ? '<a href="' + esc(p.url) + '" target="_blank" rel="noopener">' + esc(p.title || 'Pull request ' + p.number) + '</a>' : esc(p.title || '');
    var meta = [];
    if (p.branch) meta.push('Branch <code>' + esc(p.branch) + '</code>');
    if (p.task) meta.push('task ' + taskLink(state, p.task));
    if (p.updated) meta.push((p.live ? 'updated live ' : 'updated ') + esc(fmtTime(p.updated)));
    return '<li class="pr ' + (p.state === 'ready' ? 'ready' : 'open') + '" id="pr-' + esc(p.number) + '">'
      + '<span class="pr-n">#' + esc(p.number) + '</span><span class="pr-title">' + title + '</span>'
      + (p.state === 'ready' ? '<span class="pill accent">Ready for review</span>' : '<span class="pill muted">Draft</span>')
      + (meta.length ? '<span class="pr-meta">' + meta.join(', ') + '</span>' : '') + '</li>';
  }
  function renderNeeds(state, live) {
    var open = openDecisions(live);
    var prs = livePrs(state, live.events);
    var ready = prs.filter(function (p) { return p.state === 'ready'; });
    var drafts = prs.filter(function (p) { return p.state !== 'ready'; });
    var notes = state.needs || [];
    var n = open.length + ready.length + notes.length;
    var parts = [];
    if (open.length) parts.push(plural(open.length, 'decision'));
    if (ready.length) parts.push(plural(ready.length, 'pull request'));
    if (notes.length) parts.push(plural(notes.length, 'task note'));
    var sum = n ? 'Waiting for you: ' + joinAnd(parts) + '.' : 'Nothing waits for you right now.';
    if (live.db === 'pending') sum += ' Decisions are still loading.';
    var out = '<div class="queue-head ' + (n ? 'busy' : 'clear') + '"><span class="queue-n">' + n + '</span><p class="queue-sum">' + esc(sum) + '</p></div>';

    out += '<section class="block" aria-labelledby="h-decisions"><h2 id="h-decisions">Decisions</h2>';
    if (live.db === 'pending') out += '<p class="note">Connecting to the store that holds the decision cards.</p>';
    else if (live.db === 'off') out += '<p class="note warn">Decision cards live in this page\'s store, which this view cannot reach. Open the control room from claude.ai while signed in.</p>';
    else if (!open.length) out += '<p class="note">No decision waits for you. Decided cards are under Records.</p>';
    else out += '<p class="hint">Each card is one question only you can answer. Pick an option, add a note if you like, and save. A saved decision moves to Records.</p><div class="questions">' + open.map(function (q) { return decisionCard(state, q); }).join('') + '</div>';
    out += '</section>';

    out += '<section class="block" aria-labelledby="h-prs"><div class="block-head"><h2 id="h-prs">Pull requests</h2>';
    out += '<span class="hint">' + (state.prs_included ? 'From GitHub at ' + esc(fmtTime(state.generated_at)) + ', with live updates since.' : 'This state file has no pull request list; live updates only.') + '</span></div>';
    out += ready.length ? '<ul class="prs">' + ready.map(function (p) { return prRow(state, p); }).join('') + '</ul>' : '<p class="note">No pull request is ready for you.</p>';
    if (drafts.length) out += '<details class="drafts"><summary>' + plural(drafts.length, 'draft') + ' still in progress</summary><ul class="prs">' + drafts.map(function (p) { return prRow(state, p); }).join('') + '</ul></details>';
    out += '</section>';

    if (notes.length) {
      out += '<section class="block" aria-labelledby="h-notes"><h2 id="h-notes">From the task files</h2><ul class="tasknotes">'
        + notes.map(function (x) { return '<li class="' + esc(x.kind) + '">' + taskLink(state, x.task) + ': ' + link(state, x.link, x.text.replace(/^[^:]*:\s*/, '')) + '</li>'; }).join('')
        + '</ul></section>';
    }
    return out;
  }

  /* ---------- Lanes ---------- */

  function card(state, t) {
    var done = !!DONE[t.state];
    var meta = [];
    if (t.branch) meta.push(['Branch', '<code>' + esc(t.branch) + '</code>']);
    if (t.pr) meta.push(['PR', link(state, t.pr_link, t.pr.slice(0, 60))]);
    if (t.model) meta.push(['Model', esc(t.model)]);
    if (t.deps && t.deps.length) meta.push(['After', t.deps.map(function (d) { return taskLink(state, d); }).join(', ')]);
    return '<article class="card' + (t.critical ? ' critical' : '') + (done ? ' done' : '') + '" id="' + esc(t.anchor) + '" tabindex="0" aria-describedby="plain-' + esc(t.anchor) + '">'
      + (t.critical ? '<span class="tag">Critical path</span>' : '')
      + '<div class="card-top"><span class="tid">' + link(state, t.task_file, t.id) + '</span>' + pill(t.state) + '</div>'
      + '<div class="card-name">' + esc(t.name) + '</div>'
      + (meta.length ? '<dl class="card-meta">' + meta.map(function (m) { return '<dt>' + m[0] + '</dt><dd>' + m[1] + '</dd>'; }).join('') + '</dl>' : '')
      + '<div class="tip" role="tooltip" id="plain-' + esc(t.anchor) + '"><span class="tip-h">In plain words</span>' + esc(t.plain) + '</div>'
      + '</article>';
  }
  function renderLanes(state) {
    var by = taskIndex(state);
    var done = {};
    (state.tracks || []).forEach(function (tr) { if (tr.done) done[tr.slug] = 1; });
    var active = (state.tasks || []).filter(function (t) { return !done[t.track]; });
    var counts = {};
    active.forEach(function (t) { counts[t.state] = (counts[t.state] || 0) + 1; });
    var order = ['blocked', 'review', 'active', 'planned', 'done', 'accepted', 'dropped'];
    var keys = Object.keys(counts).sort(function (a, b) { return (order.indexOf(a) + 99) % 99 - (order.indexOf(b) + 99) % 99; });
    var out = '<div class="lanes-sum"><div class="counts">' + keys.map(function (k) {
      return '<span class="pill ' + (STATE_CLASS[k] || 'muted') + '">' + counts[k] + ' ' + esc(k) + '</span>';
    }).join('') + '</div>';
    out += (state.critical_path || []).length
      ? '<p class="critline">Critical path: ' + state.critical_path.map(function (a) { return taskLink(state, a); }).join(' → ') + '. Cards on it carry a stripe.</p>'
      : '<p class="critline note">No chain of unfinished tasks waits on another.</p>';
    out += '</div><p class="hint">Hover over a card, or focus it, for what the task does in plain words.</p>';
    out += '<div class="lanes">';
    // The track's goal lines (Coordinator, Done when, Budget) from its plan head, when the lane has a plan.
    function laneGoal(state, l) {
      var tr = (state.tracks || []).filter(function (t) { return l.plan && t.path === l.plan; })[0];
      if (!tr || !(tr.done_when || tr.budget || tr.coordinator)) return '';
      return '<dl class="lane-goal">'
        + (tr.coordinator ? '<dt>Coordinator</dt><dd>' + esc(tr.coordinator) + '</dd>' : '')
        + (tr.done_when ? '<dt>Done when</dt><dd>' + esc(tr.done_when) + '</dd>' : '')
        + (tr.budget ? '<dt>Budget</dt><dd>' + esc(tr.budget) + '</dd>' : '')
        + '</dl>';
    }
    (state.lanes || []).forEach(function (l) {
      var id = 'lane-' + safeId(l.key || l.slug || l.name);
      var sub = [l.where, l.model].filter(Boolean).join(', ');
      out += '<div class="lane' + (l.kind === 'track' ? ' track' : '') + '" id="' + esc(id) + '"><div class="lane-head">'
        + (l.key ? '<div class="lane-key">' + esc(l.key) + '</div>' : '')
        + (l.name && l.name !== l.key ? '<div class="lane-name">' + esc(l.name) + '</div>' : '')
        + (sub ? '<div class="lane-sub">' + esc(sub) + '</div>' : '')
        + (l.kind === 'track' ? '<div class="lane-sub">Track without a lane</div>' : '')
        + (l.plan ? '<div class="lane-sub">' + link(state, l.plan, 'Track plan') + '</div>' : '')
        + laneGoal(state, l)
        + '</div><div class="cards">';
      out += (l.tasks || []).length
        ? l.tasks.map(function (a) { return by[a] ? card(state, by[a]) : ''; }).join('')
        : '<p class="none">' + esc(l.work || 'No task in this lane.') + '</p>';
      out += '</div></div>';
    });
    out += '</div>';
    var finished = (state.tracks || []).filter(function (tr) { return tr.done; });
    if (finished.length) {
      out += '<details class="finished" id="finished"><summary>' + plural(finished.length, 'finished track') + '</summary><div class="ftracks">'
        + finished.map(function (tr) {
          return '<div class="ftrack"><h3>' + link(state, tr.path, tr.title) + '</h3><ul>'
            + (tr.tasks || []).map(function (a) {
              var t = by[a]; if (!t) return '';
              return '<li id="' + esc(t.anchor) + '"><span class="tid">' + link(state, t.task_file, t.id) + '</span><span class="name">' + esc(t.name) + '</span>' + pill(t.state) + '</li>';
            }).join('') + '</ul></div>';
        }).join('') + '</div></details>';
    }
    return out;
  }

  /* ---------- Findings ---------- */

  function helpSpan(label, help) {
    return help ? '<span class="colhelp" tabindex="0">' + label + '<span class="tip" role="tooltip">' + esc(help) + '</span></span>' : label;
  }
  function fmtNum(col, v) {
    if (v == null) return '';
    if (/^(purity|inverse_purity|ari|coverage|coverage_overall)$/.test(col)) return Number(v).toFixed(3);
    return Number.isInteger(v) ? String(v) : String(Math.round(v * 10) / 10);
  }
  function renderFindings(state) {
    var f = state.findings || {};
    var rows = f.rows || [];
    if (!rows.length) return '<p class="note">No scored method yet. Each bench report under a track\'s evidence folder adds a row.</p>';
    var methods = f.methods || {}, sets = f.set_words || {}, cols = f.columns || {};
    var out = '';
    if ((f.readings || []).length) {
      var plans = {};
      f.readings.forEach(function (r) { plans[r.plan] = r.track; });
      out += '<section class="block" aria-labelledby="h-read"><h2 id="h-read">What the numbers say</h2><ul class="readings">'
        + f.readings.map(function (r) { return '<li><b>' + esc(r.lead) + '</b> ' + esc(r.text) + '</li>'; }).join('')
        + '</ul><p class="hint">From the findings in ' + Object.keys(plans).map(function (p) { return link(state, p, plans[p]); }).join(', ') + '.</p></section>';
    }
    var kinds = [];
    rows.forEach(function (r) { if (kinds.indexOf(r.kind) < 0) kinds.push(r.kind); });
    kinds.forEach(function (kind) {
      var colKeys = (f.kind_columns || {})[kind] || ['variant', 'set', 'records'];
      var bests = (f.sets || []).filter(function (s) { return s.kind === kind; });
      out += '<section class="block" aria-labelledby="h-kind-' + esc(safeId(kind)) + '"><h2 id="h-kind-' + esc(safeId(kind)) + '">' + esc((f.kinds || {})[kind] || kind) + '</h2>';
      if (bests.length) {
        out += '<ul class="bests">' + bests.map(function (s) {
          var names = joinAnd((s.best.variants || []).map(function (v) { return '<b>' + esc(v) + '</b>'; }));
          return '<li>Highest ' + esc(METRIC_NAMES[s.metric] || s.metric) + ' on ' + esc(s.set) + ': ' + names
            + ((s.best.variants || []).length > 1 ? ', tied,' : '') + ' at ' + fmtNum(s.metric, s.best.value) + ', of ' + plural(s.rows, 'method') + '.</li>';
        }).join('') + '</ul>';
      }
      out += '<p class="hint">Hover over a column name, a method or a set, or focus it, for what it means.</p>';
      out += '<div class="tablewrap"><table><thead><tr>' + colKeys.map(function (k) {
        var c = cols[k] || { label: k };
        return '<th class="' + (k === 'variant' || k === 'set' ? '' : 'num') + '" scope="col">' + helpSpan(esc(c.label), c.help) + '</th>';
      }).join('') + '</tr></thead><tbody>';
      var mine = rows.filter(function (r) { return r.kind === kind; }).slice().sort(function (a, b) {
        return String(a.set).localeCompare(String(b.set)) || String(a.variant).localeCompare(String(b.variant));
      });
      mine.forEach(function (r) {
        var best = bests.filter(function (s) { return s.set === r.set; })[0];
        out += '<tr>' + colKeys.map(function (k) {
          if (k === 'variant') return '<td>' + helpSpan(link(state, r.file, r.variant || ''), methods[r.variant]) + (r.note ? '<span class="rownote">' + esc(r.note) + '</span>' : '') + '</td>';
          if (k === 'set') return '<td>' + helpSpan(esc(r.set), sets[r.set]) + '</td>';
          var isBest = best && k === best.metric && r[k] === best.best.value;
          return '<td class="num' + (isBest ? ' best' : '') + '">' + fmtNum(k, r[k]) + '</td>';
        }).join('') + '</tr>';
      });
      out += '</tbody></table></div></section>';
    });
    return out;
  }

  /* ---------- Records ---------- */

  function recordFor(state, qid) {
    var hit = null;
    (state.records || []).forEach(function (r) { (r.questions || []).forEach(function (q) { if (q.id === qid && !hit) hit = { rec: r, q: q }; }); });
    return hit;
  }
  function renderRecords(state, live) {
    var out = '<section class="block" aria-labelledby="h-records"><h2 id="h-records">Decision records</h2>'
      + '<p class="hint">One entry per round of decisions. A decision you save on this page shows here at once, marked as not yet written to the repository; the coordinator then writes the round to docs/inputs and the entry fills in.</p>';
    if (live.db === 'pending') out += '<p class="note">Connecting to the store.</p>';
    else if (live.db === 'off') out += '<p class="note warn">Decisions saved on this page live in its store, which this view cannot reach; only the rounds already written to the repository show.</p>';
    var pending = answeredDecisions(live).filter(function (q) { return !recordFor(state, q.id); });
    if (pending.length) {
      out += '<article class="record pending" id="rec-pending"><h3>Saved on this page, not yet written to the repository</h3>'
        + '<p class="record-meta">The coordinator records each round under docs/inputs/&lt;date&gt;-&lt;slug&gt;.md; until then the choice lives only in this page\'s store.</p>'
        + '<ul class="decided">' + pending.map(function (q) {
          var a = live.answers[q.id];
          var opt = (q.options || []).filter(function (o) { return o.id === a.choice; })[0];
          return '<li id="q-' + esc(q.id) + '"><strong>' + esc(q.title) + '</strong>'
            + '<span>You chose <b>' + esc(opt ? opt.label : a.choice) + '</b>' + (a.updated ? ' on ' + esc(fmtDate(a.updated)) : '') + '.' + (a.note ? ' Your note: ' + esc(a.note) : '') + '</span>'
            + '<span class="sub">Not yet recorded.</span></li>';
        }).join('') + '</ul></article>';
    }
    if (!(state.records || []).length && !pending.length) out += '<p class="note">No decision yet. Each saved card and each file docs/inputs/&lt;date&gt;-&lt;slug&gt;.md adds one.</p>';
    (state.records || []).forEach(function (r) {
      out += '<article class="record" id="' + esc(r.anchor) + '"><h3>' + esc(r.title) + '</h3>'
        + '<p class="record-meta">Asked on ' + esc(r.asked || r.date) + '. ' + (r.acted ? 'Acted on in ' + esc(r.acted) + '. ' : '') + link(state, r.file, 'Read the record') + '</p>';
      (r.questions || []).forEach(function (q) {
        var a = live.answers && live.answers[q.id];
        out += '<details class="rq" id="' + esc(q.anchor) + '"><summary><span id="q-' + esc(q.id) + '">' + esc(q.title) + '</span>' + (q.choice ? '<span class="chose">Recorded: ' + esc(q.choice) + '</span>' : '') + '</summary><div class="rq-body">'
          + paras(q.body)
          + (q.options.length ? '<ul class="rq-opts">' + q.options.map(function (o) {
            var picked = q.choice && o.label.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().indexOf(q.choice.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()) === 0;
            return '<li' + (picked ? ' class="picked"' : '') + '>' + esc(o.label) + (o.detail ? '<small>' + esc(o.detail) + '</small>' : '') + '</li>';
          }).join('') + '</ul>' : '')
          + (q.recommended ? '<p><b>Recommended:</b> ' + esc(q.recommended) + '</p>' : '')
          + '<p><b>Owner chose:</b> ' + esc(q.choice || 'not recorded') + (q.note ? '. Note: ' + esc(q.note) : '') + '</p>'
          + (a && a.updated ? '<p class="sub">Saved on this page on ' + esc(fmtDate(a.updated)) + '; written to the repository in this record.</p>' : '')
          + (q.next ? '<p><b>What happened next:</b> ' + esc(q.next) + '</p>' : '')
          + '</div></details>';
      });
      if (r.items) {
        out += '<div class="items"><h4>Items reviewed</h4>' + (r.items.shown ? '<p>' + esc(r.items.shown) + '</p>' : '') + (r.items.result ? '<p>' + esc(r.items.result) + '</p>' : '') + (r.items.next ? '<p>' + esc(r.items.next) + '</p>' : '') + '</div>';
      }
      out += '</article>';
    });
    out += '</section>';

    if ((state.plain_words || []).length) {
      out += '<section class="block" aria-labelledby="h-plain"><h2 id="h-plain">In plain words</h2><p class="hint">One line per task of the active tracks, as the PM wrote it.</p><dl class="plainlist">'
        + state.plain_words.map(function (p) { return '<dt><a href="#' + esc(p.anchor) + '">' + esc(p.id) + '</a></dt><dd>' + esc(p.text) + '</dd>'; }).join('') + '</dl></section>';
    }
    return out;
  }

  /* ---------- Review ---------- */

  function usedLabels(labels) {
    var counts = {};
    Object.keys(labels || {}).forEach(function (k) { var v = labels[k]; if (v && v.goal) counts[v.goal] = (counts[v.goal] || 0) + 1; });
    return Object.keys(counts).map(function (g) { return [g, counts[g]]; }).sort(function (a, b) { return b[1] - a[1] || a[0].localeCompare(b[0]); });
  }
  function reviewShell(review) {
    return '<section class="block" aria-labelledby="h-review"><h2 id="h-review">' + esc(review.heading || 'Items to review') + '</h2>'
      + (review.lede ? '<p class="note">' + esc(review.lede) + '</p>' : '')
      + '<p class="status" id="review-conn"></p>'
      + '<div class="progress"><div class="status" id="progressText"></div><div class="bar"><div id="progressBar"></div></div></div>'
      + '<div class="bench"><div class="list" id="list" role="listbox" aria-label="Items"></div><div class="detail" id="detail"></div></div></section>';
  }
  function reviewList(review, labels, current) {
    return (review.rows || []).map(function (r) {
      var l = labels[r.id];
      var title = r.title || (r.turns && r.turns[0] ? String(r.turns[0].text).slice(0, 90) : '') || '(untitled)';
      return '<div class="row' + (r.id === current ? ' active' : '') + '" tabindex="0" role="option" aria-selected="' + (r.id === current) + '" id="item-' + esc(r.id) + '" data-item="' + esc(r.id) + '">'
        + '<div class="t">' + esc(title) + '</div><div class="m"><span>' + esc(r.meta_short || '') + '</span>'
        + (l && l.goal ? '<span class="chip">' + esc(l.goal) + '</span>' : '<span class="chip empty">not yet</span>') + '</div></div>';
    }).join('');
  }
  function reviewProgress(review, labels) {
    var rows = review.rows || [];
    var n = rows.filter(function (r) { return labels[r.id] && labels[r.id].goal; }).length;
    return { done: n, total: rows.length, text: n === rows.length && n ? 'All ' + n + ' done. Thank you; the PM reads them from here.' : n + ' of ' + rows.length + ' done' };
  }
  function reviewDetail(review, r, label, value, used, said) {
    if (!r) return '<p class="hint">Pick an item on the left.</p>';
    return '<h3>' + esc(r.title || '(untitled)') + '</h3>'
      + (r.meta ? '<div class="meta">' + esc(r.meta) + '</div>' : '')
      + (r.turns || []).map(function (t, i) { return '<div class="turn' + (i % 2 ? ' a' : '') + '"><div class="speaker">' + esc(t.who) + '</div><div class="quote">' + (esc(t.text) || '(empty)') + '</div></div>'; }).join('')
      + ((r.tags || []).length ? '<div class="tools">' + r.tags.map(function (t) { return '<span>' + esc(t) + '</span>'; }).join('') + '</div>' : '')
      + '<div class="labelbox"><label class="fieldlabel" for="goal">' + esc(review.field) + '</label>'
      + '<input type="text" id="goal" list="goals" autocomplete="off" placeholder="' + esc(review.placeholder || '') + '" value="' + esc(value) + '">'
      + '<datalist id="goals">' + used.map(function (u) { return '<option value="' + esc(u[0]) + '">'; }).join('') + '</datalist>'
      + (used.length ? '<div class="used">' + used.map(function (u) { return '<button type="button" data-goal="' + esc(u[0]) + '">' + esc(u[0]) + ' <span class="hint">×' + u[1] + '</span></button>'; }).join('') + '</div>' : '')
      + '<div class="assist" id="assist" hidden><label class="hint" for="said">Not sure what to call it? Say in your own words what you wanted, and ask for a suggestion.</label>'
      + '<textarea id="said" placeholder="For example: I was trying to get the tests passing after a dependency bump">' + esc(said || '') + '</textarea>'
      + '<div class="actions"><button type="button" id="suggest">Suggest a label</button><span class="suggestion" id="suggestion" role="status"></span></div></div>'
      + '<div class="actions"><button class="primary" type="button" id="save">Save and next</button><button type="button" id="skip">Skip</button>'
      + (label && label.goal ? '<button type="button" id="clear">Clear</button>' : '')
      + '<span class="status" id="ls" role="status">' + (label && label.updated ? 'saved ' + esc(fmtTime(label.updated)) : '') + '</span></div>'
      + '<div class="hint">Enter saves. Keep the same word for the same kind of thing.</div></div>';
  }

  /* ---------- routing ---------- */

  // Which tab a link anchor opens, and the element to bring into view.
  function route(hash, ctx) {
    var h = String(hash || '').replace(/^#/, '');
    if (!h) return null;
    if (TABS.indexOf(h) >= 0) return h === 'review' && !ctx.review ? { tab: 'needs' } : { tab: h };
    if (/^q-/.test(h)) {
      var id = h.slice(2);
      var a = ctx.live && ctx.live.answers[id];
      return { tab: a && a.choice ? 'records' : 'needs', target: h };
    }
    if (/^item-/.test(h)) return ctx.review ? { tab: 'review', target: h } : { tab: 'needs' };
    if (/^(task|lane)-/.test(h) || h === 'finished') return { tab: 'lanes', target: h };
    if (/^rec-/.test(h)) return { tab: 'records', target: h };
    if (/^pr-/.test(h)) return { tab: 'needs', target: h };
    return null;
  }
  function freshness(state) {
    var parts = [];
    var rev = state.revision ? 'Built from commit ' + state.revision : 'Built from the repository';
    parts.push(rev + ' on ' + fmtTime(state.generated_at) + '.');
    var c = state.counts || {};
    if (c.tasks != null) parts.push(plural(c.tasks, 'task') + ' in active tracks: ' + c.active + ' active, ' + c.done + ' finished.');
    return parts.join(' ');
  }

  var api = {
    esc: esc, safeId: safeId, fmtTime: fmtTime, TABS: TABS, openDecisions: openDecisions, answeredDecisions: answeredDecisions,
    livePrs: livePrs, needsCount: needsCount, renderNeeds: renderNeeds, renderLanes: renderLanes, renderFindings: renderFindings,
    renderRecords: renderRecords, reviewShell: reviewShell, reviewList: reviewList, reviewProgress: reviewProgress,
    reviewDetail: reviewDetail, usedLabels: usedLabels, route: route, freshness: freshness,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  return api;
})();
