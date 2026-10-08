import { useEffect, useState } from 'react';
import { RefreshCw, ArrowLeft, Play, Square, GitCommitHorizontal, ArrowUpRight } from 'lucide-react';
import type { Workbench } from '../useWorkbench';
import * as api from '../api';
import { request } from '../productApi';
import AcceptanceEvidenceView from '../AcceptanceEvidence';
import ExecutionPreview, { stopPreviewBeforeAcceptance } from '../ExecutionPreview';
import TaskAssignmentEditor from '../TaskAssignmentEditor';
import { parseRoute, openTask, openRun, routeUrl } from './navigation';
import type { Tab } from './navigation';
import useEngineeringSession from './useEngineeringSession';
import { isActive, stages } from './state';
import EngineeringTaskPicker, { EngineeringEmptyState, useEngineeringInventory } from './EngineeringTaskPicker';
import { EngineeringTaskHeader, EngineeringTabs, WorkflowRail } from './EngineeringChrome';
import PlanView from './PlanView';
import type { ApprovalOptions } from './PlanView';
import DiffViewer, { ChangedFilesList } from './DiffViewer';
import { TestsView, ReviewView } from './EvidenceViews';
import ExecutionHistory, { HistoryList } from './ExecutionHistory';
import HumanReviewDialog from './HumanReviewDialog';
import OverviewView, { HistoricalPreview } from './OverviewView';

