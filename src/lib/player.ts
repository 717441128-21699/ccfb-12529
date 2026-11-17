/**
 * EME ClearKey 播放引擎：
 * - MSE SourceBuffer 逐个喂 init/媒体分片，原生支持 seek 与倍速；
 * - requestMediaKeySystemAccess('org.w3.clearkey') + 本地模拟 license 响应；
 * - 每个分片 append 前先做 SHA-256 校验，损坏即中止并报错，不送解码器；
 * - 到期/吊销通过时间闸门与密钥获取拦截双重保证。
 */

import { LicenseFile, PackageManifest } from '../types';
import { storage } from './storage';
import { verifyOneSegment } from './verifier';
import { buildClearKeyLicense, encodeClearKeyLicense, parseClearKeyMessage } from './crypto/license';

const CLEAR_KEY = 'org.w3.clearkey';

export interface PlayerGate {
  /** 返回错误信息表示拒绝放行（到期/吊销/签名问题已在外面处理，这里做时间闸门） */
  checkPlaybackAllowed: () => string | null;
}

export interface ClearKeyPlayerOptions {
  video: HTMLVideoElement;
  manifest: PackageManifest;
  license: LicenseFile;
  /** 本地“许可证服务”：根据请求中的 KID 返回 CEK（已做授权校验后才调用） */
  resolveKey: (kidHex: string) => Promise<Uint8Array>;
  gate: PlayerGate;
  onEvent?: (e: PlayerEvent) => void;
}

export type PlayerEvent =
  | { type: 'log'; message: string }
  | { type: 'verify'; fileName: string; ok: boolean }
  | { type: 'license'; message: string }
  | { type: 'error'; message: string; fatal: boolean }
  | { type: 'state'; state: string }
  | { type: 'progress'; bufferedSec: number; durationSec: number };

export class ClearKeyPlayer {
  private video: HTMLVideoElement;
  private manifest: PackageManifest;
  private license: LicenseFile;
  private resolveKey: (kidHex: string) => Promise<Uint8Array>;
  private gate: PlayerGate;
  private emit: (e: PlayerEvent) => void;

  private mediaSource: MediaSource | null = null;
  private sourceBuffer: SourceBuffer | null = null;
  private objectUrl: string | null = null;
  private sessions: MediaKeySession[] = [];
  private appendQueue: Promise<void> = Promise.resolve();
  private stopped = false;
  private appendIndex = 0;
  private timer: number | null = null;

  constructor(opts: ClearKeyPlayerOptions) {
    this.video = opts.video;
    this.manifest = opts.manifest;
    this.license = opts.license;
    this.resolveKey = opts.resolveKey;
    this.gate = opts.gate;
    this.emit = opts.onEvent ?? (() => undefined);
  }

  async start(): Promise<void> {
    this.stopped = false;
    // 启动前最后一道授权闸门
    const denied = this.gate.checkPlaybackAllowed();
    if (denied) throw new Error(denied);

    await this.setupEme();
    await this.setupMse();
    this.startTimeGate();
    this.emit({ type: 'state', state: 'ready' });
  }

  // ---------------- EME / ClearKey ----------------

