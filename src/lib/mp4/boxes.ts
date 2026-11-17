/**
 * ISO-BMFF / fMP4 box 解析与构造（CENC 加密所需的最小子集）。
 *
 * 设计：
 * - parseBoxes() 解析整棵 box 树；普通容器挂 children；
 * - stsd 的 sample entry 是“固定头 + 嵌套 box”混合结构，保留 rawHeader，
 *   其内部 box 挂在 children 上，重写时按 rawHeader + children 原样拼回；
 * - 叶子 box（mdat、free、senc 等）保留 raw 字节，避免解析全部业务数据；
 * - serialize() 可整树拼回，因此加密流程只需原地改 box（加 sinf、加 senc…）。
 */

export interface Box {
  type: string;
  /** 完整 box 字节（含 size/type，可能含 largesize/version+flags），叶子 box 使用 */
  raw: Uint8Array;
  /** fullbox 的 version（非 fullbox 为 undefined） */
  version?: number;
  /** fullbox 的 flags（24bit 整数） */
  flags?: number;
  /** 容器 box 的子节点 */
  children?: Box[];
  /** stsd sample entry 的固定头（avc1=78B, mp4a=28B…），重写时原样保留 */
  rawHeader?: Uint8Array;
  /** 叶子 box 的 payload（去掉 size/type/version+flags） */
  payload?: Uint8Array;
  /** 原始起点（解析时记录，便于调试） */
  start: number;
  /** 原始总大小 */
  size: number;
}

const CONTAINER_TYPES = new Set([
  'moov',
  'trak',
  'mdia',
  'minf',
  'stbl',
  'mvex',
  'moof',
  'traf',
  'edts',
  'dinf',
  'sinf',
  'schi',
]);

/** 标准 sample entry 固定头长度（ISO 14496-12 8.8.2 / 8.8.3），qt 变体在解析时动态探测 */
const SAMPLE_ENTRY_HEADER_SIZE: Record<string, number> = {
  avc1: 78,
  avc3: 78,
  hvc1: 78,
  hev1: 78,
  encv: 78,
  mp4a: 28,
  enca: 28,
  'ac-3': 28,
  'ec-3': 28,
};

/** 已知 4cc box 类型（用于探测 qt 变体音频 entry 的固定头真实长度） */
const KNOWN_BOX_TYPES = new Set([
  'avcC', 'hvcC', 'esds', 'sinf', 'btrt', 'pasp', 'colr', 'clap', 'd263',
  'dfLa', 'dfLa', 'ac-3', 'dec3', 'dOps', 'dtsc', 'mhaC', 'vpcC', 'av1C',
]);

const FULLBOX_TYPES = new Set([
  'mvhd', 'tkhd', 'mdhd', 'hdlr', 'vmhd', 'smhd', 'dref', 'stsd',
  'stts', 'stsc', 'stsz', 'stco', 'co64', 'stss', 'ctts', 'elst',
  'mehd', 'trex', 'mfhd', 'tfhd', 'trun', 'tfdt', 'sdtp', 'senc',
  'saiz', 'saio', 'pdin', 'schm', 'tenc',
]);

/** 4 字节 type 转字符串 */
export function typeStr(t: Uint8Array, off = 0): string {
  return String.fromCharCode(t[off], t[off + 1], t[off + 2], t[off + 3]);
}

function strType(s: string): Uint8Array {
  return new Uint8Array([s.charCodeAt(0), s.charCodeAt(1), s.charCodeAt(2), s.charCodeAt(3)]);
}

/**
 * 探测 sample entry 固定头的真实长度。
 * entry 起点 p（含 size/type），内容从 p+8 开始；标准固定头长 standardFixed。
 * 从 standardFixed 起每 2 字节步进，找第一个 type 命中已知嵌套 box 且 size 自洽的位置。
 * 找不到则回退标准长度。
 */
function probeHeaderLength(data: Uint8Array, p: number, entSize: number, standardFixed: number): number {
  const contentStart = p + 8;
  const contentEnd = p + entSize;
  for (let off = standardFixed; off + 8 <= entSize; off += 2) {
    const childSize = readU32(data, contentStart + off);
    const t = typeStr(data, contentStart + off + 4);
    if (KNOWN_BOX_TYPES.has(t) && childSize >= 8 && contentStart + off + childSize <= contentEnd) {
      return off;
    }
  }
  return standardFixed;
}

