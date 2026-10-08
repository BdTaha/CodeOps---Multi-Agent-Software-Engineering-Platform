const {test}=require('node:test');
const assert=require('node:assert/strict');
const React=require('react');
const {renderToStaticMarkup:render}=require('react-dom/server');
const {uxPhase,tabAvailability,preferredTabForTask,firstChangedFile,primaryAction,navigatorReadiness}=require('../.test-dist/engineering/lifecycle.js');
const {Requirements,Readiness,PreRunInspector}=require('../.test-dist/engineering/LifecycleContext.js');
const Actions=require('../.test-dist/engineering/WorkflowActions.js').default;
const Overview=require('../.test-dist/engineering/OverviewView.js').default;
const {EngineeringTabs}=require('../.test-dist/engineering/EngineeringChrome.js');
const {TestsView,ReviewView}=require('../.test-dist/engineering/EvidenceViews.js');
const f=require('./lifecycle-fixtures.cjs');
const noop=()=>{};
const actions=(state,job,historical=false,extra={})=>render(React.createElement(Actions,{state,job,historical,busy:false,evidence:null,github:false,onAssign:noop,onRun:noop,onTab:noop,onCancel:noop,onDecision:noop,onRetry:noop,onDelivery:noop,...extra}));
const overview=(state,job,historical=false)=>render(React.createElement(Overview,{state,job,historical,evidence:null,onTab:noop}));
test('unassigned defaults to Overview and unavailable saved Files falls back',()=>{
 assert.equal(uxPhase(f.state(),null),'UNASSIGNED');assert.equal(preferredTabForTask(f.state(),null),'overview');assert.equal(preferredTabForTask(f.state(),null,'files'),'overview');
});
for(const tab of ['plan','files','diff','tests','review','preview','history'])test(`${tab} disabled before execution`,()=>assert.equal(tabAvailability(f.state(),null)[tab].state,'disabled'));
test('Acceptance remains available and renders neutral requirements',()=>{
 assert.equal(tabAvailability(f.state(),null).acceptance.state,'enabled');const html=render(React.createElement(Requirements,{task:f.task}));assert.match(html,/Passwords are hashed/);assert.match(html,/Requirements · no execution evidence yet/);assert.doesNotMatch(html,/VERIFIED|UNVERIFIED|Unverified/);assert.doesNotMatch(overview(f.state(),null),/Unverified|No validated edits/);
});
test('assignment is the dominant action before execution; run follows eligible assignment',()=>{
 assert.equal(primaryAction(f.state(),null),'assign');assert.match(actions(f.state(),null),/class="button primary"[^>]*>Assign AI developer/);
 assert.equal(uxPhase(f.ready(),null),'READY');assert.match(actions(f.ready(),null),/Run with CodeOps/);assert.doesNotMatch(actions(f.ready(),null),/Assign AI developer/);
});
test('blocked dependency includes key and status, disables Run and offers assignment change',()=>{
 const state=f.ready();state.eligibility={...state.eligibility,can_start:false,reasons:['CO-8 must be Done before running this task.'],dependencies:[{key:'CO-8',title:'Schema',status:'in_progress'}]};
 assert.equal(uxPhase(state,null),'BLOCKED');const html=render(React.createElement(PreRunInspector,{state,onAssign:noop,onRun:noop,busy:false}));assert.match(html,/Waiting for dependencies/);assert.match(html,/CO-8/);assert.match(html,/in progress/);assert.match(html,/disabled=""[^>]*>Run with CodeOps/);
});
test('offline AI displays the actual reason and change-assignment control',()=>{
 const state=f.ready();state.owner={...f.owner,availability:'offline'};state.eligibility={...state.eligibility,can_start:false,reasons:['The AI identity is offline.']};
 const html=overview(state,null);assert.equal(uxPhase(state,null),'BLOCKED');assert.match(html,/offline/);assert.match(html,/Change assignment/);
});
test('files select first recorded change and discard a stale selection',()=>{
 const changes=[{path:'first.py'},{path:'second.py'}];assert.equal(firstChangedFile(changes,null),'first.py');assert.equal(firstChangedFile(changes,'stale.py'),'first.py');assert.equal(firstChangedFile(changes,'second.py'),'second.py');assert.equal(firstChangedFile([],null),null);
});
test('analysis enables compact Plan context but no later stages',()=>{
 const j=f.job();assert.equal(uxPhase(f.ready(),j),'RUNNING_ANALYSIS');assert.equal(tabAvailability(f.ready(),j).plan.state,'available_with_empty_state');assert.equal(tabAvailability(f.ready(),j).tests.state,'disabled');assert.equal(tabAvailability(f.ready(),j).review.state,'disabled');assert.match(overview(f.ready(),j),/Analyzing repository/);assert.doesNotMatch(overview(f.ready(),j),/No validated edits recorded|Counts remain unknown/);
});
test('approval defaults to Plan, marks attention and emphasizes Review plan',()=>{
 const j=f.job({phase:'awaiting_approval',node:null});j.snapshot.plan=f.plan;assert.equal(uxPhase(f.ready(),j),'AWAITING_PLAN_APPROVAL');assert.equal(preferredTabForTask(f.ready(),j),'plan');assert.equal(preferredTabForTask(f.ready(),j,'files'),'plan');assert.equal(tabAvailability(f.ready(),j).plan.attention,true);assert.match(actions(f.ready(),j),/Review plan/);
});
test('running implementation makes execution dominant and exposes only recorded artifacts',()=>{
 const j=f.changed();assert.equal(uxPhase(f.ready(),j),'RUNNING_IMPLEMENTATION');assert.equal(tabAvailability(f.ready(),j).files.state,'enabled');assert.equal(tabAvailability(f.ready(),j).diff.state,'enabled');assert.match(actions(f.ready(),j),/class="button primary"[^>]*>View execution/);assert.equal(tabAvailability(f.ready(),j).preview.state,'disabled');
});
test('tests and review enable when each stage starts and show running context',()=>{
 const j=f.changed();j.node='run_tests';assert.equal(tabAvailability(f.ready(),j).tests.state,'available_with_empty_state');assert.equal(tabAvailability(f.ready(),j).review.state,'disabled');assert.match(render(React.createElement(TestsView,{snapshot:j.snapshot,running:true})),/Tests are running/);
 j.node='review_changes';assert.equal(tabAvailability(f.ready(),j).review.state,'available_with_empty_state');assert.match(render(React.createElement(ReviewView,{snapshot:j.snapshot,running:true,onFile:noop})),/AI review in progress/);
});
test('review exposes accept and request changes, with preview only for a reviewable linked result',()=>{
 const j=f.succeeded(),state=f.ready();state.can_accept=true;state.can_request_changes=true;state.task.status='review';assert.equal(uxPhase(state,j),'REVIEW');const html=actions(state,j);assert.match(html,/Accept result/);assert.match(html,/Request changes/);assert.equal((html.match(/button primary/g)||[]).length,1);assert.equal(tabAvailability(state,j).preview.state,'enabled');state.can_accept=false;assert.equal(tabAvailability(state,j).preview.state,'disabled');assert.equal(tabAvailability(null,j).preview.state,'disabled');
});
test('done exposes one dominant explicit delivery and promotes the next undelivered action',()=>{
 const state=f.ready(),j=f.succeeded();state.current={review_state:'accepted'};state.task.status='done';assert.equal(uxPhase(state,j),'DONE');assert.match(actions(state,j),/Create commit/);assert.match(actions(state,j,false,{github:true}),/class="button primary"[^>]*>.*?Create draft PR/);assert.equal((actions(state,j).match(/button primary/g)||[]).length,1);j.delivery.export={receipt:'recorded'};assert.match(actions(state,j),/class="button primary"[^>]*>.*?Apply locally/);assert.match(overview(state,j),/Accepted result|Delivery state/);
});
test('failed and cancelled executions show error, history and eligibility-guarded retry',()=>{
 const j=f.job({phase:'failed',node:null});j.snapshot.errors=[{code:'MODEL_ERROR',message:'Model unavailable'}];const state=f.ready();assert.equal(uxPhase(state,j),'FAILED');assert.match(actions(state,j),/Retry with CodeOps/);assert.match(overview(state,j),/MODEL_ERROR|Last successful operation|Execution history/);state.eligibility.can_start=false;assert.doesNotMatch(actions(state,j),/Retry with CodeOps/);assert.equal(uxPhase(state,{...j,phase:'cancelled'}),'FAILED');assert.equal(tabAvailability(state,j).preview.state,'disabled');
});
test('historical phase isolates mutations and preserves retained tabs even against current task state',()=>{
 const state=f.state(),j=f.succeeded();state.can_accept=true;state.current={review_state:'accepted'};assert.equal(uxPhase(state,j,true),'HISTORICAL');assert.equal(actions(state,j,true),'');assert.equal(preferredTabForTask(state,j,'diff',true),'diff');assert.equal(tabAvailability(state,j,true).preview.state,'enabled');
});
test('explicit valid deep links survive phases; impossible bookmarks fall back predictably',()=>{
 for(const tab of ['overview','files','diff','tests','review','acceptance','history'])assert.equal(preferredTabForTask(f.ready(),f.succeeded(),tab),tab);
 assert.equal(preferredTabForTask(f.ready(),f.job(),'tests'),'overview');assert.equal(preferredTabForTask(f.state(),null,'acceptance'),'acceptance');
});
test('stable tabs advertise disabled reasons and attention using semantic attributes',()=>{
 const html=render(React.createElement(EngineeringTabs,{tab:'overview',state:f.state(),job:null,onTab:noop,collapsed:false,onCollapse:noop}));assert.equal((html.match(/role="tab"/g)||[]).length,9);assert.equal((html.match(/aria-disabled="true"/g)||[]).length,7);assert.match(html,/Available after CodeOps records file changes/);
});
test('disabled tab clicks cannot navigate and keyboard actions skip unavailable tabs',()=>{
 const chosen=[],focused=[];
 const root=EngineeringTabs({tab:'overview',state:f.state(),job:null,onTab:tab=>chosen.push(tab),collapsed:false,onCollapse:noop});
 const buttons=root.props.children[1].props.children;
 buttons.find(button=>button.props.id==='engineering-tab-files').props.onClick();assert.deepEqual(chosen,[]);
 const previous=global.document;global.document={getElementById:id=>({focus:()=>focused.push(id)})};
 try{buttons[0].props.onKeyDown({key:'ArrowRight',preventDefault:noop});assert.deepEqual(chosen,['acceptance']);assert.deepEqual(focused,['engineering-tab-acceptance']);}
 finally{global.document=previous;}
});
test('a manually Done task without an accepted run does not expose delivery',()=>{
 const state=f.ready();state.task.status='done';state.current={review_state:'pending'};
 assert.doesNotMatch(actions(state,f.succeeded()),/Create commit|Apply locally|Create draft PR/);assert.doesNotMatch(overview(state,f.succeeded()),/Accepted result/);
});
test('navigator uses known blockers without inferring eligibility from incomplete inventory',()=>{
 const workspace={members:[f.owner],tasks:[],capacities:[f.capacity]};const task={...f.task,assignee_id:'ai'};assert.equal(navigatorReadiness(task,workspace,[]),'Assigned · check readiness');workspace.members[0]={...f.owner,availability:'offline'};assert.equal(navigatorReadiness(task,workspace,[]),'AI offline');workspace.tasks=[{id:'dep',key:'CO-8',status:'in_progress'}];task.dependencies=[{task_id:'dep'}];assert.equal(navigatorReadiness(task,workspace,[]),'Waiting for CO-8');
});
