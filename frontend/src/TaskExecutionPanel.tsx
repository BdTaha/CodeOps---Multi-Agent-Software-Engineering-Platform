import { useContext, useEffect, useRef, useState } from 'react';
import type { EngineeringTask } from './productTypes';
import type { TeamMember } from './teamTypes';
import type { Job } from './api';
import ModelTrace from './ModelTrace';
import * as execution from './api';
import { WorkbenchContext } from './WorkbenchContext';
import AcceptanceEvidenceView, { unresolvedEvidence } from './AcceptanceEvidence';
import type { AcceptanceEvidence } from './AcceptanceEvidence';
import ExecutionPreview, { stopPreviewBeforeAcceptance } from './ExecutionPreview';

interface Link { execution_task_id:string; run_id:string; ai_member_id:string; phase:string; node:string|null; review_state:string; reviewed_at:string|null; created_at:string; feedback:string|null }
interface State { task:EngineeringTask; owner:TeamMember|null; execution_owner:TeamMember|null; current:Link|null; execution:Job|null; history:Link[]; can_accept:boolean; can_request_changes:boolean; acceptance_evidence:AcceptanceEvidence|null; eligibility:{can_start:boolean;reasons:string[];active_execution_count:number|null;max_concurrent_executions:number|null;dependencies:{key:string;title:string;status:string}[]} }
async function request(path:string,body?:unknown):Promise<State> {
  const response=await fetch(path,body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await response.json(); if(!response.ok) throw new Error(typeof data.detail==='string'?data.detail:`Request failed (${response.status})`); return data;
}
const phaseNames:Record<string,string>={queued_planning:'Queued for repository analysis',planning:'Analyzing repository and preparing coding plan',awaiting_approval:'Implementation plan ready',queued_development:'Approved; queued for development',development:'Implementing and validating',succeeded:'Ready for your review',failed:'Implementation failed',cancelled:'Execution cancelled'};
export default function TaskExecutionPanel({task,onChange,onActiveChange}:{task:EngineeringTask;onChange:(task:EngineeringTask)=>void;onActiveChange?:(active:boolean)=>void}) {
  const lab=useContext(WorkbenchContext);
  const [data,setData]=useState<State|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[feedback,setFeedback]=useState('');
  const [backend,setBackend]=useState<'docker'|'local'>('docker'),[framework,setFramework]=useState<'unittest'|'pytest'|'npm'>('unittest'),[attempts,setAttempts]=useState(3);
  const [reviewTab,setReviewTab]=useState<'acceptance'|'preview'|'summary'|'diff'|'tests'|'review'>('acceptance');
  const [acknowledged,setAcknowledged]=useState(false);
  const [historical,setHistorical]=useState<AcceptanceEvidence|null>(null),[historicalId,setHistoricalId]=useState('');
  const notify=useRef(onChange);notify.current=onChange;
  const revision=useRef(task.revision);revision.current=task.revision;
  const loadedOptions=useRef<string|null>(null);
  const path=`/engineering-tasks/${task.id}`;
  useEffect(()=>{
    let alive=true,timer:ReturnType<typeof setTimeout>;
    setData(null);setError('');setFeedback('');loadedOptions.current=null;
    async function poll(){try{const next=await request(path+'/execution');if(alive){setData(next);if(next.task.revision!==revision.current)notify.current(next.task);
      if(next.execution && loadedOptions.current!==next.execution.id){loadedOptions.current=next.execution.id;setBackend(next.execution.options.test_backend as 'docker'|'local');setFramework(next.execution.options.framework as 'unittest'|'pytest'|'npm');setAttempts(next.execution.options.max_attempts);}
    }}catch(e){if(alive)setError((e as Error).message);}finally{if(alive)timer=setTimeout(poll,1500);}}
    void poll();return()=>{alive=false;clearTimeout(timer);};
  },[task.id,task.revision]);
  useEffect(()=>{onActiveChange?.(!!data?.execution&&!['succeeded','failed','cancelled'].includes(data.execution.phase));},[data?.execution?.phase,onActiveChange]);
  useEffect(()=>{setAcknowledged(false);},[data?.execution?.id,data?.acceptance_evidence?.version,data?.acceptance_evidence?.state]);
  useEffect(()=>{setHistorical(null);setHistoricalId('');setReviewTab('acceptance');},[task.id]);
  async function action(operation:()=>Promise<unknown>){setBusy(true);setError('');try{await operation();const next=await request(path+'/execution');setData(next);notify.current(next.task);}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  if(!data)return error?<p className="product-error" role="alert">{error}</p>:<p className="small muted">Loading execution eligibility…</p>;
  if(!data.current && data.owner?.member_type!=='ai')return null;
  const job=data.execution,snapshot=job?.snapshot;
  const active=!!job && !['succeeded','failed','cancelled'].includes(job.phase);
  const completed=job?.phase==='succeeded';
  const files=[...new Set(snapshot?.plan?.steps.flatMap(step=>step.files)??[])];
  const phase=job ? phaseNames[job.phase]??job.phase : 'Ready to run when requirements are met';
  return <section className="task-execution-panel" aria-label="AI execution"><h3>AI Execution</h3>
    <p><strong>{data.owner?.name??'Unassigned'}</strong>{data.eligibility.max_concurrent_executions!==null && <span className="small muted"> · Runtime slots reserved: {data.eligibility.active_execution_count} / {data.eligibility.max_concurrent_executions}</span>}</p>
    {data.execution_owner && data.execution_owner.id!==data.owner?.id && <p className="small muted">Execution owner: {data.execution_owner.name}</p>}
    <p className="small muted">Assigned ownership does not dispatch work. Planning, coding-plan approval waiting and implementation reserve a runtime slot. The slot is released when execution succeeds, fails or is cancelled; human result review happens afterward.</p>
    {error&&<p className="product-error" role="alert">{error}</p>}
    <strong className="execution-phase">{data.current?.review_state==='accepted'?'Result accepted':phase}</strong>
    {job?.cancel===1 && active&&<p>Cancellation requested; waiting for the worker to stop safely.</p>}
    {!data.eligibility.can_start && !active && !completed&&<div className="execution-blockers"><strong>Cannot start yet</strong><ul>{data.eligibility.reasons.map(reason=><li key={reason}>{reason}</li>)}</ul></div>}
    {!!data.eligibility.dependencies.length&&<ul className="small muted">{data.eligibility.dependencies.map(item=><li key={item.key}>{item.status==='done'?'✓':'●'} {item.key} · {item.title} — {item.status.replaceAll('_',' ')}</li>)}</ul>}
    {!completed&&!active&&data.owner?.member_type==='ai'&&<button className="button primary" disabled={busy||!data.eligibility.can_start} onClick={()=>void action(()=>request(path+'/executions',{revision:data.task.revision}))}>{job?'Retry with CodeOps':'Run with CodeOps'}</button>}
    {snapshot?.errors.length ? <p className="capacity-warning">{snapshot.errors.at(-1)?.message}</p>:null}
    {job?.phase==='awaiting_approval'&&snapshot?.plan&&<div className="coding-plan-review"><h4>Review implementation plan</h4><p>{snapshot.plan.problem_interpretation}</p><ul>{snapshot.plan.steps.map((step,index)=><li key={index}>{step.description}<small>{step.files.join(' · ')}</small></li>)}</ul><p className="small muted">Files likely affected: {files.join(', ')}</p>
      {!!snapshot.plan.risks.length&&<details><summary>Risks and limitations</summary><ul>{[...snapshot.plan.risks,...snapshot.plan.limitations].map((text,index)=><li key={index}>{text}</li>)}</ul></details>}
      <div className="execution-test-options"><label>Test runner<select value={backend} onChange={e=>setBackend(e.target.value as 'docker'|'local')}><option value="docker">Docker</option><option value="local">Trusted local</option></select></label><label>Test framework<select value={framework} onChange={e=>setFramework(e.target.value as 'unittest'|'pytest'|'npm')}><option value="unittest">unittest</option><option value="pytest">pytest</option><option value="npm">npm</option></select></label><label>Maximum attempts<input type="number" min={1} max={5} value={attempts} onChange={e=>setAttempts(Number(e.target.value))}/></label></div>
      <button className="button primary" disabled={busy} onClick={()=>void action(()=>execution.approve(job.id,{approval_id:job.approval,run_tests:true,test_backend:backend,framework,max_attempts:attempts}))}>Approve &amp; continue</button><p className="small muted">Approves this coding plan and runs its tests in the isolated workspace.</p>
    </div>}
    {snapshot&&<details className="execution-timeline"><summary>Execution timeline · {snapshot.executions.length} recorded operations</summary>{snapshot.executions.map(record=><div className="execution-operation" key={record.execution_id}><strong>{record.operation.replaceAll('_',' ')} · {record.status}</strong><small>{record.output_summary}</small><ModelTrace items={record.model_invocations}/></div>)}{job?.node&&active&&<p>Current operation: {job.node.replaceAll('_',' ')}</p>}</details>}
    {completed&&snapshot&&<div className="human-result-review"><h4>{data.current?.review_state==='accepted'?'Accepted implementation':'Preview / Review'}</h4><p>{snapshot.changes.length} files changed · Tests: {snapshot.tests?.outcome??'Unavailable'} · AI review: {snapshot.review?.approved?'Approved':'Unavailable'} · {snapshot.development_attempts} development attempts</p>
      <div className="execution-review-tabs" role="tablist" aria-label="Execution review"><button role="tab" aria-selected={reviewTab==='acceptance'} onClick={()=>setReviewTab('acceptance')}>Acceptance</button><button role="tab" aria-selected={reviewTab==='preview'} onClick={()=>setReviewTab('preview')}>Preview</button><button role="tab" aria-selected={reviewTab==='summary'} onClick={()=>setReviewTab('summary')}>Summary</button><button role="tab" aria-selected={reviewTab==='diff'} onClick={()=>setReviewTab('diff')}>View diff</button><button role="tab" aria-selected={reviewTab==='tests'} onClick={()=>setReviewTab('tests')}>View tests</button><button role="tab" aria-selected={reviewTab==='review'} onClick={()=>setReviewTab('review')}>View AI review</button></div>
      {reviewTab==='acceptance'&&<AcceptanceEvidenceView evidence={data.acceptance_evidence} onRaw={setReviewTab}/>}
      {reviewTab==='preview'&&<ExecutionPreview taskId={task.id} projectId={task.project_id} executionId={job.id} revision={data.task.revision}/> }
      {reviewTab==='summary'&&<><p>{snapshot.development?.explanation??snapshot.report?.summary}</p><ul>{snapshot.changes.map(change=><li key={change.path}>{change.path} · {change.kind}</li>)}</ul><p className="small muted">Acceptance criteria below are requirements. Passing tests and AI review do not individually verify each criterion.</p></>}
      {reviewTab==='diff'&&<pre className="execution-diff">{snapshot.development?.diff??'No diff available'}</pre>}
      {reviewTab==='tests'&&<><p>{snapshot.tests?.summary}</p>{snapshot.tests?.counts&&<p>{snapshot.tests.counts.passed} passed · {snapshot.tests.counts.failed} failed · {snapshot.tests.counts.skipped} skipped</p>}{snapshot.tests?.executions.map((result,index)=><pre className="execution-diff" key={index}>{result.command.join(' ')}{'\n'}{result.output_summary}</pre>)}</>}
      {reviewTab==='review'&&<><p>{snapshot.review?.summary}</p><ul>{snapshot.review?.findings.map((finding,index)=><li key={index}>{finding.file} · {finding.severity}: {finding.description}</li>)}</ul></>}
      {data.can_accept&&<div className="execution-review-actions">{unresolvedEvidence(data.acceptance_evidence)&&<label className="acceptance-acknowledgment"><input type="checkbox" checked={acknowledged} onChange={e=>setAcknowledged(e.target.checked)}/>I reviewed the unresolved acceptance criteria and any unavailable evidence.</label>}<label>Feedback for a fresh implementation run<textarea maxLength={4000} value={feedback} onChange={e=>setFeedback(e.target.value)} placeholder="Describe the changes you need"/></label><div className="row"><button className="button quiet" disabled={busy||!feedback.trim()} onClick={()=>void action(()=>request(path+'/request-changes',{revision:data.task.revision,execution_task_id:job.id,feedback}))}>Request changes</button><button className="button primary" disabled={busy||['waiting','pending','processing'].includes(data.acceptance_evidence?.state??'not_generated')||(unresolvedEvidence(data.acceptance_evidence)&&!acknowledged)} onClick={()=>void action(async()=>{await stopPreviewBeforeAcceptance(task.id,job.id);return request(path+'/accept',{revision:data.task.revision,execution_task_id:job.id,evidence_version:data.acceptance_evidence?.version??null,unresolved_acknowledged:acknowledged});})}>{busy?'Finishing review…':'Accept result'}</button></div><p className="small muted">Acceptance marks this EngineeringTask Done. Delivery is a separate explicit action.</p></div>}
      {data.current?.review_state==='accepted'&&<><p>Accepted {data.current.reviewed_at ? new Date(data.current.reviewed_at).toLocaleString():''}</p>{data.acceptance_evidence?.acceptance?.unresolved_acknowledged&&<p className="small muted">Unresolved criteria or unavailable evidence were explicitly reviewed and acknowledged.</p>}<h4>Delivery</h4><p>{Object.keys(job.delivery).some(key=>['export','apply','github'].includes(key))?'Saved delivery details are available in Engineering results.':'Not published'}</p><div className="execution-delivery-actions">{(['export','apply','github'] as const).map((delivery,index)=><button key={delivery} className="button quiet" disabled={busy||!lab||(delivery==='github'&&!lab.system?.github_configured)} onClick={()=>void lab?.prepareExecutionDelivery(job.id,delivery)}>{['Create commit','Apply locally','Create draft PR'][index]}</button>)}</div></>}
    </div>}
    {job&&<div className="execution-details-actions"><button className="text-button" onClick={()=>void lab?.openExecution(job.id,'workspace')}>View engineering details</button>{active&&<button className="text-button" disabled={busy||!!job.cancel} onClick={()=>void action(()=>execution.cancel(job.id))}>Cancel execution</button>}</div>}
    {!!data.history.length&&<details className="execution-history"><summary>Execution history · {data.history.length} runs</summary>{data.history.map((run,index)=><div key={run.execution_task_id}><span>Run {index+1} · {run.phase} · {run.review_state}</span><button className="text-button" onClick={()=>void lab?.openExecution(run.execution_task_id,'results')}>Inspect run {index+1}</button><button className="text-button" onClick={()=>void action(async()=>{const response=await fetch(`/tasks/${run.execution_task_id}/acceptance-evidence`,{cache:'no-store'});const result=await response.json();if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'Could not load historical evidence.');setHistorical(result);setHistoricalId(run.execution_task_id);})}>View evidence for run {index+1}</button>{run.feedback&&<p>Human feedback: {run.feedback}</p>}</div>)}</details>}
    {historical&&<details open className="historical-evidence"><summary>Historical acceptance evidence · {historicalId.slice(0,8)}</summary><AcceptanceEvidenceView evidence={historical} onRaw={()=>void lab?.openExecution(historicalId,'results')}/>{historical.acceptance&&<p className="small muted">Accepted through {historical.acceptance.action.replaceAll('_',' ')}. Unresolved evidence acknowledged: {historical.acceptance.unresolved_acknowledged?'Yes':'No'}.</p>}</details>}
  </section>;
}
