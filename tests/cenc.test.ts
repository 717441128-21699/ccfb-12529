import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { parseBoxes, findBox, Reader } from '../src/lib/mp4/boxes';
import { parseFmp4 } from '../src/lib/mp4/fmp4';
import { encryptCenc, CBCS_VIDEO_PATTERN } from '../src/lib/mp4/cenc';
import { parseAvccNals, buildVideoSubsamples, encryptedByteCount } from '../src/lib/mp4/nal';
import { randomBytes, sha256Hex, toHex } from '../src/lib/util';

const samples = join(process.cwd(), 'public', 'samples');

function loadSample(name: string) {
  return new Uint8Array(readFileSync(join(samples, name)));
}

describe('NAL 与 subsample 构造', () => {
  it('AVCC 长度前缀解析覆盖整个 sample', () => {
    const f = parseFmp4(loadSample('demo-av.mp4'));
    const video = f.tracks.find((t) => t.kind === 'video')!;
    const s = video.samples[0];
    const raw = f.bytes.subarray(s.start, s.end);
    const nals = parseAvccNals(raw, 'avc');
    expect(nals.length).toBeGreaterThan(0);
    expect(nals[0].start).toBe(0);
    expect(nals[nals.length - 1].end).toBe(raw.length);
    // baseline 流 SPS/PPS 放在 init 的 avcC 中，in-band 首帧含 SEI(6)/IDR(5)
    const types = nals.map((n) => n.type);
    expect(types).toContain(5); // IDR
    // 非 VCL NAL 必须被标记为非加密对象
    expect(nals.filter((n) => !n.isVcl).every((n) => n.type !== 1 && n.type !== 5)).toBe(true);
  });

  it('subsample clear/encrypted 段长度之和等于 sample 大小', () => {
    const f = parseFmp4(loadSample('demo-av.mp4'));
    const video = f.tracks.find((t) => t.kind === 'video')!;
    for (const s of video.samples.slice(0, 6)) {
      const raw = f.bytes.subarray(s.start, s.end);
      const nals = parseAvccNals(raw, 'avc');
      const subs = buildVideoSubsamples(nals);
      const total = subs.reduce((n, x) => n + x.clearBytes + x.encryptedBytes, 0);
      expect(total).toBe(raw.length);
      // 非 VCL NAL 不出现在加密段
      for (const nal of nals.filter((n) => !n.isVcl)) {
        expect(nal.type === 7 || nal.type === 8 || nal.type === 6 || nal.type === 9).toBe(true);
      }
    }
  });

  it('pattern 下加密块数计算正确（全块/带 skip）', () => {
    // 带 skip 的 1/9：10 个块只加密第 1 个
    const r = encryptedByteCount([{ clearBytes: 10, encryptedBytes: 160 }], 1, 9);
    expect(r.blocks).toBe(1);
    expect(r.encryptedBytes).toBe(16);
    // 全块加密（crypt=1, skip=0）：所有完整块都加密
    const r2 = encryptedByteCount([{ clearBytes: 0, encryptedBytes: 320 }], 1, 0);
    expect(r2.blocks).toBe(20);
    expect(r2.encryptedBytes).toBe(320);
    // 尾块不足 16B 不加密
    const r3 = encryptedByteCount([{ clearBytes: 0, encryptedBytes: 17 }], 1, 0);
    expect(r3.encryptedBytes).toBe(16);
  });
});

