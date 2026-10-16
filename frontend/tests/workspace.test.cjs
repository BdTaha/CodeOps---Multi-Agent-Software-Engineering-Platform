const {test}=require('node:test');
const assert=require('node:assert/strict');
const {parseDiff,splitLines}=require('../.test-dist/engineering/diff.js');
const {parseRoute,routeUrl}=require('../.test-dist/engineering/navigation.js');
const {stages,nextAction}=require('../.test-dist/engineering/state.js');
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const {EngineeringTabs}=require('../.test-dist/engineering/EngineeringChrome.js');

test('model settings separate bounded generation checks, reasoning, and operator timeout',()=>{
 const {ReasoningControls,ModelTimeoutNotice,SelectedModelResult}=require('../.test-dist/ModelControls.js');
 const Settings=require('../.test-dist/ModelSettings.js').default;
 const render=(component,props)=>renderToStaticMarkup(React.createElement(component,props));
 const options=render(ReasoningControls,{value:'provider_default',onChange:()=>{}});
 for(const label of ['Provider default','Disabled','Enabled (Laguna)','Low','Medium','High'])assert.ok(options.includes(label));
 assert.match(options,/materially increase latency/);assert.match(options,/Kimi K3 supports Low\/High/);
 assert.match(render(ModelTimeoutNotice,{seconds:600}),/up to 600 seconds/);
 assert.match(render(ModelTimeoutNotice,{seconds:600}),/25-second limit and never falls back/);
 const valid=render(SelectedModelResult,{result:{compatible:true,message:'Tiny JSON generation check passed. Large engineering tasks may still fail.',invocation:{latency_ms:123,reasoning:'disabled'}}});
 assert.match(valid,/Selected model generation: Compatible/);assert.match(valid,/Large engineering tasks may still fail/);assert.match(valid,/Reasoning: disabled/);
 const failed=render(SelectedModelResult,{result:{compatible:false,message:'Selected model timed out.',invocation:{latency_ms:25000}}});
 assert.match(failed,/Not compatible/);assert.match(failed,/timed out/);
 assert.match(render(Settings,{}),/Catalog tests check connectivity/);
 assert.match(render(Settings,{}),/Test selected model/);
});

test('failed repair history retains actual diff, failed test output, and separate repair failure',()=>{
 const DiffViewer=require('../.test-dist/engineering/DiffViewer.js').default;
 const {TestsView}=require('../.test-dist/engineering/EvidenceViews.js');
 const History=require('../.test-dist/engineering/ExecutionHistory.js').default;
 const {RetainedArtifactNotice}=require('../.test-dist/engineering/EngineeringChrome.js');
 const development={diff:'--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old_value\n+new_value\n'};
 const snapshot={development,changes:[{path:'app.py',kind:'modified'}],tests:{outcome:'failed',summary:'unittest returned nonzero',executions:[{command:['python','-m','unittest'],exit_code:1,duration_seconds:0.2,output_summary:'AssertionError: original test failure',timed_out:false,error:null}]},executions:[
  {execution_id:'test',operation:'run_tests',status:'failed',duration_seconds:0.2,attempt:1,output_summary:'unittest returned nonzero',error:{code:'TESTS_FAILED',message:'Original test failure'}},
  {execution_id:'repair',operation:'develop_implementation',status:'failed',duration_seconds:0.3,attempt:2,output_summary:'Development did not complete',error:{code:'INVALID_DEVELOPMENT',message:'Invalid repair response'}}
 ]};
 const failedJob={id:'retained',phase:'failed',snapshot};
 const render=(component,props)=>renderToStaticMarkup(React.createElement(component,props));
 const diff=render(DiffViewer,{diff:development.diff,path:'app.py',runId:'retained'});
 assert.match(diff,/new_value/);assert.match(diff,/old_value/);assert.doesNotMatch(diff,/No text hunk retained|No diff yet/);
 const tests=render(TestsView,{snapshot});
 assert.match(tests,/AssertionError: original test failure/);assert.match(tests,/python -m unittest/);assert.match(tests,/Exit 1/);
 assert.doesNotMatch(tests,/without retained test results|No test runs recorded/);
 const history=render(History,{state:null,job:failedJob,onRun:()=>{},onTab:()=>{}});
 assert.match(history,/TESTS_FAILED/);assert.match(history,/INVALID_DEVELOPMENT/);assert.match(history,/Invalid repair response/);
 const notice=render(RetainedArtifactNotice,{job:failedJob});
 assert.match(notice,/last successfully produced code artifact/);assert.match(notice,/do not indicate a successful run/);
 const {tabAvailability}=require('../.test-dist/engineering/lifecycle.js');
 const tabs=tabAvailability(null,failedJob,true);
 for(const name of ['files','diff','tests','history'])assert.equal(tabs[name].state,'enabled');
 assert.equal(render(RetainedArtifactNotice,{job:{...failedJob,phase:'succeeded'}}),'');
});
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

