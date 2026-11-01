import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import path from 'node:path';
const env = { ...process.env, RAW_STUDIO_TOKEN: randomBytes(32).toString('hex') };
const python = path.resolve('.venv/Scripts/python.exe');
const backend = spawn(python, ['-m', 'backend.server', '--port', '18763'], { env, stdio: ['ignore', 'pipe', 'inherit'], windowsHide: true });
const frontend = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5173', '--strictPort'], { env, stdio: 'inherit', windowsHide: true });
backend.stdout.on('data', () => {}); // Readiness contains a session token; never print it.
let exiting = false;
function close(code = 0) { if (exiting) return; exiting = true; backend.kill(); frontend.kill(); process.exit(code); }
backend.on('error', e => { console.error('后端启动失败：', e.message); close(1); });
frontend.on('error', e => { console.error('界面启动失败：', e.message); close(1); });
backend.on('exit', code => close(code || 0));
frontend.on('exit', code => close(code || 0));
process.on('SIGINT', () => close());
process.on('SIGTERM', () => close());
