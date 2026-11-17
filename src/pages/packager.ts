/** 加密打包页：素材 → CENC cbcs → 分片加密信息表 → .cpkg 导出 */

import { PackageManifest, SegmentCryptoInfo } from '../types';
import { storage } from '../lib/storage';
import { packageCourse, exportPackageFile, DEFAULT_WATERMARK, PackageProgress } from '../lib/packager';
import { download, esc, toast } from '../app';
import { formatBytes, formatTime } from '../lib/util';

export async function packagerPage(root: HTMLElement): Promise<void> {
  const materials = await storage.listMaterials();
  const packages = await storage.listPackages();

  root.innerHTML = `
    <div class="card">
      <h3>① 选择素材并打包</h3>
      ${materials.length === 0
        ? '<div class="empty">请先到「课程素材」页入库或导入 fMP4 素材</div>'
        : `<div class="grid cols-2">
             <div>
               <label>素材</label>
               <select id="pkg-material">
                 ${materials.map((m) => `<option value="${esc(m.materialId)}">${esc(m.name)}（${formatBytes(m.bytes.length)}）</option>`).join('')}
               </select>
             </div>
             <div>
               <label>课程标题</label>
               <input id="pkg-title" value="职业培训课程 ${new Date().toLocaleDateString()}" />
             </div>
             <div>
               <label>水印漂移间隔（秒）</label>
               <input id="pkg-interval" type="number" min="3" max="60" value="${DEFAULT_WATERMARK.moveIntervalSec}" />
             </div>
             <div>
               <label>水印透明度（0~1）</label>
               <input id="pkg-opacity" type="number" min="0.1" max="0.9" step="0.05" value="${DEFAULT_WATERMARK.opacity}" />
             </div>
           </div>
           <div class="row end" style="margin-top:14px">
             <button class="primary" id="pkg-run">🔐 开始 CENC cbcs 加密打包</button>
           </div>
           <div id="pkg-progress" style="display:none">
             <div class="progress-bar"><div id="pkg-bar" style="width:0%"></div></div>
             <div id="pkg-phase" class="file-hint"></div>
           </div>
           <div class="log" id="pkg-log" style="display:none;margin-top:12px"></div>`}
    </div>
    <div class="card">
      <h3>② 已打包课程（${packages.length}）</h3>
      <div id="pkg-existing">${renderExisting(packages)}</div>
    </div>
    <div class="card" id="pkg-detail-card" style="display:none">
      <h3>③ 分片加密信息（sinf/tenc/senc/saiz/saio 已写入，逐片 SHA-256）</h3>
      <div id="pkg-detail"></div>
    </div>`;

  const logEl = root.querySelector('#pkg-log') as HTMLElement | null;
  const log = (msg: string, cls = 'dim'): void => {
    if (!logEl) return;
    logEl.style.display = 'block';
    const line = document.createElement('div');
    line.className = cls;
    line.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
    logEl.appendChild(line);
    logEl.scrollTop = logEl.scrollHeight;
  };

  const runBtn = root.querySelector<HTMLButtonElement>('#pkg-run');
  runBtn?.addEventListener('click', async () => {
    const matId = (root.querySelector('#pkg-material') as HTMLSelectElement).value;
    const material = materials.find((m) => m.materialId === matId)!;
    const title = (root.querySelector('#pkg-title') as HTMLInputElement).value || material.name;
    const interval = Number((root.querySelector('#pkg-interval') as HTMLInputElement).value);
    const opacity = Number((root.querySelector('#pkg-opacity') as HTMLInputElement).value);

    runBtn.disabled = true;
    const prog = root.querySelector('#pkg-progress') as HTMLElement;
    const bar = root.querySelector('#pkg-bar') as HTMLElement;
    const phase = root.querySelector('#pkg-phase') as HTMLElement;
    prog.style.display = 'block';
    logEl && (logEl.innerHTML = '');
    log(`开始打包：${material.name}`, 'info');

    const onProgress = (p: PackageProgress): void => {
      bar.style.width = `${(p.current / p.total) * 100}%`;
      phase.textContent = `${p.phase}（${p.current}/${p.total}）`;
      log(p.phase);
    };
    try {
      const result = await packageCourse(material.bytes, material.name, {
        title,
        watermark: { ...DEFAULT_WATERMARK, moveIntervalSec: interval, opacity },
        onProgress,
      });
      bar.style.width = '100%';
      log(`打包完成：courseId=${result.manifest.courseId}`, 'ok');
      log(`分片数=${result.manifest.segments.length}（1 init + ${result.manifest.segments.length - 1} 媒体）`, 'ok');
      const encTotal = result.manifest.segments.reduce((n, s) => n + s.encryptedBytes, 0);
      log(`AES-CBC 实际加密字节=${formatBytes(encTotal)}，方案=cbcs，视频 pattern=1/9`, 'ok');
      toast('加密打包完成', 'ok');
      showDetail(result.manifest);
      setTimeout(() => void reload(), 600);
    } catch (e) {
      log(`打包失败：${(e as Error).message}`, 'err');
      toast((e as Error).message, 'err');
    } finally {
      runBtn.disabled = false;
    }
  });

  function showDetail(manifest: PackageManifest): void {
    const card = root.querySelector('#pkg-detail-card') as HTMLElement;
    const detail = root.querySelector('#pkg-detail') as HTMLElement;
    card.style.display = 'block';
    detail.innerHTML = renderManifestDetail(manifest);
    detail.querySelector<HTMLElement>('#pkg-export')?.addEventListener('click', async () => {
      const file = await exportPackageFile(manifest);
      download(`${manifest.courseId}.cpkg`, JSON.stringify(file), 'application/json');
      toast('已导出 .cpkg（不含 CEK，播放仍需授权）', 'ok');
    });
  }

  async function reload(): Promise<void> {
    const fresh = await storage.listPackages();
    root.querySelector('#pkg-existing')!.innerHTML = renderExisting(fresh);
    bindExisting(root);
  }
  bindExisting(root);
}

