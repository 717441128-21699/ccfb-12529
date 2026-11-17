/**
 * 学员授权（.lic）：签发、验签、有效期/吊销校验。
 * 签名内容 = 除 signature 外全部字段的 canonical JSON，ECDSA-P256/SHA-256。
 */

import { LicenseFile } from '../../types';
import { base64urlEncode, fromHex, utf8 } from '../util';
import { signCanonical, verifyCanonical } from './keystore';

export interface IssueLicenseInput {
  studentId: string;
  studentName: string;
  courseId: string;
  kid: string; // hex
  expiresAt: number;
  revocationVersion: number;
  allowSpeed?: number[];
  allowSeek?: boolean;
}

export async function issueLicense(input: IssueLicenseInput): Promise<LicenseFile> {
  const unsigned = {
    format: 'courseguard-license',
    version: 1,
    studentId: input.studentId,
    studentName: input.studentName,
    courseId: input.courseId,
    kid: input.kid,
    issuedAt: Date.now(),
    expiresAt: input.expiresAt,
    revocationVersion: input.revocationVersion,
    scope: {
      allowSpeed: input.allowSpeed ?? [0.75, 1, 1.25, 1.5, 2],
      allowSeek: input.allowSeek ?? true,
    },
  } satisfies Omit<LicenseFile, 'signature' | 'issuerKeyId'>;

  const { signature, issuerKeyId } = await signCanonical(unsigned);
  return { ...unsigned, signature, issuerKeyId };
}

/** 验签 + 字段完整性。返回错误信息数组，空数组表示通过。 */
export async function verifyLicense(
  lic: LicenseFile,
  publicJwk: JsonWebKey,
  now: number = Date.now(),
): Promise<string[]> {
  const errors: string[] = [];
  if (lic.format !== 'courseguard-license' || lic.version !== 1) errors.push('授权文件格式/版本不识别');

  // 签名覆盖范围 = 除 signature 与 issuerKeyId 外的全部字段（与 issueLicense 的 unsigned 一致）
  const { signature, issuerKeyId: _issuerKeyId, ...unsigned } = lic;
  void _issuerKeyId;
  const ok = await verifyCanonical(unsigned, signature, publicJwk);
  if (!ok) errors.push('授权签名无效（文件可能被篡改）');

  if (now < lic.issuedAt - 5 * 60 * 1000) errors.push('授权尚未生效（系统时间早于签发时间）');
  if (now >= lic.expiresAt) errors.push(`授权已于 ${new Date(lic.expiresAt).toLocaleString()} 到期`);
  if (!/^[0-9a-f]{32}$/i.test(lic.kid)) errors.push('KID 字段非法');
  return errors;
}

/** 吊销检查：授权携带的 revocationVersion 低于学员当前吊销版本即失效 */
export function checkRevocation(lic: LicenseFile, currentRevocationVersion: number): string | null {
  if (lic.revocationVersion < currentRevocationVersion) {
    return `授权已被吊销（授权版本 v${lic.revocationVersion} < 当前版本 v${currentRevocationVersion}）`;
  }
  return null;
}

export function licenseToFileBlob(lic: LicenseFile): Blob {
  return new Blob([JSON.stringify(lic, null, 2)], { type: 'application/json' });
}

export function parseLicenseFile(text: string): LicenseFile {
  const obj = JSON.parse(text) as LicenseFile;
  if (obj.format !== 'courseguard-license') throw new Error('不是 CourseGuard 授权文件');
  return obj;
}

/** ClearKey 许可证内容（本地 DRM 服务返回给 EME 的 JSON） */
export interface ClearKeyLicense {
  keys: { kty: 'oct'; kid: string; k: string }[];
  type: 'temporary' | 'persistent';
}

export function buildClearKeyLicense(kidHex: string, cek: Uint8Array): ClearKeyLicense {
  return {
    keys: [
      {
        kty: 'oct',
        kid: base64urlEncode(fromHex(kidHex)),
        k: base64urlEncode(cek),
      },
    ],
    type: 'temporary',
  };
}

/** 解析 EME 发来的 ClearKey license request（base64 的 JSON，含 kids） */
export function parseClearKeyMessage(message: ArrayBuffer): { kids: string[]; type: string } {
  const text = new TextDecoder().decode(message);
  const json = JSON.parse(text) as { kids?: string[]; type?: string };
  return { kids: json.kids ?? [], type: json.type ?? '' };
}

export function encodeClearKeyLicense(lic: ClearKeyLicense): ArrayBuffer {
  return utf8(JSON.stringify(lic)).buffer as ArrayBuffer;
}

export function licenseFingerprint(lic: LicenseFile): string {
  return base64urlEncode(new Uint8Array(0)).length >= 0
    ? `${lic.studentId}@${lic.courseId}`
    : '';
}
