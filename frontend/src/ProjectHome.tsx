import { useState } from 'react';
import { ArrowRight, FolderGit2, Plus, X, Settings2, GitBranch, LayoutList, Kanban, Workflow } from 'lucide-react';
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
    <div className="page-heading repository-heading"><div><h1>Projects <span className="count">{lab.projects.length}</span></h1><p>Repositories in this workspace.</p></div>
      <button className="button quiet" onClick={() => setAdding(true)}><Plus size={15} /> Add project</button></div>
    <div className="project-desk"><section className="repository-browser" aria-label="Registered repositories">
    <div className="desk-section-heading"><span>Repository</span><span>Open project</span></div>
    <div className="product-project-list">
      {lab.connected === null ? <p className="muted">Loading projects…</p> : !lab.connected ? <p className="muted">Connect to the local CodeOps backend to load your projects.</p> : lab.projects.length ? lab.projects.map(project =>
        <Spotlight key={project.id} className="repository-card"><button className="product-project-row" onClick={() => lab.openProject(project)}>
          <span className="repository-symbol"><FolderGit2 size={21}/></span><span><strong>{project.name}</strong><small>{project.description || 'Local project'}</small></span><ArrowRight size={16}/>
        </button><div className="repository-stack">{project.stack.map(item=><span key={item}>{item}</span>)}</div><div className="repository-path"><GitBranch size={13}/><code>{project.path}</code></div><footer><span>Registered source</span><button className="text-button project-preview-settings" onClick={()=>setPreviewProject(project.id)}><Settings2 size={13}/>Preview configuration</button></footer></Spotlight>) : <div className="empty"><FolderGit2 size={28} /><h3>Add your first project</h3><p>Choose an existing local repository, then describe what the team should build.</p></div>}
    </div>
    </section><aside className="project-context" aria-label="Current project"><div className="desk-section-heading">Current project</div><div className="project-context-body"><FolderGit2 size={22}/><h2>{lab.project.name}</h2><p>{lab.project.description || 'Choose a repository to begin planning.'}</p><div className="context-path"><GitBranch size={13}/><code>{lab.project.path}</code></div><div className="context-stack">{lab.project.stack.map(item=><span key={item}>{item}</span>)}</div><nav aria-label="Project work"><button onClick={()=>lab.setView('planning')}><LayoutList size={15}/><span>Planning</span><ArrowRight size={14}/></button><button onClick={()=>lab.setView('board')}><Kanban size={15}/><span>Board</span><ArrowRight size={14}/></button><button onClick={()=>lab.setView('workspace')}><Workflow size={15}/><span>Engineering</span><ArrowRight size={14}/></button></nav></div></aside></div>
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
