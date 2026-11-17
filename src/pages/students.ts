/** 学员授权页：学员 CRUD、按课程签发带到期时间的 .lic、吊销版本管理 */

import { LicenseFile } from '../types';
import { storage } from '../lib/storage';
import { issueLicense, licenseToFileBlob, verifyLicense, checkRevocation } from '../lib/crypto/license';
import { exportIssuerPublicJwk } from '../lib/crypto/keystore';
import { download, esc, readFileText, toast } from '../app';
import { formatTime } from '../lib/util';

export async function studentsPage(root: HTMLElement): Promise<void> {
  await render(root);
}

async function render(root: HTMLElement): Promise<void> {
  const students = await storage.listStudents();
  const packages = await storage.listPackages();
  const jwk = await exportIssuerPublicJwk();

  root.innerHTML = `
    <div class="grid cols-2">
      <div class="card">
        <h3>① 新增学员</h3>
        <div class="stack">
          <div><label>学员编号（登录名，将叠在水印上）</label><input id="st-id" placeholder="如 STU2026001" /></div>
          <div><label>姓名</label><input id="st-name" placeholder="如 张三" /></div>
          <div><label>备注（可选）</label><input id="st-note" /></div>
          <div class="row end"><button class="primary" id="st-add">添加学员</button></div>
        </div>
      </div>
      <div class="card">
        <h3>② 签发授权 .lic（绑定学员 + 课程 + 到期时间）</h3>
        ${students.length === 0 || packages.length === 0
          ? '<div class="empty">需要先有学员和已打包课程</div>'
          : `<div class="stack">
               <div><label>学员</label>
                 <select id="lic-student">${students.map((s) => `<option value="${esc(s.studentId)}">${esc(s.studentId)} · ${esc(s.name)}</option>`).join('')}</select></div>
               <div><label>课程</label>
                 <select id="lic-course">${packages.map((p) => `<option value="${esc(p.courseId)}">${esc(p.title)}</option>`).join('')}</select></div>
               <div class="grid cols-2">
                 <div><label>有效天数</label><input id="lic-days" type="number" min="1" value="30" /></div>
                 <div><label>或指定到期日</label><input id="lic-date" type="datetime-local" /></div>
               </div>
               <div class="row end"><button class="primary" id="lic-issue">🎫 签发并下载 .lic</button></div>
             </div>`}
      </div>
    </div>

    <div class="card">
      <h3>③ 学员与吊销状态（${students.length}）</h3>
      ${students.length === 0
        ? '<div class="empty"><div class="icon">👥</div>暂无学员</div>'
        : `<div class="table-wrap" style="overflow-x:auto"><table>
            <thead><tr><th>编号</th><th>姓名</th><th>状态</th><th>吊销版本</th><th>备注</th><th>创建时间</th><th>操作</th></tr></thead>
            <tbody>${students.map((s) => `
              <tr>
                <td class="mono"><strong>${esc(s.studentId)}</strong></td>
                <td>${esc(s.name)}</td>
                <td>${s.revoked ? '<span class="badge red">已吊销</span>' : '<span class="badge green">正常</span>'}</td>
                <td class="mono">v${s.revocationVersion}</td>
                <td>${esc(s.note ?? '')}</td>
                <td class="mono">${formatTime(s.createdAt)}</td>
                <td class="row">
                  <button class="small danger" data-revoke="${esc(s.studentId)}" ${s.revoked ? 'disabled' : ''}>吊销</button>
                  <button class="small danger" data-remove="${esc(s.studentId)}">删除</button>
                </td>
              </tr>`).join('')}
            </tbody></table></div>`}
    </div>

    <div class="card">
      <h3>④ 校验 .lic 文件（验签 / 到期 / 吊销）</h3>
      <input type="file" id="lic-verify" accept=".lic,application/json" />
      <div id="lic-verify-result" style="margin-top:12px"></div>
    </div>`;

  root.querySelector<HTMLElement>('#st-add')?.addEventListener('click', async () => {
    const id = (root.querySelector('#st-id') as HTMLInputElement).value.trim();
    const name = (root.querySelector('#st-name') as HTMLInputElement).value.trim();
    const note = (root.querySelector('#st-note') as HTMLInputElement).value.trim();
    if (!id || !name) return toast('编号和姓名必填', 'err');
    if (await storage.getStudent(id)) return toast('该学员编号已存在', 'err');
    await storage.putStudent({
      studentId: id, name, createdAt: Date.now(), revocationVersion: 0, revoked: false, note: note || undefined,
    });
    toast(`学员 ${id} 已添加`, 'ok');
    void render(root);
  });

  root.querySelectorAll<HTMLElement>('[data-revoke]').forEach((b) =>
    b.addEventListener('click', async () => {
      const id = b.dataset.revoke!;
      if (!confirm(`吊销学员 ${id}？其所有已签发 .lic 在下次校验/播放时立即失效（版本号递增）`)) return;
      const s = (await storage.getStudent(id))!;
      const nextVersion = s.revocationVersion + 1;
      await storage.putStudent({ ...s, revoked: true, revocationVersion: nextVersion });
      toast(`已吊销，当前版本 v${nextVersion}`, 'ok');
      void render(root);
    }));

  root.querySelectorAll<HTMLElement>('[data-remove]').forEach((b) =>
    b.addEventListener('click', async () => {
      if (!confirm('确认删除该学员记录？')) return;
      await storage.deleteStudent(b.dataset.remove!);
      void render(root);
    }));

  root.querySelector<HTMLElement>('#lic-issue')?.addEventListener('click', async () => {
    const studentId = (root.querySelector('#lic-student') as HTMLSelectElement).value;
    const courseId = (root.querySelector('#lic-course') as HTMLSelectElement).value;
    const days = Number((root.querySelector('#lic-days') as HTMLInputElement).value);
    const dateStr = (root.querySelector('#lic-date') as HTMLInputElement).value;
    const student = (await storage.getStudent(studentId))!;
    const manifest = await storage.getPackage(courseId);
    if (!manifest) return toast('课程不存在', 'err');
    const expiresAt = dateStr ? new Date(dateStr).getTime() : Date.now() + days * 86400_000;
    const currentRev = await storage.getRevocation(courseId);
    const lic = await issueLicense({
      studentId, studentName: student.name, courseId, kid: manifest.kid,
      expiresAt, revocationVersion: Math.max(student.revocationVersion, currentRev),
    });
    download(`${studentId}.${courseId}.lic`, licenseToFileBlob(lic));
    toast(`授权已签发，到期 ${new Date(expiresAt).toLocaleString()}`, 'ok');
  });

  const verifyInput = root.querySelector<HTMLInputElement>('#lic-verify');
  verifyInput?.addEventListener('change', async () => {
    const file = verifyInput.files?.[0];
    const resultEl = root.querySelector('#lic-verify-result')!;
    if (!file) return;
    try {
      const lic = JSON.parse(await readFileText(file)) as LicenseFile;
      const errors = await verifyLicense(lic, jwk);
      const student = await storage.getStudent(lic.studentId);
      const revError = student ? checkRevocation(lic, student.revocationVersion) : '本地无该学员记录';
      const allErrors = [...errors];
      if (student && student.revoked && revError) allErrors.push(revError);
      if (!student) allErrors.push(String(revError));
      resultEl.innerHTML = `
        <dl class="kv">
          <dt>学员</dt><dd>${esc(lic.studentName)}（${esc(lic.studentId)}）</dd>
          <dt>课程</dt><dd class="mono">${esc(lic.courseId)}</dd>
          <dt>KID</dt><dd class="mono tiny">${esc(lic.kid)}</dd>
          <dt>有效期</dt><dd class="mono">${formatTime(lic.issuedAt)} → ${formatTime(lic.expiresAt)}</dd>
          <dt>吊销版本</dt><dd class="mono">v${lic.revocationVersion}</dd>
          <dt>结论</dt><dd>${allErrors.length === 0
            ? '<span class="badge green">✓ 授权有效</span>'
            : allErrors.map((e) => `<span class="badge red">✗ ${esc(e)}</span>`).join('<br/>')}</dd>
        </dl>`;
    } catch (e) {
      resultEl.innerHTML = `<span class="badge red">文件解析失败：${esc((e as Error).message)}</span>`;
    }
  });
}
