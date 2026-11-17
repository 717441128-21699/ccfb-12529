/** 密钥管理页：发行方公钥指纹、每课程 KID/CEK/IV/水印种子（本地 KMS 模拟） */

import { storage } from '../lib/storage';
import { exportIssuerPublicJwk, issuerKeyFingerprint } from '../lib/crypto/keystore';
import { download, esc, toast } from '../app';
import { base64urlEncode, formatTime, toHex } from '../lib/util';

export async function keysPage(root: HTMLElement): Promise<void> {
  const keys = await storage.listKeys();
  const packages = await storage.listPackages();
  const fp = await issuerKeyFingerprint();
  const jwk = await exportIssuerPublicJwk();

  root.innerHTML = `
    <div class="card">
      <h3>发行方签名密钥（ECDSA P-256，本地生成，用于 .lic 签名）</h3>
      <dl class="kv">
        <dt>keyId</dt><dd class="mono">issuer-p256-local</dd>
        <dt>公钥指纹</dt><dd class="mono">${esc(fp)}</dd>
        <dt>算法</dt><dd>ECDSA P-256 / SHA-256，签名输出 raw r||s（存储 base64url）</dd>
      </dl>
      <div class="row" style="margin-top:10px">
        <button id="keys-pub">查看/导出公钥 JWK</button>
      </div>
    </div>
    <div class="card">
      <h3>课程内容密钥（每课程独立，AES-128 CEK + cbcs 常量 IV）</h3>
      ${keys.length === 0
        ? '<div class="empty"><div class="icon">🗝️</div>尚无课程密钥，完成「加密打包」后自动生成</div>'
        : `<div class="table-wrap" style="overflow-x:auto"><table>
            <thead><tr><th>课程</th><th>KID</th><th>CEK（仅本机）</th><th>常量 IV</th><th>水印种子</th><th>创建时间</th></tr></thead>
            <tbody>${keys.map((k) => `
              <tr>
                <td><strong>${esc(packages.find((p) => p.courseId === k.courseId)?.title ?? k.courseId)}</strong>
                    <div class="file-hint mono">${esc(k.courseId)}</div></td>
                <td class="mono tiny">${esc(k.kid)}</td>
                <td class="mono tiny" title="ClearKey k 字段值">${esc(toHex(k.key))}<div class="file-hint">ck:${esc(base64urlEncode(k.key))}</div></td>
                <td class="mono tiny">${esc(toHex(k.iv))}</td>
                <td class="mono tiny">${esc(toHex(k.watermarkSeed).slice(0, 32))}…</td>
                <td class="mono">${formatTime(k.createdAt)}</td>
              </tr>`).join('')}
            </tbody></table></div>
        <p class="file-hint" style="margin-top:10px">
          ⚠️ CEK 仅存在浏览器 IndexedDB，导出的 .cpkg 不含密钥；学员拿到课程包后，必须凭 .lic 由本地许可证服务换取 ClearKey 才能播放。
        </p>`}
    </div>`;

  root.querySelector<HTMLElement>('#keys-pub')?.addEventListener('click', () => {
    const json = JSON.stringify(jwk, null, 2);
    download('issuer-public.jwk.json', json, 'application/json');
    toast('公钥 JWK 已导出（可随播放端分发验签）', 'ok');
  });
}
