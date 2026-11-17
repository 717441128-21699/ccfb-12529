/** 播放端：导入 .lic → 验签/到期/吊销 → 分片哈希 → EME ClearKey 播放 + 漂移水印 */

import { LicenseFile, PackageManifest } from '../types';
import { storage } from '../lib/storage';
import { verifyLicense, checkRevocation, parseLicenseFile } from '../lib/crypto/license';
import { verifyPackage, VerifyReport } from '../lib/verifier';
import { exportIssuerPublicJwk } from '../lib/crypto/keystore';
import { ClearKeyPlayer, PlayerEvent } from '../lib/player';
import { buildWatermarkSchedule, slotAtTime, watermarkText, WatermarkSlot } from '../lib/crypto/watermark';
import { base64urlDecode, formatDuration } from '../lib/util';
import { esc, readFileText, toast } from '../app';

export async function playerPage(root: HTMLElement): Promise<void> {
  const packages = await storage.listPackages();
  root.innerHTML = `
    <div class="card">
      <h3>① 选择课程并加载学员授权</h3>
      <div class="grid cols-2">
        <div><label>本地课程包</label>
          <select id="pl-course">
            ${packages.map((p) => `<option value="${esc(p.courseId)}">${esc(p.title)}（${p.segments.length} 分片）</option>`).join('')}
          </select></div>
        <div><label>学员授权文件 .lic</label>
          <input type="file" id="pl-lic" accept=".lic,application/json" />
          <div id="pl-lic-status" class="file-hint"></div></div>
      </div>
      <div class="row end" style="margin-top:14px">
        <button id="pl-verify">② 校验授权与全分片哈希</button>
        <button class="primary" id="pl-play" disabled>③ 开始播放</button>
        <button class="danger" id="pl-stop" disabled>停止</button>
      </div>
      <div id="pl-gate" style="margin-top:12px"></div>
    </div>

    <div class="card">
      <h3>播放（EME ClearKey · 原生 MSE，支持拖动与倍速）</h3>
      <div class="video-wrap">
        <video id="pl-video" controls playsinline></video>
        <div class="wm-layer" id="pl-wm"></div>
      </div>
      <div class="row" style="margin-top:12px">
        <label style="margin:0">倍速</label>
        <select id="pl-rate" style="width:auto">
          ${[0.75, 1, 1.25, 1.5, 2].map((r) => `<option value="${r}" ${r === 1 ? 'selected' : ''}>${r}x</option>`).join('')}
        </select>
        <button class="small" data-seek="0">开头</button>
        <button class="small" data-seek="0.25">25%</button>
        <button class="small" data-seek="0.5">50%</button>
        <button class="small" data-seek="0.75">75%</button>
        <span id="pl-time" class="mono file-hint" style="margin-left:auto"></span>
      </div>
      <div class="log" id="pl-log" style="display:none;margin-top:12px"></div>
    </div>`;

  let license: LicenseFile | null = null;
  let manifest: PackageManifest | null = null;
  let verifyReport: VerifyReport | null = null;
  let player: ClearKeyPlayer | null = null;
  let slots: WatermarkSlot[] = [];
  let wmTimer: number | null = null;

  const logEl = root.querySelector('#pl-log') as HTMLElement;
  const log = (msg: string, cls = 'dim'): void => {
    logEl.style.display = 'block';
    const d = document.createElement('div');
    d.className = cls;
    d.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
    logEl.appendChild(d);
    logEl.scrollTop = logEl.scrollHeight;
  };

  const licInput = root.querySelector<HTMLInputElement>('#pl-lic');
  licInput?.addEventListener('change', async () => {
    const file = licInput.files?.[0];
    const status = root.querySelector('#pl-lic-status')!;
    if (!file) return;
    try {
      license = parseLicenseFile(await readFileText(file));
      status.innerHTML = `<span class="badge blue">已加载</span> ${esc(license.studentName)} · ${esc(license.studentId)} · 到期 ${new Date(license.expiresAt).toLocaleString()}`;
    } catch (e) {
      status.innerHTML = `<span class="badge red">${esc((e as Error).message)}</span>`;
      license = null;
    }
  });

  root.querySelector<HTMLElement>('#pl-verify')?.addEventListener('click', async () => {
    const courseId = (root.querySelector('#pl-course') as HTMLSelectElement).value;
    manifest = (await storage.getPackage(courseId)) ?? null;
    const gateEl = root.querySelector('#pl-gate')!;
    if (!manifest) return toast('课程包不存在', 'err');
    if (!license) return toast('请先加载 .lic 授权文件', 'err');

    const jwk = await exportIssuerPublicJwk();
    const errors = await verifyLicense(license, jwk);
    const student = await storage.getStudent(license.studentId);
    const revMsg = student ? checkRevocation(license, student.revocationVersion) : '本地无学员记录';
    if (student && revMsg) errors.push(revMsg);
    if (license.courseId !== manifest.courseId) errors.push('授权课程与所选课程包不匹配');
    if (license.kid.toLowerCase() !== manifest.kid.toLowerCase()) errors.push('授权 KID 与课程包 KID 不一致');

    log('开始逐分片 SHA-256 校验…', 'info');
    verifyReport = await verifyPackage(manifest, {
      onProgress: (cur, total) => {
        if (cur % 5 === 0 || cur === total - 1) log(`哈希校验 ${cur + 1}/${total}`);
      },
    });
    const bad = verifyReport.results.filter((r) => !r.ok);
    log(verifyReport.ok ? `全部 ${verifyReport.results.length} 个分片哈希通过` : `${bad.length} 个分片损坏/被篡改`, verifyReport.ok ? 'ok' : 'err');

    const ok = errors.length === 0 && verifyReport.ok;
    gateEl.innerHTML = `
      <div class="card" style="margin:0">
        <div class="row" style="justify-content:space-between">
          <strong>授权校验</strong>
          ${errors.length === 0 ? '<span class="badge green">✓ 签名/有效期/吊销/KID 全部通过</span>' : errors.map((e) => `<span class="badge red">✗ ${esc(e)}</span>`).join(' ')}
        </div>
        <div class="row" style="justify-content:space-between;margin-top:8px">
          <strong>完整性校验</strong>
          ${verifyReport.ok
            ? `<span class="badge green">✓ ${verifyReport.results.length} 个分片 SHA-256 全部匹配</span>`
            : `<span class="badge red">✗ ${bad.length} 个分片损坏：${esc(bad.map((b) => b.info.fileName).join(', '))}</span>`}
        </div>
      </div>`;
    (root.querySelector('#pl-play') as HTMLButtonElement).disabled = !ok;
    if (ok) toast('校验通过，可以播放', 'ok');
    else toast('校验未通过，已禁止播放', 'err');
  });

  root.querySelector<HTMLElement>('#pl-play')?.addEventListener('click', async () => {
    if (!manifest || !license) return;
    const video = root.querySelector('#pl-video') as HTMLVideoElement;
    const keyRecord = await storage.getKey(manifest.courseId);
    if (!keyRecord) return toast('本地缺少该课程 CEK，无法发放 ClearKey 许可证', 'err');

    const gate = {
      checkPlaybackAllowed: (): string | null => {
        const now = Date.now();
        if (now >= license!.expiresAt) return `授权已过期（${new Date(license!.expiresAt).toLocaleString()}），播放已中止`;
        return null;
      },
    };

    player = new ClearKeyPlayer({
      video,
      manifest,
      license,
      resolveKey: async (kidHex) => {
        if (kidHex.toLowerCase() !== keyRecord.kid.toLowerCase()) throw new Error('KID 不匹配');
        // 播放端再做一次吊销检查（模拟本地许可证服务的发放策略）
        const stu = await storage.getStudent(license!.studentId);
        if (stu) {
          const rev = checkRevocation(license!, stu.revocationVersion);
          if (rev) throw new Error(rev);
        }
        return keyRecord.key;
      },
      gate,
      onEvent: (e: PlayerEvent) => {
        if (e.type === 'error') log(e.message, 'err');
        else if (e.type === 'verify') log(`分片校验 ${e.ok ? '通过' : '失败'}：${e.fileName}`, e.ok ? 'ok' : 'err');
        else if (e.type === 'license' || e.type === 'log') log(e.message, 'info');
        else if (e.type === 'state') log(e.state, 'info');
        else if (e.type === 'progress') log(`已缓冲 ${e.bufferedSec.toFixed(1)}s / ${e.durationSec}s`);
      },
    });

    try {
      await player.start();
      (root.querySelector('#pl-stop') as HTMLButtonElement).disabled = false;
      (root.querySelector('#pl-play') as HTMLButtonElement).disabled = true;
      await video.play();
      // 水印：用该学员的确定性序列
      const seed = base64urlDecode(manifest.watermarkSeed);
      slots = await buildWatermarkSchedule(seed, license.studentId, manifest.durationSec, manifest.watermark);
      startWatermark(root, video, slots, manifest, license);
      toast('播放已启动，水印按学员编号独立漂移', 'ok');
    } catch (e) {
      log(`播放失败：${(e as Error).message}`, 'err');
      toast((e as Error).message, 'err');
    }
  });

  root.querySelector<HTMLElement>('#pl-stop')?.addEventListener('click', () => {
    void player?.stop();
    if (wmTimer) clearInterval(wmTimer);
    root.querySelector('#pl-wm')!.innerHTML = '';
    (root.querySelector('#pl-stop') as HTMLButtonElement).disabled = true;
    (root.querySelector('#pl-play') as HTMLButtonElement).disabled = false;
  });

  root.querySelector<HTMLElement>('#pl-rate')?.addEventListener('change', (e) => {
    player?.setPlaybackRate(Number((e.target as HTMLSelectElement).value));
  });
  root.querySelectorAll<HTMLElement>('[data-seek]').forEach((b) =>
    b.addEventListener('click', () => {
      const video = root.querySelector('#pl-video') as HTMLVideoElement;
      if (manifest) player?.seekTo(Number(b.dataset.seek) * manifest.durationSec);
      else video.currentTime = 0;
    }));
}

