import type { EngineeringTask } from '../productTypes';
import type { MemberCapacity, TeamMember } from '../teamTypes';
import type { ExecutionState } from './state';

export function Requirements({task}:{task:EngineeringTask}) {
  return <section><h3>Acceptance criteria</h3><p className="eng-evidence-note">Requirements · no execution evidence yet.</p>{task.acceptance_criteria.length?<ul className="eng-pending-criteria">{task.acceptance_criteria.map(item=><li key={item.id}><span aria-hidden="true">○</span><span>{item.description}</span></li>)}</ul>:<p>No acceptance criteria recorded.</p>}</section>;
}
export function Dependencies({state,compact=false}:{state:ExecutionState;compact?:boolean}) {
  return <section><h3>Dependencies</h3>{state.eligibility.dependencies.length?state.eligibility.dependencies.map(item=><p key={item.key} className={item.status==='done'?'eng-success':'eng-blocked'}><span aria-hidden="true">{item.status==='done'?'✓':'○'}</span> <code>{item.key}</code>{!compact&&` · ${item.title}`} · {item.status.replaceAll('_',' ')}</p>):<p>No task dependencies.</p>}</section>;
}
export function OwnerSummary({owner,capacity,squad}:{owner:TeamMember|null;capacity?:MemberCapacity;squad?:string}) {
  return <div className="eng-owner-summary"><strong>{owner?owner.name:'No AI developer assigned'}</strong>{squad&&<span>{squad}</span>}{owner&&<span>{owner.member_type==='ai'?`AI · ${owner.future_execution_role??'role unset'} · ${owner.availability??'availability unknown'}`:'Human owner'}</span>}{owner?.member_type==='ai'&&<span>{capacity?.active_execution_count!=null&&capacity.max_concurrent_executions!=null?`Runtime ${capacity.active_execution_count} / ${capacity.max_concurrent_executions}`:'Runtime capacity not reported'}{capacity?.assigned_queue_depth!=null?` · Queued work ${capacity.assigned_queue_depth}`:''}</span>}</div>;
}
export function Readiness({state,onAssign}:{state:ExecutionState;onAssign:()=>void;onRun:()=>void;busy?:boolean}) {
  const unassigned=!state.owner||state.owner.member_type!=='ai'||state.owner.future_execution_role!=='developer';
  const waiting=state.eligibility.dependencies.filter(item=>item.status!=='done');
  const dependencyReasons=state.eligibility.dependencies.map(item=>`${item.key} must be Done before running this task.`);
  const otherReasons=state.eligibility.reasons.filter(reason=>!dependencyReasons.includes(reason)&&reason!=='Assign an AI developer to this task first.');
  return <section className="eng-readiness"><h3>Readiness</h3><p>{state.eligibility.can_start?'Ready for execution':unassigned?'Needs AI developer assignment':'Execution blocked'}</p>{waiting.length>0&&<p>{waiting.length} blocking {waiting.length===1?'dependency':'dependencies'} · Execution will remain blocked until {waiting.map(item=>item.key).join(' and ')} {waiting.length===1?'is':'are'} Done.</p>}{otherReasons.map(reason=><p key={reason}>{reason}</p>)}{unassigned?<button className="button quiet" onClick={onAssign}>Assign AI developer</button>:!state.eligibility.can_start?<button className="text-button" onClick={onAssign}>Change assignment</button>:null}</section>;

}
export function PreRunInspector({state,capacity,squad}:{state:ExecutionState;capacity?:MemberCapacity;squad?:string;onAssign:()=>void;onRun:()=>void;busy:boolean}) {
  return <div className="eng-pre-run-inspector"><section><h3>Task</h3><code>{state.task.key}</code><p>{state.task.status.replaceAll('_',' ')} · {state.task.technical_area}</p></section><section><h3>Assignment</h3><OwnerSummary owner={state.owner} capacity={capacity} squad={squad}/></section><Dependencies state={state} compact/><section><h3>Acceptance</h3><p>{state.task.acceptance_criteria.length} criteria</p></section><section><h3>Execution</h3><p>{state.eligibility.can_start?'Ready · not started':'Not started'}</p></section></div>;
}
