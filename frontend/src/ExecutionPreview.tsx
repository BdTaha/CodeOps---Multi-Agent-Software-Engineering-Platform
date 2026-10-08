import {useEffect,useRef,useState} from 'react';
import {request} from './productApi';
import PreviewSettings from './PreviewSettings';
import type {PreviewProfile} from './PreviewSettings';
interface Preview {id:string;execution_task_id:string;run_id:string;status:string;preview_url:string|null;base_url:string|null;ready_at:string|null;expires_at:string;logs:string;failure_reason:string|null;profile:PreviewProfile}
interface PreviewState {profile:PreviewProfile;can_start:boolean;reason:string|null;current:Preview|null;history:Preview[]}
const active=['queued','building','starting','ready','stopping'];
export async function stopPreviewBeforeAcceptance(taskId:string,executionId:string) {
  let data=await request<PreviewState>(`/engineering-tasks/${taskId}/preview`);
  const preview=data.current;
  if(!preview||preview.execution_task_id!==executionId||!active.includes(preview.status))return;
  await request(`/previews/${preview.id}/stop`,'POST');
  const deadline=Date.now()+60000;
  while(Date.now()<deadline){await new Promise(resolve=>setTimeout(resolve,1000));data=await request<PreviewState>(`/engineering-tasks/${taskId}/preview`);const current=data.history.find(p=>p.id===preview.id);if(current&&!active.includes(current.status))return;}
  throw new Error('Preview cleanup is still pending. Ensure the preview worker and Docker are running, then accept again after it stops.');
}
export default function ExecutionPreview({taskId,projectId,executionId,revision}:{taskId:string;projectId:string;executionId:string;revision:number}) {
  const [data,setData]=useState<PreviewState|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[settings,setSettings]=useState(false);
  const restartId=useRef<string|null>(null),latest=useRef({executionId,revision});latest.current={executionId,revision};
  useEffect(()=>{let live=true,timer:ReturnType<typeof setTimeout>;restartId.current=null;setData(null);async function poll(){try{const result=await request<PreviewState>(`/engineering-tasks/${taskId}/preview`);if(live){setData(result);const intent=restartId.current;if(intent&&result.current?.id===intent&&!active.includes(result.current.status)){restartId.current=null;if(result.can_start)await request(`/previews/${intent}/restart`,'POST',{revision:latest.current.revision,execution_task_id:latest.current.executionId});}}}catch(e){if(live)setError((e as Error).message);}finally{if(live)timer=setTimeout(poll,1500);}}void poll();return()=>{live=false;clearTimeout(timer);};},[taskId,executionId]);
  async function action(path:string,body?:unknown,restart=false){setBusy(true);setError('');try{await request(path,'POST',body);if(restart)restartId.current=data?.current?.id??null;setData(await request<PreviewState>(`/engineering-tasks/${taskId}/preview`));}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  const current=data?.current;const ready=current?.status==='ready';
  return <section className="execution-preview" aria-label="Preview environment"><h4>Preview / Verification</h4><p className="small muted">A temporary local environment for human review. Opening it does not verify criteria or accept the result.</p>{error&&<p className="product-error" role="alert">{error}</p>}
    {!data?<p>Loading preview configuration…</p>:<><p>{current?<strong>{current.status==='ready'?'✓ Preview ready':current.status.replaceAll('_',' ')}</strong>:'No preview running.'}</p>
    {!data.can_start&&<p>{data.reason}</p>}{data.can_start&&!current&&<p>{data.profile.name} · {data.profile.preview_type} · {data.profile.runtime}</p>}
    {ready&&current?.preview_url&&<><p className="preview-url">{current.preview_url}</p><div className="row"><a className="button primary" href={current.profile.preview_type==='api'?current.base_url+'/':current.preview_url} target="_blank" rel="noopener noreferrer">{current.profile.preview_type==='api'?'Open API':'Open Preview'}</a>{current.profile.preview_type==='api'&&current.profile.open_path!=='/'&&<a className="button quiet" href={current.preview_url} target="_blank" rel="noopener noreferrer">Open API Docs</a>}</div><p className="small muted">Started {current.ready_at?new Date(current.ready_at).toLocaleTimeString():''} · Expires {new Date(current.expires_at).toLocaleTimeString()}</p></>}
    {current?.failure_reason&&<p className="capacity-warning">{current.failure_reason}</p>}
    <div className="row">{data.can_start&&(!current||!active.includes(current.status))&&<button className="button primary" disabled={busy} onClick={()=>void action(`/engineering-tasks/${taskId}/preview`,{revision,execution_task_id:executionId})}>{data.profile.preview_type==='api'?'Start API Preview':'Start Preview'}</button>}{current&&active.includes(current.status)&&<><button className="button quiet" disabled={busy||current.status==='stopping'} onClick={()=>void action(`/previews/${current.id}/stop`)}>Stop Preview</button>{data.can_start&&<button className="button quiet" disabled={busy||current.status==='stopping'} onClick={()=>void action(`/previews/${current.id}/stop`,undefined,true)}>Restart</button>}</>}
    <button className="text-button" onClick={()=>setSettings(true)}>Preview settings</button></div>
    {current?.status==='stopping'&&<p className="small muted">Cleanup requested. The preview worker must confirm resource removal before restart.</p>}
    {current&&<details><summary>Preview logs · bounded tail</summary><pre className="execution-diff">{current.logs||'No retained output yet.'}</pre></details>}
    {!!data.history.length&&<details><summary>Preview history · {data.history.length} attempts</summary>{data.history.map(p=><div className="preview-history-item" key={p.id}><strong>Run {p.run_id.slice(0,8)} · {p.status}</strong><small>{p.profile.name}</small>{p.failure_reason&&<p>{p.failure_reason}</p>}<details><summary>Logs</summary><pre className="execution-diff">{p.logs||'No retained output.'}</pre></details></div>)}</details>}
    {!data.can_start&&!current&&<p className="small muted">Use Acceptance, Diff, Tests and AI Review to inspect this implementation.</p>}</>}
    {settings&&<PreviewSettings projectId={projectId} onClose={()=>setSettings(false)}/>}
  </section>;
}
