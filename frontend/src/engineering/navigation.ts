export const tabs = ['overview', 'plan', 'files', 'diff', 'tests', 'review', 'acceptance', 'preview', 'history'] as const;
export type Tab = typeof tabs[number];
export type NavigatorMode = 'workspace'|'active'|'reviews'|'done'|'history';
export interface EngineeringRoute { mode:NavigatorMode; kind:'task'|'run'|null; id:string|null; tab:Tab; run:string|null; inspection?:boolean }
export function parseRoute(hash:string):EngineeringRoute {
  const [path,query=''] = hash.replace(/^#/, '').split('?');
  const parts = path.split('/').filter(Boolean);
  const valid = parts[0] === 'engineering';
  const kind = valid && ['task','run'].includes(parts[1]) ? parts[1] as 'task'|'run' : null;
  const params = new URLSearchParams(query);
  const requestedMode = params.get('mode') ?? parts[1];
  const mode = valid && ['active','reviews','done','history'].includes(requestedMode) ? requestedMode as NavigatorMode : 'workspace';
  const tab = tabs.includes(parts[3] as Tab) ? parts[3] as Tab : 'overview';
  return {mode,kind,id:kind?parts[2]??null:null,tab,run:params.get('run'),...(params.get('inspect')==='1'?{inspection:true}:{})};
}
export function routeUrl(kind:'task'|'run',id:string,tab:Tab='overview',run:string|null=null,mode:NavigatorMode='workspace',inspection=false) {
  const params=new URLSearchParams();
  if(run)params.set('run',run);
  if(mode!=='workspace')params.set('mode',mode);
  if(inspection)params.set('inspect','1');
  return `#/engineering/${kind}/${encodeURIComponent(id)}/${tab}${params.size?'?'+params:''}`;
}
export function openTask(id:string,tab:Tab='overview',run:string|null=null) {window.location.hash=routeUrl('task',id,tab,run);}
export function openRun(id:string,tab:Tab='overview') {window.location.hash=routeUrl('run',id,tab);}
export function isHistoricalSelection(route:EngineeringRoute,currentExecutionId?:string|null) {
  return !!route.inspection||!!route.run&&route.run!==currentExecutionId;
}
