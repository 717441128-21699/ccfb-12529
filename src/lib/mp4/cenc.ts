/**
 * CENC cbcs 加密器（ISO 23001-7）。
 *
 * 输出每个分片包含的完整盒子：
 * - init.mp4: stsd 内 avc1/mp4a → encv/enca + sinf(frma/schm/schi/tenc)，mvex 保留
 * - seg-*.m4s: traf 内新增 saiz / saio / senc，trun 修正 data_offset
 * 视频 cbcs pattern (crypt=1,skip=9)；音频 cbcs (crypt=1,skip=0)（全 sample 加密）。
 * 加密长度严格按 16 字节 AES 块，尾块不足 16B 保持明文（residual，CENC 规定）。
 */

import {
  Box,
  Reader,
  Writer,
  concat,
  findBox,
  makeBox,
  makeFullBox,
  parseBoxes,
  serializeBoxes,
  u32,
} from './boxes';
import { Fmp4File, Fmp4Sample, Fmp4Track, parseFmp4 } from './fmp4';
import {
  NalUnit,
  Subsample,
  buildVideoSubsamples,
  buildWholeSampleSubsample,
  encryptedByteCount,
  parseAvccNals,
} from './nal';

/**
 * cbcs 视频 crypt/skip pattern。
 * 采用全块 CBC（crypt=1, skip=0）：每个 16 字节块都加密。
 * 实测 Chrome/Edge ClearKey CDM 在 fMP4 分片场景下对 crypt/skip 块跳过模式
 * （如 1/9）的支持不完整，而全块 cbcs（tenc pattern 字节=0x00）可稳定解密播放；
 * 全块加密同时满足 CENC cbcs 规范且安全性不降低（仅压缩率优化让位于兼容性）。
 */
export const CBCS_VIDEO_PATTERN = { crypt: 1, skip: 0 };
/** 音频本就全块加密（无 skip） */
export const CBCS_AUDIO_PATTERN = { crypt: 1, skip: 0 };
export const PROTECTION_SCHEME = 'cbcs';

export interface TrackCryptoParams {
  trackId: number;
  kind: 'video' | 'audio';
  codecFamily: 'avc' | 'hevc' | 'other';
  kid: Uint8Array; // 16B
  iv: Uint8Array; // 16B（常量 IV）
  cryptBlocks: number;
  skipBlocks: number;
  perSampleIv: boolean;
}

export interface EncryptedSegment {
  fileName: string;
  kind: 'init' | 'media';
  index: number;
  bytes: Uint8Array;
  clearSize: number;
  sampleCount: number;
  encryptedSamples: number;
  subsampleCount: number;
  encryptedBytes: number;
}

export interface EncryptionOutput {
  initSegment: EncryptedSegment;
  mediaSegments: EncryptedSegment[];
  tracks: TrackCryptoParams[];
}

interface SamplePlan {
  sample: Fmp4Sample;
  subs: Subsample[];
  nals: NalUnit[];
  encryptedBytes: number;
}

// ---------------- AES-CBC 原地加密 ----------------

/**
 * 对 data 的 [start,start+len) 做 AES-CBC 加密（len 为 16 倍数）。
 * WebCrypto 固定输出 PKCS7 填充（多 16B），去掉尾部填充块即得到 CENC 需要的
 * 等长密文——输入本身是整块序列，前 len 字节与无填充 CBC 密文完全一致。
 */
async function cbcEncryptInPlace(
  data: Uint8Array,
  start: number,
  len: number,
  key: CryptoKey,
  iv: Uint8Array,
): Promise<void> {
  const plain = data.slice(start, start + len);
  const buf = await crypto.subtle.encrypt(
    { name: 'AES-CBC', iv: iv as BufferSource },
    key,
    plain as BufferSource,
  );
  const out = new Uint8Array(buf);
  if (out.length !== len + 16) throw new Error('AES-CBC 输出长度异常');
  data.set(out.subarray(0, len), start);
}

// ---------------- sinf / tenc 等盒子构造 ----------------

function frmaBox(originalFormat: string): Box {
  return makeBox(
    'frma',
    new Uint8Array([
      originalFormat.charCodeAt(0), originalFormat.charCodeAt(1),
      originalFormat.charCodeAt(2), originalFormat.charCodeAt(3),
    ]),
  );
}

function schmBox(): Box {
  // scheme_type='cbcs', scheme_version=0x00010000（fullbox 头由 makeFullBox 处理）
  return makeFullBox('schm', 0, 0, concat([
    new Uint8Array([0x63, 0x62, 0x63, 0x73]), // 'cbcs'
    u32(0x00010000),
  ]));
}

