import { useState } from 'react';
import { FileCode2, Download, GitPullRequest, ShieldCheck, ArrowRight, Columns2, List, MessageSquare } from 'lucide-react';
import type { Workbench } from './useWorkbench';
import { Empty, downloadDiff } from './components';

function splitDiff(diff: string): { path: string; lines: string[] }[] {
  const chunks: { path: string; lines: string[] }[] = [];
  let current: { path: string; lines: string[] } | null = null;
  const lines = diff.replace(/\r\n/g, '\n').split('\n');
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].startsWith('--- ') && lines[i + 1]?.startsWith('+++ ')) {
      const next = lines[i + 1].slice(4), previous = lines[i].slice(4);
      current = { path: (next === '/dev/null' ? previous : next).replace(/^[ab]\//, ''), lines: [] };
      chunks.push(current); i++;
    } else if (current) current.lines.push(lines[i]);
  }
  return chunks;
}
function diffRows(lines: string[]) {
  let old = 0, next = 0;
  return lines.filter((line, index) => line || index < lines.length - 1).map(line => {
    const hunk = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (hunk) { old = Number(hunk[1]); next = Number(hunk[2]); return { line, old: '', next: '', kind: 'hunk' }; }
    if (line.startsWith('\\')) return { line, old: '', next: '', kind: 'meta' };
    const kind = line.startsWith('+') ? 'addition' : line.startsWith('-') ? 'deletion' : 'context';
    return { line, old: kind === 'addition' ? '' : String(old++), next: kind === 'deletion' ? '' : String(next++), kind };
  });
}
export default function Review({ lab }: { lab: Workbench }) {
  const [selected, setSelected] = useState<string | null>(null);
  const [sideBySide, setSideBySide] = useState(false);
  const artifact = lab.displayed?.development;
  const changes = lab.displayed?.changes ?? [];
  const chunks = splitDiff(artifact?.diff ?? '');
  const additions = chunks.flatMap(c => c.lines).filter(line => line.startsWith('+')).length;
  const deletions = chunks.flatMap(c => c.lines).filter(line => line.startsWith('-')).length;
  const shown = selected && changes.some(c => c.path === selected) ? selected : changes[0]?.path;
  const chunk = chunks.find(c => c.path === shown);
  const comments = lab.displayed?.review?.findings.filter(f => f.file === shown) ?? [];
  function download() {
    if (!artifact) return;
    downloadDiff(artifact.diff, lab.preview, lab.displayed?.run_id);
  }
  return <div className="review-screen page-pad"><div className="eyebrow">WORKSPACE / CODE REVIEW</div><div className="page-heading"><div><h1>Make every change visible.</h1><p>{lab.preview ? 'An example of the review experience after the agents finish.' : 'Actual snapshot changes. Inspect the diff before moving forward.'}</p></div><div className="row"><button className="button quiet" disabled={!artifact} onClick={download}><Download size={15} /> Download diff</button><button className="button quiet" disabled={lab.preview || lab.displayed?.task.status !== "succeeded" || !lab.system?.github_configured} onClick={() => lab.prepareDelivery("github")} title={lab.system?.github_configured ? "Review publication details" : "Configure ASE_GITHUB_TOKEN and import a GitHub repository"}><GitPullRequest size={15} /> Create pull request</button></div></div>
    {!artifact ? <Empty title="No code changes yet">Run a real task, review the plan, and approve snapshot development to see the actual diff here.<button className="button primary" onClick={() => lab.setView('workspace')}>Open workspace <ArrowRight size={14} /></button></Empty> : <><div className="review-summary"><div><span className="repo-icon"><FileCode2 size={20} /></span><span><strong>{changes.length} files changed</strong><small>{lab.preview ? 'Illustrative changes' : 'Managed snapshot only'}</small></span><span className="diff-count addition-text">+{additions}</span><span className="diff-count deletion-text">−{deletions}</span></div><div className="row"><span className="subtle-pill"><ShieldCheck size={13} />{lab.preview ? 'Example review · approved' : lab.displayed?.review ? lab.displayed.review.approved ? 'Model review approved' : 'Model review rejected' : lab.displayed?.tests?.outcome === 'passed' ? 'Tests passed · review pending' : 'Validation pending'}</span><button className="button quiet" onClick={() => lab.setView('results')}>View result <ArrowRight size={14} /></button></div></div>
      <div className="review-layout"><aside className="changed-files"><div className="pane-title"><span>Changed files</span><small>{changes.length}</small></div>{changes.map(change => <button key={change.path} className={shown === change.path ? 'active' : ''} onClick={() => setSelected(change.path)}><FileCode2 size={14} /><span>{change.path}<small>{change.kind}</small></span><b>{change.kind === 'created' ? 'A' : change.kind === 'deleted' ? 'D' : 'M'}</b></button>)}<div className="review-note"><ShieldCheck size={17} /><strong>{lab.preview ? 'Preview changes' : 'Source repository preserved'}</strong><p>{lab.preview ? 'These examples are for exploring the interface.' : 'Changes exist only in the isolated snapshot until you choose how to apply them.'}</p></div></aside>
      <section className="diff-panel"><div className="diff-heading"><span><FileCode2 size={14} />{shown}</span><div className="tabs"><button className={!sideBySide ? 'active' : ''} aria-label="Unified diff" onClick={() => setSideBySide(false)}><List size={14} /></button><button className={sideBySide ? 'active' : ''} aria-label="Side by side diff" onClick={() => setSideBySide(true)}><Columns2 size={14} /></button></div></div>
        {chunk ? <div className={`diff-content ${sideBySide ? 'split-diff' : ''}`}>{diffRows(chunk.lines).map((row, i) => sideBySide && row.kind !== 'hunk' && row.kind !== 'meta' ? <div key={i} className="split-row"><div className={`diff-line ${row.kind === 'deletion' ? 'deletion' : ''}`}><span className="line-number">{row.old}</span><code>{row.kind === 'addition' ? '' : row.line.slice(1)}</code></div><div className={`diff-line ${row.kind === 'addition' ? 'addition' : ''}`}><span className="line-number">{row.next}</span><code>{row.kind === 'deletion' ? '' : row.line.slice(1)}</code></div></div> : <div key={i} className={`diff-line ${row.kind}`}><span className="line-number">{row.old}</span><span className="line-number">{row.next}</span><code>{row.line}</code></div>)}</div> : <div className="no-diff"><p>This file has no text hunk in the available diff.</p><p>{changes.find(c => c.path === shown)?.summary}</p><pre>{artifact.diff}</pre></div>}
        {comments.map((comment, i) => <div className="review-comment" key={i}><MessageSquare size={16} /><div><strong>Reviewer Agent <span className="subtle-pill">{lab.preview ? 'Example comment' : comment.severity}</span></strong><small>{comment.file}{comment.line ? `:${comment.line}` : ''}</small><p>{comment.description}</p>{comment.evidence && <pre className="raw-record">{comment.evidence}</pre>}{comment.recommended_fix && <p>Recommended fix: {comment.recommended_fix}</p>}</div></div>)}
      </section></div><div className="implementation-note"><span className="tiny-label">IMPLEMENTATION SUMMARY</span><p>{artifact.explanation}</p>{!lab.preview && <ul>{artifact.limitations.map(text => <li key={text}>{text}</li>)}</ul>}</div></>}
  </div>;
}
