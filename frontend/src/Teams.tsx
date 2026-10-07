import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Bot, UserRound, Plus, Users, X } from 'lucide-react';
import type { Workbench } from './useWorkbench';
import type { TeamSnapshot, Squad, SquadInput, TeamMember, MemberInput, SuggestedPlan } from './teamTypes';
import { technicalAreas } from './teamTypes';
import type { EngineeringStatus } from './productTypes';
import * as api from './teamApi';
import * as product from './productApi';
import { TaskDetail } from './Planning';

const hours = (value: number) => `${Number(value.toFixed(1))}h`;
export default function Teams({lab}: {lab: Workbench}) {
  const [data, setData] = useState<TeamSnapshot | null>(null);
  const [planId, setPlanId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editor, setEditor] = useState<'squad' | 'member' | null>(null);
  const [editSquad, setEditSquad] = useState<Squad>();
  const [editMember, setEditMember] = useState<TeamMember>();
  const [proposal, setProposal] = useState<SuggestedPlan | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const projectId = lab.project.id;
  const currentProject = useRef(projectId); currentProject.current = projectId;
  async function refresh() {
    const snapshot = await api.getTeams(projectId);
    if (currentProject.current === projectId) { setData(snapshot); setPlanId(snapshot.current_plan_id); }
  }
  useEffect(() => {
    setData(null); setError(null); setProposal(null); setSelected(null); setEditor(null); setPlanId(null);
    let alive = true;
    api.getTeams(projectId).then(snapshot => { if (alive) {setData(snapshot);setPlanId(snapshot.current_plan_id);} }).catch(e => {if (alive) setError(e.message);});
    return () => {alive = false;};
  }, [projectId]);
  async function suggest() {
    setBusy(true); setError(null);
    try { const result = await api.suggestAssignments(projectId); if (currentProject.current === projectId) { await refresh(); setProposal(result); } }
    catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function apply() {
    if (!proposal) return;
    setBusy(true);setError(null);
    try {const result = await api.applySuggestions(projectId, proposal); if (currentProject.current === projectId) {setData(result);setProposal(null);} }
    catch (e) {setError((e as Error).message);setProposal(null);await refresh();} finally {setBusy(false);}
  }
  async function status(status: EngineeringStatus) {
    const task = data?.tasks.find(item => item.id === selected); if (!task) return;
    setBusy(true);setError(null);
    try {await product.setTaskStatus(task,status); await refresh();setProposal(null);}
    catch (e) {setError((e as Error).message); await refresh();} finally {setBusy(false);}
  }
  const selectedTask = data?.tasks.find(task => task.id === selected);
  const unassigned = data?.tasks.filter(task => task.plan_id === planId && !task.assignee_id && task.status !== 'done') ?? [];
  return <div className="page-pad teams-page"><div className="page-heading"><div><h1>Teams</h1><p>Plan who owns the work, with capacity left for everything around it.</p></div><label className="project-picker"><span>Project</span><select aria-label="Teams project" value={projectId} onChange={e => {const next = lab.projects.find(item => item.id === e.target.value); if (next) {lab.setProject(next);localStorage.setItem('codeops-project',next.id);} }}>{lab.projects.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label></div>
    {error && <div role="alert" className="product-error">{error}<button className="text-button" onClick={() => void refresh().then(() => setError(null)).catch(e => setError(e.message))}>Refresh teams</button></div>}
    <div className="teams-toolbar"><div className="row"><Users size={16}/><span>{data?.squads.length ?? 0} squads · {data?.members.length ?? 0} members</span></div><div className="row"><button className="button quiet" onClick={() => {setEditSquad(undefined);setEditor('squad');}} disabled={!data}><Plus size={14}/>New squad</button><button className="button quiet" disabled={!data?.squads.length} onClick={() => {setEditMember(undefined);setEditor('member');}}><Plus size={14}/>Add member</button></div></div>
    <p className="team-capacity-note">Human capacity is a weekly planning budget, not hours worked or a delivery schedule. All assigned tasks that are not Done count, including earlier plans. AI capacity uses planned task slots.</p>
    {!data ? <p className="planning-placeholder">Loading team resources…</p> : <>
      {!data.squads.length && <div className="team-empty"><Users size={24}/><h2>Create your first squad</h2><p>Add a squad, then configure human or AI members and their skills.</p></div>}
      {data.squads.map(squad => <section className="squad-panel" key={squad.id}><header><div><h2>{squad.name}</h2><p>{squad.description}</p><span className="small muted">{squad.technical_areas.join(' · ')}</span></div><button className="text-button" onClick={() => {setEditSquad(squad);setEditor('squad');}}>Edit squad</button></header>
        {!data.members.some(member => member.squad_id === squad.id) && <p className="team-empty-row">No members yet.</p>}
        {data.members.filter(member => member.squad_id === squad.id).map(member => {
          const capacity = data.capacities.find(item => item.member_id === member.id)!;
          const owned = data.tasks.filter(task => task.assignee_id === member.id && task.status !== 'done');
          const human = member.member_type === 'human';
          const percent = human && capacity.assignable_capacity_hours ? Math.min(100,capacity.planned_load_hours / capacity.assignable_capacity_hours * 100) : 0;
          return <article className={`team-member ${!member.active ? 'inactive-member' : ''}`} key={member.id}><div className="member-overview"><div className="member-identity">{human ? <UserRound size={18}/> : <Bot size={18}/>}<div><strong>{member.name}</strong><small>{member.role} · {human ? 'Human' : `AI · ${member.future_execution_role}`}{!member.active ? ' · inactive' : ''}</small></div></div><button className="text-button" onClick={() => {setEditMember(member);setEditor('member');}}>Edit {member.name}</button></div>
            <div className="member-capacity">{human ? <><div className="capacity-values"><strong>{hours(capacity.planned_load_hours)} / {hours(capacity.assignable_capacity_hours!)} assignable</strong><span className={capacity.remaining_capacity_hours! < 0 ? 'capacity-warning' : ''}>{hours(capacity.remaining_capacity_hours!)} remaining</span></div><div className="capacity-track" role="meter" aria-label={`Planned capacity for ${member.name}`} aria-valuemin={0} aria-valuemax={capacity.assignable_capacity_hours! || 1} aria-valuenow={Math.min(capacity.planned_load_hours,capacity.assignable_capacity_hours! || 1)} aria-valuetext={`${hours(capacity.planned_load_hours)} planned, ${hours(capacity.assignable_capacity_hours!)} assignable`}><span style={{width:`${percent}%`}} className={capacity.remaining_capacity_hours! < 0 ? 'over-capacity' : ''}/></div><p>{hours(member.weekly_capacity_hours!)} weekly · {Math.round(member.target_utilization! * 100)}% target · {hours(capacity.reserved_capacity_hours!)} reserved</p></> : <><div className="capacity-values"><strong className={`ai-availability availability-${member.availability}`}>{member.availability}</strong><span>{capacity.assigned_task_count} / {member.max_concurrent_tasks} planned task slots</span></div><p>Organizational identity; no execution worker is connected.</p></>}</div>
            <div className="member-skills">{member.skills.map(skill => <span key={skill.technical_area}>{skill.technical_area} <small>{skill.proficiency}/5</small></span>)}</div>
            {!!owned.length && <details className="member-work"><summary>{owned.length} assigned tasks not Done</summary>{owned.map(task => <button key={task.id} onClick={() => setSelected(task.id)}><span className="task-key">{task.key}</span><span>{task.title}</span><small>{hours(task.estimated_hours)} · {task.status.replace('_',' ')}</small></button>)}</details>}
          </article>;
        })}</section>)}
      <section className="unassigned-work"><div className="section-heading"><div><h2>Needs assignment <span className="count">{unassigned.length}</span></h2><p className="small muted">Unassigned work in the current project plan.</p></div><button className="button quiet" disabled={busy || !unassigned.length} onClick={() => void suggest()}>Recommend assignments</button></div>
        {!unassigned.length && <p className="team-empty-row">No unassigned work in the current plan.</p>}
        {unassigned.map(task => <div className="unassigned-row" key={task.id}><span className="task-key">{task.key}</span><div><strong>{task.title}</strong><small>{task.technical_area} · {hours(task.estimated_hours)}{task.squad_id ? ` · ${data.squads.find(squad => squad.id === task.squad_id)?.name}` : ''}</small></div><button className="text-button" onClick={() => setSelected(task.id)}>Assign / recommendations</button></div>)}
      </section>
      {proposal && <section className="suggested-plan"><h2>Suggested assignments</h2><p>Review these suggestions before applying. Dependencies can still block execution.</p>{proposal.suggestions.map(item => <div className="suggestion-row" key={item.task_id}><strong>{item.key} · {item.title}</strong><span>→ {data.members.find(member => member.id === item.assignee_id)?.name}</span><ul>{item.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>{!!item.warnings.length && <ul className="capacity-warning">{item.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>}</div>)}{proposal.unfilled.map(item => <p className="small muted" key={item.task_id}>{item.key}: {item.reason}</p>)}<div className="assignment-actions"><button className="button primary" disabled={busy || !proposal.suggestions.length} onClick={() => void apply()}>Apply {proposal.suggestions.length} suggested assignments</button><button className="text-button" onClick={() => setProposal(null)}>Dismiss suggestions</button></div></section>}
    </>}
    {editor && data && <TeamDialog title={editor === 'squad' ? (editSquad ? 'Edit squad' : 'New squad') : (editMember ? 'Edit member' : 'Add member')} onClose={() => setEditor(null)}>{editor === 'squad' ? <SquadForm existing={editSquad} onSave={async body => {await api.saveSquad(projectId,body,editSquad);await refresh();setProposal(null);setEditor(null);}}/> : <MemberForm existing={editMember} squads={data.squads} onSave={async body => {await api.saveMember(projectId,body,editMember);await refresh();setProposal(null);setEditor(null);}}/>}</TeamDialog>}
    {selectedTask && data && <TaskDetail task={selectedTask} tasks={data.tasks} changing={busy} error={error} onClose={() => setSelected(null)} onStatus={next => void status(next)} onDependency={setSelected} onTaskChange={() => {void refresh();setProposal(null);}}/>}
  </div>;
}

function TeamDialog({title,onClose,children}: {title:string;onClose:()=>void;children:ReactNode}) {
  const dialog = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose);closeRef.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    dialog.current?.querySelector<HTMLElement>('input,button')?.focus();
    function key(e: KeyboardEvent) {
      if (e.key === 'Escape') closeRef.current();
      if (e.key !== 'Tab') return;
      const controls = dialog.current?.querySelectorAll<HTMLElement>('input:not(:disabled),button:not(:disabled),select:not(:disabled),textarea:not(:disabled)');
      if (!controls?.length) return;
      const first = controls[0],last=controls[controls.length-1];
      if (e.shiftKey && document.activeElement===first) {e.preventDefault();last.focus();}
      else if (!e.shiftKey && document.activeElement===last) {e.preventDefault();first.focus();}
    }
    window.addEventListener('keydown',key);return () => {window.removeEventListener('keydown',key);previous?.focus();};
  },[]);
  return <div className="modal-backdrop" onClick={onClose}><section className="team-dialog" ref={dialog} role="dialog" aria-modal="true" aria-labelledby="team-dialog-title" onClick={e => e.stopPropagation()}><header><h2 id="team-dialog-title">{title}</h2><button aria-label="Close team editor" className="text-button" onClick={onClose}><X size={18}/></button></header>{children}</section></div>;
}

function SquadForm({existing,onSave}: {existing?:Squad;onSave:(body:SquadInput)=>Promise<void>}) {
  const [name,setName] = useState(existing?.name ?? '');const [description,setDescription] = useState(existing?.description ?? '');
  const [areas,setAreas] = useState(existing?.technical_areas ?? ['Backend']);const [error,setError] = useState('');const [busy,setBusy] = useState(false);
  return <form className="team-form" onSubmit={async e => {e.preventDefault();setBusy(true);setError('');try {await onSave({name,description,technical_areas:areas});}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}><label>Squad name<input required maxLength={200} value={name} onChange={e => setName(e.target.value)}/></label><label>Description<textarea maxLength={4000} value={description} onChange={e => setDescription(e.target.value)}/></label><fieldset><legend>Technical areas</legend>{technicalAreas.map(area => <label className="team-checkbox" key={area}><input type="checkbox" checked={areas.includes(area)} onChange={e => setAreas(previous => e.target.checked ? [...previous,area] : previous.filter(item => item!==area))}/>{area}</label>)}</fieldset>{error && <p className="product-error" role="alert">{error}</p>}<button className="button primary" disabled={busy || !areas.length}>Save squad</button></form>;
}

function MemberForm({existing,squads,onSave}: {existing?:TeamMember;squads:Squad[];onSave:(body:MemberInput)=>Promise<void>}) {
  const [name,setName] = useState(existing?.name ?? '');const [role,setRole] = useState(existing?.role ?? '');const [type,setType] = useState<'human'|'ai'>(existing?.member_type ?? 'human');
  const [squadId,setSquadId] = useState(existing?.squad_id ?? squads[0]?.id ?? '');const [active,setActive] = useState(existing?.active ?? true);
  const [weekly,setWeekly] = useState(existing?.weekly_capacity_hours ?? 30);const [utilization,setUtilization] = useState((existing?.target_utilization ?? .8)*100);
  const [availability,setAvailability] = useState<MemberInput['availability']>(existing?.availability ?? 'available');const [limit,setLimit] = useState(existing?.max_concurrent_tasks ?? 1);const [executionRole,setExecutionRole] = useState<MemberInput['future_execution_role']>(existing?.future_execution_role ?? 'general');
  const [skills,setSkills] = useState(existing?.skills ?? []);const [error,setError] = useState('');const [busy,setBusy] = useState(false);
  return <form className="team-form" onSubmit={async e => {e.preventDefault();setBusy(true);setError('');try {await onSave({name,role,member_type:type,squad_id:squadId,skills,active,weekly_capacity_hours:type==='human'?weekly:null,target_utilization:type==='human'?utilization/100:null,availability:type==='ai'?availability:null,max_concurrent_tasks:type==='ai'?limit:null,future_execution_role:type==='ai'?executionRole:null});}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>
    <label>Name<input required maxLength={200} value={name} onChange={e => setName(e.target.value)}/></label><label>Role<input required maxLength={200} value={role} onChange={e => setRole(e.target.value)}/></label><div className="team-form-grid"><label>Member type<select disabled={!!existing} value={type} onChange={e => setType(e.target.value as 'human'|'ai')}><option value="human">Human</option><option value="ai">AI</option></select></label><label>Primary squad<select required value={squadId} onChange={e => setSquadId(e.target.value)}>{squads.map(squad => <option key={squad.id} value={squad.id}>{squad.name}</option>)}</select></label></div>
    {type==='human' ? <><div className="team-form-grid"><label>Weekly capacity (hours)<input type="number" required min={0} max={168} step="0.5" value={weekly} onChange={e => setWeekly(Number(e.target.value))}/></label><label>Target utilization (%)<input type="number" required min={1} max={100} step="1" value={utilization} onChange={e => setUtilization(Number(e.target.value))}/></label></div><p className="small muted">{hours(weekly*utilization/100)} assignable · {hours(weekly*(1-utilization/100))} reserved. Planned effort, not tracked working time.</p></> : <><div className="team-form-grid"><label>Availability<select value={availability!} onChange={e => setAvailability(e.target.value as MemberInput['availability'])}><option value="available">Available</option><option value="busy">Busy</option><option value="offline">Offline</option></select></label><label>Maximum planned tasks<input type="number" required min={1} max={100} value={limit} onChange={e => setLimit(Number(e.target.value))}/></label></div><label>Future execution role<select value={executionRole!} onChange={e => setExecutionRole(e.target.value as MemberInput['future_execution_role'])}>{['developer','tester','reviewer','general'].map(role => <option key={role}>{role}</option>)}</select></label><p className="small muted">An organizational identity. No coding execution starts from this record.</p></>}
    <fieldset><legend>Skills · manually configured proficiency</legend>{technicalAreas.map(area => {const skill=skills.find(item=>item.technical_area===area);return <div className="skill-editor-row" key={area}><label className="team-checkbox"><input type="checkbox" checked={!!skill} onChange={e => setSkills(previous=>e.target.checked?[...previous,{technical_area:area,proficiency:3}]:previous.filter(item=>item.technical_area!==area))}/>{area}</label>{skill && <select aria-label={`${area} proficiency`} value={skill.proficiency} onChange={e => setSkills(previous=>previous.map(item=>item.technical_area===area?{...item,proficiency:Number(e.target.value)}:item))}>{[1,2,3,4,5].map(level=><option key={level} value={level}>{level}/5</option>)}</select>}</div>;})}</fieldset>
    <label className="team-checkbox"><input type="checkbox" checked={active} onChange={e => setActive(e.target.checked)}/>Active member</label>{error && <p className="product-error" role="alert">{error}</p>}<button className="button primary" disabled={busy || !skills.length}>Save member</button>
  </form>;
}
