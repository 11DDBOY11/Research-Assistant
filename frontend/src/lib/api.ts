// lib/api.ts — Typed API client for all backend endpoints

const BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options?.headers ?? {}) },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

// ── Upload ────────────────────────────────────────────────────────────────────

export async function uploadLiterature(files: File[]) {
  const form = new FormData();
  files.forEach(f => form.append('files', f));
  const res = await fetch(`${BASE}/api/upload/literature`, { method: 'POST', body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Upload failed');
  }
  return res.json();
}

export async function uploadProject(file: File) {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${BASE}/api/upload/project`, { method: 'POST', body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Upload failed');
  }
  return res.json();
}

export async function getUploadStatus() {
  return apiFetch<{
    literature_count: number;
    project_count: number;
    max_literature: number;
    ready_to_run: boolean;
    literature_files: { id: number; filename: string; status: string }[];
  }>('/api/upload/status');
}

export async function resetSession() {
  return apiFetch('/api/upload/reset', { method: 'DELETE' });
}

// ── Pipeline ──────────────────────────────────────────────────────────────────

export async function startPipeline() {
  return apiFetch<{ run_id: string; message: string }>('/api/pipeline/start', { method: 'POST' });
}

export function subscribeToPipeline(
  runId: string,
  onEvent: (event: import('./types').PipelineEvent) => void,
  onError: (err: string) => void,
): () => void {
  const es = new EventSource(`${BASE}/api/pipeline/stream/${runId}`);
  es.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data.error) { onError(data.error); es.close(); return; }
      onEvent(data);
      if (data.done) es.close();
    } catch { /* ignore parse errors */ }
  };
  es.onerror = () => { onError('Connection lost'); es.close(); };
  return () => es.close();
}

// ── Clarifications ────────────────────────────────────────────────────────────

export async function getClarifications() {
  return apiFetch<{ count: number; clarifications: import('./types').ClarificationRequest[] }>(
    '/api/extract/clarifications'
  );
}

export async function submitClarification(id: number, response: string) {
  return apiFetch(`/api/extract/clarifications/${id}?response=${encodeURIComponent(response)}`, {
    method: 'POST',
  });
}

// ── Output ────────────────────────────────────────────────────────────────────

export async function getPaperPreview() {
  return apiFetch<import('./types').PaperPreviewData>('/api/output/preview');
}

export function getDownloadUrl() {
  return `${BASE}/api/output/download`;
}

export async function getTransparencyReport() {
  return apiFetch<import('./types').TransparencyReport>('/api/output/transparency');
}