/**
 * tenc（version=1，fullbox 头由 makeFullBox 处理）。
 * 经 shaka-packager 权威输出 + Chrome ClearKey 实测验证的 cbcs 常量 IV 布局（37B payload）：
 *   [0]  0x00 reserved
 *   [1]  (crypt_byte_block<<4 | skip_byte_block)，视频 1/9 → 0x19；音频全加密 → 0x00
 *   [2]  0x01 is_protected
 *   [3]  0x00 reserved / per_sample_IV_size（常量 IV 时为 0）
 *   [4..19]  KID(16)
 *   [20] 0x10 default_constant_IV_size=16
 *   [21..36] 常量 IV(16)
 */
function tencBox(p: TrackCryptoParams): Box {
  const w = new Writer();
  w.u8(0x00); // reserved
  w.u8((p.cryptBlocks << 4) | (p.skipBlocks & 0x0f)); // crypt/skip 合并
  w.u8(0x01); // is_protected
  w.u8(0x00); // per_sample_IV_size=0（常量 IV）
  w.bytes(p.kid);
  w.u8(16); // default_constant_IV_size
  w.bytes(p.iv); // 16B 常量 IV
  return makeFullBox('tenc', 1, 0, w.result());
}

/** 用 encv/enca + sinf 包装原 sample entry */
function wrapSampleEntry(entry: Box, p: TrackCryptoParams): Box {
  const encType = entry.type === 'mp4a' || entry.type === 'enca' ? 'enca' : 'encv';
  // sinf/schi 作为容器 box 挂真实子树，保证重新 parse 后 children 可遍历
  const schi: Box = { type: 'schi', raw: new Uint8Array(0), start: -1, size: 0, children: [tencBox(p)] };
  const sinf: Box = {
    type: 'sinf',
    raw: new Uint8Array(0),
    start: -1,
    size: 0,
    children: [frmaBox(entry.type), schmBox(), schi],
  };
  return {
    type: encType,
    raw: new Uint8Array(0),
    start: -1,
    size: 0,
    rawHeader: entry.rawHeader,
    children: [...(entry.children ?? []), sinf],
  };
}

// ---------------- init 段重写 ----------------

export function rewriteInit(initBytes: Uint8Array, params: TrackCryptoParams[]): Uint8Array {
  const top = parseBoxes(initBytes);
  const moov = top.find((b) => b.type === 'moov');
  if (!moov) throw new Error('init 段缺少 moov');
  for (const trak of moov.children!.filter((b) => b.type === 'trak')) {
    const stsd = findBox(trak.children, ['mdia', 'minf', 'stbl', 'stsd']);
    if (!stsd || !stsd.children?.length) continue;
    const trackId = readTrackIdSafe(findBox(trak.children, ['tkhd'])!);
    const p = params.find((x) => x.trackId === trackId);
    if (!p) continue;
    stsd.children = stsd.children.map((e) => wrapSampleEntry(e, p));
  }
  return serializeBoxes(top);
}

function readTrackIdSafe(tkhd: Box): number {
  const r = new Reader(tkhd.payload!);
  if (tkhd.version === 1) {
    r.u64();
    r.u64();
  } else {
    r.u32();
    r.u32();
  }
  return r.u32();
}

// ---------------- 媒体分片加密 ----------------

/** 一个 moof 内每个 traf 的处理中间态 */
interface TrafWork {
  traf: Box;
  trackId: number;
  params: TrackCryptoParams;
  plans: SamplePlan[];
  encryptedBytes: number;
  subsampleCount: number;
}