export default function EngineeringWorkspace({lab}:{lab:Workbench}) {
  const [route,setRoute]=useState(()=>parseRoute(window.location.hash));
  const [collapsed,setCollapsed]=useState(false),[selectedFile,setSelectedFile]=useState<string|null>(null),[source,setSource]=useState<string|null>(null),[sourceError,setSourceError]=useState('');
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[decision,setDecision]=useState<'accept'|'changes'|null>(null);
  const [options,setOptions]=useState<ApprovalOptions>({backend:'docker',framework:'unittest',attempts:3});
  const inventory=useEngineeringInventory();
  const session=useEngineeringSession(route);const {state,job,historical,evidence}=session;
  const project=lab.projects.find(p=>p.id===state?.task.project_id||p.path===job?.snapshot.task.request.repository_path);
  const snapshot=job?.snapshot,changes=snapshot?.changes??[];
  const file=route.tab==='files'&&selectedFile?selectedFile:changes.some(c=>c.path===selectedFile)?selectedFile:changes[0]?.path??null;
  useEffect(()=>{const update=()=>setRoute(parseRoute(window.location.hash));window.addEventListener('hashchange',update);return()=>window.removeEventListener('hashchange',update);},[]);
  useEffect(()=>{setSelectedFile(null);setDecision(null);setError('');},[route.id,route.run]);
  useEffect(()=>{if(job)setOptions({backend:job.options.test_backend as ApprovalOptions['backend'],framework:job.options.framework as ApprovalOptions['framework'],attempts:job.options.max_attempts});},[job?.id]);
  useEffect(()=>{if(route.kind==='run'&&job?.engineering_origin)openTask(job.engineering_origin.engineering_task_id,route.tab,job.id);},[route.kind,job?.id,job?.engineering_origin]);
  useEffect(()=>{
    let live=true;setSource(null);setSourceError('');
    if(route.tab!=='files'||!job||!file||changes.find(c=>c.path===file)?.kind==='deleted')return;
    api.source(job.id,file).then(result=>{if(live)setSource(result.content);}).catch(e=>{if(live)setSourceError(e.message);});
    return()=>{live=false;};
  },[job?.id,job?.revision,route.tab,file]);
  function onTab(tab:Tab){if(route.kind&&route.id)window.location.hash=routeUrl(route.kind,route.id,tab,route.run);}
  function onRun(id:string){if(state)openTask(state.task.id,route.tab,id===state.current?.execution_task_id?null:id);else openRun(id,route.tab);}
  async function action(operation:()=>Promise<unknown>) {setBusy(true);setError('');try{await operation();setDecision(null);session.refresh();inventory.refresh();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  function approve(){if(!job||historical)return;void action(()=>api.approve(job.id,{approval_id:job.approval,run_tests:true,test_backend:options.backend,framework:options.framework,max_attempts:options.attempts}));}
  function submit(feedback:string,acknowledged:boolean){if(!state||!job||historical)return;void action(async()=>{
    if(decision==='changes'){await request(`/engineering-tasks/${state.task.id}/request-changes`,'POST',{revision:state.task.revision,execution_task_id:job.id,feedback});openTask(state.task.id,'overview');}
    else {await stopPreviewBeforeAcceptance(state.task.id,job.id);await request(`/engineering-tasks/${state.task.id}/accept`,'POST',{revision:state.task.revision,execution_task_id:job.id,evidence_version:evidence?.version??null,unresolved_acknowledged:acknowledged});}
  });}
  const canDeliver=!historical&&job?.phase==='succeeded'&&(!state||state.current?.review_state==='accepted');
  const headerActions=<>{!historical&&state?.eligibility.can_start&&<button className="button primary" disabled={busy} onClick={()=>void action(()=>request(`/engineering-tasks/${state.task.id}/executions`,'POST',{revision:state.task.revision}))}><Play size={13}/>{job?'Retry with CodeOps':'Run with CodeOps'}</button>}
    {!historical&&job?.phase==='awaiting_approval'&&<button className="button primary" disabled={busy} onClick={()=>onTab('plan')}>Review implementation plan</button>}
    {!historical&&isActive(job)&&job?.phase!=='awaiting_approval'&&<button className="button quiet" onClick={()=>onTab('history')}>View execution</button>}
    {!historical&&isActive(job)&&<button className="button eng-reject" disabled={busy||!!job?.cancel} onClick={()=>void action(()=>api.cancel(job!.id))}><Square size={12}/>Cancel execution</button>}
    {!historical&&state?.can_request_changes&&<button className="button eng-reject" disabled={busy} onClick={()=>{setError('');setDecision('changes');}}>Request changes</button>}
    {!historical&&state?.can_accept&&<button className="button primary" disabled={busy||['waiting','pending','processing'].includes(evidence?.state??'not_generated')} onClick={()=>{setError('');setDecision('accept');}}>Accept result</button>}
    {!historical&&!state&&job&&['failed','cancelled'].includes(job.phase)&&<button className="button primary" disabled={busy} onClick={()=>void action(async()=>{const result=await api.retry(job.id);openRun(result.id);})}>Retry as new run</button>}
    {canDeliver&&(['export','apply','github'] as const).filter(type=>type!=='github'||(lab.system?.github_configured&&!!(project as {github?:unknown}|undefined)?.github)).map((type,index)=><button className="button quiet" disabled={busy||!!job?.delivery[type]} key={type} onClick={()=>void lab.prepareExecutionDelivery(job!.id,type)}><GitCommitHorizontal size={13}/>{['Create commit','Apply locally','Create draft PR'][index]}</button>)}
    <button className="text-button" disabled={busy} aria-label="Refresh selected engineering task" onClick={()=>{session.refresh();inventory.refresh();}}><RefreshCw size={14}/></button></>;
  function secondary(){
    if(route.tab==='diff'||route.tab==='files')return <ChangedFilesList changes={changes} selected={file} onSelect={setSelectedFile}/>;
    if(route.tab==='history')return <HistoryList state={state} job={job} onRun={onRun}/>;
    if(route.tab==='plan')return <div className="eng-plan-nav"><div className="eng-pane-heading">Implementation plan</div>{snapshot?.plan?.steps.map((step,index)=><button key={index} onClick={()=>document.getElementById(`plan-step-${index}`)?.scrollIntoView({block:'center'})}><span>{index+1}</span><strong>{step.description}</strong></button>)}{!snapshot?.plan&&<p className="eng-empty-note">Awaiting a recorded plan.</p>}</div>;
    if(route.tab==='tests')return <div className="eng-plan-nav"><div className="eng-pane-heading">Test runs</div>{snapshot?.tests?.executions.map((test,index)=><button key={index} onClick={()=>document.getElementById(`test-run-${index}`)?.scrollIntoView({block:'center'})}><span className={test.exit_code===0?'eng-success':'eng-danger'}>{test.exit_code===0?'✓':'!'}</span><strong>{test.command.join(' ')}</strong></button>)}{!snapshot?.tests&&<p className="eng-empty-note">No test runs recorded.</p>}</div>;
    if(route.tab==='review')return <div className="eng-plan-nav"><div className="eng-pane-heading">Review findings</div>{snapshot?.review?.findings.map((finding,index)=><button key={index} onClick={()=>document.getElementById(`finding-${index}`)?.scrollIntoView({block:'center'})}><span className="eng-severity">{finding.severity}</span><strong>{finding.file??finding.description}</strong></button>)}{!snapshot?.review?.findings.length&&<p className="eng-empty-note">{snapshot?.review?'No findings recorded.':'Awaiting review.'}</p>}</div>;
    return <WorkflowRail items={stages(state,job,historical,evidence)} onSelect={id=>onTab(id==='approve'||id==='plan_implementation'?'plan':id==='run_tests'?'tests':id==='review_changes'?'review':id==='acceptance'||id==='human'?'acceptance':'history')}/>;
  }
  function content(){
    if(session.loading)return <div className="eng-empty-note" role="status">Loading selected engineering work…</div>;
    if(session.artifactLoading&&['files','diff','tests','review'].includes(route.tab))return <div className="eng-empty-note" role="status">Loading retained {route.tab} artifacts…</div>;
    if(!state&&!job)return <div className="eng-empty-note"><h2>Selected work unavailable</h2><p>Refresh the workspace or choose another task.</p></div>;
    if(route.tab==='overview')return <><OverviewView state={state} job={job} evidence={evidence} historical={historical} onTab={onTab}/>{state&&!historical&&!isActive(job)&&!state.can_accept&&state.task.status!=='done'&&<div className="eng-assignment"><h3>Task ownership</h3><TaskAssignmentEditor task={state.task} onChange={()=>{session.refresh();inventory.refresh();}} locked={false}/></div>}</>;
    if(route.tab==='plan')return <PlanView job={job} historical={historical} busy={busy} options={options} onOptions={setOptions} onApprove={approve}/>;
    if(route.tab==='diff')return <DiffViewer key={`${job?.id}/${file}`} diff={snapshot?.development?.diff??''} path={file} runId={snapshot?.run_id??''} summary={changes.find(c=>c.path===file)?.summary}/>;
    if(route.tab==='files')return <div className="eng-file-view"><div className="eng-code-toolbar"><span>{file??'Select a changed file'}</span><button className="text-button" onClick={()=>onTab('diff')}>View diff <ArrowUpRight size={13}/></button></div>{changes.find(c=>c.path===file)?.kind==='deleted'?<p className="eng-empty-note">This file was deleted. Inspect its retained diff.</p>:sourceError?<p role="alert" className="product-error">{sourceError}</p>:source===null?<p className="eng-empty-note">{file?'Loading read-only snapshot source…':'No changed files recorded.'}</p>:<div className="eng-source-lines" tabIndex={0} role="region" aria-label={`Source for ${file}`}>{source.split('\n').map((line,index)=><div key={index}><span>{index+1}</span><code>{line||' '}</code></div>)}</div>}</div>;
    if(route.tab==='tests')return <TestsView snapshot={snapshot??null}/>;
    if(route.tab==='review')return <ReviewView snapshot={snapshot??null} onFile={path=>{setSelectedFile(path);onTab(changes.some(change=>change.path===path)?'diff':'files');}}/>;
    if(route.tab==='acceptance')return <div className="eng-document"><h2>Acceptance criteria</h2><AcceptanceEvidenceView evidence={evidence} onRaw={onTab}/>{!job&&state?.task.acceptance_criteria.map(criterion=><article className="eng-criterion-pending" key={criterion.id}><span>UNVERIFIED</span><p>{criterion.description}</p></article>)}</div>;
    if(route.tab==='preview')return state&&job?historical?<HistoricalPreview taskId={state.task.id} executionId={job.id}/>:<div className="eng-document"><ExecutionPreview taskId={state.task.id} projectId={state.task.project_id} executionId={job.id} revision={state.task.revision}/></div>:<div className="eng-empty-note"><h2>No interactive preview available</h2><p>{state?'Start an execution and inspect its successful result before previewing.':'Preview environments require an EngineeringTask-linked execution.'} Use Acceptance, Diff, Tests, and AI Review to verify the implementation.</p></div>;
    return <ExecutionHistory state={state} job={job} onRun={onRun} onTab={onTab}/>;
  }
  return <div className="eng-workspace">{route.id?<><EngineeringTaskHeader state={state} job={job} project={project} historical={historical} historicalOwner={inventory.workspace?.members.find(member=>member.id===state?.history.find(run=>run.execution_task_id===job?.id)?.ai_member_id)??null} actions={headerActions}/>{historical&&<div className="eng-historical-banner"><strong>Historical run · inspection only</strong><span>These artifacts belong to the selected run.</span><button className="text-button" onClick={()=>state&&openTask(state.task.id,route.tab)}><ArrowLeft size={13}/>Return to current run</button></div>}<EngineeringTabs tab={route.tab} onTab={onTab} job={job} state={state} collapsed={collapsed} onCollapse={()=>setCollapsed(value=>!value)}/></>:<div className="eng-entry-header"><h2>{route.mode==='reviews'?'Review queue':route.mode==='history'?'Execution history':'Engineering Workspace'}</h2><p>Select work from the task navigator.</p></div>}{(error||session.error)&&<div className="product-error eng-error" role="alert">{error||session.error}<button className="text-button" onClick={session.refresh}>Retry loading</button></div>}<div className={`eng-split-workspace ${collapsed?'pane-collapsed':''}`}><aside className="eng-secondary-pane">{route.id?<><details className="eng-task-switcher"><summary>Switch engineering task</summary><EngineeringTaskPicker inventory={inventory} route={route}/></details>{secondary()}</>:<EngineeringTaskPicker inventory={inventory} route={route}/>}</aside><section className="eng-main-pane" role={route.id?'tabpanel':undefined} id={`engineering-panel-${route.tab}`} aria-labelledby={route.id?`engineering-tab-${route.tab}`:undefined} tabIndex={0}>{route.id?content():<EngineeringEmptyState route={route} inventory={inventory} lab={lab}/>}</section></div>{decision&&<HumanReviewDialog mode={decision} evidence={evidence} busy={busy} error={error} onClose={()=>setDecision(null)} onSubmit={submit}/>}</div>;
}
