const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const html = fs.readFileSync(process.argv[2] || path.join(__dirname, '../dashboard/ringside.html'), 'utf8');
const freshness = html.slice(html.indexOf('    function freshnessView('), html.indexOf('    function tickClock()'));
const polling = html.slice(html.indexOf('    async function fetchRuns()'), html.indexOf('    els.artifactVersion.addEventListener'));
assert.ok(freshness && polling);
let now = Date.parse('2026-09-28T18:00:00Z');
const state = {runs:[],artifacts:[],runsCheckedAt:now,libraryCheckedAt:now};
const strip = {dataset:{}};
let mode = 'ok';
let fetchCount = 0;
let release;
const context = vm.createContext({
  Date, state, document:{getElementById:()=>strip}, AbortSignal,
  fetch:async()=>{fetchCount++; if(mode==='hold') await new Promise(resolve=>release=resolve); if(mode==='reject') throw new Error('network'); return {ok:mode!=='http',status:503,json:async()=>{if(mode==='json') throw new Error('invalid JSON'); return {runs:[],artifacts:[],active:{}};}};},
  normalizeRuns:payload=>payload.runs, normalizeLibrary:payload=>payload.artifacts,
  renderTop(){},renderUpdateBanner(){},renderRunningNow(){},renderLive(){},renderArtifacts(){},renderArtifactControls(){},loadArtifactFrame(){}
});
vm.runInContext(freshness + polling, context);
const view=()=>context.freshnessView(state,now);
state.artifacts=[{updated_at:new Date(now-47*3600000).toISOString()}];
assert.equal(view().status,'fresh');
now+=2*3600000;state.runsCheckedAt=state.libraryCheckedAt=now;
assert.equal(view().status,'stale'); // ages without regeneration
state.artifacts=[{updated_at:new Date(now).toISOString()}];
assert.equal(view().status,'fresh'); // new source clears stale
state.artifacts=[];assert.equal(view().status,'unknown');
state.artifacts=[{updated_at:'bad timestamp'}];assert.equal(view().status,'unknown');
state.artifacts=[{updated_at:new Date(now+3600000).toISOString()}];assert.equal(view().status,'unknown');
state.artifacts=[{updated_at:new Date(now-48*3600000).toISOString()}];assert.equal(view().status,'fresh');
now++;state.runsCheckedAt=state.libraryCheckedAt=now;assert.equal(view().status,'stale');
state.runsCheckedAt=now-10001;assert.equal(view().status,'unavailable');
state.runsCheckedAt=0;assert.equal(view().status,'checking');
(async()=>{
 for(const poll of [context.fetchRuns,context.fetchLibrary]) {
  for(mode of ['reject','http','json']) {await poll();assert.match(strip.textContent,/Connection interrupted/);}
  mode='ok';await poll();
 }
 assert.equal(state.runError,null);assert.equal(state.libraryError,null);
 assert.ok(state.runsCheckedAt>0 && state.libraryCheckedAt>0);
 mode='hold';const pending=context.fetchRuns();const count=fetchCount;await context.fetchRuns();assert.equal(fetchCount,count);release();await pending;assert.equal(state.runsPending,false);
 console.log('PASS: aging, new data, exact 48h boundary, missing/invalid/future timestamps, stalled polling, both API failures and recovery, overlapping poll suppression');
})().catch(error=>{console.error(error);process.exitCode=1;});
