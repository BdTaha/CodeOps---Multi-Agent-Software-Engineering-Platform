import type { Job } from '../api';
import type { EngineeringTask } from '../productTypes';
import type { TeamMember } from '../teamTypes';
import type { AcceptanceEvidence } from '../AcceptanceEvidence';
export interface ExecutionLink {execution_task_id:string;run_id:string;ai_member_id:string;phase:string;node:string|null;review_state:string;reviewed_at:string|null;created_at:string;feedback:string|null}
export interface ExecutionState {task:EngineeringTask;owner:TeamMember|null;execution_owner:TeamMember|null;current:ExecutionLink|null;execution:Job|null;history:ExecutionLink[];can_accept:boolean;can_request_changes:boolean;acceptance_evidence:AcceptanceEvidence|null;eligibility:{can_start:boolean;reasons:string[];active_execution_count:number|null;max_concurrent_executions:number|null;dependencies:{key:string;title:string;status:string}[]}}
export const isActive = (job:Job|null|undefined) => !!job && !['succeeded','failed','cancelled'].includes(job.phase);
export function nextAction(state:ExecutionState|null,job:Job|null,historical:boolean) {
  if(historical)return 'Historical run · inspection only';
  if(job?.phase==='awaiting_approval')return 'Review the implementation plan and approve continuation';
  if(isActive(job))return job?.cancel?'Cancellation requested':'Execution in progress';
  if(state?.can_accept)return 'Inspect the evidence, then accept or request changes';
  if(state?.current?.review_state==='accepted')return 'Accepted · choose an explicit delivery action';
  if(job?.phase==='failed'||job?.phase==='cancelled')return 'Inspect the recorded failure and readiness before retrying';
  if(state?.eligibility.can_start)return 'Ready to run with CodeOps';
  if(!state&&job?.phase==='succeeded')return 'Inspect the result, then choose delivery';
  return state?.eligibility.reasons[0]??(job?.phase==='failed'?'Inspect the recorded failure before retrying':'Select an engineering task');
}
export interface Stage {id:string;label:string;state:'complete'|'failed'|'running'|'waiting'|'attention'|'skipped';detail?:string}
export function stages(state:ExecutionState|null,job:Job|null,historical:boolean,evidence:AcceptanceEvidence|null=historical?null:state?.acceptance_evidence??null):Stage[] {
  const s=job?.snapshot;
  const operations=[['analyze_repository','Analyze'],['plan_implementation','Plan'],['approve','Human approval'],['develop_implementation','Develop'],['run_tests','Tests'],['review_changes','AI review'],['acceptance','Acceptance evidence'],['human','Human review']];
  return operations.map(([id,label])=>{
    let outcome:Stage['state']='waiting';
    const record=s?.executions.filter(e=>e.operation===id).at(-1);
    if(record)outcome=record.status==='succeeded'?'complete':record.status==='failed'?'failed':'running';
    if(id==='analyze_repository'&&s?.analysis)outcome='complete';
    if(id==='plan_implementation'&&s?.plan)outcome='complete';
    if(id==='approve'&&s?.plan)outcome=job?.phase==='awaiting_approval'?'attention':s.development_attempts>0||['queued_development','development','succeeded'].includes(job?.phase??'')?'complete':'waiting';
    if(id==='run_tests'&&s?.tests)outcome=s.tests.outcome==='passed'?'complete':s.tests.outcome==='skipped'?'skipped':'failed';
    if(id==='review_changes'&&s?.review)outcome=s.review.approved?'complete':'failed';
    if(id==='acceptance'){outcome=evidence?.state==='ready'?'complete':evidence?.state==='processing'||evidence?.state==='pending'?'running':evidence?.state==='unavailable'?'attention':'waiting';}
    if(id==='human'){const review=historical?state?.history.find(run=>run.execution_task_id===job?.id)?.review_state:state?.current?.review_state;outcome=review==='accepted'?'complete':!historical&&state?.can_accept?'attention':'waiting';}
    if(id===job?.node&&isActive(job))outcome='running';
    return {id,label,state:outcome};
  });
}
