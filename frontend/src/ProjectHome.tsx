import { useState } from 'react';
import { ArrowRight, FolderGit2, Plus, X, Settings2, GitBranch, LayoutList, Kanban, Workflow, ShieldCheck } from 'lucide-react';
import type { Workbench } from './useWorkbench';
import PreviewSettings from './PreviewSettings';
import Spotlight from './design/Spotlight';

export default function ProjectHome({ lab }: { lab: Workbench }) {
  const [adding, setAdding] = useState(false);
  const [previewProject,setPreviewProject]=useState<string|null>(null);
  const [name, setName] = useState(''); const [path, setPath] = useState('');
  const [saving, setSaving] = useState(false);
  async function add() {
    setSaving(true);
    const result = await lab.register(name.trim(), path.trim());
    setSaving(false);
    if (result) { setAdding(false); lab.openProject(result); }
  }
  return <div className="page-pad product-home">
    <section className="project-welcome">
      <div className="project-welcome-copy"><span className="workspace-caption"><FolderGit2 size={16}/> Your engineering workspace</span><h1>Build with a plan.<br/>Ship with confidence.</h1><p>Bring your repositories, shape the work, and review what your agents build. Every decision stays in your hands.</p><button className="button primary" onClick={()=>lab.setView('planning')}>Start planning <ArrowRight size={16}/></button></div>
      <div className="workspace-route" aria-label="CodeOps workflow"><div><LayoutList size={20}/><span><strong>Plan the work</strong><small>Goals, tasks and acceptance criteria</small></span></div><div><Workflow size={20}/><span><strong>Build in isolation</strong><small>Review the coding plan before execution</small></span></div><div><ShieldCheck size={20}/><span><strong>Review and accept</strong><small>Inspect evidence, then decide on delivery</small></span></div></div>
    </section>
    <div className="page-heading repository-heading"><div><h2>Your repositories <span className="count">{lab.projects.length}</span></h2><p>Choose a project to open its plans and engineering work.</p></div>
      <button className="button quiet" onClick={() => setAdding(true)}><Plus size={15} /> Add project</button></div>
    <div className="product-project-list">
      {lab.connected === null ? <p className="muted">Loading projects…</p> : !lab.connected ? <p className="muted">Connect to the local CodeOps backend to load your projects.</p> : lab.projects.length ? lab.projects.map(project =>
        <Spotlight key={project.id} className="repository-card"><button className="product-project-row" onClick={() => lab.openProject(project)}>
          <span className="repository-symbol"><FolderGit2 size={21}/></span><span><strong>{project.name}</strong><small>{project.description || 'Local project'}</small></span><ArrowRight size={16}/>
        </button><div className="repository-stack">{project.stack.map(item=><span key={item}>{item}</span>)}</div><div className="repository-path"><GitBranch size={13}/><code>{project.path}</code></div><footer><span>Registered source</span><button className="text-button project-preview-settings" onClick={()=>setPreviewProject(project.id)}><Settings2 size={13}/>Preview configuration</button></footer></Spotlight>) : <div className="empty"><FolderGit2 size={28} /><h3>Add your first project</h3><p>Choose an existing local repository, then describe what the team should build.</p></div>}
    </div>
    <div className="workspace-shortcuts"><button onClick={()=>lab.setView('board')}><Kanban size={22}/><span><strong>Organize the work</strong><small>Track approved tasks on your board.</small></span><ArrowRight size={17}/></button><button onClick={()=>lab.setView('workspace')}><ShieldCheck size={22}/><span><strong>Review the evidence</strong><small>Inspect plans, code, tests and retained runs.</small></span><ArrowRight size={17}/></button></div>
    {previewProject&&<PreviewSettings projectId={previewProject} onClose={()=>setPreviewProject(null)}/>}
    {adding && <div className="modal-backdrop" onClick={() => !saving && setAdding(false)}><form className="modal" role="dialog" aria-modal="true" aria-labelledby="add-project-title" onClick={e => e.stopPropagation()} onSubmit={e => { e.preventDefault(); void add(); }}>
      <button className="modal-close" type="button" aria-label="Close add project" disabled={saving} onClick={() => setAdding(false)}><X size={18} /></button>
      <h2 id="add-project-title">Add a local project</h2><p>Use a repository already on this computer.</p>
      <label>Project name<input required maxLength={200} value={name} onChange={e => setName(e.target.value)} /></label>
      <label>Repository path<input required value={path} onChange={e => setPath(e.target.value)} placeholder="C:\Users\…\my-project" /></label>
      <div className="modal-actions"><button className="button quiet" type="button" disabled={saving} onClick={() => setAdding(false)}>Cancel</button><button className="button primary" disabled={saving || !name.trim() || !path.trim()}>{saving ? 'Adding…' : 'Add project'}</button></div>
    </form></div>}
  </div>;
}
