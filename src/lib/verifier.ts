/**
 * 播放前完整性校验：逐分片重算 SHA-256 与清单比对。
 * 任何一个字节被改动 → 哈希不匹配 → 拒绝播放并报出具体分片，
 * 而不是把坏数据喂给解码器导致花屏。
 */

import { PackageManifest, SegmentCryptoInfo } from '../types';
import { sha256Hex } from './util';
import { storage } from './storage';

export interface SegmentVerifyResult {
  info: SegmentCryptoInfo;
  ok: boolean;
  actualSha256?: string;
  error?: string;
}

export interface VerifyReport {
  ok: boolean;
  results: SegmentVerifyResult[];
  checkedAt: number;
}

export async function verifyPackage(
  manifest: PackageManifest,
  opts: { onProgress?: (cur: number, total: number, info: SegmentCryptoInfo) => void } = {},
): Promise<VerifyReport> {
  const results: SegmentVerifyResult[] = [];
  let ok = true;
  for (let i = 0; i < manifest.segments.length; i++) {
    const info = manifest.segments[i];
    opts.onProgress?.(i, manifest.segments.length, info);
    const bytes = await storage.getSegment(manifest.courseId, info.fileName);
    if (!bytes) {
      ok = false;
      results.push({ info, ok: false, error: '本地缺少该分片文件' });
      continue;
    }
    const actual = await sha256Hex(bytes);
    const match = actual === info.sha256;
    if (!match) ok = false;
    results.push({
      info,
      ok: match,
      actualSha256: actual,
      ...(match ? {} : { error: `哈希不匹配：期望 ${info.sha256.slice(0, 16)}… 实际 ${actual.slice(0, 16)}…` }),
    });
  }
  return { ok, results, checkedAt: Date.now() };
}

/** 单分片即时校验（播放到该片前调用） */
export async function verifyOneSegment(
  manifest: PackageManifest,
  fileName: string,
): Promise<SegmentVerifyResult> {
  const info = manifest.segments.find((s) => s.fileName === fileName);
  if (!info) throw new Error(`清单中不存在分片 ${fileName}`);
  const bytes = await storage.getSegment(manifest.courseId, fileName);
  if (!bytes) return { info, ok: false, error: '本地缺少该分片文件' };
  const actual = await sha256Hex(bytes);
  const match = actual === info.sha256;
  return {
    info,
    ok: match,
    actualSha256: actual,
    ...(match ? {} : { error: `分片 ${fileName} 已损坏或被篡改（SHA-256 不匹配），已阻止解码` }),
  };
}
