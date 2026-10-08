export const tabs = ['overview', 'plan', 'files', 'diff', 'tests', 'review', 'acceptance', 'preview', 'history'] as const;
export type Tab = typeof tabs[number];
export interface EngineeringRoute { mode:'workspace'|'reviews'|'history'; kind:'task'|'run'|null; id:string|null; tab:Tab; run:string|null }
export function parseRoute(hash:string):EngineeringRoute {
  const [path,query=''] = hash.replace(/^#/, '').split('?');
  const parts = path.split('/').filter(Boolean);
  const valid = parts[0] === 'engineering';
  const kind = valid && ['task','run'].includes(parts[1]) ? parts[1] as 'task'|'run' : null;
  const mode = valid && ['reviews','history'].includes(parts[1]) ? parts[1] as 'reviews'|'history' : 'workspace';
  const tab = tabs.includes(parts[3] as Tab) ? parts[3] as Tab : 'overview';
  return {mode,kind,id:kind?parts[2]??null:null,tab,run:new URLSearchParams(query).get('run')};
}
export function routeUrl(kind:'task'|'run',id:string,tab:Tab='overview',run:string|null=null) {
  return `#/engineering/${kind}/${encodeURIComponent(id)}/${tab}${run?'?run='+encodeURIComponent(run):''}`;
}
export function openTask(id:string,tab:Tab='overview',run:string|null=null) {window.location.hash=routeUrl('task',id,tab,run);}
export function openRun(id:string,tab:Tab='overview') {window.location.hash=routeUrl('run',id,tab);}
