import { useEffect, useState } from 'react';
import { Search, RefreshCw } from 'lucide-react';
import { getWorkspace } from '../teamApi';
import { request } from '../productApi';
import * as api from '../api';
import type { Job } from '../api';
import type { WorkspaceSnapshot } from '../teamTypes';
import type { EngineeringRoute, NavigatorMode } from './navigation';
import { routeUrl } from './navigation';
import type { ExecutionLink } from './state';
import { isActive } from './state';
import { navigatorReadiness } from './lifecycle';

export function useEngineeringInventory() {
  const [workspace,setWorkspace]=useState<WorkspaceSnapshot|null>(null),[jobs,setJobs]=useState<Job[]>([]),[error,setError]=useState(''),[key,setKey]=useState(0);
  useEffect(()=>{let live=true,timer:ReturnType<typeof setTimeout>;async function load(){try{const [w,j]=await Promise.all([getWorkspace(),api.jobs()]);if(live){setWorkspace(w);setJobs(j.tasks);setError('');if(j.tasks.some(isActive))timer=setTimeout(load,6000);}}catch(e){if(live){setError((e as Error).message);timer=setTimeout(load,10000);}}}void load();return()=>{live=false;clearTimeout(timer);};},[key]);
  return {workspace,jobs,error,key,refresh:()=>setKey(value=>value+1)};
}
export const navigatorModes:{mode:NavigatorMode;label:string}[]=[{mode:'workspace',label:'All'},{mode:'active',label:'Active'},{mode:'reviews',label:'Review'},{mode:'done',label:'Done'},{mode:'history',label:'History'}];
export function NavigatorModes({mode,onMode}:{mode:NavigatorMode;onMode:(mode:NavigatorMode)=>void}) {
  return <div className="eng-navigator-modes" role="group" aria-label="Engineering navigator filter">{navigatorModes.map(item=><button key={item.mode} aria-pressed={mode===item.mode} onClick={()=>onMode(item.mode)}>{item.label}</button>)}</div>;
}
interface RunRow extends ExecutionLink {taskId?:string;key?:string;title:string;number?:number}
export default function EngineeringTaskPicker({inventory,route,onSelect,onMode,metrics}:{inventory:ReturnType<typeof useEngineeringInventory>;route:EngineeringRoute;onSelect:(url:string)=>void;onMode:(mode:NavigatorMode)=>void;metrics:Record<string,unknown>|null}) {
  const [project,setProject]=useState(''),[search,setSearch]=useState(''),[status,setStatus]=useState('');
  const [runs,setRuns]=useState<RunRow[]>([]),[historyLoading,setHistoryLoading]=useState(false),[historyError,setHistoryError]=useState('');
  const allTasks=inventory.workspace?.tasks??[];
  const linked=allTasks.filter(task=>!!task.execution_run_id);
  const signature=linked.map(task=>`${task.id}/${task.revision}`).join(',');
  useEffect(()=>{
    if(route.mode!=='history')return;
    let live=true;setHistoryLoading(true);setHistoryError('');
    async function load(){const rows:RunRow[]=[];let failures=0;
      // Load small groups of existing history links, not detailed run artifacts.
      for(let offset=0;offset<linked.length;offset+=4){
        const results=await Promise.allSettled(linked.slice(offset,offset+4).map(async task=>{
          const result=await request<{executions:ExecutionLink[]}>(`/engineering-tasks/${task.id}/executions`);
          return result.executions.map((run,index)=>({...run,taskId:task.id,key:task.key,title:task.title,number:index+1}));
        }));
        if(!live)return;for(const result of results){if(result.status==='fulfilled')rows.push(...result.value);else failures++;}
      }
      if(live){setRuns(rows.sort((a,b)=>b.created_at.localeCompare(a.created_at)));setHistoryLoading(false);if(failures)setHistoryError('Some run histories could not load. Refresh to retry.');}
    }
    void load();return()=>{live=false;};
  },[route.mode,signature,inventory.key]);
  const matches=(task:typeof allTasks[number])=>(!project||task.project_id===project)&&(!status||task.status===status)&&`${task.key} ${task.title}`.toLowerCase().includes(search.toLowerCase());
  const tasks=allTasks.filter(task=>matches(task)&&(route.mode!=='reviews'||task.status==='review')&&(route.mode!=='active'||inventory.jobs.some(job=>isActive(job)&&job.snapshot.run_id===task.execution_run_id))&&(route.mode!=='done'||task.status==='done'));
  const recordedIds=new Set(runs.map(run=>run.execution_task_id));
  const standalone=inventory.jobs.filter(job=>!recordedIds.has(job.id)&&!allTasks.some(task=>task.execution_run_id===job.snapshot.run_id));
  const visibleJobs=standalone.filter(job=>!project&&!status&&job.snapshot.task.request.user_request.toLowerCase().includes(search.toLowerCase())&&(route.mode!=='active'||isActive(job))&&route.mode!=='reviews'&&(route.mode!=='done'||job.phase==='succeeded'));
  const visibleRuns=runs.filter(run=>{const task=allTasks.find(task=>task.id===run.taskId);return task&&matches(task);});
  const empty=route.mode==='reviews'?'No tasks awaiting review.':route.mode==='history'?'No execution history matches these filters.':'No work matches these filters.';
  return <div className="eng-task-picker">
    <div className="eng-pane-heading">Engineering<button className="text-button" aria-label="Refresh engineering tasks" onClick={inventory.refresh}><RefreshCw size={13}/></button></div>
    <NavigatorModes mode={route.mode} onMode={onMode}/>
    <div className="eng-search"><Search size={13}/><input aria-label="Search engineering tasks" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search work…"/></div>
    <div className="eng-picker-filters"><select aria-label="Engineering project" value={project} onChange={e=>setProject(e.target.value)}><option value="">All projects</option>{inventory.workspace?.projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select><select aria-label="Filter engineering task status" value={status} onChange={e=>setStatus(e.target.value)}><option value="">All statuses</option>{['backlog','planned','in_progress','review','done'].map(value=><option key={value} value={value}>{value.replaceAll('_',' ')}</option>)}</select></div>
    {route.mode==='history'&&metrics&&<div className="eng-compact-metrics"><span>{String(metrics.terminal_tasks??0)} ended</span><span>{String(metrics.successful_tasks??0)} succeeded</span><a href="/evaluation" target="_blank" rel="noreferrer">Metrics</a></div>}
    {(inventory.error||historyError)&&<p className="product-error" role="alert">{inventory.error||historyError}</p>}
    <div className="eng-task-list">
      {!inventory.workspace?<p className="eng-empty-note">Loading engineering work…</p>:route.mode==='history'?<>
        {historyLoading&&<p className="eng-empty-note" role="status">Loading run history…</p>}
        {visibleRuns.map(run=><button key={run.execution_task_id} className={route.run===run.execution_task_id?'selected':''} onClick={()=>onSelect(routeUrl('task',run.taskId!,'diff',run.execution_task_id,'history',true))}><span><code>{run.key}</code><small>{run.review_state.replaceAll('_',' ')}</small></span><strong>{run.title}</strong><small>Run {run.number} · {run.phase.replaceAll('_',' ')}</small></button>)}
      </>:tasks.map(task=><button key={task.id} className={route.kind==='task'&&route.id===task.id?'selected':''} onClick={()=>onSelect(routeUrl('task',task.id,task.execution_run_id?'diff':'overview',null,route.mode))}><span><code>{task.key}</code><small>{task.status.replaceAll('_',' ')}</small></span><strong>{task.title}</strong><small>{inventory.workspace?.projects.find(p=>p.id===task.project_id)?.name} · {inventory.workspace?.members.find(m=>m.id===task.assignee_id)?.name??'Unassigned'} · {inventory.workspace&&navigatorReadiness(task,inventory.workspace,inventory.jobs)}</small></button>)}
      {visibleJobs.map(job=><button key={job.id} className={route.id===job.id?'selected':''} onClick={()=>onSelect(routeUrl('run',job.id,job.snapshot.changes.length?'diff':'overview',null,route.mode,route.mode==='history'))}><span><code>{job.snapshot.run_id.slice(0,8)}</code><small>{job.phase.replaceAll('_',' ')}</small></span><strong>{job.snapshot.task.request.user_request}</strong><small>Standalone run · {job.snapshot.task.request.repository_path.split(/[\\/]/).at(-1)}</small></button>)}
      {inventory.workspace&&!historyLoading&&!visibleJobs.length&&!(route.mode==='history'?visibleRuns.length:tasks.length)&&<div className="eng-empty-note"><p>{empty}</p>{route.mode!=='workspace'&&<button className="text-button" onClick={()=>onMode('workspace')}>Show all engineering work</button>}</div>}
    </div>
  </div>;
}