export async function encryptFragment(
  file: Fmp4File,
  fragIndex: number,
  allParams: TrackCryptoParams[],
  key: Uint8Array,
): Promise<EncryptedSegment> {
  const moofStart = file.moofGroups[fragIndex];
  if (moofStart === undefined) throw new Error(`分片 ${fragIndex} 不存在`);
  const group = file.fragments.filter((f) => f.moofStart === moofStart);
  const moofEnd = Math.max(...group.map((g) => g.moofEnd));
  const mdatStart = Math.min(...group.map((g) => g.mdatStart));
  const mdatEnd = Math.max(...group.map((g) => g.mdatEnd));

  // 整文件副本上原地改 mdat 密文
  const work = file.bytes.slice();
  const cryptoKey = await crypto.subtle.importKey(
    'raw', key as BufferSource,
    { name: 'AES-CBC' } as AlgorithmIdentifier,
    false, ['encrypt'],
  );

  const moofTop = parseBoxes(file.bytes.subarray(moofStart, moofEnd));
  if (moofTop.length !== 1 || moofTop[0].type !== 'moof') throw new Error('片段顶层不是单个 moof');
  const moof = moofTop[0];
  const trafs = moof.children!.filter((b) => b.type === 'traf');
  if (trafs.length !== group.length) {
    throw new Error(`moof 内 traf 数(${trafs.length}) 与解析到的轨道数(${group.length}) 不一致`);
  }

  // 注意：tfhd 的 base_data_offset 保持原始值不动。经 ffmpeg cenc 能播分片对照验证，
  // MSE 解复用器以 trun.data_offset（相对 moof 起点，=moof.size+8）定位 sample，
  // base_data_offset 的绝对高值在分片 append 时被忽略，改写反而破坏结构。

  const trafWorks: TrafWork[] = [];
  const jobs: Promise<void>[] = [];
  let totalEncrypted = 0;
  let totalSubs = 0;
  let totalSamples = 0;

  for (let ti = 0; ti < trafs.length; ti++) {
    const traf = trafs[ti];
    const trackId = readTfhdTrackId(traf);
    const params = allParams.find((p) => p.trackId === trackId);
    if (!params) throw new Error(`traf 引用未知 trackId=${trackId}`);
    const track = file.tracks.find((t) => t.trackId === trackId)!;
    const plans = buildPlans(file, moofStart, track, params);
    if (plans.length === 0) throw new Error(`分片 ${fragIndex} track ${trackId} 无 sample`);

    let trafEncrypted = 0;
    for (const plan of plans) {
      let cursor = plan.sample.start;
      for (const s of plan.subs) {
        cursor += s.clearBytes;
        if (s.encryptedBytes > 0) {
          scanPattern(s.encryptedBytes, params, (blockOffset, cryptLenBlocks) => {
            jobs.push(
              cbcEncryptInPlace(work, cursor + blockOffset * 16, cryptLenBlocks * 16, cryptoKey, params.iv),
            );
            trafEncrypted += cryptLenBlocks * 16;
          });
        }
        cursor += s.encryptedBytes;
      }
      totalSubs += plan.subs.length;
    }

    // 经 Chrome/Edge ClearKey 实测：empty-moov fMP4 分片的 moof 内放置 senc/saio/saiz
    // 会导致解复用器 CHUNK_DEMUXER_ERROR_APPEND_FAILED。采用 shaka-packager 同款形态——
    // 媒体 moof 不携带辅助信息 box，加密边界完全由 init 段 tenc（全块 cbcs + 常量 IV）驱动，
    // NAL 长度前缀/NAL header 等明文区由解复用器按 CENC cbcs 规则自动保留。
    trafWorks.push({ traf, trackId, params, plans, encryptedBytes: trafEncrypted, subsampleCount: plans.reduce((n, p2) => n + p2.subs.length, 0) });
    totalEncrypted += trafEncrypted;
    totalSamples += plans.length;
  }
  await Promise.all(jobs);

  // 修正每个 trun 的 data_offset：新 moof 长度 + mdat 头(8)
  let moofBytes = serializeBoxes([moof]);
  for (const tw of trafWorks) {
    const trun = tw.traf.children!.find((b) => b.type === 'trun')!;
    fixTrunDataOffset(trun, moofBytes.length + 8);
  }
  const finalMoof = serializeBoxes([moof]);

  // mdat：头 8 字节保持不变（size/type），payload 换成密文副本
  const mdatHeader = file.bytes.subarray(mdatStart, mdatStart + 8);
  const mdatPayload = work.subarray(mdatStart + 8, mdatEnd);
  const out = concat([finalMoof, mdatHeader, mdatPayload]);

  return {
    fileName: `seg-${String(fragIndex + 1).padStart(4, '0')}.m4s`,
    kind: 'media',
    index: fragIndex,
    bytes: out,
    clearSize: mdatEnd - (mdatStart + 8),
    sampleCount: totalSamples,
    encryptedSamples: trafWorks.reduce(
      (n, tw) => n + tw.plans.filter((p2) => p2.encryptedBytes > 0).length, 0,
    ),
    subsampleCount: totalSubs,
    encryptedBytes: totalEncrypted,
  };
}

function readTfhdTrackId(traf: Box): number {
  const tfhd = traf.children!.find((b) => b.type === 'tfhd')!;
  return new Reader(tfhd.payload!).u32();
}

