/**
 * AVCC/HEVCC 长度前缀 NAL 解析，以及 CENC subsample 构造。
 *
 * cbcs 视频加密规则（ISO 23001-7 §10）：
 * - slice NAL（AVC 1/5、HEVC 0..21 中的 VCL 类）按 crypt/skip pattern 加密，
 *   每个被保护 NAL 前 2 字节（NAL header + slice_header 首字节）保持明文；
 * - 非 slice NAL（SPS/PPS/SEI/IDR 之外的参数集等）整体保持明文；
 * - 相邻明文合并为一个 subsample 的 clear 段，随后挂一个 encrypted 段。
 */

export interface NalUnit {
  type: number;
  /** 含 4 字节长度前缀在内的完整区间 */
  start: number;
  end: number;
  /** NAL payload（不含长度前缀）区间 */
  nalStart: number;
  nalEnd: number;
  isVcl: boolean;
}

export interface Subsample {
  clearBytes: number;
  encryptedBytes: number;
}

export function parseAvccNals(sample: Uint8Array, codec: 'avc' | 'hevc'): NalUnit[] {
  const out: NalUnit[] = [];
  let off = 0;
  while (off + 4 <= sample.length) {
    const len =
      (sample[off] << 24) | (sample[off + 1] << 16) | (sample[off + 2] << 8) | sample[off + 3];
    if (len <= 0 || off + 4 + len > sample.length) {
      throw new Error(`AVCC NAL 长度非法: len=${len} off=${off} sample=${sample.length}`);
    }
    const nalStart = off + 4;
    const nalEnd = nalStart + len;
    const header = sample[nalStart];
    let type: number;
    let isVcl: boolean;
    if (codec === 'avc') {
      type = header & 0x1f;
      isVcl = type === 1 || type === 5;
    } else {
      type = (header >> 1) & 0x3f;
      isVcl = type <= 31; // HEVC: 0..31 VCL
    }
    out.push({ type, start: off, end: nalEnd, nalStart, nalEnd, isVcl });
    off = nalEnd;
  }
  if (off !== sample.length) throw new Error('AVCC sample 尾部有残余字节');
  return out;
}

/**
 * 构造 cbcs 视频 subsample 表。
 * 返回的 subsample 顺序与字节区间一一对应；最后一个 subsample 的 encryptedBytes 可能为 0。
 */
export function buildVideoSubsamples(nals: NalUnit[]): Subsample[] {
  const subs: Subsample[] = [];
  let pendingClear = 0;

  const flushEncrypted = (encLen: number) => {
    subs.push({ clearBytes: pendingClear, encryptedBytes: encLen });
    pendingClear = 0;
  };

  for (const nal of nals) {
    const nalLen = nal.nalEnd - nal.nalStart;
    const prefixLen = nal.nalStart - nal.start; // 长度前缀 4 字节
    if (!nal.isVcl) {
      // 整 NAL 明文（含长度前缀）
      pendingClear += prefixLen + nalLen;
      continue;
    }
    // VCL NAL（ISO 23001-7 §10.2 cbcs）：长度前缀(4) + NAL_unit_header(AVC 1B) 明文，
    // 即 clearHead = 5；NAL 其余字节进入加密段，块网格从 NAL 负载起点开始。
    const clearHead = prefixLen + 1;
    const encLen = Math.max(0, nalLen - 1);
    pendingClear += clearHead;
    if (encLen > 0) flushEncrypted(encLen);
  }
  if (pendingClear > 0 || subs.length === 0) subs.push({ clearBytes: pendingClear, encryptedBytes: 0 });
  return subs;
}

/** 音频/未知格式：整 sample 作为一个加密 subsample */
export function buildWholeSampleSubsample(sampleSize: number): Subsample[] {
  return [{ clearBytes: 0, encryptedBytes: sampleSize }];
}

/**
 * 计算一个 sample 内实际被 AES 加密的字节数。
 * cbcs: 从每个 subsample 的 encryptedBytes 中按 pattern 取 crypt 块，
 * 不足 16B 的尾块不加密（CENC: residual 区域）。
 */
export function encryptedByteCount(
  subs: Subsample[],
  cryptBlocks: number,
  skipBlocks: number,
): { encryptedBytes: number; blocks: number } {
  let bytes = 0;
  let blocks = 0;
  for (const s of subs) {
    if (s.encryptedBytes === 0) continue;
    const totalBlocks = Math.floor(s.encryptedBytes / 16);
    let crypted = 0;
    if (cryptBlocks === 0) {
      // 全加密（cenc 或 cbcs 无 pattern 的退化情形）
      crypted = totalBlocks;
    } else {
      const period = cryptBlocks + skipBlocks;
      const fullPeriods = Math.floor(totalBlocks / period);
      const rem = totalBlocks - fullPeriods * period;
      crypted = fullPeriods * cryptBlocks + Math.min(rem, cryptBlocks);
    }
    blocks += crypted;
    bytes += crypted * 16;
  }
  return { encryptedBytes: bytes, blocks };
}

/** AVC 关键帧判断：sample flags 的 sample_depends_on==2（非参考帧）或含 IDR(5) */
export function isSyncSample(flags: number, nals: NalUnit[]): boolean {
  const dependsOn = (flags >>> 8) & 0x03;
  if (dependsOn === 2) return false;
  return nals.some((n) => n.isVcl && n.type === 5);
}
