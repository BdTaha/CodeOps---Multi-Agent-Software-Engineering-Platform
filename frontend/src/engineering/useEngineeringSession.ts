import { useEffect, useRef, useState } from 'react';
import { request } from '../productApi';
import type { Job } from '../api';
import type { AcceptanceEvidence } from '../AcceptanceEvidence';
import type { EngineeringRoute } from './navigation';
import { isHistoricalSelection } from './navigation';
import { isActive } from './state';
import type { ExecutionState } from './state';

export default function useEngineeringSession(route:EngineeringRoute) {
  const [state,setState]=useState<ExecutionState|null>(null),[job,setJob]=useState<Job|null>(null),[evidence,setEvidence]=useState<AcceptanceEvidence|null>(null);
  const [error,setError]=useState(''),[loading,setLoading]=useState(false),[refreshKey,setRefreshKey]=useState(0),[artifactLoading,setArtifactLoading]=useState(false);
  const selected=useRef('');selected.current=`${route.kind}/${route.id}/${route.run??''}`;
  const artifacts=useRef<{signature:string;job:Job}|null>(null);
  const historical=isHistoricalSelection(route,state?.current?.execution_task_id);
  useEffect(()=>{
    let live=true,timer:ReturnType<typeof setTimeout>;const identity=selected.current;
    artifacts.current=null;setState(null);setJob(null);setEvidence(null);setError('');setLoading(!!route.id);setArtifactLoading(false);
    if(!route.id)return;
    async function poll(){
      try{
        const next=route.kind==='task'?await request<ExecutionState>(`/engineering-tasks/${route.id}/execution?details=false`):null;
        const historicalId=route.kind==='task'&&route.run&&route.run!==next?.current?.execution_task_id?route.run:null;
        if(historicalId&&!next?.history.some(link=>link.execution_task_id===historicalId))throw new Error('This execution does not belong to the selected EngineeringTask.');
        const latest=historicalId?await request<Job>(`/tasks/${historicalId}?details=false`):next?.execution??(route.kind==='run'?await request<Job>(`/tasks/${route.id}?details=false`):null);
        if(!live||selected.current!==identity)return;
        const signature=latest?`${latest.id}/${latest.revision??0}`:'';
        setState(next);setJob(artifacts.current?.signature===signature?artifacts.current.job:latest);setError('');
        const mapped=historicalId||(route.kind==='run'&&latest?.engineering_origin)?await request<AcceptanceEvidence>(`/tasks/${latest!.id}/acceptance-evidence`):next?.acceptance_evidence??null;
        if(!live)return;setEvidence(mapped);
        const pendingEvidence=!!mapped&&['waiting','pending','processing'].includes(mapped.state);
        if(isActive(historicalId?latest:next?.execution??latest)||pendingEvidence)timer=setTimeout(poll,1800);
      }catch(e){if(live){setError((e as Error).message);timer=setTimeout(poll,6000);}}
      finally{if(live)setLoading(false);}
    }
    void poll();return()=>{live=false;clearTimeout(timer);};
  },[route.kind,route.id,route.run,refreshKey]);
  const needArtifacts=['files','diff','tests','review'].includes(route.tab);
  const signature=job?`${job.id}/${job.revision??0}`:'';
  useEffect(()=>{
    let live=true;
    if(!job||!needArtifacts||artifacts.current?.signature===signature)return;
    const id=job.id;setArtifactLoading(true);
    request<Job>(`/tasks/${id}`).then(full=>{if(live&&full.id===id){artifacts.current={signature:`${full.id}/${full.revision??0}`,job:full};setJob(full);}}).catch(e=>{if(live)setError((e as Error).message);}).finally(()=>{if(live)setArtifactLoading(false);});
    return()=>{live=false;};
  },[job?.id,signature,needArtifacts,refreshKey]);
  return {state,job,evidence,historical,loading,artifactLoading,error,refresh:()=>setRefreshKey(key=>key+1)};
}
