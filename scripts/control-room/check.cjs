// Render every tab of the control room under node, from files, without a browser.
//   node scripts/control-room/check.cjs state.json [review.json|-] [store.json|-]
// store.json holds what the page's store would deliver:
//   {"db": "on"|"off"|"pending", "questions": [...], "answers": {...}, "events": {...}, "labels": {...}}
// Prints {"tabs": {needs, lanes, findings, review, records}, "count", "prs", "routes"} as JSON.
'use strict';
const fs = require('fs');
const path = require('path');
const CR = require(path.join(__dirname, 'render.js'));

const read = (p) => (p && p !== '-' ? JSON.parse(fs.readFileSync(p, 'utf8')) : null);
const [statePath, reviewPath, storePath] = process.argv.slice(2);
const state = read(statePath);
const review = read(reviewPath);
const store = read(storePath) || { db: 'off' };
const live = Object.assign({ db: 'off', questions: [], answers: {}, events: {}, labels: {} }, store);

const tabs = {
  needs: CR.renderNeeds(state, live),
  lanes: CR.renderLanes(state),
  findings: CR.renderFindings(state),
  records: CR.renderRecords(state, live),
  review: null,
};
if (review && (review.rows || []).length) {
  const first = review.rows[0];
  tabs.review = CR.reviewShell(review) + CR.reviewList(review, live.labels, first.id)
    + CR.reviewDetail(review, first, live.labels[first.id] || {}, (live.labels[first.id] || {}).goal || '', CR.usedLabels(live.labels), '');
}
const routes = {};
for (const h of (process.env.ROUTES || '').split(',').filter(Boolean)) routes[h] = CR.route(h, { review, live });
process.stdout.write(JSON.stringify({ tabs, count: CR.needsCount(state, live), prs: CR.livePrs(state, live.events), routes }));