const {selectInitialWork}=require('../.test-dist/engineering/selection.js');
const {isHistoricalSelection}=require('../.test-dist/engineering/navigation.js');
const {highlightLines}=require('../.test-dist/engineering/syntax.js');
const {SourceCode}=require('../.test-dist/engineering/SyntaxCode.js');
const Picker=require('../.test-dist/engineering/EngineeringTaskPicker.js').default;
const task=(id,status='backlog',extra={})=>({id,key:'CO-'+id,title:'Task '+id,project_id:'project',status,assignee_id:null,execution_run_id:null,...extra});
const run=(id,phase='succeeded')=>({id,phase,snapshot:{run_id:id,changes:[],task:{request:{user_request:'Run '+id,repository_path:'/repo'}}}});
test('automatic selection restores valid task then executing, review, planned/assigned, first visible',()=>{
 const tasks=[task('first'),task('assigned','backlog',{assignee_id:'ai'}),task('planned','planned'),task('review','review'),task('active','in_progress',{execution_run_id:'execution'})];
 const jobs=[run('execution','development')];
 assert.equal(selectInitialWork(tasks,jobs,{kind:'task',id:'planned',tab:'plan'}).id,'planned');
 assert.equal(selectInitialWork(tasks,jobs,{kind:'task',id:'deleted',tab:'plan'}).id,'active');
 assert.equal(selectInitialWork(tasks,[],null).id,'review');
 assert.equal(selectInitialWork(tasks.slice(0,3),[],null).id,'assigned');
 assert.equal(selectInitialWork(tasks.slice(0,1),[],null).id,'first');
 assert.equal(selectInitialWork([],jobs,null).kind,'run');
 assert.equal(selectInitialWork([],[],null),null);
});
test('navigator modes and historical inspection survive tab bookmarks, including current and standalone runs',()=>{
 const route=parseRoute(routeUrl('task','t','diff','latest','history',true));
 assert.equal(route.mode,'history');assert.equal(isHistoricalSelection(route,'latest'),true);
 assert.equal(isHistoricalSelection({...route,inspection:false},'latest'),false);
 assert.equal(isHistoricalSelection({...route,inspection:false},'newer'),true);
 assert.equal(isHistoricalSelection(parseRoute(routeUrl('run','legacy','tests',null,'history',true))),true);
 assert.equal(parseRoute('#/engineering/reviews').mode,'reviews');
});
test('task browser is the sole discovery list and review empty state is compact',()=>{
 const inventory={workspace:{tasks:[task('first')],projects:[],members:[]},jobs:[],error:'',key:0,refresh:()=>{}};
 const html=renderToStaticMarkup(React.createElement(Picker,{inventory,route:parseRoute('#/engineering'),onSelect:()=>{},onMode:()=>{},metrics:null}));
 assert.equal((html.match(/Task first/g)||[]).length,1);assert.doesNotMatch(html,/Recent engineering work|CONTROL ROOM|<h1/);
 const empty=renderToStaticMarkup(React.createElement(Picker,{inventory,route:parseRoute('#/engineering/reviews'),onSelect:()=>{},onMode:()=>{},metrics:null}));
 assert.match(empty,/No tasks awaiting review/);assert.doesNotMatch(empty,/Task first|Engineering Reviews/);
});
test('syntax tokens preserve exact text, whitespace, and line boundaries for supported grammars',()=>{
 const samples={'app.py':'def greet(name):\n    return "Hello " + name.strip()\n','app.ts':'const value: number = 1;\n','app.tsx':'const App = () => <h1>Hello</h1>;\n','app.jsx':'const App = () => <h1>Hello</h1>;\n','app.java':'class App { int n = 1; }','app.cpp':'#include <iostream>\nint main() { return 0; }','app.c':'int main() { return 0; }','data.json':'{"name": "hello", "n": 2}','data.yaml':'name: hello\nitems:\n  - value','app.html':'<html>\n<!-- a -->\n</html>','app.css':'h1 { color: green; }','script.sh':'#!/bin/bash\necho "hello"','readme.md':'# Hello\n\nSome **text**.','unknown.xyz':'<script>alert("x")</script>\t\n'};
 for(const [path,text] of Object.entries(samples)) {
   const lines=highlightLines(text,path);assert.equal(lines.map(line=>line.map(part=>part.text).join('')).join('\n'),text,path);
   assert.equal(lines.length,text.split('\n').length,path);
 }
 assert.ok(highlightLines('return 2','app.py')[0].some(part=>part.classes.includes('keyword')));
 assert.equal(highlightLines('return 2','unknown.xyz')[0][0].classes,'');
});
test('highlighted source renders escaped markup and retains numbered lines',()=>{
 const html=renderToStaticMarkup(React.createElement(SourceCode,{source:'<script>alert(1)</script>\n<div>hello</div>',path:'app.html'}));
 assert.doesNotMatch(html,/<script>|<div>hello/);assert.match(html,/&lt;/);
 assert.match(html,/<span>1<\/span>/);assert.match(html,/<span>2<\/span>/);
});
