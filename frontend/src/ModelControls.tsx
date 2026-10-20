export type ReasoningPolicy='provider_default'|'disabled'|'enabled'|'low'|'medium'|'high';
export function ReasoningControls({value,onChange}:{value:ReasoningPolicy;onChange:(value:ReasoningPolicy)=>void}) {
  return <label>Reasoning<select value={value} onChange={event=>onChange(event.target.value as ReasoningPolicy)}>
    <option value="provider_default">Provider default</option><option value="disabled">Disabled</option><option value="enabled">Enabled</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>
  </select><small>Reasoning may help complex tasks and materially increase latency. Model support varies: Laguna and Nemotron 3.5 Super use Disabled/Enabled; Kimi K3 supports Low/High; GPT-OSS supports Low/Medium/High. Other models use Provider default. CodeOps applies documented compatibility defaults.</small></label>;
}
export function ModelReasoningSummary({model,policy,source}:{model:string|null;policy:string;source?:string}) {
  const compatibilityModels:Record<string,string>={'poolside/laguna-xs-2.1':'Laguna','nvidia/nemotron-3.5-super-vl-120b-a12b':'Nemotron'};
  const name=model&&Object.hasOwn(compatibilityModels,model)?compatibilityModels[model]:undefined;
  if(name&&(source==='compatibility_default'||policy==='provider_default'))return <>Disabled · CodeOps {name} compatibility default</>;
  if(source==='legacy_default'||policy==='provider_default'&&model==='moonshotai/kimi-k3')return <>Low · Kimi legacy default</>;
  return <>{policy.replaceAll('_',' ')}</>;
}
export function ModelTimeoutNotice({seconds}:{seconds:number}) {
  return <p className="small muted">Primary requests may wait up to {seconds} seconds before eligible fallback. The selected-model generation check uses a separate 25-second limit and never falls back.</p>;
}
export function SelectedModelResult({result}:{result:{compatible:boolean;message:string;invocation:{latency_ms:number;reasoning?:string|null}}}) {
  return <p role="status" className={result.compatible?'small mint':'small capacity-warning'}>Selected model generation: {result.compatible?'Compatible ✓':'Not compatible'} · {result.message} ({Math.round(result.invocation.latency_ms)} ms){result.invocation.reasoning&&` · Reasoning: ${result.invocation.reasoning}`}</p>;
}
