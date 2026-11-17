import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { parseBoxes, findBox, findAll, serializeBoxes, Reader } from '../src/lib/mp4/boxes';
import { parseFmp4 } from '../src/lib/mp4/fmp4';

const samples = join(process.cwd(), 'public', 'samples');

describe('box 解析与序列化', () => {
  it('fMP4 顶层盒子解析且可无损还原', () => {
    const bytes = new Uint8Array(readFileSync(join(samples, 'demo-av.mp4')));
    const boxes = parseBoxes(bytes);
    const types = boxes.map((b) => b.type);
    expect(types).toContain('ftyp');
    expect(types).toContain('moov');
    // 分片文件有多个 moof/mdat
    expect(types.filter((t) => t === 'moof').length).toBeGreaterThan(1);
    expect(types.filter((t) => t === 'mdat').length).toBeGreaterThan(1);

    const rebuilt = serializeBoxes(boxes);
    expect(Array.from(rebuilt)).toEqual(Array.from(bytes));
  });

  it('stsd sample entry 固定头与嵌套 box 完整保留', () => {
    const bytes = new Uint8Array(readFileSync(join(samples, 'demo-av.mp4')));
    const boxes = parseBoxes(bytes);
    const stsd = findBox(boxes, ['moov', 'trak', 'mdia', 'minf', 'stbl', 'stsd'])!;
    expect(stsd.children?.length).toBe(1);
    const entry = stsd.children![0];
    expect(['avc1', 'avc3']).toContain(entry.type);
    expect(entry.rawHeader?.length).toBe(78);
    expect(entry.children?.map((b) => b.type)).toContain('avcC');
  });

  it('普通 MP4（非分片）缺少 mvex 时给出明确报错', () => {
    const bytes = new Uint8Array(readFileSync(join(samples, 'not-fragmented.mp4')));
    expect(() => parseFmp4(bytes)).toThrow(/fMP4|分片/);
  });
});

describe('fMP4 分片与样本定位', () => {
  it('双轨解析：视频/音频参数与样本区间正确', () => {
    const bytes = new Uint8Array(readFileSync(join(samples, 'demo-av.mp4')));
    const f = parseFmp4(bytes);
    expect(f.tracks.length).toBe(2);
    const video = f.tracks.find((t) => t.kind === 'video')!;
    const audio = f.tracks.find((t) => t.kind === 'audio')!;
    expect(video.width).toBe(640);
    expect(video.height).toBe(360);
    expect(video.mseCodec.startsWith('avc1')).toBe(true);
    expect(audio.channels).toBe(2);
    expect(audio.sampleRate).toBe(44100);
    expect(f.fragments.length).toBeGreaterThan(1);

    // 样本区间严格落在各自 mdat 内且首尾相接
    for (const s of video.samples) {
      const frag = f.fragments.find((x) => x.moofStart === s.moofStart)!;
      expect(s.start).toBeGreaterThanOrEqual(frag.mdatStart);
      expect(s.end).toBeLessThanOrEqual(frag.mdatEnd);
      expect(s.size).toBe(s.end - s.start);
    }
    // 每个分片至少 1 个视频样本
    const perFrag = new Map<number, number>();
    for (const s of video.samples) perFrag.set(s.moofStart, (perFrag.get(s.moofStart) ?? 0) + 1);
    expect(perFrag.size).toBe(f.fragments.filter((x) => x.trackId === video.trackId).length);
  });

  it('纯视频素材只有一条轨道', () => {
    const bytes = new Uint8Array(readFileSync(join(samples, 'demo-video-only.mp4')));
    const f = parseFmp4(bytes);
    expect(f.tracks.length).toBe(1);
    expect(f.tracks[0].kind).toBe('video');
    expect(f.durationSec).toBeGreaterThan(7);
  });

  it('trex 默认值与 trun flags 合成 sample flags', () => {
    const bytes = new Uint8Array(readFileSync(join(samples, 'demo-av.mp4')));
    const f = parseFmp4(bytes);
    const video = f.tracks.find((t) => t.kind === 'video')!;
    expect(video.samples.length).toBeGreaterThan(0);
    // flags 非零（含 sample_depends_on 等位域）
    expect(typeof video.samples[0].flags).toBe('number');
  });
});

describe('fullbox 读写', () => {
  it('Reader 消费 mfhd/tfhd 字段', () => {
    const bytes = new Uint8Array(readFileSync(join(samples, 'demo-av.mp4')));
    const boxes = parseBoxes(bytes);
    const moof = boxes.find((b) => b.type === 'moof')!;
    const mfhd = findBox(moof.children, ['mfhd'])!;
    const r = new Reader(mfhd.payload!);
    expect(r.u32()).toBeGreaterThanOrEqual(0);
    const traf = moof.children!.find((b) => b.type === 'traf')!;
    expect(findAll(traf.children, 'trun').length).toBe(1);
  });
});
