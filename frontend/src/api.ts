import type { FileList, Project, Snapshot } from './types';
import { apiFetch } from './transport';
export interface Job { id: string; revision?:number; created?:number; engineering_origin?:{engineering_task_id:string}|null; artifacts_loaded?:boolean; phase: string; node: string | null; approval: string | null; snapshot: Snapshot; cancel: number; options: { test_backend: string; framework: string; max_attempts: number }; delivery: Record<string, unknown> }
export interface Delivery { receipt: string; files: string[]; diff: string; github_available: boolean; github?: { slug: string; base: string }; delivery: Record<string, unknown> }
async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await apiFetch(path, body === undefined ? { cache: 'no-store' } : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(typeof error.detail === 'string' ? error.detail : `Request failed (${response.status}).`); }
  return response.json();
}
export const jobs = () => request<{ tasks: Job[] }>('/tasks?details=false');
export const job = (id: string, details=true) => request<Job>(`/tasks/${id}${details?'':'?details=false'}`);
export const create = (path: string, task: string) => request<{ id: string; project: Project }>('/tasks', { repository_path: path, user_request: task });
export const approve = (id: string, options: object) => request(`/tasks/${id}/approve`, options);
export const cancel = (id: string) => request(`/tasks/${id}/cancel`, {});
export const retry = (id: string) => request<{ id: string; project: Project }>(`/tasks/${id}/retry`, {});
export const projects = () => request<{ projects: Project[] }>('/projects');
export const register = (name: string, path: string) => request<Project>('/projects', { name, path });
export const importRepository = (repository: string, branch?: string) => request<Project>('/projects/import', { repository, branch });
export const files = (id: string) => request<FileList>(`/tasks/${id}/files`);
export const source = (id: string, path: string) => request<{ content: string }>(`/tasks/${id}/file?path=${encodeURIComponent(path)}`);
export const prepareDelivery = (id: string) => request<Delivery>(`/tasks/${id}/delivery`);
export const deliver = (id: string, receipt: string, action: string) => request<{ url?: string; commit?: string; applied_files?: string[] }>(`/tasks/${id}/delivery`, { receipt, action });
export const evaluation = () => request<Record<string, number | string | null>>('/evaluation');
export const system = () => request<{ database: string; model: string | null; test_backend: string; github_configured: boolean; git_available: boolean; docker_available: boolean }>('/system/status');
