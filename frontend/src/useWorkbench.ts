import { useEffect, useRef, useState } from 'react';
import * as api from './api';
import type { Agent, Project, Snapshot, Status, View } from './types';
import { agents } from './types';
import { previewSnapshot, previewProject, previewFiles } from './preview';
const initialProjects: Project[] = [
  { id: 'system', name: 'engineering-system', path: '.', description: 'Multi-agent platform', stack: ['Python', 'FastAPI', 'LangGraph'] },
  { id: 'greeting', name: 'developer-demo', path: 'examples/developer-demo', description: 'A focused local demonstration', stack: ['Python'] },
];
const operationAgents = new Map(agents.map(agent => [agent.operation, agent.id]));
operationAgents.set('route_validation', 'supervisor');
export default function useWorkbench() {
  const [view, setView] = useState<View>('projects');
  const [preview, setPreview] = useState(true);
  const [projects, setProjects] = useState<Project[]>(initialProjects);
  const [project, setProject] = useState<Project>(initialProjects[1]);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [filePaths, setFilePaths] = useState<string[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<Agent>('planner');
  const [activeAgent, setActiveAgent] = useState<Agent | null>(null);
  const [runTests, setRunTests] = useState(true);
  const [testBackend, setTestBackend] = useState<'docker' | 'local'>('docker');
  const [framework, setFramework] = useState<'unittest' | 'pytest' | 'npm'>('unittest');
  const [maxAttempts, setMaxAttempts] = useState(3);
  const [approvalId, setApprovalId] = useState<string | null>(null);
  const [busy, setBusy] = useState<'planning' | 'development' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [previewIndex, setPreviewIndex] = useState<number | null>(null);
  const [taskModal, setTaskModal] = useState(false);
  const [sessionRuns, setSessionRuns] = useState<Snapshot[]>([]);
  const [currentJob, setCurrentJob] = useState<api.Job | null>(null);
  const [activeTask, setActiveTask] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<Record<string, number | string | null> | null>(null);
  const [system, setSystem] = useState<Awaited<ReturnType<typeof api.system>> | null>(null);
  const [delivery, setDelivery] = useState<{ action: 'export' | 'apply' | 'github'; evidence: api.Delivery } | null>(null);
  const [deliveryResult, setDeliveryResult] = useState<{ url?: string; commit?: string; applied_files?: string[] } | null>(null);
  const latestTask = useRef<string | null>(null);
  async function refreshFiles(id: string) {
    try { const result = await api.files(id); if (latestTask.current === id) setFilePaths(result.files); }
    catch { /* A queued task has no workspace yet. */ }
  }
  function accept(item: api.Job) {
    setCurrentJob(item); setSnapshot(item.snapshot); latestTask.current = item.id;
    const savedDelivery = item.delivery.github ?? item.delivery.export ?? item.delivery.apply;
    if (savedDelivery && typeof savedDelivery === 'object') setDeliveryResult(savedDelivery as { url?: string; commit?: string; applied_files?: string[] });
    setApprovalId(item.phase === 'awaiting_approval' ? item.approval : null);
    setBusy(['queued_planning', 'planning'].includes(item.phase) ? 'planning' : ['queued_development', 'development'].includes(item.phase) ? 'development' : null);
    const agent = item.node ? operationAgents.get(item.node) : undefined;
    setActiveAgent(agent ?? null); if (agent) setSelectedAgent(agent);
    setSessionRuns(runs => [item.snapshot, ...runs.filter(run => run.task.task_id !== item.id)].slice(0, 100));
    if (item.snapshot.workspace_path) void refreshFiles(item.id);
  }
  useEffect(() => { let alive = true;
    async function load() {
      try {
        const [registered, history, stats, service] = await Promise.all([api.projects(), api.jobs(), api.evaluation(), api.system()]);
        if (!alive) return;
        let saved = registered.projects;
        if (!saved.length) { saved = []; for (const p of initialProjects) saved.push(await api.register(p.name, p.path)); }
        if (!alive) return;
        setProjects(saved); setProject(saved.find(p => p.name === 'developer-demo') ?? saved[0] ?? initialProjects[1]);
        setSessionRuns(history.tasks.map(item => item.snapshot)); setMetrics(stats); setSystem(service); setConnected(true);
        const remembered = localStorage.getItem('engineering-active-task');
        const item = history.tasks.find(t => t.id === remembered);
        if (item) { setProject(saved.find(p => p.path === item.snapshot.task.request.repository_path) ?? saved[0]); setPreview(false); setActiveTask(item.id); }
      } catch (failure) { if (alive) { setConnected(false); setError((failure as Error).message); } }
    } void load(); return () => { alive = false; };
  }, []);
  useEffect(() => {
    if (!activeTask) return;
    latestTask.current = activeTask; localStorage.setItem('engineering-active-task', activeTask);
    let alive = true, timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const item = await api.job(activeTask!); if (alive) { accept(item); setConnected(true); }
        if (alive && ['succeeded', 'failed', 'cancelled', 'awaiting_approval'].includes(item.phase)) { setMetrics(await api.evaluation()); timer = setTimeout(poll, 4000); }
        else if (alive) timer = setTimeout(poll, 1000);
      } catch (failure) { if (alive) { setConnected(false); setError((failure as Error).message); timer = setTimeout(poll, 4000); } }
    } void poll(); return () => { alive = false; clearTimeout(timer); };
  }, [activeTask]);
  useEffect(() => {
    if (previewIndex === null) return;
    if (previewIndex >= previewSnapshot.executions.length) { setPreviewIndex(null); return; }
    setSelectedAgent(previewSnapshot.executions[previewIndex].agent as Agent);
    const timer = setTimeout(() => setPreviewIndex(index => index === null ? null : index + 1), 1300);
    return () => clearTimeout(timer);
  }, [previewIndex]);
  const displayed = preview ? previewIndex === null ? previewSnapshot : { ...previewSnapshot, executions: previewSnapshot.executions.slice(0, previewIndex), task: { ...previewSnapshot.task, status: 'running' }, tests: null, review: null, report: null } : snapshot?.task.request.repository_path === project.path ? snapshot : null;
  const currentProject = preview ? previewProject : project;
  const currentFiles = preview ? previewFiles : displayed ? filePaths : [];
  const runningAgent = preview && previewIndex !== null ? previewSnapshot.executions[previewIndex]?.agent as Agent : activeAgent;
  function agentStatus(agent: Agent): Status {
    if (runningAgent === agent) return 'running';
    const last = displayed?.executions.filter(record => record.agent === agent && record.operation === agents.find(a => a.id === agent)?.operation).at(-1);
    if (agent === 'tester' && displayed?.tests?.outcome === 'skipped') return 'skipped';
    if (last) return last.status === 'succeeded' ? 'succeeded' : 'failed';
    if (!preview && agent === 'developer' && approvalId) return 'approval';
    if (!preview && agent === 'reviewer' && displayed?.tests?.outcome && displayed.tests.outcome !== 'passed') return 'skipped';
    return 'waiting';
  }
  async function start(path: string, task: string) {
    if (busy) return;
    setBusy('planning');
    setError(null); setPreview(false); setPreviewIndex(null); setView('workspace'); setTaskModal(false); setFilePaths([]); setApprovalId(null); setDeliveryResult(null);
    try { const result = await api.create(path, task); setProject(result.project); setProjects(current => [result.project, ...current.filter(p => p.path !== result.project.path)]); setActiveTask(result.id); accept(await api.job(result.id)); }
    catch (failure) { setBusy(null); setError((failure as Error).message); }
  }
  async function approve() {
    if (!activeTask || !approvalId || preview || busy) return;
    try { await api.approve(activeTask, { approval_id: approvalId, run_tests: runTests, test_backend: testBackend, framework, max_attempts: maxAttempts }); setApprovalId(null); accept(await api.job(activeTask)); }
    catch (failure) { setError((failure as Error).message); }
  }
  async function register(name: string, path: string) {
    try { const added = await api.register(name, path); setProjects(current => [added, ...current.filter(p => p.path !== added.path)]); setProject(added); setPreview(false); }
    catch (failure) { setError((failure as Error).message); }
  }
  async function importRepository(repository: string, branch?: string) {
    try { const added = await api.importRepository(repository, branch); setProjects(current => [added, ...current]); setProject(added); setPreview(false); }
    catch (failure) { setError((failure as Error).message); }
  }
  function openProject(next: Project) { setProject(next); setPreview(next.id === 'preview'); setView('workspace'); }
  function inspectRun(run: Snapshot) {
    if (!preview) { setProject(projects.find(p => p.path === run.task.request.repository_path) ?? project); setActiveTask(run.task.task_id); }
    setView('results');
  }
  async function cancel() { if (activeTask) { try { await api.cancel(activeTask); } catch (failure) { setError((failure as Error).message); } } }
  async function retry() { if (activeTask) { try { const item = await api.retry(activeTask); setProject(item.project); setActiveTask(item.id); setView('workspace'); } catch (failure) { setError((failure as Error).message); } } }
  async function prepareDelivery(action: 'export' | 'apply' | 'github') {
    if (activeTask && !preview) { try { const evidence = await api.prepareDelivery(activeTask); setDelivery({ action, evidence }); } catch (failure) { setError((failure as Error).message); } }
  }
  async function confirmDelivery() {
    if (!delivery || !activeTask) return;
    try { const result = await api.deliver(activeTask, delivery.evidence.receipt, delivery.action); setDeliveryResult(result);
      if (delivery.action === 'export') { const link = document.createElement('a'); link.href = `/tasks/${activeTask}/archive`; link.download = ''; link.click(); }
      setDelivery(null);
    } catch (failure) { setError((failure as Error).message); }
  }
  return { view, setView, preview, setPreview, projects, project, setProject, currentProject, displayed, currentFiles, selectedAgent, setSelectedAgent, runningAgent, agentStatus, busy, error, setError, connected, approvalId, approve, runTests, setRunTests, testBackend, setTestBackend, framework, setFramework, maxAttempts, setMaxAttempts, taskModal, setTaskModal, start, register, importRepository, openProject, inspectRun, sessionRuns, currentJob, metrics, system, cancel, retry, prepareDelivery, delivery, setDelivery, confirmDelivery, deliveryResult, previewIndex, replay: () => { setPreviewIndex(0); setView('workspace'); } };
}
export type Workbench = ReturnType<typeof useWorkbench>;
