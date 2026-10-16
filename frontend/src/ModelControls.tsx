export type ReasoningPolicy='provider_default'|'disabled'|'enabled'|'low'|'medium'|'high';
export function ReasoningControls({value,onChange}:{value:ReasoningPolicy;onChange:(value:ReasoningPolicy)=>void}) {
  return <label>Reasoning<select value={value} onChange={event=>onChange(event.target.value as ReasoningPolicy)}>
    <option value="provider_default">Provider default</option><option value="disabled">Disabled</option><option value="enabled">Enabled (Laguna)</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>
  </select><small>Reasoning may help complex tasks and materially increase latency. Model support varies: Laguna uses Disabled/Enabled; Kimi K3 supports Low/High; GPT-OSS supports Low/Medium/High. Other models use Provider default. CodeOps applies documented compatibility defaults.</small></label>;
}
export function ModelTimeoutNotice({seconds}:{seconds:number}) {
  return <p className="small muted">Primary requests may wait up to {seconds} seconds before eligible fallback. The selected-model generation check uses a separate 25-second limit and never falls back.</p>;
}
export function SelectedModelResult({result}:{result:{compatible:boolean;message:string;invocation:{latency_ms:number;reasoning?:string|null}}}) {
  return <p role="status" className={result.compatible?'small mint':'small capacity-warning'}>Selected model generation: {result.compatible?'Compatible ✓':'Not compatible'} · {result.message} ({Math.round(result.invocation.latency_ms)} ms){result.invocation.reasoning&&` · Reasoning: ${result.invocation.reasoning}`}</p>;
}