/** 递归解析一段字节流中的所有顶层 box */
export function parseBoxes(data: Uint8Array, start = 0, end = data.length): Box[] {
  const boxes: Box[] = [];
  let off = start;
  while (off + 8 <= end) {
    let size = readU32(data, off);
    const type = typeStr(data, off + 4);
    let headerLen = 8;
    if (size === 1) {
      // largesize（64bit）
      size = Number(readU64(data, off + 8));
      headerLen = 16;
    } else if (size === 0) {
      // box 延伸到文件尾
      size = end - off;
    }
    if (size < headerLen || off + size > end) {
      throw new Error(`box ${type} 长度非法 @${off}: size=${size}, 剩余=${end - off}`);
    }
    boxes.push(parseOne(data, off, size, type, headerLen));
    off += size;
  }
  if (off !== end) throw new Error(`box 流解析后剩余 ${end - off} 字节未消费`);
  return boxes;
}

function parseOne(data: Uint8Array, start: number, size: number, type: string, headerLen: number): Box {
  const raw = data.subarray(start, start + size);
  const box: Box = { type, raw: raw.slice(), start, size };

  if (type === 'stsd') {
    // fullbox: version(1)+flags(3)+entry_count(4)，随后是 sample entry 列表
    box.version = data[start + headerLen];
    box.flags = readU24(data, start + headerLen + 1);
    const entryCount = readU32(data, start + headerLen + 4);
    const children: Box[] = [];
    let p = start + headerLen + 8;
    for (let i = 0; i < entryCount; i++) {
      const entSize = readU32(data, p);
      const entType = typeStr(data, p + 4);
      const standardFixed = SAMPLE_ENTRY_HEADER_SIZE[entType];
      if (!standardFixed) throw new Error(`不支持的 sample entry: ${entType}`);
      // qt 变体（如 ffmpeg 的 mp4a）固定头可能比 ISO 标准长：
      // 从标准长度起逐个 4 字节扫描第一个“合法嵌套 box”，其起点即固定头结束位置。
      const fixed = probeHeaderLength(data, p, entSize, standardFixed);
      const entry: Box = {
        type: entType,
        raw: data.subarray(p, p + entSize).slice(),
        rawHeader: data.subarray(p + 8, p + 8 + fixed).slice(),
        children: parseBoxes(data, p + 8 + fixed, p + entSize),
        start: p,
        size: entSize,
      };
      children.push(entry);
      p += entSize;
    }
    box.children = children;
    return box;
  }

  if (CONTAINER_TYPES.has(type)) {
    box.children = parseBoxes(data, start + headerLen, start + size);
    return box;
  }

  if (FULLBOX_TYPES.has(type)) {
    box.version = data[start + headerLen];
    box.flags = readU24(data, start + headerLen + 1);
    box.payload = data.subarray(start + headerLen + 4, start + size).slice();
    return box;
  }

  // 叶子 box
  box.payload = data.subarray(start + headerLen, start + size).slice();
  return box;
}

/** 序列化整棵 box 树（容器递归；叶子用 payload 重拼，fullbox 补 version/flags） */
export function serializeBoxes(boxes: Box[]): Uint8Array {
  const parts: Uint8Array[] = [];
  for (const b of boxes) parts.push(serializeOne(b));
  return concat(parts);
}

function serializeOne(b: Box): Uint8Array {
  if (b.type === 'stsd') {
    const inner = concat(b.children!.map(serializeSampleEntry));
    const body = concat([
      u8(b.version ?? 0),
      u24(b.flags ?? 0),
      u32(b.children!.length),
      inner,
    ]);
    return wrap(b.type, body);
  }
  if (b.rawHeader) return serializeSampleEntry(b);
  if (b.children) return wrap(b.type, concat(b.children.map(serializeOne)));
  if (b.flags !== undefined) {
    return wrap(b.type, concat([u8(b.version ?? 0), u24(b.flags), b.payload ?? new Uint8Array(0)]));
  }
  return wrap(b.type, b.payload ?? new Uint8Array(0));
}

function serializeSampleEntry(b: Box): Uint8Array {
  const inner = concat((b.children ?? []).map(serializeOne));
  const body = concat([b.rawHeader!, inner]);
  return wrap(b.type, body);
}

/** 构造普通 box（自动加 8 字节头） */
export function makeBox(type: string, payload: Uint8Array): Box {
  return { type, payload, raw: new Uint8Array(0), start: -1, size: payload.length + 8 };
}

/** 构造 fullbox */
export function makeFullBox(type: string, version: number, flags: number, payload: Uint8Array): Box {
  return {
    type,
    version,
    flags,
    payload,
    raw: new Uint8Array(0),
    start: -1,
    size: payload.length + 12,
  };
}

