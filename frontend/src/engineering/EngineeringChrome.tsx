import { Bot, UserRound, GitBranch, PanelLeftClose, PanelLeftOpen, Check, Circle, AlertCircle, LoaderCircle } from 'lucide-react';
import type { ReactNode } from 'react';
import type { Job } from '../api';
import type { TeamMember } from '../teamTypes';
import type { Project } from '../types';
import type { ExecutionState, Stage } from './state';
import { nextAction } from './state';
import { tabs } from './navigation';
import type { Tab } from './navigation';

export function EngineeringTaskHeader({state,job,project,historical,actions,historicalOwner}:{state:ExecutionState|null;job:Job|null;project:Project|undefined;historical:boolean;actions:ReactNode;historicalOwner?:TeamMember|null}) {
  const task=state?.task,owner=historical?historicalOwner:state?.execution_owner??state?.owner;
  const index=state?.history.findIndex(run=>run.execution_task_id===job?.id)??-1;
  const status=historical?'Historical · '+job?.phase:state?.current?.review_state==='accepted'?'Accepted':job?.phase==='awaiting_approval'?'Plan approval':state?.can_accept?'In review':job?.phase??task?.status??'No execution';
  return <header className="eng-task-header"><div className="eng-title-row"><div><div className="eng-task-title">{task&&<span className="eng-key">{task.key}</span>}<h1>{task?.title??job?.snapshot.task.request.user_request??'Engineering Workspace'}</h1></div><div className="eng-task-meta">{task&&<span>{task.technical_area}</span>}{job&&<span title={project?.path??job.snapshot.task.request.repository_path}><GitBranch size={12}/>{task?'Snapshot execution':project?.name??'Local repository'}</span>}{!owner&&task&&<span>Unassigned</span>}{owner&&<span>{owner.member_type==='ai'?<Bot size={13}/>:<UserRound size={13}/>} {owner.name}</span>}<span>{index>=0?`Run ${index+1}`:job?`Run ${job.snapshot.run_id.slice(0,8)}`:'No execution yet'}</span></div></div><span className={`eng-status eng-status-${state?.can_accept?'review':job?.phase??task?.status}`}>{status?.replaceAll('_',' ')}</span></div><div className="eng-action-bar">{!historical&&<p>{nextAction(state,job,historical)}</p>}<div className="eng-actions">{actions}</div></div></header>;
}
export function EngineeringTabs({tab,onTab,job,state,collapsed,onCollapse}:{tab:Tab;onTab:(tab:Tab)=>void;job:Job|null;state:ExecutionState|null;collapsed:boolean;onCollapse:()=>void}) {
  const counts:Partial<Record<Tab,string|number>>={files:job?.snapshot.changes.length||undefined,diff:job?.snapshot.changes.length||undefined,tests:job?.snapshot.tests?.outcome==='passed'?'✓':undefined,review:job?.snapshot.review?.findings.length||undefined,history:state?.history.length||undefined};
  return <div className="eng-tabs-bar"><button className="eng-pane-toggle" onClick={onCollapse} aria-label={collapsed?'Expand workspace pane':'Collapse workspace pane'} aria-expanded={!collapsed}>{collapsed?<PanelLeftOpen size={16}/>:<PanelLeftClose size={16}/>}</button><div role="tablist" aria-label="Engineering task views" className="eng-tabs">{tabs.map((item,index)=><button role="tab" id={`engineering-tab-${item}`} aria-controls={`engineering-panel-${item}`} aria-selected={tab===item} tabIndex={tab===item?0:-1} key={item} onClick={()=>onTab(item)} onKeyDown={event=>{let target=index;if(event.key==='ArrowRight')target=(index+1)%tabs.length;else if(event.key==='ArrowLeft')target=(index+tabs.length-1)%tabs.length;else if(event.key==='Home')target=0;else if(event.key==='End')target=tabs.length-1;else return;event.preventDefault();onTab(tabs[target]);document.getElementById(`engineering-tab-${tabs[target]}`)?.focus();}}>{item[0].toUpperCase()+item.slice(1)}{counts[item]!==undefined&&<small>{counts[item]}</small>}</button>)}</div></div>;
}
export function WorkflowRail({items,onSelect}:{items:Stage[];onSelect?:(id:string)=>void}) {
  return <ol className="eng-workflow-rail">{items.map(stage=><li key={stage.id} className={stage.state}><button aria-label={`${stage.label}: ${stage.state==='waiting'?'not recorded':stage.state}`} onClick={()=>onSelect?.(stage.id)}><span className="eng-stage-icon">{stage.state==='complete'?<Check size={14}/>:stage.state==='running'?<LoaderCircle size={14} className="spin"/>:stage.state==='failed'||stage.state==='attention'?<AlertCircle size={14}/>:<Circle size={12}/>}</span><span>{stage.label}<small>{stage.state==='complete'?'Recorded complete':stage.state==='waiting'?'Not recorded':stage.state.replaceAll('_',' ')}</small></span></button></li>)}</ol>;
}
