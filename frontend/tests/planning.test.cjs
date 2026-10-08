const {test}=require('node:test');
const assert=require('node:assert/strict');
const React=require('react');
const {renderToStaticMarkup:render}=require('react-dom/server');
const {default:Editor,PlanningBasisView,removeDraftTask,removeDraftEpic,nextDraftRef}=require('../.test-dist/DraftPlanEditor.js');
const draft={title:'Registration',summary:'Reuse existing validation',assumptions:[],epics:[{ref:'E1',title:'Storage',description:'Persistence'},{ref:'E2',title:'API',description:'Input'}],tasks:[{ref:'T1',epic_ref:'E1',title:'Users',description:'Store users',priority:'high',estimated_hours:2,technical_area:'Database',dependencies:[],acceptance_criteria:[{description:'Unique email'}]},{ref:'T2',epic_ref:'E2',title:'Register',description:'Validate input',priority:'high',estimated_hours:8,technical_area:'Backend',dependencies:['T1'],acceptance_criteria:[{description:'Reject invalid input'}]}]};
test('draft editing exposes all fields and a separate explicit approval gate',()=>{
 const html=render(React.createElement(Editor,{record:{goal:{id:'p'},draft,draft_revision:7},onChange:()=>{}}));
 for(const label of ['Draft plan title','Draft plan summary','Draft assumptions','T2 title','T2 description','T2 epic','T2 priority','T2 estimate','T2 area','T2 dependencies','T2 criteria'])assert.ok(html.includes(`aria-label="${label}"`));
 assert.match(html,/revision 7/);assert.match(html,/Approve Plan &amp; Create Work Items/);assert.match(html,/Draft tasks stay out of Board/);assert.doesNotMatch(html,/CO-\d/);
});
test('deletion removes dangling dependencies and empty epics without modifying the original',()=>{
 const result=removeDraftTask(draft,'T1');assert.deepEqual(result.tasks[0].dependencies,[]);assert.deepEqual(result.epics.map(e=>e.ref),['E2']);assert.equal(draft.tasks.length,2);assert.deepEqual(draft.tasks[1].dependencies,['T1']);
 assert.deepEqual(removeDraftEpic(draft,'E1'),result);assert.equal(nextDraftRef('T',['T1','T7']),'T8');
});
test('provenance shows only observed context or the explicit unavailable reason',()=>{
 const grounded=render(React.createElement(PlanningBasisView,{basis:{mode:'repository_grounded',analysis:{languages:['Python'],frameworks:['FastAPI'],architecture_summary:'API and tests',limitations:[]},inspected_files:['pyproject.toml'],limitations:['Bounded sample']}}));assert.match(grounded,/Repository-grounded/);assert.match(grounded,/pyproject.toml/);
 const fallback=render(React.createElement(PlanningBasisView,{basis:{mode:'goal_only',analysis:null,reason:'Repository unavailable',inspected_files:[],limitations:[]}}));assert.match(fallback,/Goal-only/);assert.match(fallback,/Repository unavailable/);assert.doesNotMatch(fallback,/FastAPI|Python/);
});