function wrap(type: string, payload: Uint8Array): Uint8Array {
  return concat([u32(payload.length + 8), strType(type), payload]);
}

/** 深度优先查找第一个匹配 type 的 box（可给路径，如 ['moov','mvex','trex']） */
export function findBox(boxes: Box[] | undefined, path: string[]): Box | undefined {
  let list: Box[] | undefined = boxes;
  let cur: Box | undefined;
  for (const t of path) {
    cur = list?.find((b) => b.type === t);
    if (!cur) return undefined;
    list = cur.children;
  }
  return cur;
}

export function findAll(boxes: Box[] | undefined, type: string): Box[] {
  const out: Box[] = [];
  const walk = (list?: Box[]) => {
    if (!list) return;
    for (const b of list) {
      if (b.type === type) out.push(b);
      if (b.children) walk(b.children);
    }
  };
  walk(boxes);
  return out;
}

// ---------- 基础数值读写 ----------

export function readU32(d: Uint8Array, o: number): number {
  return d[o] * 0x1000000 + ((d[o + 1] << 16) | (d[o + 2] << 8) | d[o + 3]);
}

export function readU24(d: Uint8Array, o: number): number {
  return (d[o] << 16) | (d[o + 1] << 8) | d[o + 2];
}

export function readU64(d: Uint8Array, o: number): bigint {
  let v = 0n;
  for (let i = 0; i < 8; i++) v = (v << 8n) | BigInt(d[o + i]);
  return v;
}

export function u8(v: number): Uint8Array {
  return new Uint8Array([v & 0xff]);
}

export function u16(v: number): Uint8Array {
  return new Uint8Array([(v >> 8) & 0xff, v & 0xff]);
}

export function u24(v: number): Uint8Array {
  return new Uint8Array([(v >> 16) & 0xff, (v >> 8) & 0xff, v & 0xff]);
}

export function u32(v: number): Uint8Array {
  return new Uint8Array([(v >>> 24) & 0xff, (v >>> 16) & 0xff, (v >>> 8) & 0xff, v & 0xff]);
}

export function u64(v: bigint): Uint8Array {
  const out = new Uint8Array(8);
  let x = v;
  for (let i = 7; i >= 0; i--) {
    out[i] = Number(x & 0xffn);
    x >>= 8n;
  }
  return out;
}

export function concat(parts: Uint8Array[]): Uint8Array {
  let len = 0;
  for (const p of parts) len += p.length;
  const out = new Uint8Array(len);
  let off = 0;
  for (const p of parts) {
    out.set(p, off);
    off += p.length;
  }
  return out;
}

// ---------- fullbox 字段读取辅助 ----------

export class Reader {
  off = 0;
  d: Uint8Array;
  constructor(d: Uint8Array) {
    this.d = d;
  }
  u8(): number {
    return this.d[this.off++];
  }
  u16(): number {
    const v = (this.d[this.off] << 8) | this.d[this.off + 1];
    this.off += 2;
    return v >>> 0;
  }
  u24(): number {
    const v = (this.d[this.off] << 16) | (this.d[this.off + 1] << 8) | this.d[this.off + 2];
    this.off += 3;
    return v >>> 0;
  }
  u32(): number {
    const v = readU32(this.d, this.off);
    this.off += 4;
    return v;
  }
  u64(): bigint {
    const v = readU64(this.d, this.off);
    this.off += 8;
    return v;
  }
  bytes(n: number): Uint8Array {
    const v = this.d.subarray(this.off, this.off + n).slice();
    this.off += n;
    return v;
  }
  get eof(): boolean {
    return this.off >= this.d.length;
  }
}

export class Writer {
  private parts: Uint8Array[] = [];
  private len = 0;
  u8(v: number): this {
    this.push(new Uint8Array([v & 0xff]));
    return this;
  }
  u16(v: number): this {
    this.push(u16(v));
    return this;
  }
  u24(v: number): this {
    this.push(u24(v));
    return this;
  }
  u32(v: number): this {
    this.push(u32(v));
    return this;
  }
  u64(v: bigint): this {
    this.push(u64(v));
    return this;
  }
  bytes(b: Uint8Array): this {
    this.push(b);
    return this;
  }
  private push(b: Uint8Array): void {
    this.parts.push(b);
    this.len += b.length;
  }
  result(): Uint8Array {
    return concat(this.parts);
  }
  get length(): number {
    return this.len;
  }
}
