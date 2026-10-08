import { useEffect } from 'react';
import type { EngineeringTask } from './productTypes';
import useEngineeringSession from './engineering/useEngineeringSession';
import { openTask } from './engineering/navigation';
import { isActive, nextAction } from './engineering/state';

/** Board and Teams hand off execution controls to the same task workspace. */
export default function TaskExecutionPanel({task,onChange,onActiveChange}:{task:EngineeringTask;onChange:(task:EngineeringTask)=>void;onActiveChange?:(active:boolean)=>void}) {
  const {state,job,error}=useEngineeringSession({mode:'workspace',kind:'task',id:task.id,tab:'overview',run:null});
  useEffect(()=>{if(state&&state.task.revision!==task.revision)onChange(state.task);},[state?.task.revision,task.revision]);
  useEffect(()=>{onActiveChange?.(isActive(job));},[job?.phase,onActiveChange]);
  return <section className="task-execution-panel eng-task-handoff" aria-label="Engineering workspace"><h3>Engineering workspace</h3>{error&&<p className="product-error" role="alert">{error}</p>}<p>{state?nextAction(state,job,false):'Loading execution status…'}</p>{state?.owner&&<p className="small muted">{state.owner.member_type==='ai'?'AI':'Human'} ownership · {state.owner.name}{state.history.length?` · ${state.history.length} execution runs`:''}</p>}<button className="button primary" onClick={()=>openTask(task.id,job?.phase==='awaiting_approval'?'plan':state?.can_accept?'acceptance':'overview')}>{job?.phase==='awaiting_approval'?'Review implementation plan':state?.can_accept?'Review implementation result':'Open engineering workspace'}</button></section>;
}