  private async setupEme(): Promise<void> {
    if (!navigator.requestMediaKeySystemAccess) {
      throw new Error('当前浏览器不支持 EME（Encrypted Media Extensions）');
    }
    const videoCodec = this.manifest.tracks.find((t) => t.kind === 'video')?.mseCodec ?? 'avc1.42E01E';
    const audioTrack = this.manifest.tracks.find((t) => t.kind === 'audio');
    // 必须显式声明 encryptionScheme='cbcs'，否则 CDM 按默认 cenc 解析会拒绝 cbcs 分片
    const config: MediaKeySystemConfiguration = {
      initDataTypes: ['keyids'],
      audioCapabilities: audioTrack
        ? [{ contentType: `audio/mp4; codecs="${audioTrack.mseCodec}"`, encryptionScheme: 'cbcs' } as MediaKeySystemMediaCapability]
        : [],
      videoCapabilities: [
        { contentType: `video/mp4; codecs="${videoCodec}"`, encryptionScheme: 'cbcs' } as MediaKeySystemMediaCapability,
      ],
      distinctiveIdentifier: 'not-allowed',
      persistentState: 'not-allowed',
      sessionTypes: ['temporary'],
    };

    let access: MediaKeySystemAccess;
    try {
      access = await navigator.requestMediaKeySystemAccess(CLEAR_KEY, [config]);
    } catch (e) {
      throw new Error(`ClearKey CDM 不可用：${(e as Error).message}。请使用 Chrome/Edge 并通过 http(s) 或 localhost 打开。`);
    }
    const mediaKeys = await access.createMediaKeys();
    await this.video.setMediaKeys(mediaKeys);
    this.emit({ type: 'log', message: '已创建 ClearKey MediaKeys' });

    // 用 keyids init data 直接建立会话（不依赖 pssh）
    const session = mediaKeys.createSession('temporary');
    this.sessions.push(session);
    session.addEventListener('message', async (ev) => {
      try {
        await this.handleLicenseMessage(session, ev);
      } catch (e) {
        this.emit({ type: 'error', message: `许可证处理失败：${(e as Error).message}`, fatal: true });
      }
    });
    session.addEventListener('keystatuseschange', () => {
      const statuses: string[] = [];
      session.keyStatuses.forEach((status) => statuses.push(status));
      this.emit({ type: 'license', message: `密钥状态：${statuses.join(', ') || '无'}` });
    });

    const initData = this.buildKeyIdsInitData(this.manifest.kid);
    await session.generateRequest('keyids', initData as BufferSource);
    this.emit({ type: 'log', message: '已发送 ClearKey license request（本地模拟）' });
  }

  /** keyids init data: {"kids":["<base64url KID>"],"type":"temporary"} */
  private buildKeyIdsInitData(kidHex: string): Uint8Array {
    const payload = JSON.stringify({ kids: [base64urlFromHex(kidHex)], type: 'temporary' });
    return new TextEncoder().encode(payload);
  }

  private async handleLicenseMessage(session: MediaKeySession, ev: MediaKeyMessageEvent): Promise<void> {
    const { kids } = parseClearKeyMessage(ev.message);
    if (kids.length === 0) throw new Error('license request 中没有 KID');

    // 发放前再次过授权闸门（过期/吊销瞬间拦截）
    const denied = this.gate.checkPlaybackAllowed();
    if (denied) {
      this.emit({ type: 'error', message: `许可证发放被拒绝：${denied}`, fatal: true });
      await this.stop();
      return;
    }

    const requestedKidB64 = kids[0];
    const kidHex = hexFromBase64url(requestedKidB64);
    if (kidHex.toLowerCase() !== this.license.kid.toLowerCase()) {
      throw new Error(`请求的 KID ${kidHex} 与授权课程 ${this.license.kid} 不一致`);
    }
    const cek = await this.resolveKey(kidHex);
    const license = buildClearKeyLicense(kidHex, cek);
    const response = encodeClearKeyLicense(license);
    await session.update(response);
    this.emit({ type: 'license', message: '本地许可证服务已下发 ClearKey 密钥（KID 匹配授权）' });
  }

  // ---------------- MSE ----------------

  private async setupMse(): Promise<void> {
    const codecs = this.manifest.tracks.map((t) => t.mseCodec).filter(Boolean).join(', ');
    const mimeType = `video/mp4; codecs="${codecs}"`;
    if (!window.MediaSource || !MediaSource.isTypeSupported(mimeType)) {
      throw new Error(`MSE 不支持该编码组合：${mimeType}`);
    }

    const ms = new MediaSource();
    this.mediaSource = ms;
    this.objectUrl = URL.createObjectURL(ms);
    this.video.src = this.objectUrl;

    await new Promise<void>((resolve, reject) => {
      ms.addEventListener('sourceopen', () => resolve(), { once: true });
      ms.addEventListener('sourceended', () => this.emit({ type: 'state', state: 'ended' }));
      setTimeout(() => reject(new Error('MediaSource 打开超时')), 10000);
    });

    this.sourceBuffer = ms.addSourceBuffer(mimeType);
    this.sourceBuffer.mode = 'sequence';
    this.sourceBuffer.addEventListener('error', () => {
      this.emit({ type: 'error', message: 'SourceBuffer 解码错误（分片可能损坏）', fatal: true });
    });

    this.emit({ type: 'log', message: `SourceBuffer 已创建：${mimeType}` });
    void this.pumpSegments();
  }

