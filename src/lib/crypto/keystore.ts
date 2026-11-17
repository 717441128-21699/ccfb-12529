/**
 * 密钥管理（本地模拟 KMS）：
 * - 发行方 ECDSA-P256 签名密钥对，用于给 .lic 授权文件签名/验签；
 * - 每课程随机 KID/CEK/常量 IV/水印种子，存 IndexedDB；
 * - 课程密钥用发行方公钥指纹做逻辑归属，全部操作仅在浏览器本地完成。
 */

import { KeyRecord, PackageManifest, StudentRecord } from '../../types';
import { base64urlDecode, base64urlEncode, canonicalJson, fromHex, randomBytes, sha256Hex, toHex, utf8 } from '../util';

const ISSUER_KEY_ID = 'issuer-p256-local';
const JWK_STORE_KEY = 'courseguard.issuer.jwk';

export interface IssuerKeyPair {
  keyId: string;
  privateKey: CryptoKey;
  publicKey: CryptoKey;
  publicJwk: JsonWebKey;
}

async function getIssuerPairRaw(): Promise<IssuerKeyPair> {
  const stored = localStorage.getItem(JWK_STORE_KEY);
  if (stored) {
    const jwk = JSON.parse(stored) as JsonWebKey;
    const privateKey = await crypto.subtle.importKey(
      'jwk', jwk,
      { name: 'ECDSA', namedCurve: 'P-256' },
      true, ['sign'],
    );
    const publicJwk = { ...jwk };
    delete publicJwk.d;
    publicJwk.key_ops = ['verify'];
    const publicKey = await crypto.subtle.importKey(
      'jwk', publicJwk,
      { name: 'ECDSA', namedCurve: 'P-256' },
      true, ['verify'],
    );
    return { keyId: ISSUER_KEY_ID, privateKey, publicKey, publicJwk };
  }
  const pair = await crypto.subtle.generateKey(
    { name: 'ECDSA', namedCurve: 'P-256' },
    true,
    ['sign', 'verify'],
  );
  const jwk = await crypto.subtle.exportKey('jwk', pair.privateKey);
  localStorage.setItem(JWK_STORE_KEY, JSON.stringify(jwk));
  const publicJwk = await crypto.subtle.exportKey('jwk', pair.publicKey);
  return { keyId: ISSUER_KEY_ID, privateKey: pair.privateKey, publicKey: pair.publicKey, publicJwk };
}

let cachedPair: IssuerKeyPair | null = null;

export async function getIssuerKeyPair(): Promise<IssuerKeyPair> {
  if (!cachedPair) cachedPair = await getIssuerPairRaw();
  return cachedPair;
}

/** 导出公钥 JWK（播放端验签用，随应用分发） */
export async function exportIssuerPublicJwk(): Promise<JsonWebKey> {
  return (await getIssuerKeyPair()).publicJwk;
}

export async function issuerKeyFingerprint(): Promise<string> {
  const jwk = await exportIssuerPublicJwk();
  return (await sha256Hex(utf8(canonicalJson(jwk)))).slice(0, 16);
}

/** 对 canonical JSON 做 ECDSA 签名，统一输出 base64url(raw r||s, 64B) */
export async function signCanonical(value: unknown): Promise<{ signature: string; issuerKeyId: string }> {
  const pair = await getIssuerKeyPair();
  const data = utf8(canonicalJson(value));
  const sig = new Uint8Array(
    await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, pair.privateKey, data as BufferSource),
  );
  // 浏览器返回 DER（0x30 开头，约 70~72B）；Node 可能直接返回 raw 64B
  const raw = sig.length === 64 && sig[0] !== 0x30 ? sig : derToRaw(sig);
  return { signature: base64urlEncode(raw), issuerKeyId: pair.keyId };
}

