/**
 * 分片 MP4（fMP4 / CMAF）解析：
 * 把 init 段与一组 moof+mdat 片段解析成 track / sample 表，
 * 供 CENC 加密器定位每个 sample 在文件中的字节范围与默认 flags。
 */

import {
  Box,
  Reader,
  findAll,
  findBox,
  parseBoxes,
  readU32,
} from './boxes';

export interface Fmp4Sample {
  trackId: number;
  /** track 内序号 */
  index: number;
  /** 所属 moof 在原文件中的起点 */
  moofStart: number;
  /** sample 数据在原文件中的绝对区间 [start, end) */
  start: number;
  end: number;
  size: number;
  /** 合成后的 sample flags（trun 优先，否则用 tfhd/trex 默认值） */
  flags: number;
  duration: number;
  cts: number;
  /** 解码时间戳（track timescale 单位） */
  dts: number;
}

export interface Fmp4Track {
  trackId: number;
  kind: 'video' | 'audio';
  timescale: number;
  codecFourcc: string;
  mseCodec: string;
  width?: number;
  height?: number;
  sampleRate?: number;
  channels?: number;
  samples: Fmp4Sample[];
}

export interface Fragment {
  index: number;
  moofStart: number;
  moofEnd: number;
  mdatStart: number;
  mdatEnd: number;
  moof: Box;
  mdat: Box;
  trackId: number;
}

export interface Fmp4File {
  bytes: Uint8Array;
  /** init 段（首个 moof 之前的所有字节，通常 ftyp+moov[+free]） */
  initSegment: Uint8Array;
  initEnd: number;
  tracks: Fmp4Track[];
  /** 每个 traf 一条（多轨 moof 会产生多条同 moofStart 记录） */
  fragments: Fragment[];
  /** 去重后的 moof 起点列表，一项对应一个输出媒体分片 */
  moofGroups: number[];
  durationSec: number;
}

// trun flags
const TRUN_DATA_OFFSET = 0x000001;
const TRUN_FIRST_FLAGS = 0x000004;
const TRUN_DURATION = 0x000100;
const TRUN_SIZE = 0x000200;
const TRUN_FLAGS = 0x000400;
const TRUN_CTS = 0x000800;

// tfhd flags
const TFHD_BASE_DATA_OFFSET = 0x000001;
const TFHD_DESC_IDX = 0x000002;
const TFHD_DEFAULT_DURATION = 0x000008;
const TFHD_DEFAULT_SIZE = 0x000010;
const TFHD_DEFAULT_FLAGS = 0x000020;

interface TrexDefaults {
  duration: number;
  size: number;
  flags: number;
}

