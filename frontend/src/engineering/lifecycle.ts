import type { Job } from '../api';
import type { Change } from '../types';
import type { EngineeringTask } from '../productTypes';
import type { WorkspaceSnapshot } from '../teamTypes';
import type { ExecutionState } from './state';
import { isActive } from './state';
import type { Tab } from './navigation';

export type UXPhase = 'UNASSIGNED'|'READY'|'BLOCKED'|'RUNNING_ANALYSIS'|'AWAITING_PLAN_APPROVAL'|'RUNNING_IMPLEMENTATION'|'REVIEW'|'DONE'|'FAILED'|'HISTORICAL';
export function uxPhase(state:ExecutionState|null,job:Job|null,historical=false):UXPhase {
  if(historical)return 'HISTORICAL';
  if(job?.phase==='awaiting_approval')return 'AWAITING_PLAN_APPROVAL';
  if(isActive(job))return job?.snapshot.plan||job?.snapshot.development_attempts||['develop_implementation','run_tests','review_changes'].includes(job?.node??'')?'RUNNING_IMPLEMENTATION':'RUNNING_ANALYSIS';
  if(state?.current?.review_state==='accepted'||state?.task.status==='done')return 'DONE';
  if(state?.can_accept||(!state&&job?.phase==='succeeded'))return 'REVIEW';
  if(job&&['failed','cancelled'].includes(job.phase))return 'FAILED';
  if(state?.eligibility.can_start)return 'READY';
  if(state&&(!state.owner||state.owner.member_type!=='ai'||state.owner.future_execution_role!=='developer'))return 'UNASSIGNED';
  return 'BLOCKED';
}
export type Availability = {state:'enabled'|'disabled'|'available_with_empty_state';reason?:string;attention?:boolean};
export function tabAvailability(state:ExecutionState|null,job:Job|null,historical=false):Record<Tab,Availability> {
  const s=job?.snapshot,phase=uxPhase(state,job,historical);
  const stage=(operation:string)=>!!job&&(job.node===operation||!!s?.executions.some(record=>record.operation===operation));
  const result=(exists:boolean,started:boolean,reason:string):Availability=>({state:exists?'enabled':started?'available_with_empty_state':'disabled',reason:exists?undefined:reason});
  const preview=!!state&&!!job&&(historical||job.phase==='succeeded'&&(state.can_accept||state.current?.review_state==='accepted'));
  return {
    overview:{state:'enabled'},
    plan:{...result(!!s?.plan,phase==='RUNNING_ANALYSIS',phase==='RUNNING_ANALYSIS'?'Implementation plan is being generated.':'Available after repository analysis starts.'),attention:phase==='AWAITING_PLAN_APPROVAL'},
    files:result(!!s?.changes.length,false,'Available after CodeOps records file changes.'),
    diff:result(!!s?.changes.length,false,'Available after CodeOps records file changes.'),
    tests:result(!!s?.tests,stage('run_tests'),stage('run_tests')?'Awaiting recorded test results.':'Available after test execution.'),
    review:result(!!s?.review,stage('review_changes'),stage('review_changes')?'Awaiting recorded AI review.':'Available after AI review.'),
    acceptance:{state:'enabled'},
    preview:result(preview,false,'Available after a successful implementation enters human review.'),
    history:result(!!job||!!state?.history.length,false,'Available after the first execution.'),
  };
}
// A sensible explicit choice wins. Defaults and unavailable bookmarks are phase-aware.
export function preferredTabForTask(state:ExecutionState|null,job:Job|null,requestedTab?:Tab,historical=false):Tab {
  const available=tabAvailability(state,job,historical);
  if(requestedTab&&available[requestedTab].state!=='disabled')return requestedTab;
  return uxPhase(state,job,historical)==='AWAITING_PLAN_APPROVAL'?'plan':'overview';
}
export function firstChangedFile(changes:Change[],selected:string|null):string|null {
  return changes.some(change=>change.path===selected)?selected:changes[0]?.path??null;
}
export function primaryAction(state:ExecutionState|null,job:Job|null,historical=false):'assign'|'run'|'plan'|'execution'|'accept'|'delivery'|'retry'|null {
  switch(uxPhase(state,job,historical)){
    case 'UNASSIGNED':return 'assign';case 'READY':return 'run';case 'AWAITING_PLAN_APPROVAL':return 'plan';
    case 'RUNNING_ANALYSIS':case 'RUNNING_IMPLEMENTATION':return 'execution';
    case 'REVIEW':return state?.can_accept?'accept':!state?'delivery':null;
    case 'DONE':return job?.phase==='succeeded'&&state?.current?.review_state==='accepted'?'delivery':null;
    case 'FAILED':return !state||state.eligibility.can_start?'retry':null;
    default:return null;
  }
}
export function navigatorReadiness(task:EngineeringTask,workspace:WorkspaceSnapshot,jobs:Job[]):string {
  const job=jobs.find(item=>item.snapshot.run_id===task.execution_run_id);
  if(job)return isActive(job)?job.phase.replaceAll('_',' '):job.phase==='succeeded'?`${job.snapshot.changes.length} files · ${task.status==='done'?'done':task.status==='review'?'human review':'succeeded'}`:job.phase;
  if(task.status==='done')return 'Done';
  const owner=workspace.members.find(member=>member.id===task.assignee_id);
  if(!owner||owner.member_type!=='ai'||owner.future_execution_role!=='developer')return 'Assign AI developer';
  const waiting=(task.dependencies??[]).map(ref=>workspace.tasks.find(item=>item.id===ref.task_id)).filter(item=>!item||item.status!=='done');
  if(waiting.length)return `Waiting for ${waiting.map(item=>item?.key??'dependency').join(', ')}`;
  if(!owner.active)return 'AI inactive';
  if(owner.availability==='offline')return 'AI offline';
  const capacity=workspace.capacities?.find(item=>item.member_id===owner.id);
  if(capacity?.active_execution_count!=null&&capacity.max_concurrent_executions!=null&&capacity.active_execution_count>=capacity.max_concurrent_executions)return 'At execution capacity';
  // The inventory is not an authoritative eligibility response.
  return 'Assigned · check readiness';
}
