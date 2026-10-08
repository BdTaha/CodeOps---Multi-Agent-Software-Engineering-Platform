import { Play, Square, GitCommitHorizontal } from 'lucide-react';
import type { Job } from '../api';
import type { AcceptanceEvidence } from '../AcceptanceEvidence';
import type { ExecutionState } from './state';
import { isActive } from './state';
import { primaryAction, uxPhase } from './lifecycle';
import type { Tab } from './navigation';
export type DeliveryKind='export'|'apply'|'github';
export default function WorkflowActions({state,job,historical,evidence,busy,github,onAssign,onRun,onTab,onCancel,onDecision,onRetry,onDelivery}:{state:ExecutionState|null;job:Job|null;historical:boolean;evidence:AcceptanceEvidence|null;busy:boolean;github:boolean;onAssign:()=>void;onRun:()=>void;onTab:(tab:Tab)=>void;onCancel:()=>void;onDecision:(decision:'accept'|'changes')=>void;onRetry:()=>void;onDelivery:(type:DeliveryKind)=>void}) {
  if(historical)return null;
  const primary=primaryAction(state,job),phase=uxPhase(state,job);
  const delivery=primary==='delivery';
  const deliveries:DeliveryKind[]=github?['github','export','apply']:['export','apply'];
  const nextDelivery=deliveries.find(type=>!job?.delivery?.[type]);
  return <>
    {primary==='assign'&&<button className="button primary" disabled={busy} onClick={onAssign}>Assign AI developer</button>}
    {(primary==='run'||primary==='retry'&&state)&&<button className="button primary" disabled={busy} onClick={onRun}><Play size={13}/>{primary==='retry'?'Retry with CodeOps':'Run with CodeOps'}</button>}
    {primary==='plan'&&<button className="button primary" disabled={busy} onClick={()=>onTab('plan')}>Review plan</button>}
    {primary==='execution'&&<button className="button primary" onClick={()=>onTab('history')}>View execution</button>}
    {isActive(job)&&<button className="button eng-reject" disabled={busy||!!job?.cancel} onClick={onCancel}><Square size={12}/>Cancel execution</button>}
    {state?.can_request_changes&&<button className="button eng-reject" disabled={busy} onClick={()=>onDecision('changes')}>Request changes</button>}
    {primary==='accept'&&<button className="button primary" disabled={busy||['waiting','pending','processing'].includes(evidence?.state??'not_generated')} onClick={()=>onDecision('accept')}>Accept result</button>}
    {primary==='retry'&&!state&&<button className="button primary" disabled={busy} onClick={onRetry}>Retry as new run</button>}
    {state&&(phase==='BLOCKED'||phase==='FAILED'&&!state.eligibility.can_start)&&<><button className="button quiet" onClick={onAssign}>Change assignment</button><button className="button quiet" disabled>Run with CodeOps</button></>}
    {delivery&&deliveries.map(type=><button className={`button ${type===nextDelivery?'primary':'quiet'}`} disabled={busy||!!job?.delivery?.[type]} key={type} onClick={()=>onDelivery(type)}><GitCommitHorizontal size={13}/>{{export:'Create commit',apply:'Apply locally',github:'Create draft PR'}[type]}</button>)}
  </>;
}