export function parseFmp4(bytes: Uint8Array): Fmp4File {
  const top = parseBoxes(bytes);
  const moov = top.find((b) => b.type === 'moov');
  if (!moov) throw new Error('未找到 moov，输入必须是 fMP4（分片 MP4）');
  if (!findBox(moov.children, ['mvex', 'trex'])) {
    throw new Error('moov 内缺少 mvex/trex，输入不是分片 MP4（fMP4）。请先用 ffmpeg -f dash 或 -movflags frag_keyframe+empty_moov 转换。');
  }

  // trex 默认值
  const trexMap = new Map<number, TrexDefaults>();
  for (const trex of findAll(moov.children, 'trex')) {
    const r = new Reader(trex.payload!);
    const trackId = r.u32();
    r.u32(); // desc idx
    trexMap.set(trackId, { duration: r.u32(), size: r.u32(), flags: r.u32() });
  }

  const tracks = parseTracks(moov);

  // 片段：顶层 moof 后面紧跟 mdat（一个 moof 可含多个 traf，对应多轨）
  const fragments: Fragment[] = [];
  const moofGroups: number[] = [];
  const samplesByTrack = new Map<number, Fmp4Sample[]>();
  for (const t of tracks) samplesByTrack.set(t.trackId, t.samples);

  let initEnd = bytes.length;
  for (let i = 0; i < top.length; i++) {
    if (top[i].type !== 'moof') continue;
    if (moofGroups.length === 0) initEnd = top[i].start;
    const moof = top[i];
    const mdat = top[i + 1];
    if (!mdat || mdat.type !== 'mdat') throw new Error(`moof@${moof.start} 后缺少 mdat`);
    moofGroups.push(moof.start);

    for (const traf of moof.children!.filter((b) => b.type === 'traf')) {
      const tfhd = traf.children!.find((b) => b.type === 'tfhd')!;
      const tr = new Reader(tfhd.payload!);
      const trackId = tr.u32();
      let baseDataOffset: number | undefined;
      let defDuration: number | undefined;
      let defSize: number | undefined;
      let defFlags: number | undefined;
      const flags = tfhd.flags!;
      if (flags & TFHD_BASE_DATA_OFFSET) baseDataOffset = Number(tr.u64());
      if (flags & TFHD_DESC_IDX) tr.u32();
      if (flags & TFHD_DEFAULT_DURATION) defDuration = tr.u32();
      if (flags & TFHD_DEFAULT_SIZE) defSize = tr.u32();
      if (flags & TFHD_DEFAULT_FLAGS) defFlags = tr.u32();

      const trex = trexMap.get(trackId);
      if (!trex) throw new Error(`tfhd 引用了未知 trackId=${trackId}`);
      const sampleDuration = defDuration ?? trex.duration;
      const sampleSize = defSize ?? trex.size;
      const sampleFlags = defFlags ?? trex.flags;

      // tfdt
      const tfdt = traf.children!.find((b) => b.type === 'tfdt');
      let baseDts = 0;
      if (tfdt) {
        const rr = new Reader(tfdt.payload!);
        baseDts = tfdt.version === 1 ? Number(rr.u64()) : rr.u32();
      }

      const trun = traf.children!.find((b) => b.type === 'trun');
      if (!trun) throw new Error('traf 缺少 trun');
      const rr = new Reader(trun.payload!);
      const sampleCount = rr.u32();
      let dataOffset = 0;
      if (trun.flags! & TRUN_DATA_OFFSET) dataOffset = rr.u32();
      let firstFlags = 0;
      if (trun.flags! & TRUN_FIRST_FLAGS) firstFlags = rr.u32();

      // 数据基准：默认 base-data-offset 指向 moof 起点
      const base = baseDataOffset ?? moof.start;
      let cursor = base + dataOffset;
      let dts = baseDts;
      const list = samplesByTrack.get(trackId)!;
      const indexBase = list.length;

      for (let s = 0; s < sampleCount; s++) {
        const dur = trun.flags! & TRUN_DURATION ? rr.u32() : sampleDuration;
        const size = trun.flags! & TRUN_SIZE ? rr.u32() : sampleSize;
        let fl = sampleFlags;
        if (trun.flags! & TRUN_FLAGS) fl = rr.u32();
        else if (s === 0 && trun.flags! & TRUN_FIRST_FLAGS) fl = firstFlags;
        let cts = 0;
        if (trun.flags! & TRUN_CTS) {
          cts = trun.version === 1 ? rr.u32() | 0 : (rr.u32() | 0);
        }
        list.push({
          trackId,
          index: indexBase + s,
          moofStart: moof.start,
          start: cursor,
          end: cursor + size,
          size,
          flags: fl,
          duration: dur,
          cts,
          dts,
        });
        cursor += size;
        dts += dur;
      }

      fragments.push({
        index: moofGroups.length - 1,
        moofStart: moof.start,
        moofEnd: moof.start + moof.size,
        mdatStart: mdat.start,
        mdatEnd: mdat.start + mdat.size,
        moof,
        mdat,
        trackId,
      });
    }
  }

  // 时长：最大 (末 sample dts+duration)/timescale
  let durationSec = 0;
  for (const t of tracks) {
    const last = t.samples[t.samples.length - 1];
    if (last) durationSec = Math.max(durationSec, (last.dts + last.duration) / t.timescale);
  }

  return {
    bytes,
    initSegment: bytes.subarray(0, initEnd).slice(),
    initEnd,
    tracks,
    fragments,
    moofGroups,
    durationSec,
  };
}