function startWatermark(
  root: HTMLElement,
  video: HTMLVideoElement,
  slots: WatermarkSlot[],
  manifest: PackageManifest,
  license: LicenseFile,
): void {
  const layer = root.querySelector('#pl-wm') as HTMLElement;
  const text = watermarkText(license.studentId, license.studentName);
  const opacity = manifest.watermark.opacity;

  const render = (): void => {
    const slot = slotAtTime(slots, video.currentTime);
    const rect = video.getBoundingClientRect();
    const fontSize = Math.max(13, rect.height * manifest.watermark.fontSizeRatio);
    layer.innerHTML = `
      <div class="wm-main" style="
        left:${slot.x * 100}%; top:${slot.y * 100}%;
        font-size:${fontSize}px; opacity:${opacity};
        transform:translate(-50%,-50%) rotate(${slot.rotation}deg);">
        ${esc(text)}
      </div>
      ${manifest.watermark.cornerWatermarks ? `
        <div class="wm-corner" style="left:10px;top:8px;opacity:${opacity * 0.9}">${esc(license.studentId)}</div>
        <div class="wm-corner" style="right:10px;top:8px;opacity:${opacity * 0.9}">${esc(license.studentId)}</div>
        <div class="wm-corner" style="left:10px;bottom:8px;opacity:${opacity * 0.9}">${esc(license.studentId)}</div>
        <div class="wm-corner" style="right:10px;bottom:8px;opacity:${opacity * 0.9}">${esc(license.studentId)}</div>` : ''}`;
    (root.querySelector('#pl-time') as HTMLElement).textContent =
      `${formatDuration(video.currentTime)} / ${formatDuration(manifest.durationSec)} · 槽位 t=${slot.timeSec}s 坐标(${(slot.x * 100).toFixed(0)}%,${(slot.y * 100).toFixed(0)}%)`;
  };
  render();
  // 每 500ms 检查是否进入下一个漂移槽位
  const wmTimer = window.setInterval(render, 500);
  video.addEventListener('seeked', render);
  // 保存 timer 引用以便停止（挂到元素上）
  (root.querySelector('#pl-video') as HTMLVideoElement & { _wmTimer?: number })._wmTimer = wmTimer;
}
