import type { ModelInvocation } from './types';
export default function ModelTrace({items}:{items?:ModelInvocation[]}) {
  if(!items?.length)return null;
  return <div className="model-trace">{items.map((item,index)=><div key={index}><strong>{item.provider_name??({nvidia:'NVIDIA NIM',ollama:'Ollama',openai:'OpenAI compatible',anthropic:'Anthropic',gemini:'Gemini'}[item.provider]??item.provider)} · {item.model}</strong><small>{item.purpose.replaceAll('_',' ')} · {item.outcome.replaceAll('_',' ')} · {Math.round(item.latency_ms)} ms</small>{item.fallback_used&&<small className="capacity-warning">Fallback: {item.fallback_reason?.replaceAll('_',' ')}</small>}{item.input_tokens!=null&&<small>Input {item.input_tokens} · Output {item.output_tokens??'unreported'}</small>}</div>)}</div>;
}