function parseTracks(moov: Box): Fmp4Track[] {
  const out: Fmp4Track[] = [];
  for (const trak of moov.children!.filter((b) => b.type === 'trak')) {
    const tkhd = findBox(trak.children, ['tkhd'])!;
    const trackId = readTrackId(tkhd);
    const mdhd = findBox(trak.children, ['mdia', 'mdhd'])!;
    const timescale = new Reader(mdhd.payload!).u32(); // mdhd v0: ...timescale 在第 2 个 u32
    // mdhd v0 payload: creation(4) modification(4) timescale(4) duration(4)...
    const mdhdReader = new Reader(mdhd.payload!);
    if (mdhd.version === 1) {
      mdhdReader.u64();
      mdhdReader.u64();
    } else {
      mdhdReader.u32();
      mdhdReader.u32();
    }
    const ts = mdhdReader.u32();

    const hdlr = findBox(trak.children, ['mdia', 'hdlr']);
    const handler = hdlr ? readHandler(hdlr.payload!) : '';
    const kind: 'video' | 'audio' = handler === 'soun' ? 'audio' : 'video';

    const stsd = findBox(trak.children, ['mdia', 'minf', 'stbl', 'stsd'])!;
    const entry = stsd.children![0];
    const codecFourcc = entry.type === 'encv' || entry.type === 'enca'
      ? readOriginalType(entry)
      : entry.type;

    let mseCodec: string;
    let width: number | undefined;
    let height: number | undefined;
    let sampleRate: number | undefined;
    let channels: number | undefined;

    if (kind === 'video') {
      // VisualSampleEntry 固定头：width(u16)@24 后还有 2B horizresolution 前缀，
      // 实际 width@24 是 u16、紧接着的 u16 是 horizresolution 的高 16 位？
      // ISO 14496-12: reserved(6)+dri(2)+pre_defined(2)+reserved(12)+width(2)@24+height(2)@26...
      // 实测 ffmpeg：width 在 rawHeader 偏移 24（u16），height 在 26（u16）
      width = (entry.rawHeader![24] << 8) | entry.rawHeader![25];
      height = (entry.rawHeader![26] << 8) | entry.rawHeader![27];
      mseCodec = buildVideoCodec(codecFourcc, entry.children ?? []);
    } else {
      // rawHeader 已去掉 8 字节 box 头（size+type），内部即 AudioSampleEntry 字段区。
      // ffmpeg 输出的 qt 变体：标准 ISO 字段位（@8 声道/@16 采样率）为 0，
      // 真实值在 qt v1 字段位（@16 声道/@24 采样率 u16）。按“ISO 位是否为 0”判别。
      const h = entry.rawHeader!;
      const isoChannels = (h[8] << 8) | h[9];
      if (isoChannels !== 0) {
        channels = isoChannels;
        sampleRate = readU32(h, 16) >>> 16;
      } else {
        channels = (h[16] << 8) | h[17];
        sampleRate = (h[24] << 8) | h[25];
      }
      mseCodec = buildAudioCodec(codecFourcc, entry.children ?? []);
    }

    out.push({
      trackId,
      kind,
      timescale: ts ?? timescale,
      codecFourcc,
      mseCodec,
      width,
      height,
      sampleRate,
      channels,
      samples: [],
    });
  }
  return out;
}

function readTrackId(tkhd: Box): number {
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

function readHandler(payload: Uint8Array): string {
  // version/flags 已剥离: pre_defined(u32) handler_type(4cc)
  return String.fromCharCode(payload[4], payload[5], payload[6], payload[7]);
}

function readOriginalType(entry: Box): string {
  const frma = entry.children!.find((b) => b.type === 'frma');
  if (!frma) throw new Error('encv/enca 缺少 frma');
  const p = frma.payload!;
  return String.fromCharCode(p[0], p[1], p[2], p[3]);
}

function buildVideoCodec(fourcc: string, children: Box[]): string {
  if (fourcc === 'avc1' || fourcc === 'avc3') {
    const avcC = children.find((b) => b.type === 'avcC');
    if (avcC) {
      const p = avcC.payload!;
      const hex = (x: number) => x.toString(16).padStart(2, '0');
      return `avc1.${hex(p[1])}${hex(p[2])}${hex(p[3])}`;
    }
    return 'avc1.42E01E';
  }
  if (fourcc === 'hvc1' || fourcc === 'hev1') {
    // 简化：完整 HEVC codec string 需要解 hvcC，这里给通用兜底
    const hvcC = children.find((b) => b.type === 'hvcC');
    if (hvcC) return hevcCodecString(hvcC.payload!);
    return 'hvc1.1.6.L93.B0';
  }
  return fourcc;
}

function hevcCodecString(hvcC: Uint8Array): string {
  // hvcC: ... general_profile_space/tier/idc 在偏移 1
  const p = hvcC;
  const profileByte = p[1];
  const profileSpace = profileByte >> 6;
  const tier = (profileByte >> 5) & 1;
  const profileIdc = profileByte & 0x1f;
  const levelIdc = p[12];
  const tag = profileSpace === 0 ? '' : String.fromCharCode(65 + profileSpace - 1);
  return `hvc1.${tag}${profileIdc}.${tier ? 'H' : 'L'}${levelIdc}.B0`;
}

function buildAudioCodec(fourcc: string, _children: Box[]): string {
  if (fourcc === 'mp4a') return 'mp4a.40.2'; // AAC LC，ffmpeg 默认
  return fourcc;
}

/** 取 sample entry 内某个子 box 的 payload（如 avcC/esds） */
export function findChildPayload(entry: Box, type: string): Uint8Array | undefined {
  return entry.children?.find((b) => b.type === type)?.payload;
}
