import { invoke } from '@tauri-apps/api/core';

export const native = '__TAURI_INTERNALS__' in window;
let connection: Promise<{url: string; token: string}>;
function config() {
  connection ??= native ? invoke('backend_connection') : Promise.resolve({ url: '', token: import.meta.env.VITE_API_TOKEN || '' });
  return connection;
}
export async function request(path: string, options: RequestInit = {}) {
  const c = await config();
  const response = await fetch(c.url + '/api' + path, { ...options, headers: { Authorization: 'Bearer ' + c.token, ...options.headers } });
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(typeof error?.detail === 'string' ? error.detail : `请求失败（${response.status}）`);
  }
  return response;
}
export async function json<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  return (await request(path, options)).json();
}
export function post(body: unknown): RequestInit {
  return { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}
export async function download(blob: Blob, name: string) {
  if (native) {
    return invoke<boolean>('save_xmp', { contents: await blob.text(), name });
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return true;
}