function bindExisting(root: HTMLElement): void {
  root.querySelectorAll<HTMLElement>('[data-view]').forEach((b) =>
    b.addEventListener('click', async () => {
      const m = await storage.getPackage(b.dataset.view!);
      if (m) {
        const card = root.querySelector('#pkg-detail-card') as HTMLElement;
        card.style.display = 'block';
        card.scrollIntoView({ behavior: 'smooth' });
        root.querySelector('#pkg-detail')!.innerHTML = renderManifestDetail(m);
        root.querySelector<HTMLElement>('#pkg-export')?.addEventListener('click', async () => {
          const file = await exportPackageFile(m);
          download(`${m.courseId}.cpkg`, JSON.stringify(file), 'application/json');
        });
      }
    }));
  root.querySelectorAll<HTMLElement>('[data-del-pkg]').forEach((b) =>
    b.addEventListener('click', async () => {
      if (!confirm(`确认删除课程包 ${b.dataset.delPkg}？其分片将一并清除（密钥保留）`)) return;
      await storage.deletePackage(b.dataset.delPkg!);
      toast('课程包已删除', 'ok');
      location.reload();
    }));
}

function renderExisting(packages: PackageManifest[]): string {
  if (packages.length === 0) return '<div class="empty"><div class="icon">📦</div>尚无已打包课程</div>';
  return `<table>
    <thead><tr><th>课程</th><th>courseId</th><th>分片</th><th>时长</th><th>创建时间</th><th></th></tr></thead>
    <tbody>${packages.map((p) => `
      <tr>
        <td><strong>${esc(p.title)}</strong></td>
        <td class="mono tiny">${esc(p.courseId)}</td>
        <td><span class="badge blue">${p.segments.length}</span></td>
        <td class="mono">${p.durationSec}s</td>
        <td class="mono">${formatTime(p.createdAt)}</td>
        <td class="row">
          <button class="small" data-view="${esc(p.courseId)}">分片详情</button>
          <button class="small danger" data-del-pkg="${esc(p.courseId)}">删除</button>
        </td>
      </tr>`).join('')}
    </tbody></table>`;
}

function renderManifestDetail(m: PackageManifest): string {
  const totalSize = m.segments.reduce((n, s) => n + s.encryptedSize, 0);
  return `
    <dl class="kv" style="margin-bottom:14px">
      <dt>courseId</dt><dd class="mono">${esc(m.courseId)}</dd>
      <dt>KID</dt><dd class="mono">${esc(m.kid)}</dd>
      <dt>常量 IV</dt><dd class="mono">${esc(m.iv)}</dd>
      <dt>水印种子</dt><dd class="mono tiny">${esc(m.watermarkSeed)}</dd>
      <dt>轨道</dt><dd>${m.tracks.map((t) => `<span class="badge purple">${esc(t.kind)} ${esc(t.mseCodec)}</span>`).join(' ')}</dd>
      <dt>加密方案</dt><dd><span class="badge green">cbcs</span> 视频 crypt=1/skip=9，音频全 sample，常量 IV</dd>
      <dt>总大小</dt><dd class="mono">${formatBytes(totalSize)}</dd>
    </dl>
    <div class="table-wrap" style="overflow-x:auto">
    <table>
      <thead><tr>
        <th>#</th><th>文件</th><th>类型</th><th>明文→密文</th><th>样本</th>
        <th>加密样本</th><th>子样本</th><th>加密字节</th><th>SHA-256（篡改 1 字节即不匹配）</th>
      </tr></thead>
      <tbody>${m.segments.map((s: SegmentCryptoInfo) => `
        <tr>
          <td class="mono">${s.index < 0 ? 'init' : s.index + 1}</td>
          <td class="mono">${esc(s.fileName)}</td>
          <td><span class="badge ${s.kind === 'init' ? 'amber' : 'blue'}">${s.kind}</span></td>
          <td class="mono">${formatBytes(s.clearSize)} → ${formatBytes(s.encryptedSize)}</td>
          <td class="mono">${s.sampleCount}</td>
          <td class="mono">${s.encryptedSamples}</td>
          <td class="mono">${s.subsampleCount}</td>
          <td class="mono">${formatBytes(s.encryptedBytes)}</td>
          <td class="mono tiny" title="${esc(s.sha256)}">${esc(s.sha256.slice(0, 24))}…</td>
        </tr>`).join('')}
      </tbody>
    </table>
    </div>
    <div class="row end" style="margin-top:14px">
      <button class="primary" id="pkg-export">⬇️ 导出 .cpkg 课程包</button>
    </div>`;
}
