import type { EngineeringTask } from '../productTypes';
import type { Job } from '../api';
import type { EngineeringRoute } from './navigation';
import { isActive } from './state';
import { tabs } from './navigation';

export function selectInitialWork(tasks:EngineeringTask[],jobs:Job[],saved:EngineeringRoute|null):EngineeringRoute|null {
  const restored=tasks.find(task=>saved?.kind==='task'&&task.id===saved.id);
  const active=tasks.find(task=>jobs.some(job=>isActive(job)&&job.snapshot.run_id===task.execution_run_id));
  const task=restored??active??tasks.find(task=>task.status==='review')??tasks.find(task=>task.status==='planned'||!!task.assignee_id)??tasks[0];
  if(task)return {mode:'workspace',kind:'task',id:task.id,tab:restored?saved!.tab:'overview',run:null};
  const run=jobs.find(job=>saved?.kind==='run'&&job.id===saved.id)??jobs.find(isActive)??jobs[0];
  if(!run)return null;
  return {mode:'workspace',kind:'run',id:run.id,tab:saved?.kind==='run'&&saved.id===run.id?saved.tab:run.snapshot.changes.length?'diff':'overview',run:null};
}

export function readSelection(kind:'task'|'run'='task'):EngineeringRoute|null {
  try {const value=JSON.parse(localStorage.getItem('codeops-engineering-selection-'+kind)??localStorage.getItem('codeops-engineering-selection')??'null');return value&&['task','run'].includes(value.kind)&&typeof value.id==='string'?{...value,tab:tabs.includes(value.tab)?value.tab:'overview'}:null;}catch{return null;}
}
