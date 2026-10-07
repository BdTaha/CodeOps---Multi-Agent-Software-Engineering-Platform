import { Check, Circle, LoaderCircle, AlertCircle, Clock3, LockKeyhole, ChevronRight, Folder, FileCode2, FileText } from 'lucide-react';
import type { Status } from './types';

export function Badge({ status, children }: { status: Status; children?: React.ReactNode }) {
  const Icon = status === 'succeeded' ? Check : status === 'running' ? LoaderCircle : status === 'failed' ? AlertCircle : status === 'approval' ? LockKeyhole : status === 'unavailable' ? Clock3 : Circle;
  return <span className={`badge ${status}`}><Icon size={12} className={status === 'running' ? 'spin' : ''} />{children ?? ({ succeeded: 'Completed', running: 'Running', failed: 'Failed', approval: 'Review required', unavailable: 'Coming next', waiting: 'Waiting', skipped: 'Skipped' }[status])}</span>;
}
export function Empty({ title, children }: { title: string; children: React.ReactNode }) { return <div className="empty"><Circle size={26} /><h3>{title}</h3><p>{children}</p></div>; }
export function duration(seconds: number) { return seconds >= 60 ? `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s` : `${seconds.toFixed(1)}s`; }
export function downloadDiff(diff: string, preview: boolean, run?: string) {
  const url = URL.createObjectURL(new Blob([diff], { type: 'text/plain;charset=utf-8' }));
  const link = document.createElement('a'); link.href = url; link.download = preview ? 'example-changes.diff' : `changes-${run?.slice(0, 8)}.diff`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

interface Tree { name: string; path: string; children: Tree[] }
export function FileTree({ files, changes, selected, choose }: { files: string[]; changes: { path: string; kind: string }[]; selected: string | null; choose: (path: string) => void }) {
  const root: Tree = { name: '', path: '', children: [] };
  for (const file of [...files].sort()) {
    let node = root;
    for (const [i, part] of file.split('/').entries()) {
      const path = file.split('/').slice(0, i + 1).join('/');
      let next = node.children.find(child => child.name === part);
      if (!next) { next = { name: part, path, children: [] }; node.children.push(next); }
      node = next;
    }
  }
  function branch(node: Tree, depth: number): React.ReactNode {
    const folder = node.children.length > 0;
    if (folder) return <details className="tree-folder" key={node.path} open><summary style={{ paddingLeft: 12 + depth * 14 }}><ChevronRight size={12} /><Folder size={14} /><span>{node.name}</span></summary>{node.children.map(child => branch(child, depth + 1))}</details>;
    const change = changes.find(change => change.path === node.path);
    return <button key={node.path} className={`tree-file ${selected === node.path ? 'selected' : ''} ${change ? `changed ${change.kind}` : ''}`} style={{ paddingLeft: 26 + depth * 14 }} onClick={() => choose(node.path)} title={node.path}>{node.name.endsWith('.md') ? <FileText size={14} /> : <FileCode2 size={14} />}<span>{node.name}</span>{change && <small>{change.kind === 'created' ? 'A' : change.kind === 'deleted' ? 'D' : 'M'}</small>}</button>;
  }
  return <div className="file-tree">{root.children.map(node => branch(node, 0))}</div>;
}
