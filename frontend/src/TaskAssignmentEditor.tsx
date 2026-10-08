import { useEffect, useState } from 'react';
import { Bot, UserRound } from 'lucide-react';
import type { EngineeringTask } from './productTypes';
import type { TeamSnapshot, TaskRecommendations } from './teamTypes';
import * as teams from './teamApi';
import { AssignmentWarning } from './productApi';

export default function TaskAssignmentEditor({ task, onChange, locked=false, aiDevelopersOnly=false, onResources }: { aiDevelopersOnly?:boolean; onResources?:(data:TeamSnapshot)=>void; task: EngineeringTask; onChange: (task: EngineeringTask) => void; locked?: boolean }) {
  const [data, setData] = useState<TeamSnapshot | null>(null);
  const [squadId, setSquadId] = useState(task.squad_id ?? '');
  const [memberId, setMemberId] = useState(task.assignee_id ?? '');
  const [recommendations, setRecommendations] = useState<TaskRecommendations | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    setData(null); setError(null);
    teams.getTeams(task.project_id).then(result => { if (alive) {setData(result);onResources?.(result);} }).catch(e => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [task.project_id]);
  useEffect(() => { setSquadId(task.squad_id ?? ''); setMemberId(task.assignee_id ?? ''); setWarnings([]); setRecommendations(null); }, [task.id, task.revision]);
  const visibleRecommendations=recommendations?.recommendations.filter(option=>!aiDevelopersOnly||data?.members.some(member=>member.id===option.member_id&&member.member_type==='ai'&&member.future_execution_role==='developer'))??[];
  async function save(override = false, remove = false) {
    setBusy(true); setError(null);
    try {
      const result = remove ? await teams.unassignTask(task) : await teams.assignTask(task, squadId, memberId, override);
      onChange(result.task); setWarnings([]); setRecommendations(null);
      const resources=await teams.getTeams(task.project_id);setData(resources);onResources?.(resources);
    } catch (e) { if (e instanceof AssignmentWarning) setWarnings(e.warnings); else setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function recommend() {
    setBusy(true); setError(null);
    try { setRecommendations(await teams.getRecommendations(task.id)); const resources=await teams.getTeams(task.project_id);setData(resources);onResources?.(resources); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <section className="task-assignment-editor"><h3>Assignment</h3>
    <p className="small muted">{locked?'Ownership is locked while execution is active. Cancel and wait before reassigning. ':''}Choose a planned owner. Assigning an AI member does not start execution.</p>
    {error && <p role="alert" className="product-error">{error}</p>}
    {data ? <><div className="assignment-fields"><label>Squad<select aria-label="Task squad" value={squadId} disabled={busy || locked} onChange={e => { setSquadId(e.target.value); setMemberId(''); setWarnings([]); }}><option value="">Unassigned</option>{data.squads.map(squad => <option key={squad.id} value={squad.id}>{squad.name}</option>)}</select></label>
      <label>{aiDevelopersOnly?'AI developer':'Assignee'}<select aria-label="Task assignee" value={memberId} disabled={busy || locked} onChange={e => { const joined = data.memberships.find(item => item.member_id === e.target.value); setMemberId(e.target.value); if (joined) setSquadId(joined.squad_id); setWarnings([]); }}><option value="">Unassigned</option>{data.members.filter(member => (!aiDevelopersOnly||member.member_type==='ai'&&member.future_execution_role==='developer'||member.id===task.assignee_id)).filter(member => data.memberships.some(joined => joined.member_id === member.id && joined.active && (!squadId || joined.squad_id === squadId)) || member.id === task.assignee_id).map(member => <option key={member.id} value={member.id}>{member.name} · {member.member_type === 'ai' ? 'AI' : 'Human'}{!member.active ? ' · inactive' : ''}</option>)}</select></label></div>
      <div className="assignment-actions"><button className="button quiet" disabled={busy || locked || (!squadId && !memberId)} onClick={() => void save()}>Save assignment</button>{(task.squad_id || task.assignee_id) && <button className="text-button" disabled={busy || locked} onClick={() => void save(false, true)}>Remove assignment</button>}{!task.assignee_id && task.status !== 'done' && <button className="text-button" disabled={busy || locked} onClick={() => void recommend()}>View recommendations</button>}</div>
      {!data.squads.length && <p className="small muted">Create a squad and members in Teams to assign work.</p>}
      {!!warnings.length && <div className="assignment-warnings" role="alert"><strong>Review before assigning</strong><ul>{warnings.map((warning,i) => <li key={i}>{warning}</li>)}</ul><button className="button quiet" disabled={busy || locked} onClick={() => void save(true)}>Assign despite these warnings</button></div>}
      {recommendations && <div className="recommendation-list"><h4>Recommended assignees</h4>{!visibleRecommendations.length && <p className="small muted">No active, available members with a matching skill in this squad.</p>}{visibleRecommendations.map(option => {
        const member = data.members.find(item => item.id === option.member_id);
        const capacity=data.capacities.find(item=>item.member_id===option.member_id);
        return <div className="recommendation-row" key={option.member_id}><div className="member-identity">{member?.member_type === 'ai' ? <Bot size={16} /> : <UserRound size={16} />}<strong>{member?.name}</strong><span>{option.fits_capacity ? 'Fits capacity' : 'Capacity warning'}</span></div>{member?.member_type==='ai'&&<p className="small muted">{member.availability??'Availability unknown'}{capacity?.active_execution_count!=null&&capacity.max_concurrent_executions!=null?` · Runtime ${capacity.active_execution_count} / ${capacity.max_concurrent_executions}`:''}{capacity?.assigned_queue_depth!=null?` · Queued work ${capacity.assigned_queue_depth}`:''}</p>}<ul>{option.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>{!!option.warnings.length && <ul className="capacity-warning">{option.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>}<button className="text-button" onClick={() => { setSquadId(option.squad_id); setMemberId(option.member_id); setWarnings([]); }}>Select assignee</button></div>;
      })}</div>}
    </> : <p className="small muted">Loading team resources…</p>}
  </section>;
}
