import { memo, useMemo } from 'react';
import { highlightLines } from './syntax';
import type { SyntaxPart } from './syntax';

function Tokens({parts}:{parts:SyntaxPart[]}) {
  return <>{parts.length?parts.map((part,index)=>part.classes?<span className={`syntax-token ${part.classes}`} key={index}>{part.text}</span>:part.text):' '}</>;
}
export const SyntaxCode=memo(function SyntaxCode({text,path}:{text:string;path:string}) {
  const lines=useMemo(()=>highlightLines(text,path),[text,path]);
  return <code><Tokens parts={lines[0]??[]}/></code>;
});
export function SourceCode({source,path}:{source:string;path:string}) {
  const lines=useMemo(()=>highlightLines(source,path),[source,path]);
  return <div className="eng-source-lines" tabIndex={0} role="region" aria-label={`Source for ${path}`}>{lines.map((parts,index)=><div key={index}><span>{index+1}</span><code><Tokens parts={parts}/></code></div>)}</div>;
}