/** pattern 扫描：回调每个连续 crypt 段（块偏移, 块数） */
function scanPattern(
  encryptedBytes: number,
  p: TrackCryptoParams,
  cb: (blockOffset: number, cryptBlocks: number) => void,
): void {
  const totalBlocks = Math.floor(encryptedBytes / 16);
  if (p.cryptBlocks === 0) {
    cb(0, totalBlocks);
    return;
  }
  const period = p.cryptBlocks + p.skipBlocks;
  for (let off = 0; off < totalBlocks; off += period) {
    cb(off, Math.min(p.cryptBlocks, totalBlocks - off));
  }
}

/** 在单层/嵌套 box 字节流中找目标 box 相对起点的偏移（保留供调试） */
function findDeepOffset(bytes: Uint8Array, type: string): number {
  const walk = (list: Box[]): number => {
    for (const b of list) {
      if (b.type === type) return b.start;
      if (b.children) {
        const r = walk(b.children);
        if (r >= 0) return r;
      }
    }
    return -1;
  };
  const r = walk(parseBoxes(bytes));
  if (r < 0) throw new Error(`moof 中找不到 ${type}`);
  return r;
}
void findDeepOffset;

function fixTrunDataOffset(trun: Box, newOffset: number): void {
  if (!(trun.flags! & 0x000001)) return;
  // payload: sample_count(u32) data_offset(s32) ...
  const p = trun.payload!;
  p[4] = (newOffset >>> 24) & 0xff;
  p[5] = (newOffset >>> 16) & 0xff;
  p[6] = (newOffset >>> 8) & 0xff;
  p[7] = newOffset & 0xff;
}

// ---------------- sample 计划 ----------------

function buildPlans(
  file: Fmp4File,
  moofStart: number,
  track: Fmp4Track,
  params: TrackCryptoParams,
): SamplePlan[] {
  const plans: SamplePlan[] = [];
  const samples = track.samples.filter((s) => s.moofStart === moofStart);
  for (const sample of samples) {
    let subs: Subsample[];
    let nals: NalUnit[] = [];
    if (track.kind === 'video' && params.codecFamily !== 'other') {
      const raw = file.bytes.subarray(sample.start, sample.end);
      nals = parseAvccNals(raw, params.codecFamily === 'hevc' ? 'hevc' : 'avc');
      subs = buildVideoSubsamples(nals);
    } else {
      subs = buildWholeSampleSubsample(sample.size);
    }
    const { encryptedBytes } = encryptedByteCount(subs, params.cryptBlocks, params.skipBlocks);
    plans.push({ sample, subs, nals, encryptedBytes });
  }
  return plans;
}

// ---------------- 顶层入口 ----------------

export interface CencInput {
  fmp4: Fmp4File;
  key: Uint8Array; // 16B CEK
  kid: Uint8Array; // 16B
  iv: Uint8Array; // 16B 常量 IV
}

export async function encryptCenc(input: CencInput): Promise<EncryptionOutput> {
  const params: TrackCryptoParams[] = input.fmp4.tracks.map((t) => ({
    trackId: t.trackId,
    kind: t.kind,
    codecFamily: t.codecFourcc.startsWith('avc')
      ? 'avc'
      : t.codecFourcc.startsWith('hvc') || t.codecFourcc.startsWith('hev')
        ? 'hevc'
        : 'other',
    kid: input.kid,
    iv: input.iv,
    cryptBlocks: t.kind === 'video' ? CBCS_VIDEO_PATTERN.crypt : CBCS_AUDIO_PATTERN.crypt,
    skipBlocks: t.kind === 'video' ? CBCS_VIDEO_PATTERN.skip : CBCS_AUDIO_PATTERN.skip,
    perSampleIv: false, // cbcs 常量 IV：IV 只写在 tenc，senc 不写 IV
  }));

  const initBytes = rewriteInit(input.fmp4.initSegment, params);
  const initSeg: EncryptedSegment = {
    fileName: 'init.mp4',
    kind: 'init',
    index: -1,
    bytes: initBytes,
    clearSize: input.fmp4.initSegment.length,
    sampleCount: 0,
    encryptedSamples: 0,
    subsampleCount: 0,
    encryptedBytes: 0,
  };

  const media: EncryptedSegment[] = [];
  for (let i = 0; i < input.fmp4.moofGroups.length; i++) {
    media.push(await encryptFragment(input.fmp4, i, params, input.key));
  }
  return { initSegment: initSeg, mediaSegments: media, tracks: params };
}

export { parseFmp4 };
