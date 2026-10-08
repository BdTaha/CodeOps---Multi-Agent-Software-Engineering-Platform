const {test}=require('node:test');
const assert=require('node:assert/strict');
const {parseDiff,splitLines}=require('../.test-dist/engineering/diff.js');
const {parseRoute,routeUrl}=require('../.test-dist/engineering/navigation.js');
const {stages,nextAction}=require('../.test-dist/engineering/state.js');
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const {EngineeringTabs}=require('../.test-dist/engineering/EngineeringChrome.js');
test('unified file hunks preserve real old/new numbers and created/deleted paths',()=>{
  const files=parseDiff('--- a/old.py\n+++ b/old.py\n@@ -18,2 +18,2 @@\n context\n-old\n+new\n--- /dev/null\n+++ b/new.py\n@@ -0,0 +1,1 @@\n+hello\n--- a/gone.py\n+++ /dev/null\n@@ -1,1 +0,0 @@\n-gone\n');
  assert.deepEqual(files.map(f=>f.path),['old.py','new.py','gone.py']);
  assert.equal(files[0].lines[2].old,19);assert.equal(files[0].lines[2].next,null);assert.equal(files[0].lines[3].next,19);
  assert.equal(files[1].additions,1);assert.equal(files[2].deletions,1);
});
test('source lines resembling diff file headers remain source within a hunk',()=>{
  const file=parseDiff('--- a/app.txt\n+++ b/app.txt\n@@ -1,1 +1,1 @@\n--- old content\n+++ new content\n')[0];
  assert.equal(file.lines[1].text,'-- old content');assert.equal(file.lines[2].text,'++ new content');
});
test('split layout aligns replacement blocks rather than inserting empty alternating rows',()=>{
  const file=parseDiff('--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,3 @@\n-old1\n-old2\n+new1\n+new2\n+new3\n')[0];const rows=splitLines(file.lines);
  assert.equal(rows.length,4);assert.equal(rows[1].left.text,'old1');assert.equal(rows[1].right.text,'new1');assert.equal(rows[3].left,null);assert.equal(rows[3].right.text,'new3');
});
test('bookmark keeps task, tab, and pinned historical execution',()=>{
  const url=routeUrl('task','task-1','tests','execution-2');
  assert.deepEqual(parseRoute(url),{mode:'workspace',kind:'task',id:'task-1',tab:'tests',run:'execution-2'});
  assert.equal(parseRoute('#/engineering/task/task-1/unknown').tab,'overview');assert.equal(parseRoute('#/engineering/reviews').mode,'reviews');assert.equal(parseRoute('#/engineering/history').mode,'history');
});
const job={id:'execution',phase:'awaiting_approval',node:null,snapshot:{analysis:{},plan:{steps:[]},development_attempts:0,executions:[],tests:null,review:null,changes:[]}};
test('workflow shows pending human approval without inferring development or plan step completion',()=>{
  const rail=stages(null,job,false);assert.equal(rail.find(s=>s.id==='approve').state,'attention');assert.equal(rail.find(s=>s.id==='develop_implementation').state,'waiting');assert.equal(nextAction(null,job,false),'Review the implementation plan and approve continuation');
});
test('historical run cannot borrow acceptance or human review completion from latest run',()=>{
  const state={acceptance_evidence:{state:'ready'},can_accept:true,current:{review_state:'accepted'},history:[]};
  const rail=stages(state,{...job,phase:'succeeded'},true);assert.equal(rail.find(s=>s.id==='human').state,'waiting');assert.equal(rail.find(s=>s.id==='acceptance').state,'waiting');assert.equal(nextAction(state,job,true),'Historical run · inspection only');
});
test('tabs expose stable semantic navigation and only real counts',()=>{
  const html=renderToStaticMarkup(React.createElement(EngineeringTabs,{tab:'diff',onTab:()=>{},job,state:null,collapsed:false,onCollapse:()=>{}}));
  assert.equal((html.match(/role="tab"/g)||[]).length,9);assert.equal((html.match(/aria-selected="true"/g)||[]).length,1);assert.match(html,/aria-controls="engineering-panel-diff"/);assert.doesNotMatch(html,/18 passed|<small>4<\/small>/);
});

test('historical stages show only the selected retained evidence and decision',()=>{
 const state={current:{review_state:'pending'},history:[{execution_task_id:'execution',review_state:'accepted'}]};
 const rail=stages(state,{...job,phase:'succeeded'},true,{state:'ready'});
 assert.equal(rail.find(s=>s.id==='acceptance').state,'complete');assert.equal(rail.find(s=>s.id==='human').state,'complete');
});
