import TaskExecutionPanel from './TaskExecutionPanel';
import ModelTrace from './ModelTrace';
import { useEffect, useRef, useState } from 'react';
import { ArrowRight, CheckSquare, Clock3, Layers3, Loader2, Plus, X, Filter, Circle, CircleDashed, CircleDot, CircleCheck, Bot, UserRound } from 'lucide-react';
import type { Workbench } from './useWorkbench';
import type { EngineeringStatus, EngineeringTask, PlanRecord } from './productTypes';
import { boardColumns } from './productTypes';
import * as api from './productApi';
import * as teamApi from './teamApi';
import type { TeamSnapshot } from './teamTypes';
import TaskAssignmentEditor from './TaskAssignmentEditor';

const hours = (value: number) => `${Number(value.toFixed(2))}h`;

export default function Planning({ lab, board = false }: { lab: Workbench; board?: boolean }) {
  const [record, setRecord] = useState<PlanRecord | null>(null);
  const [goal, setGoal] = useState('');
  const [loading, setLoading] = useState(true); const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [changing, setChanging] = useState(false);
  const [filterOpen, setFilterOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [priorityFilter, setPriorityFilter] = useState('all');
  const [areaFilter, setAreaFilter] = useState('all');
  const [assigneeFilter, setAssigneeFilter] = useState('all');
  const [squadFilter, setSquadFilter] = useState('all');
  const [teamData, setTeamData] = useState<TeamSnapshot | null>(null);
  const projectId = lab.project.id;
  const current = useRef(projectId); current.current = projectId;
  const pending = record?.status === 'queued' || record?.status === 'generating';
  const plan = record?.plan;
  const filteredTasks = plan?.tasks.filter(task => `${task.key} ${task.title} ${task.description}`.toLowerCase().includes(query.toLowerCase())
    && (priorityFilter === 'all' || task.priority === priorityFilter) && (areaFilter === 'all' || task.technical_area === areaFilter)
    && (assigneeFilter === 'all' || (assigneeFilter === 'unassigned' ? !task.assignee_id : task.assignee_id === assigneeFilter))
    && (squadFilter === 'all' || task.squad_id === squadFilter)) ?? [];
  const filtersActive = !!query || priorityFilter !== 'all' || areaFilter !== 'all' || assigneeFilter !== 'all' || squadFilter !== 'all';
  const selectedTask = plan?.tasks.find(task => task.id === selected);
  useEffect(() => {
    let alive = true;
    setLoading(true); setRecord(null); setGoal(''); setSelected(null); setError(null);
    setQuery(''); setPriorityFilter('all'); setAreaFilter('all'); setAssigneeFilter('all'); setSquadFilter('all'); setTeamData(null);
    teamApi.getTeams(projectId).then(result => { if (alive) setTeamData(result); }).catch(failure => { if (alive) setError((failure as Error).message); });
    api.getPlan(projectId).then(result => { if (alive) { setRecord(result); setGoal(result?.goal.goal ?? ''); } })
      .catch(failure => { if (alive) setError((failure as Error).message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [projectId]);
  useEffect(() => {
    if (!pending && !plan) return;
    let alive = true; let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const [result, teams] = await Promise.all([api.getPlan(projectId),teamApi.getTeams(projectId)]); if (alive) { setRecord(result); setTeamData(teams); } }
      catch (failure) { if (alive) setError((failure as Error).message); }
      if (alive) timer = setTimeout(poll, pending ? 1500 : 4000);
    }
    timer = setTimeout(poll, 1000);
    return () => { alive = false; clearTimeout(timer); };
  }, [pending, projectId, !!plan]);
  function updateTask(updated: EngineeringTask) {
    if (current.current !== updated.project_id) return;
    setRecord(previous => previous?.plan ? { ...previous, plan: { ...previous.plan, tasks: previous.plan.tasks.map(item => item.id === updated.id ? updated : item) } } : previous);
    teamApi.getTeams(projectId).then(result => {if (current.current === projectId) setTeamData(result);}).catch(failure => setError((failure as Error).message));
  }
  async function submit() {
    setSubmitting(true); setError(null);
    try { const result = await api.createPlan(projectId, goal.trim()); if (current.current === projectId) setRecord(result); }
    catch (failure) { if (current.current === projectId) setError((failure as Error).message); }
    finally { setSubmitting(false); }
  }
  async function changeStatus(task: EngineeringTask, status: EngineeringStatus) {
    setChanging(true); setError(null);
    try {
      const updated = await api.setTaskStatus(task, status);
      if (current.current === projectId) setRecord(previous => previous?.plan ? {
        ...previous, plan: { ...previous.plan, tasks: previous.plan.tasks.map(item => item.id === task.id ? updated : item) },
      } : previous);
    } catch (failure) {
      if (current.current === projectId) {
        setError((failure as Error).message);
        try { setRecord(await api.getPlan(projectId)); } catch { /* Keep the last visible plan and explicit error. */ }
      }
    } finally { setChanging(false); }
  }
  return <div className={`page-pad planning-page ${board ? 'board-page' : ''}`}>
    {!board && <div className="eyebrow">CODEOPS / PLANNING</div>}
    <div className={board ? 'board-toolbar' : 'page-heading'}><div className={board ? 'board-toolbar-title' : ''}><h1>{board ? 'Board' : 'Project planning'}</h1>{board ? <><span className="board-total">{plan?.tasks.length ?? 0}</span><button className={`board-filter-button ${filtersActive ? 'has-filters' : ''}`} aria-expanded={filterOpen} aria-controls="board-filters" onClick={() => setFilterOpen(open => !open)}><Filter size={14} /> Filter</button></> : <p>Start with a goal. Build a clear engineering plan.</p>}</div>
      <label className="project-picker"><span>Project</span><select aria-label="Planning project" value={projectId} onChange={e => { const next = lab.projects.find(item => item.id === e.target.value); if (next) { lab.setProject(next); localStorage.setItem('codeops-project', next.id); } }}>{lab.projects.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
    </div>
    {board && filterOpen && <div className="board-filters" id="board-filters">
      <label>Search tasks<input aria-label="Search board tasks" placeholder="Title or task ID…" value={query} onChange={e => setQuery(e.target.value)} /></label>
      <label>Priority<select value={priorityFilter} onChange={e => setPriorityFilter(e.target.value)}><option value="all">All priorities</option>{['urgent', 'high', 'medium', 'low'].map(priority => <option key={priority} value={priority}>{priority}</option>)}</select></label>
      <label>Area<select value={areaFilter} onChange={e => setAreaFilter(e.target.value)}><option value="all">All areas</option>{[...new Set(plan?.tasks.map(task => task.technical_area) ?? [])].sort().map(area => <option key={area}>{area}</option>)}</select></label>
      <label>Assignee<select value={assigneeFilter} onChange={e => setAssigneeFilter(e.target.value)}><option value="all">All assignees</option><option value="unassigned">Unassigned</option>{teamData?.members.map(member => <option key={member.id} value={member.id}>{member.name}</option>)}</select></label>
      <label>Squad<select value={squadFilter} onChange={e => setSquadFilter(e.target.value)}><option value="all">All squads</option>{teamData?.squads.map(squad => <option key={squad.id} value={squad.id}>{squad.name}</option>)}</select></label>
      {filtersActive && <button className="text-button" onClick={() => { setQuery(''); setPriorityFilter('all'); setAreaFilter('all'); setAssigneeFilter('all'); setSquadFilter('all'); }}>Clear filters</button>}
    </div>}
    {error && <div className="product-error" role="alert">{error}</div>}
    {record?.status === 'failed' && <div className="product-error" role="alert"><strong>Planning could not complete.</strong><p>{record.error}</p><p>Your goal is retained. Check Models settings, then submit again.</p></div>}
    {!board && <form className="goal-panel" onSubmit={e => { e.preventDefault(); void submit(); }}>
      <label htmlFor="project-goal">What do you want the team to build?</label>
      <textarea id="project-goal" required maxLength={12000} value={goal} disabled={pending || submitting || loading} onChange={e => setGoal(e.target.value)} placeholder="Add authentication with registration, login, password reset and role-based access." />
      <div className="goal-actions"><span>Engineering effort will be estimated, not guaranteed.</span><button className="button primary" disabled={loading || submitting || pending || !goal.trim() || !lab.connected}>{pending || submitting ? <Loader2 className="spin" size={15} /> : <Plus size={15} />}{pending || submitting ? 'Planning…' : 'Plan with CodeOps'}</button></div>
      {plan && <p className="small muted">Submitting a new goal creates a new plan. This view shows the latest plan; previous plans remain saved.</p>}
    </form>}
    {loading ? <div className="planning-placeholder"><Loader2 className="spin" size={18} /> Loading saved plan…</div> : pending ?
      <div className="planning-placeholder" role="status"><Loader2 className="spin" size={20} /><div><strong>{record?.status === 'queued' ? 'Your goal is queued' : 'CodeOps is planning your project'}</strong><p>Preparing epics, tasks and acceptance criteria. You can refresh; the request stays saved.</p><small>Keep the CodeOps worker and configured model service available.</small></div></div> : plan ? <>
        {board ? <div className="board-context"><span>{plan.title}</span><span>{filtersActive ? `${filteredTasks.length} of ${plan.tasks.length} tasks` : `${plan.epics.length} epics`}<span className="board-context-divider">·</span>~{hours(plan.estimated_hours)} estimated effort</span></div> : <><div className="plan-heading"><div><span className="tiny-label">PROJECT PLAN</span><h2>{plan.title}</h2><p>{plan.summary}</p></div><button className="button quiet" onClick={() => lab.setView('board')}>Open board <ArrowRight size={15} /></button></div>
        <div className="plan-totals"><span><Layers3 size={15} /><strong>{plan.epics.length}</strong> Epics</span><span><CheckSquare size={15} /><strong>{plan.tasks.length}</strong> Tasks</span><span><Clock3 size={15} />Estimated effort <strong>~{hours(plan.estimated_hours)}</strong></span></div>
        <p className="estimate-notice">{plan.estimate_notice}</p><details><summary>Planning model log</summary><ModelTrace items={record?.model_invocations}/></details></>}
        {board ? <div className="engineering-board">{boardColumns.map(column => {
          const tasks = filteredTasks.filter(task => task.status === column.status);
          const StatusIcon = column.status === 'backlog' ? CircleDashed : column.status === 'planned' ? Circle : column.status === 'done' ? CircleCheck : CircleDot;
          return <section className={`board-column status-${column.status}`} key={column.status}><h2><StatusIcon className="board-column-icon" size={18} />{column.label}<span className="count">{tasks.length}</span></h2>
            <div className="board-cards">{tasks.map(task => <article className="engineering-card" key={task.id}>
              <button className="task-open" onClick={() => setSelected(task.id)} aria-label={`Open ${task.key}: ${task.title}`}><span className="task-card-heading"><span className="task-key">{task.key}</span><span className="task-estimate"><Clock3 size={12} />{hours(task.estimated_hours)}</span></span><h3>{task.title}</h3></button>
              <div className="task-card-footer"><span className={`priority-signal signal-${task.priority}`} title={`${task.priority} priority`} aria-label={`${task.priority} priority`}><i /><i /><i /></span><span className={`area-tag area-${task.technical_area.toLowerCase()}`}><i />{task.technical_area}</span><label className="card-status"><span className="sr-only">Status for {task.key}</span><select aria-label={`Status for ${task.key}`} disabled={changing || !!task.execution_run_id} value={task.status} onChange={e => void changeStatus(task, e.target.value as EngineeringStatus)}>{boardColumns.map(option => <option key={option.status} value={option.status}>{option.label}</option>)}</select></label></div>
              <div className="task-card-owner">{task.assignee_id ? <>{teamData?.members.find(member => member.id === task.assignee_id)?.member_type === 'ai' ? <Bot size={13}/> : <UserRound size={13}/>}<span>{teamData?.members.find(member => member.id === task.assignee_id)?.name ?? 'Loading assignee…'}</span></> : <><UserRound size={13}/><span>Unassigned</span></>}{task.squad_id && <small>{teamData?.squads.find(squad => squad.id === task.squad_id)?.name ?? 'Loading squad…'}</small>}</div>
            </article>)}{!tasks.length && <div className="board-empty">No tasks</div>}</div>
          </section>;
        })}</div> : <div className="epic-list">{plan.epics.map(epic => <section className="epic-panel" key={epic.id}><div className="epic-heading"><Layers3 size={16} /><div><h3>{epic.title}</h3><p>{epic.description}</p></div><span className="count">{plan.tasks.filter(task => task.epic_id === epic.id).length}</span></div>
          {plan.tasks.filter(task => task.epic_id === epic.id).map(task => <button className="engineering-task-row" key={task.id} onClick={() => setSelected(task.id)}><span className="task-key">{task.key}</span><strong>{task.title}</strong><span className={`priority priority-${task.priority}`}>{task.priority}</span><span>{task.technical_area}</span><span>{hours(task.estimated_hours)}</span><ArrowRight size={14} /></button>)}
        </section>)}</div>}
        {!board && !!plan.assumptions.length && <details className="plan-assumptions"><summary>Planning assumptions · {plan.assumptions.length}</summary><ul>{plan.assumptions.map((item, index) => <li key={index}>{item}</li>)}</ul></details>}
      </> : <div className="planning-placeholder"><Layers3 size={22} /><div><strong>No project plan yet</strong><p>{board ? 'Create a plan to organize engineering tasks on this board.' : 'Describe a goal above to generate your first plan.'}</p>{board && <button className="button quiet" onClick={() => lab.setView('planning')}>Go to planning <ArrowRight size={14} /></button>}</div></div>}
    {selectedTask && plan && <TaskDetail task={selectedTask} tasks={plan.tasks} changing={changing} error={error} onClose={() => setSelected(null)} onStatus={status => void changeStatus(selectedTask, status)} onDependency={setSelected} onTaskChange={updateTask} />}
  </div>;
}

export function TaskDetail({ task, tasks, changing, error, onClose, onStatus, onDependency, onTaskChange }: { task: EngineeringTask; tasks: EngineeringTask[]; changing: boolean; error: string | null; onClose: () => void; onStatus: (status: EngineeringStatus) => void; onDependency: (id: string) => void; onTaskChange: (task: EngineeringTask) => void }) {
  const [executionActive,setExecutionActive]=useState(false);
  const closeButton = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose); onCloseRef.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    closeButton.current?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCloseRef.current();
      if (event.key === 'Tab') {
        const controls = closeButton.current?.closest('[role="dialog"]')?.querySelectorAll<HTMLElement>('button:not(:disabled),select:not(:disabled),input:not(:disabled),textarea:not(:disabled)');
        if (!controls?.length) return;
        const first = controls[0], last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    window.addEventListener('keydown', key);
    return () => { window.removeEventListener('keydown', key); previous?.focus(); };
  }, []);
  return <div className="modal-backdrop task-detail-backdrop" onClick={onClose}><section className="task-detail" role="dialog" aria-modal="true" aria-labelledby="engineering-task-title" onClick={e => e.stopPropagation()}>
    <header><span className="task-key">{task.key}</span><button ref={closeButton} className="text-button" aria-label="Close task detail" onClick={onClose}><X size={19} /></button></header>
    <h2 id="engineering-task-title">{task.title}</h2><p className="task-description">{task.description}</p>
    {error && <div className="product-error" role="alert">{error}</div>}
    <dl className="task-properties"><div><dt>Status</dt><dd><select aria-label="Task status" disabled={changing || !!task.execution_run_id} value={task.status} onChange={e => onStatus(e.target.value as EngineeringStatus)}>{boardColumns.map(column => <option key={column.status} value={column.status}>{column.label}</option>)}</select></dd></div>
      <div><dt>Priority</dt><dd className={`priority priority-${task.priority}`}>{task.priority}</dd></div><div><dt>Estimated effort</dt><dd>{hours(task.estimated_hours)}</dd></div><div><dt>Technical area</dt><dd>{task.technical_area}</dd></div></dl>
    {!!task.execution_run_id && <p className="small muted">Linked task status follows its execution and human acceptance.</p>}
    <TaskAssignmentEditor task={task} onChange={onTaskChange} locked={executionActive}/>
    <TaskExecutionPanel task={task} onChange={onTaskChange} onActiveChange={setExecutionActive}/>
    <h3>Dependencies</h3>{task.dependencies.length ? <div className="task-dependencies">{task.dependencies.map(dependency => { const target = tasks.find(item => item.id === dependency.task_id); return <button className="dependency-link" key={dependency.task_id} onClick={() => onDependency(dependency.task_id)}>{target?.key} · {target?.title}<ArrowRight size={13} /></button>; })}</div> : <p className="muted small">No dependencies</p>}
    <h3>Acceptance criteria</h3><ul className="acceptance-list">{task.acceptance_criteria.map((criterion, index) => <li key={index}><span className="criterion-box" aria-hidden="true" />{criterion.description}</li>)}</ul>
    <p className="estimate-notice">Estimates describe rough effort. Acceptance criteria are requirements, not completed checks.</p>
  </section></div>;
}