/** 验签（播放端只持有公钥）。raw 与 DER 两种签名格式都尝试，兼容浏览器/Node 实现 */
export async function verifyCanonical(value: unknown, signatureB64: string, publicJwk: JsonWebKey): Promise<boolean> {
  try {
    const publicKey = await crypto.subtle.importKey(
      'jwk', publicJwk,
      { name: 'ECDSA', namedCurve: 'P-256' },
      false, ['verify'],
    );
    const raw = base64urlToBytes(signatureB64);
    const der = rawToDer(raw);
    const data = utf8(canonicalJson(value));
    // 优先 DER（Chrome/Edge 要求），失败再试 raw（Node 实现）
    const derOk = await crypto.subtle.verify(
      { name: 'ECDSA', hash: 'SHA-256' },
      publicKey,
      der as BufferSource,
      data as BufferSource,
    ).catch(() => false);
    if (derOk) return true;
    return crypto.subtle.verify(
      { name: 'ECDSA', hash: 'SHA-256' },
      publicKey,
      raw as BufferSource,
      data as BufferSource,
    ).catch(() => false);
  } catch {
    return false;
  }
}

// DER(seq(r,s)) <-> raw r||s（各 32B）
function derToRaw(der: Uint8Array): Uint8Array {
  let off = 1; // 0x30 SEQUENCE
  // 跳过 SEQUENCE 长度（短形式 1B；长形式 1+nB）
  if (der[off] & 0x80) off += 1 + (der[off] & 0x7f);
  else off += 1;
  const readInt = (): Uint8Array => {
    if (der[off++] !== 0x02) throw new Error('DER 缺少 INTEGER');
    const len = der[off++];
    const v = der.subarray(off, off + len);
    off += len;
    return v.length > 32 ? v.subarray(v.length - 32) : v;
  };
  const r = readInt();
  const s = readInt();
  const out = new Uint8Array(64);
  out.set(r, 32 - r.length);
  out.set(s, 64 - s.length);
  return out;
}

function rawToDer(raw: Uint8Array): Uint8Array {
  if (raw.length !== 64) throw new Error('raw 签名必须为 64 字节');
  const encInt = (x: Uint8Array): Uint8Array => {
    let i = 0;
    while (i < x.length - 1 && x[i] === 0) i++;
    let v = x.subarray(i);
    if (v[0] & 0x80) v = new Uint8Array([0, ...v]);
    return new Uint8Array([0x02, v.length, ...v]);
  };
  const r = encInt(raw.subarray(0, 32));
  const s = encInt(raw.subarray(32, 64));
  const body = new Uint8Array(r.length + s.length);
  body.set(r, 0);
  body.set(s, r.length);
  if (body.length < 128) return new Uint8Array([0x30, body.length, ...body]);
  return new Uint8Array([0x30, 0x81, body.length, ...body]);
}

// ---------------- 课程密钥生成 ----------------

export function generateCourseSecrets(): { kid: Uint8Array; key: Uint8Array; iv: Uint8Array; watermarkSeed: Uint8Array } {
  return {
    kid: randomBytes(16),
    key: randomBytes(16), // AES-128 CEK
    iv: randomBytes(16), // cbcs 常量 IV
    watermarkSeed: randomBytes(32),
  };
}

export function keyRecordFromManifest(manifest: PackageManifest, secrets: {
  key: Uint8Array; iv: Uint8Array; watermarkSeed: Uint8Array;
}): KeyRecord {
  return {
    courseId: manifest.courseId,
    kid: manifest.kid,
    key: secrets.key,
    iv: secrets.iv,
    watermarkSeed: secrets.watermarkSeed,
    createdAt: manifest.createdAt,
  };
}

export function cekToClearKeyFormat(_kidHex: string, key: Uint8Array): string {
  // ClearKey license 的 keys[].k 使用 base64url
  return base64urlEncode(key);
}

export function kidHexToClearKeyId(kidHex: string): string {
  return base64urlEncode(fromHex(kidHex));
}

export function studentFingerprint(student: StudentRecord): Promise<string> {
  return sha256Hex(utf8(`${student.studentId}|${student.name}`));
}

export { toHex };

const base64urlToBytes = base64urlDecode;