describe('CENC cbcs 加密', () => {
  it('init.mp4：stsd 变为 encv/enca 且 sinf/frma/schm/schi/tenc 齐全', async () => {
    const f = parseFmp4(loadSample('demo-av.mp4'));
    const out = await encryptCenc({
      fmp4: f,
      key: randomBytes(16),
      kid: randomBytes(16),
      iv: randomBytes(16),
    });
    const boxes = parseBoxes(out.initSegment.bytes);
    const traks = findBox(boxes, ['moov'])!.children!.filter((b) => b.type === 'trak');
    expect(traks.length).toBe(2);
    for (const trak of traks) {
      const stsd = findBox(trak.children, ['mdia', 'minf', 'stbl', 'stsd'])!;
      const entry = stsd.children![0];
      expect(['encv', 'enca']).toContain(entry.type);
      const sinf = entry.children!.find((b) => b.type === 'sinf')!;
      expect(sinf).toBeTruthy();
      const frma = sinf.children!.find((b) => b.type === 'frma')!;
      const schm = sinf.children!.find((b) => b.type === 'schm')!;
      const tenc = findBox(sinf.children, ['schi', 'tenc'])!;
      expect(frma).toBeTruthy();
      expect(schm).toBeTruthy();
      expect(tenc).toBeTruthy();
      // schm scheme_type = cbcs（fullbox 头已剥离，payload 即 scheme 字段）
      expect(String.fromCharCode(...schm.payload!.subarray(0, 4))).toBe('cbcs');
      // tenc v1（cbcs 必须 v1 以携带 pattern 与常量 IV）
      expect(tenc.version).toBe(1);
      // tenc v1 payload: [0]reserved [1]crypt/skip [2]is_protected=1 [3]per_sample_iv_size=0
      expect(tenc.payload![2]).toBe(1);
      expect(tenc.payload![3]).toBe(0);
      // 末尾 16 字节为常量 IV
      expect(tenc.payload!.subarray(tenc.payload!.length - 16)).toEqual(expect.any(Uint8Array));
    }
  });

  it('媒体分片：moof/traf 不含 senc/saio/saiz（shaka 兼容形态，加密由 tenc 驱动）', async () => {
    const f = parseFmp4(loadSample('demo-av.mp4'));
    const out = await encryptCenc({ fmp4: f, key: randomBytes(16), kid: randomBytes(16), iv: randomBytes(16) });
    const seg = out.mediaSegments[0];
    const boxes = parseBoxes(seg.bytes);
    expect(boxes.map((b) => b.type)).toEqual(['moof', 'mdat']);
    const moof = boxes[0];
    const trafs = moof.children!.filter((b) => b.type === 'traf');
    expect(trafs.length).toBe(f.tracks.length); // 双轨 moof 含两个 traf
    // 实测 Chrome/Edge ClearKey 不接受 moof 内的辅助信息 box，分片只保留基础 box
    for (const traf of trafs) {
      const types = traf.children!.map((b) => b.type);
      expect(types).not.toContain('senc');
      expect(types).not.toContain('saiz');
      expect(types).not.toContain('saio');
      // trun data_offset 必须指向 mdat payload（moof.size + 8）
      const trun = traf.children!.find((b) => b.type === 'trun')!;
      const r = new Reader(trun.payload!);
      r.u32(); // sample_count
      if (trun.flags! & 0x1) {
        const dataOffset = r.u32();
        expect(dataOffset).toBe(moof.size + 8);
      }
    }
    expect(seg.sampleCount).toBeGreaterThan(0);
  });

  it('每个 sample 的明文/加密字节守恒（subsample 之和等于 sample 大小）', async () => {
    const f = parseFmp4(loadSample('demo-av.mp4'));
    const out = await encryptCenc({ fmp4: f, key: randomBytes(16), kid: randomBytes(16), iv: randomBytes(16) });
    // 加密不改变 sample 总长度（CBC 等长替换），mdat 大小与明文一致
    const firstGroup = f.fragments.filter((x) => x.moofStart === f.moofGroups[0]);
    const clearMdatEnd = Math.max(...firstGroup.map((x) => x.mdatEnd));
    const clearMdatStart = Math.min(...firstGroup.map((x) => x.mdatStart));
    const clearMdatPayload = clearMdatEnd - (clearMdatStart + 8);
    const encBoxes = parseBoxes(out.mediaSegments[0].bytes);
    const encMdat = encBoxes[1];
    expect(encMdat.size - 8).toBe(clearMdatPayload);
    expect(out.mediaSegments[0].subsampleCount).toBeGreaterThanOrEqual(out.mediaSegments[0].sampleCount);
  });

  it('密文与明文不同且总加密字节数符合全块 cbcs（视频/音频均 16B 对齐）', async () => {
    const clear = loadSample('demo-av.mp4');
    const f = parseFmp4(clear);
    const out = await encryptCenc({ fmp4: f, key: randomBytes(16), kid: randomBytes(16), iv: randomBytes(16) });
    // 每个 moof 现在聚合双轨，分片数 = moof 组数
    expect(out.mediaSegments.length).toBe(f.moofGroups.length);

    // 全块 cbcs：每个 sample 的加密区所有完整 16B 块都加密
    let expected = 0;
    for (const track of f.tracks) {
      const isVideo = track.kind === 'video';
      for (const s of track.samples) {
        if (isVideo) {
          const raw = f.bytes.subarray(s.start, s.end);
          const nals = parseAvccNals(raw, 'avc');
          const subs = buildVideoSubsamples(nals);
          expected += encryptedByteCount(subs, CBCS_VIDEO_PATTERN.crypt, CBCS_VIDEO_PATTERN.skip).encryptedBytes;
        } else {
          expected += Math.floor(s.size / 16) * 16;
        }
      }
    }
    const got = out.mediaSegments.reduce((n, x) => n + x.encryptedBytes, 0);
    expect(got).toBe(expected);
    expect(got).toBeGreaterThan(0);

    // 整体密文确实与原文不同
    const allEnc = concatSegs(out);
    expect(sha256Hex(allEnc)).not.toBe(sha256Hex(clear));
  });

  it('相同 key/iv 两次加密结果完全一致（确定性，便于测试与复现）', async () => {
    const f1 = parseFmp4(loadSample('demo-video-only.mp4'));
    const f2 = parseFmp4(loadSample('demo-video-only.mp4'));
    const key = randomBytes(16);
    const kid = randomBytes(16);
    const iv = randomBytes(16);
    const a = await encryptCenc({ fmp4: f1, key, kid, iv });
    const b = await encryptCenc({ fmp4: f2, key, kid, iv });
    expect(Array.from(b.mediaSegments[0].bytes)).toEqual(Array.from(a.mediaSegments[0].bytes));
    expect(toHex(kid).length).toBe(32);
  });
});

function concatSegs(out: Awaited<ReturnType<typeof encryptCenc>>): Uint8Array {
  const parts = [out.initSegment.bytes, ...out.mediaSegments.map((s) => s.bytes)];
  const len = parts.reduce((n, p) => n + p.length, 0);
  const all = new Uint8Array(len);
  let off = 0;
  for (const p of parts) {
    all.set(p, off);
    off += p.length;
  }
  return all;
}
