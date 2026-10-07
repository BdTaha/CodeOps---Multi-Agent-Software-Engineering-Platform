export interface AcceptanceEvidence {
  state: 'waiting'|'pending'|'processing'|'ready'|'unavailable'|'not_generated';
  version: string|null; mapper_version: string|null; error: string|null;
  counts: {verified:number;supported:number;unverified:number;conflict:number}|null;
  criteria: {criterion_id:string;description:string;verification_status:'verified'|'supported'|'unverified';conflict:boolean;
    evidence:{id:string;source_id:string;evidence_type:string;summary:string;negative:boolean;executed:boolean;mapping:string;
      reference:{framework?:string;test_identifier?:string;test_file?:string;file?:string;outcome?:string;severity?:string;artifact:string}}[]}[];
  acceptance: {unresolved_acknowledged:boolean;action:string;evidence_version:string|null;evidence_state:string}|null;
}

export function unresolvedEvidence(evidence:AcceptanceEvidence|null|undefined) {
  return !evidence || evidence.state!=='ready' || evidence.criteria.some(c=>c.conflict||c.verification_status==='unverified');
}

export default function AcceptanceEvidenceView({evidence,onRaw}:{evidence:AcceptanceEvidence|null;onRaw:(tab:'diff'|'tests'|'review')=>void}) {
  if(!evidence || evidence.state==='not_generated')return <div className="acceptance-notice"><strong>Acceptance evidence: Not generated</strong><p>This older run has no stored evidence mapping. Review its retained files, tests and findings manually.</p></div>;
  if(evidence.state!=='ready')return <div className="acceptance-notice" role="status"><strong>Acceptance evidence: {evidence.state==='unavailable'?'Unavailable':'Processing'}</strong><p>{evidence.error??'The execution result is available. Requirement evidence has not finished processing; no verification is inferred.'}</p><p className="small muted">Raw diff, tests and AI review remain available.</p></div>;
  return <section className="acceptance-evidence" aria-label="Acceptance evidence"><p><strong>{evidence.criteria.length} criteria</strong> · {evidence.counts?.verified} verified · {evidence.counts?.supported} supported · {evidence.counts?.unverified} unverified{evidence.counts?.conflict ? ` · ${evidence.counts.conflict} conflicts`:''}</p>
    {evidence.criteria.map(criterion=><article className={`acceptance-criterion ${criterion.conflict?'evidence-conflict':criterion.verification_status}`} key={criterion.criterion_id}>
      <h5>{criterion.conflict?'!':criterion.verification_status==='verified'?'✓':criterion.verification_status==='supported'?'◐':'?'} {criterion.description}</h5>
      <strong className="evidence-status">{criterion.conflict?'Conflict — human review required':criterion.verification_status==='verified'?'Verified by passing test evidence':criterion.verification_status==='supported'?'Supported by implementation evidence':'Not automatically verified'}</strong>
      {!criterion.evidence.length&&<p>No mapped evidence was found. Human verification is required.</p>}
      {criterion.evidence.map(source=><div className={`criterion-source ${source.negative?'negative-evidence':''}`} key={source.id}><small>{source.evidence_type.replaceAll('_',' ')}{source.mapping==='semantic'?' · AI association; supports only':''}{source.mapping==='unresolved_scope'?' · applicability unresolved':''}</small><p>{source.summary.slice(0,360)}{source.summary.length>360?'…':''}</p>{source.summary.length>360&&<details><summary>Full source summary</summary><p>{source.summary}</p></details>}<small>{source.reference.framework} {source.reference.test_identifier??source.reference.file} {source.reference.outcome}</small><button className="text-button" onClick={()=>onRaw(source.evidence_type==='automated_test'?'tests':source.evidence_type==='reviewer'?'review':'diff')}>View {source.evidence_type==='automated_test'?'test':source.evidence_type==='reviewer'?'AI review':'diff'}</button></div>)}
      {criterion.verification_status==='supported'&&!criterion.conflict&&<p className="small muted">No directly mapped passing check verifies this requirement. Inspect the implementation before accepting.</p>}
    </article>)}<p className="small muted">{evidence.mapper_version}. Evidence is limited to the retained final execution artifacts; human acceptance remains the final decision.</p></section>;
}
