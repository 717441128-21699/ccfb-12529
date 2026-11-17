/** 课程素材页：内置演示素材入库 / 外部 fMP4 导入 / 素材库管理 */

import { MaterialRecord } from '../types';
import { storage } from '../lib/storage';
import { parseFmp4 } from '../lib/mp4/fmp4';
import { download, esc, readFileBytes, toast } from '../app';
import { formatBytes, formatDuration } from '../lib/util';

const BUILTIN_SAMPLES = [
  { file: 'samples/demo-av.mp4', name: '演示课·视频+音频（12s 双轨）' },
  { file: 'samples/demo-video-only.mp4', name: '演示课·纯视频（8s）' },
  { file: 'samples/demo-slide.mp4', name: '演示课·PPT 静态画面（6s）' },
];

export async function materialsPage(root: HTMLElement): Promise<void> {
  root.innerHTML = `
    <div class="grid cols-2">
      <div class="card">
        <h3>① 内置演示素材（ffmpeg 生成的真实 fMP4）</h3>
        <div class="stack">
          ${BUILTIN_SAMPLES.map((s, i) => `
            <div class="row" style="justify-content:space-between">
              <div>
                <div>${esc(s.name)}</div>
                <div class="file-hint mono">${esc(s.file)}</div>
              </div>
              <button class="small primary" data-load="${i}">入库</button>
            </div>`).join('')}
        </div>
      </div>
      <div class="card">
        <h3>② 导入外部素材</h3>
        <p class="file-hint" style="margin-top:0">
          要求分片 MP4（fMP4，含 mvex/trex）。普通 MP4 可用
          <span class="mono">ffmpeg -movflags frag_keyframe+empty_moov+default_base_moof</span> 转换。
        </p>
        <input type="file" id="mat-import" accept=".mp4,.m4s,.m4v,video/mp4" />
        <div id="mat-import-status" class="file-hint" style="margin-top:8px"></div>
      </div>
    </div>
    <div class="card">
      <h3>素材库（IndexedDB）</h3>
      <div id="mat-list"><div class="empty"><div class="icon">📂</div>暂无素材，请先入库或导入</div></div>
    </div>`;

  const listEl = root.querySelector('#mat-list')!;
  const refresh = async (): Promise<void> => {
    const all = await storage.listMaterials();
    if (all.length === 0) {
      listEl.innerHTML = '<div class="empty"><div class="icon">📂</div>暂无素材，请先入库或导入</div>';
      return;
    }
    listEl.innerHTML = `
      <table>
        <thead><tr><th>名称</th><th>类型</th><th>分辨率/声道</th><th>时长</th><th>大小</th><th>materialId</th><th></th></tr></thead>
        <tbody>
          ${all.map((m) => `
            <tr>
              <td><strong>${esc(m.name)}</strong></td>
              <td><span class="badge blue">${esc(m.kind)}</span></td>
              <td class="mono">${m.width}×${m.height}${m.hasAudio ? ' · 含音频' : ''}</td>
              <td class="mono">${formatDuration(m.durationSec)}</td>
              <td class="mono">${formatBytes(m.bytes.length)}</td>
              <td class="mono tiny">${esc(m.materialId)}</td>
              <td class="row">
                <button class="small" data-dl="${esc(m.materialId)}">下载</button>
                <button class="small danger" data-del="${esc(m.materialId)}">删除</button>
              </td>
            </tr>`).join('')}
        </tbody>
      </table>`;
    listEl.querySelectorAll<HTMLElement>('[data-del]').forEach((b) =>
      b.addEventListener('click', async () => {
        await storage.deleteMaterial(b.dataset.del!);
        toast('素材已删除', 'ok');
        void refresh();
      }));
    listEl.querySelectorAll<HTMLElement>('[data-dl]').forEach((b) =>
      b.addEventListener('click', async () => {
        const m = all.find((x) => x.materialId === b.dataset.dl)!;
        download(`${m.materialId}.mp4`, new Blob([m.bytes as BlobPart], { type: 'video/mp4' }));
      }));
  };
  void refresh();

  root.querySelectorAll<HTMLElement>('[data-load]').forEach((btn) =>
    btn.addEventListener('click', async () => {
      const sample = BUILTIN_SAMPLES[Number(btn.dataset.load)];
      btn.setAttribute('disabled', 'true');
      try {
        const resp = await fetch(sample.file);
        const bytes = new Uint8Array(await resp.arrayBuffer());
        const rec = await ingestBytes(bytes, sample.name, 'demo-generated');
        toast(`已入库：${rec.name}（${rec.durationSec.toFixed(1)}s）`, 'ok');
        void refresh();
      } catch (e) {
        toast(`入库失败：${(e as Error).message}`, 'err');
      } finally {
        btn.removeAttribute('disabled');
      }
    }));

  const importInput = root.querySelector<HTMLInputElement>('#mat-import')!;
  const statusEl = root.querySelector('#mat-import-status')!;
  importInput.addEventListener('change', async () => {
    const file = importInput.files?.[0];
    if (!file) return;
    statusEl.textContent = `解析中：${file.name} …`;
    try {
      const bytes = await readFileBytes(file);
      const rec = await ingestBytes(bytes, file.name, 'imported-fmp4');
      statusEl.innerHTML = `<span class="badge green">解析成功</span> ${rec.durationSec.toFixed(1)}s · ${formatBytes(rec.bytes.length)}`;
      toast(`导入成功：${file.name}`, 'ok');
      void refresh();
    } catch (e) {
      statusEl.innerHTML = `<span class="badge red">导入失败</span> ${esc((e as Error).message)}`;
      toast((e as Error).message, 'err');
    }
  });
}

/** 解析并写入素材，返回记录 */
export async function ingestBytes(
  bytes: Uint8Array,
  name: string,
  kind: MaterialRecord['kind'],
): Promise<MaterialRecord> {
  const fmp4 = parseFmp4(bytes);
  const video = fmp4.tracks.find((t) => t.kind === 'video');
  const audio = fmp4.tracks.find((t) => t.kind === 'audio');
  const rec: MaterialRecord = {
    materialId: `mat-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e5).toString(36)}`,
    name,
    kind,
    createdAt: Date.now(),
    durationSec: Math.round(fmp4.durationSec * 10) / 10,
    hasAudio: !!audio,
    width: video?.width ?? 0,
    height: video?.height ?? 0,
    bytes,
  };
  await storage.putMaterial(rec);
  return rec;
}