  /** 队列式 append：每片先哈希校验，再 append */
  private pumpSegments(): void {
    const segs = this.manifest.segments;
    const feedNext = (): void => {
      if (this.stopped) return;
      if (this.appendIndex >= segs.length) {
        if (this.mediaSource?.readyState === 'open') {
          try {
            this.mediaSource.endOfStream();
          } catch {
            /* 重复 endOfStream 忽略 */
          }
        }
        this.emit({ type: 'state', state: 'fully-buffered' });
        return;
      }
      const info = segs[this.appendIndex];
      this.appendQueue = this.appendQueue.then(async () => {
        if (this.stopped || !this.sourceBuffer) return;

        // 1) 完整性闸门
        const report = await verifyOneSegment(this.manifest, info.fileName);
        this.emit({ type: 'verify', fileName: info.fileName, ok: report.ok });
        if (!report.ok) {
          this.emit({ type: 'error', message: report.error ?? `${info.fileName} 校验失败`, fatal: true });
          await this.stop();
          return;
        }

        // 2) 授权时间闸门（播放过程中持续生效）
        const denied = this.gate.checkPlaybackAllowed();
        if (denied) {
          this.emit({ type: 'error', message: denied, fatal: true });
          await this.stop();
          return;
        }

        const bytes = await storage.getSegment(this.manifest.courseId, info.fileName);
        if (!bytes) {
          this.emit({ type: 'error', message: `缺少分片 ${info.fileName}`, fatal: true });
          await this.stop();
          return;
        }

        await this.waitForUpdate();
        if (this.stopped) return;
        try {
          this.sourceBuffer.appendBuffer(bytes.slice().buffer as ArrayBuffer);
        } catch (e) {
          this.emit({ type: 'error', message: `appendBuffer 失败：${(e as Error).message}`, fatal: true });
          await this.stop();
          return;
        }
        await this.waitForUpdate();
        this.appendIndex++;
        this.emit({
          type: 'progress',
          bufferedSec: this.video.buffered.length ? this.video.buffered.end(this.video.buffered.length - 1) : 0,
          durationSec: this.manifest.durationSec,
        });
        feedNext();
      });
    };
    feedNext();
  }

  private waitForUpdate(): Promise<void> {
    const sb = this.sourceBuffer;
    if (!sb || !sb.updating) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const onUpd = () => {
        sb.removeEventListener('update', onUpd);
        sb.removeEventListener('error', onErr);
        resolve();
      };
      const onErr = () => {
        sb.removeEventListener('update', onUpd);
        sb.removeEventListener('error', onErr);
        reject(new Error('SourceBuffer 更新失败'));
      };
      sb.addEventListener('update', onUpd);
      sb.addEventListener('error', onErr);
    });
  }

  // ---------------- 运行期时间闸门 ----------------

  private startTimeGate(): void {
    this.timer = window.setInterval(() => {
      if (this.stopped) return;
      const denied = this.gate.checkPlaybackAllowed();
      if (denied) {
        this.emit({ type: 'error', message: denied, fatal: true });
        void this.stop();
      }
    }, 2000);
  }

  // ---------------- 控制 ----------------

  setPlaybackRate(rate: number): void {
    this.video.playbackRate = rate;
  }

  seekTo(sec: number): void {
    const denied = this.gate.checkPlaybackAllowed();
    if (denied) {
      this.emit({ type: 'error', message: denied, fatal: false });
      return;
    }
    this.video.currentTime = Math.min(Math.max(0, sec), this.manifest.durationSec);
  }

  async stop(): Promise<void> {
    this.stopped = true;
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
    try {
      this.video.pause();
      this.video.removeAttribute('src');
      this.video.load();
    } catch {
      /* ignore */
    }
    if (this.objectUrl) URL.revokeObjectURL(this.objectUrl);
    this.objectUrl = null;
    for (const s of this.sessions) {
      try {
        await s.close();
      } catch {
        /* ignore */
      }
    }
    this.sessions = [];
    if (this.mediaSource && this.mediaSource.readyState === 'open') {
      try {
        this.mediaSource.endOfStream();
      } catch {
        /* ignore */
      }
    }
    this.mediaSource = null;
    this.sourceBuffer = null;
    this.emit({ type: 'state', state: 'stopped' });
  }
}

function base64urlFromHex(hex: string): string {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < bytes.length; i++) bytes[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  let bin = '';
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function hexFromBase64url(b64: string): string {
  const bin = atob(b64.replace(/-/g, '+').replace(/_/g, '/'));
  let hex = '';
  for (let i = 0; i < bin.length; i++) hex += bin.charCodeAt(i).toString(16).padStart(2, '0');
  return hex;
}
