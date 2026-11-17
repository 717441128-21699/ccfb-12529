/**
 * 打包编排：素材 fMP4 → CENC cbcs 加密 → 分片哈希 → 清单 → IndexedDB / .cpkg 导出。
 */

import {
  KeyRecord,
  PackageFile,
  PackageManifest,
  SegmentCryptoInfo,
  TrackMeta,
  WatermarkConfig,
} from '../types';
import { base64Encode, base64urlEncode, formatBytes, sha256Hex, toHex } from './util';
import { encryptCenc, EncryptedSegment, parseFmp4 } from './mp4/cenc';
import { generateCourseSecrets } from './crypto/keystore';
import { storage } from './storage';

export const DEFAULT_WATERMARK: WatermarkConfig = {
  moveIntervalSec: 8,
  opacity: 0.35,
  fontSizeRatio: 0.055,
  cornerWatermarks: true,
};

export interface PackageProgress {
  phase: string;
  current: number;
  total: number;
}

export interface PackageResult {
  manifest: PackageManifest;
  keyRecord: KeyRecord;
  segments: EncryptedSegment[];
}

export interface PackageOptions {
  title: string;
  courseId?: string;
  watermark?: WatermarkConfig;
  onProgress?: (p: PackageProgress) => void;
}

export async function packageCourse(
  fmp4Bytes: Uint8Array,
  sourceName: string,
  opts: PackageOptions,
): Promise<PackageResult> {
  const courseId = opts.courseId ?? `course-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e6).toString(36)}`;
  const wm = opts.watermark ?? DEFAULT_WATERMARK;
  const onProgress = opts.onProgress ?? (() => undefined);

  onProgress({ phase: '解析 fMP4 盒子结构', current: 0, total: 4 });
  const fmp4 = parseFmp4(fmp4Bytes);
  if (fmp4.fragments.length === 0) throw new Error('素材中没有任何媒体分片（moof/mdat）');

  const secrets = generateCourseSecrets();
  onProgress({ phase: 'CENC cbcs 加密分片', current: 1, total: 4 });
  const enc = await encryptCenc({ fmp4, key: secrets.key, kid: secrets.kid, iv: secrets.iv });

  onProgress({ phase: '计算分片 SHA-256', current: 2, total: 4 });
  const segmentInfos: SegmentCryptoInfo[] = [];
  const allSegments = [enc.initSegment, ...enc.mediaSegments];
  for (const seg of allSegments) {
    segmentInfos.push(await toSegmentInfo(seg, toHex(secrets.kid), toHex(secrets.iv)));
  }

  const tracks: TrackMeta[] = fmp4.tracks.map((t) => ({
    kind: t.kind,
    codec: t.codecFourcc,
    width: t.width,
    height: t.height,
    sampleRate: t.sampleRate,
    channels: t.channels,
    mseCodec: t.mseCodec,
  }));

  const manifest: PackageManifest = {
    format: 'courseguard-pkg',
    version: 1,
    courseId,
    title: opts.title,
    createdAt: Date.now(),
    kid: toHex(secrets.kid),
    iv: toHex(secrets.iv),
    watermarkSeed: base64urlEncode(secrets.watermarkSeed),
    watermark: wm,
    tracks,
    segments: segmentInfos,
    source: sourceName,
    durationSec: Math.round(fmp4.durationSec * 10) / 10,
  };

  const keyRecord: KeyRecord = {
    courseId,
    kid: manifest.kid,
    key: secrets.key,
    iv: secrets.iv,
    watermarkSeed: secrets.watermarkSeed,
    createdAt: manifest.createdAt,
  };

  onProgress({ phase: '写入本地库', current: 3, total: 4 });
  await storage.putPackage(manifest);
  await storage.putKey(keyRecord);
  for (const seg of allSegments) {
    await storage.putSegment(courseId, seg.fileName, seg.bytes);
  }

  onProgress({ phase: '完成', current: 4, total: 4 });
  return { manifest, keyRecord, segments: allSegments };
}

async function toSegmentInfo(seg: EncryptedSegment, kid: string, iv: string): Promise<SegmentCryptoInfo> {
  return {
    index: seg.kind === 'init' ? -1 : seg.index,
    kind: seg.kind,
    fileName: seg.fileName,
    clearSize: seg.clearSize,
    encryptedSize: seg.bytes.length,
    scheme: 'cbcs',
    kid,
    iv,
    sampleCount: seg.sampleCount,
    encryptedSamples: seg.encryptedSamples,
    subsampleCount: seg.subsampleCount,
    encryptedBytes: seg.encryptedBytes,
    sha256: await sha256Hex(seg.bytes),
  };
}

/** 导出单文件 .cpkg（JSON + base64 分片），便于拷贝/备份（不含 CEK） */
export async function exportPackageFile(manifest: PackageManifest): Promise<PackageFile> {
  const blobs: Record<string, string> = {};
  for (const info of manifest.segments) {
    const bytes = await storage.getSegment(manifest.courseId, info.fileName);
    if (!bytes) throw new Error(`本地缺少分片 ${info.fileName}`);
    blobs[info.fileName] = base64Encode(bytes);
  }
  return { manifest, blobs };
}

/** 导入 .cpkg 到本地库（不包含密钥，播放仍需授权） */
export async function importPackageFile(file: PackageFile): Promise<PackageManifest> {
  if (file.manifest.format !== 'courseguard-pkg') throw new Error('不是 CourseGuard 课程包');
  await storage.putPackage(file.manifest);
  for (const [name, b64] of Object.entries(file.blobs)) {
    const bin = base64ToBytes(b64);
    await storage.putSegment(file.manifest.courseId, name, bin);
  }
  return file.manifest;
}

function base64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export function packageSizeSummary(manifest: PackageManifest): string {
  const total = manifest.segments.reduce((n, s) => n + s.encryptedSize, 0);
  return formatBytes(total);
}
