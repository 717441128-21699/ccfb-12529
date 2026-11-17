import { describe, expect, it } from 'vitest';
import {
  base64urlDecode,
  base64urlEncode,
  canonicalJson,
  fromHex,
  randomBytes,
  sha256Hex,
  toHex,
} from '../src/lib/util';
import { exportIssuerPublicJwk, signCanonical, verifyCanonical } from '../src/lib/crypto/keystore';
import { checkRevocation, issueLicense, verifyLicense, buildClearKeyLicense } from '../src/lib/crypto/license';
import { Mulberry32, buildWatermarkSchedule, slotAtTime, traceLeak, watermarkRngSeed } from '../src/lib/crypto/watermark';

describe('编码工具', () => {
  it('hex / base64url 往返', () => {
    const b = randomBytes(40);
    expect(fromHex(toHex(b))).toEqual(b);
    expect(base64urlDecode(base64urlEncode(b))).toEqual(b);
  });

  it('canonicalJson 键排序稳定', () => {
    expect(canonicalJson({ b: 1, a: 2, c: { z: 1, y: 2 } }))
      .toBe('{"a":2,"b":1,"c":{"y":2,"z":1}}');
    expect(canonicalJson([1, { b: 2, a: 1 }])).toBe('[1,{"a":1,"b":2}]');
  });

  it('sha256 已知向量', async () => {
    const enc = new TextEncoder();
    expect(await sha256Hex(enc.encode('abc')))
      .toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
  });
});

describe('ECDSA 签名与授权', () => {
  it('canonical 签名可验签，篡改即失败', async () => {
    const payload = { kid: toHex(randomBytes(16)), exp: 123 };
    const { signature } = await signCanonical(payload);
    const jwk = await exportIssuerPublicJwk();
    expect(await verifyCanonical(payload, signature, jwk)).toBe(true);
    expect(await verifyCanonical({ ...payload, exp: 999 }, signature, jwk)).toBe(false);
  });

  it('授权文件签发/验签/到期/吊销全流程', async () => {
    const jwk = await exportIssuerPublicJwk();
    const now = Date.now();
    const lic = await issueLicense({
      studentId: 'STU001',
      studentName: '张三',
      courseId: 'C-DEMO',
      kid: toHex(randomBytes(16)),
      expiresAt: now + 3600_000,
      revocationVersion: 2,
    });
    expect(await verifyLicense(lic, jwk, now)).toEqual([]);

    // 篡改学员编号 → 签名失败
    const tampered = { ...lic, studentId: 'STU999' };
    expect(await verifyLicense(tampered, jwk, now)).toContain('授权签名无效（文件可能被篡改）');

    // 到期
    const expired = await verifyLicense(lic, jwk, now + 3600_001);
    expect(expired.some((e) => e.includes('到期'))).toBe(true);

    // 吊销：当前版本高于授权携带版本
    expect(checkRevocation(lic, 3)).toContain('吊销');
    expect(checkRevocation(lic, 2)).toBeNull();
    expect(checkRevocation(lic, 1)).toBeNull();
  });

  it('ClearKey 许可证 KID/CEK 为 base64url 且可还原', () => {
    const kid = randomBytes(16);
    const cek = randomBytes(16);
    const lic = buildClearKeyLicense(toHex(kid), cek);
    expect(lic.keys[0].kty).toBe('oct');
    expect(base64urlDecode(lic.keys[0].k)).toEqual(cek);
    expect(base64urlDecode(lic.keys[0].kid)).toEqual(kid);
  });
});

describe('水印调度与溯源', () => {
  it('PRNG 确定性：同种子序列一致，异种子序列不同', () => {
    const a = new Mulberry32(12345);
    const b = new Mulberry32(12345);
    const c = new Mulberry32(999);
    const sa = Array.from({ length: 8 }, () => a.next());
    const sb = Array.from({ length: 8 }, () => b.next());
    const sc = Array.from({ length: 8 }, () => c.next());
    expect(sa).toEqual(sb);
    expect(sa).not.toEqual(sc);
  });

  it('同学员同课程的水印序列可复现，不同学员轨迹不同', async () => {
    const seed = randomBytes(32);
    const cfg = { moveIntervalSec: 5, opacity: 0.35, fontSizeRatio: 0.055, cornerWatermarks: true };
    const s1 = await buildWatermarkSchedule(seed, 'STU001', 60, cfg);
    const s1again = await buildWatermarkSchedule(seed, 'STU001', 60, cfg);
    const s2 = await buildWatermarkSchedule(seed, 'STU002', 60, cfg);
    expect(s1).toEqual(s1again);
    expect(s1[0]).not.toEqual(s2[0]);
    expect(s1.every((x) => x.x > 0 && x.x < 1 && x.y > 0 && x.y < 1)).toBe(true);
    // 槽位时间按间隔排布
    expect(s1[1].timeSec - s1[0].timeSec).toBe(5);
    // PRNG 种子确实由 学员编号 参与派生
    expect(await watermarkRngSeed(seed, 'STU001')).not.toBe(await watermarkRngSeed(seed, 'STU002'));
  });

  it('溯源：拿真实槽位坐标反查，对应学员排第一且高分', async () => {
    const seed = randomBytes(32);
    const cfg = { moveIntervalSec: 8, opacity: 0.35, fontSizeRatio: 0.055, cornerWatermarks: true };
    const duration = 80;
    const students = [
      { studentId: 'STU001', studentName: '张三' },
      { studentId: 'STU002', studentName: '李四' },
      { studentId: 'STU003', studentName: '王五' },
    ];
    // 取 STU002 在 t=16s 的槽位模拟“截到的水印位置”
    const target = await buildWatermarkSchedule(seed, 'STU002', duration, cfg);
    const slot = slotAtTime(target, 16);
    const matches = await traceLeak(students, seed, duration, cfg, slot.x, slot.y, 16);
    expect(matches[0].studentId).toBe('STU002');
    expect(matches[0].score).toBeGreaterThan(0.95);
  });

  it('溯源：未知截图时间时仍能在全序列中命中', async () => {
    const seed = randomBytes(32);
    const cfg = { moveIntervalSec: 8, opacity: 0.35, fontSizeRatio: 0.055, cornerWatermarks: true };
    const target = await buildWatermarkSchedule(seed, 'STU007', 100, cfg);
    const slot = target[5];
    const matches = await traceLeak(
      [
        { studentId: 'STU007', studentName: '赵六' },
        { studentId: 'STU008', studentName: '钱七' },
      ],
      seed, 100, cfg, slot.x, slot.y,
    );
    expect(matches[0].studentId).toBe('STU007');
  });
});
