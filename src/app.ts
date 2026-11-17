/** 极简 hash 路由与全局 Toast，无第三方框架依赖。 */

import { materialsPage } from './pages/materials';
import { packagerPage } from './pages/packager';
import { keysPage } from './pages/keys';
import { studentsPage } from './pages/students';
import { playerPage } from './pages/player';
import { tracePage } from './pages/trace';

export type Route =
  | 'materials'
  | 'packager'
  | 'keys'
  | 'students'
  | 'player'
  | 'trace';

const ROUTES: { id: Route; label: string; icon: string; desc: string }[] = [
  { id: 'materials', label: '课程素材', icon: '🎬', desc: '生成或导入 fMP4 分片素材' },
  { id: 'packager', label: '加密打包', icon: '🔐', desc: 'CENC cbcs 加密、哈希、分片清单' },
  { id: 'keys', label: '密钥管理', icon: '🗝️', desc: '每课程 KID/CEK/IV 与水印种子' },
  { id: 'students', label: '学员授权', icon: '🎫', desc: '学员、到期时间、吊销与 .lic 签发' },
  { id: 'player', label: '播放端', icon: '▶️', desc: 'ClearKey EME 授权播放与漂移水印' },
  { id: 'trace', label: '水印溯源', icon: '🔍', desc: '泄露截图按水印位置反查学员' },
];

export function currentRoute(): Route {
  const h = location.hash.replace('#/', '').split('?')[0] as Route;
  return ROUTES.some((r) => r.id === h) ? h : 'materials';
}

export function navigate(route: Route): void {
  location.hash = `#/${route}`;
}

export function renderApp(): void {
  const route = currentRoute();
  const meta = ROUTES.find((r) => r.id === route)!;
  const app = document.getElementById('app')!;
  app.innerHTML = `
    <div class="layout">
      <aside class="sidebar">
        <div class="brand">CourseGuard<small>本地 CENC/cbcs · ClearKey</small></div>
        ${ROUTES.map((r) => `
          <div class="nav-item ${r.id === route ? 'active' : ''}" data-route="${r.id}">
            <span>${r.icon}</span><span>${r.label}</span>
          </div>`).join('')}
        <div style="margin-top:24px; padding:10px; font-size:11px; color:var(--text-faint); line-height:1.7">
          全流程浏览器本地完成<br/>密钥与分片不离开本机
        </div>
      </aside>
      <main class="main">
        <h1 class="page-title">${meta.icon} ${meta.label}</h1>
        <p class="page-sub">${meta.desc}</p>
        <div id="page-root"></div>
      </main>
    </div>
    <div class="toast-wrap" id="toast-wrap"></div>
  `;
  app.querySelectorAll<HTMLElement>('.nav-item').forEach((el) => {
    el.addEventListener('click', () => navigate(el.dataset.route as Route));
  });
  const root = document.getElementById('page-root')!;
  const renderers: Record<Route, (el: HTMLElement) => void | Promise<void>> = {
    materials: materialsPage,
    packager: packagerPage,
    keys: keysPage,
    students: studentsPage,
    player: playerPage,
    trace: tracePage,
  };
  void renderers[route](root);
}

export function toast(message: string, kind: 'ok' | 'err' | 'info' = 'info', ms = 3200): void {
  const wrap = document.getElementById('toast-wrap');
  if (!wrap) return;
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.textContent = message;
  wrap.appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transition = 'opacity 0.3s';
    setTimeout(() => el.remove(), 320);
  }, ms);
}

export function download(filename: string, content: Blob | string, mime = 'application/octet-stream'): void {
  const blob = typeof content === 'string' ? new Blob([content], { type: mime }) : content;
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function readFileBytes(file: File): Promise<Uint8Array> {
  return file.arrayBuffer().then((b) => new Uint8Array(b));
}

export function readFileText(file: File): Promise<string> {
  return file.text();
}

export function esc(s: unknown): string {
  return String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
