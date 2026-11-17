/** 水印溯源：上传泄露截图 → 点选水印中心 → 用课程种子重建各学员漂移轨迹 → 排名反查 */

import { storage } from '../lib/storage';
import { traceLeak, TraceMatch } from '../lib/crypto/watermark';
import { base64urlDecode } from '../lib/util';
import { esc, toast } from '../app';

interface Mark { x: number; y: number }

export async function tracePage(root: HTMLElement): Promise<void> {
  const packages = await storage.listPackages();
  const students = await storage.listStudents();

  root.innerHTML = `
    <div class="card">
      <h3>① 选择泄露课程并上传截图</h3>
      <div class="grid cols-2">
        <div><label>课程（提供水印种子与漂移参数）</label>
          <select id="tr-course">${packages.map((p) => `<option value="${esc(p.courseId)}">${esc(p.title)}</option>`).join('')}</select>
        </div>
        <div><label>截图对应的视频时间（秒，可选；留空做全序列匹配）</label>
          <input id="tr-time" type="number" min="0" step="0.5" placeholder="如 16，不确定可留空" /></div>
      </div>
      <div style="margin-top:12px"><label>泄露录屏截图</label>
        <input type="file" id="tr-file" accept="image/*" /></div>
      <p class="file-hint" style="margin-top:8px">
        上传后在图上<strong>点击水印文字的中心</strong>，系统记录归一化坐标 (x,y)。可多点采样提高置信度。
      </p>
    </div>

    <div class="card">
      <h3>② 在截图上标注水印位置</h3>
      <div id="tr-canvas-wrap" class="empty"><div class="icon">🖼️</div>上传截图后在此点选</div>
      <div class="row" style="margin-top:10px">
        <div id="tr-marks" class="pill-row"></div>
        <span class="spacer"></span>
        <button id="tr-clear" class="small">清除标注</button>
        <button class="primary" id="tr-run" disabled>③ 开始反查学员</button>
      </div>
    </div>

    <div class="card">
      <h3>④ 反查结果（按匹配置信度排序）</h3>
      <div id="tr-result"><div class="empty">结果将显示在这里</div></div>
    </div>

    <div class="card">
      <h3>原理</h3>
      <p class="file-hint" style="line-height:1.8">
        每个学员的水印漂移轨迹由 <span class="mono">PRNG(课程水印种子 + 学员编号)</span> 确定性生成，同课程学员轨迹互不相同。
        拿到截图后，系统为每个在册学员重建完整位置序列，计算标注点与各槽位的归一化距离并打分。
        真正的泄露者会在对应时间槽位上以接近 0 的距离、接近 1 的置信度排名第一。
        多点采样时取各点平均距离，抗单点误差。
      </p>
      <div class="file-hint">在册候选学员：${students.length} 人</div>
    </div>`;

  let marks: Mark[] = [];
  let imgEl: HTMLImageElement | null = null;

  const fileInput = root.querySelector<HTMLInputElement>('#tr-file');
  const wrap = root.querySelector('#tr-canvas-wrap')!;
  const marksEl = root.querySelector('#tr-marks')!;
  const runBtn = root.querySelector<HTMLButtonElement>('#tr-run')!;

  fileInput?.addEventListener('change', () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    const url = URL.createObjectURL(file);
    imgEl = document.createElement('img');
    imgEl.src = url;
    imgEl.style.maxWidth = '100%';
    imgEl.style.display = 'block';
    imgEl.style.cursor = 'crosshair';
    wrap.classList.remove('empty');
    wrap.innerHTML = '';
    wrap.appendChild(imgEl);
    marks = [];
    imgEl.addEventListener('load', () => bindClick());
  });

  function bindClick(): void {
    imgEl!.addEventListener('click', (ev) => {
      const rect = imgEl!.getBoundingClientRect();
      const x = (ev.clientX - rect.left) / rect.width;
      const y = (ev.clientY - rect.top) / rect.height;
      marks.push({ x, y });
      renderMarks();
    });
  }

  function renderMarks(): void {
    marksEl.innerHTML = marks.map((m, i) =>
      `<span class="badge blue">#${i + 1} (${m.x.toFixed(3)}, ${m.y.toFixed(3)})</span>`).join('');
    runBtn.disabled = marks.length === 0;
  }

  root.querySelector<HTMLElement>('#tr-clear')?.addEventListener('click', () => {
    marks = [];
    renderMarks();
  });

  runBtn.addEventListener('click', async () => {
    const courseId = (root.querySelector('#tr-course') as HTMLSelectElement).value;
    const manifest = await storage.getPackage(courseId);
    if (!manifest) return toast('课程包不存在', 'err');
    const allStudents = await storage.listStudents();
    if (allStudents.length === 0) return toast('没有在册学员可比对', 'err');

    const timeRaw = (root.querySelector('#tr-time') as HTMLInputElement).value;
    const queryTime = timeRaw === '' ? undefined : Number(timeRaw);
    const seed = base64urlDecode(manifest.watermarkSeed);
    runBtn.disabled = true;
    runBtn.textContent = '反查中…';

    // 每个标注点独立反查后融合排名
    const perMark: TraceMatch[][] = [];
    for (const m of marks) {
      const matches = await traceLeak(
        allStudents.map((s) => ({ studentId: s.studentId, studentName: s.name })),
        seed, manifest.durationSec, manifest.watermark, m.x, m.y, queryTime,
      );
      perMark.push(matches);
    }

    // 融合：按学员聚合各标注点的最佳分数取均值
    const agg = new Map<string, { studentId: string; studentName: string; scores: number[]; slots: TraceMatch[] }>();
    for (const matches of perMark) {
      for (const match of matches) {
        const cur = agg.get(match.studentId) ?? {
          studentId: match.studentId, studentName: match.studentName, scores: [], slots: [],
        };
        cur.scores.push(match.score);
        cur.slots.push(match);
        agg.set(match.studentId, cur);
      }
    }
    const ranked = [...agg.values()]
      .map((a) => ({
        ...a,
        avgScore: a.scores.reduce((n, x) => n + x, 0) / a.scores.length,
      }))
      .sort((a, b) => b.avgScore - a.avgScore);

    renderResult(ranked, marks.length);
    runBtn.disabled = false;
    runBtn.textContent = '③ 开始反查学员';
  });

  function renderResult(ranked: { studentId: string; studentName: string; avgScore: number; slots: TraceMatch[] }[], sampleCount: number): void {
    const el = root.querySelector('#tr-result')!;
    const top = ranked[0];
    el.innerHTML = `
      <div style="margin-bottom:14px">
        ${top && top.avgScore > 0.6
          ? `<span class="badge green" style="font-size:13px">🎯 最可能泄露者：${esc(top.studentName)}（${esc(top.studentId)}）平均置信度 ${(top.avgScore * 100).toFixed(1)}%</span>`
          : `<span class="badge amber">置信度偏低（最高分 ${(top?.avgScore ?? 0 * 100).toFixed(1)}%），建议增加标注点或核对截图时间</span>`}
      </div>
      <table>
        <thead><tr><th>排名</th><th>学员</th><th>平均置信度</th><th>最佳槽位时间</th><th>槽位坐标(x,y)</th><th>标注点数</th></tr></thead>
        <tbody>
          ${ranked.slice(0, 10).map((r, i) => {
            const best = r.slots.reduce((a, b) => (b.score > a.score ? b : a));
            return `<tr style="${i === 0 ? 'background:rgba(63,185,80,0.08)' : ''}">
              <td><strong>#${i + 1}</strong></td>
              <td>${esc(r.studentName)}<div class="file-hint mono">${esc(r.studentId)}</div></td>
              <td>
                <div class="progress-bar" style="width:120px;display:inline-block;vertical-align:middle">
                  <div style="width:${r.avgScore * 100}%;background:${r.avgScore > 0.6 ? 'var(--green)' : 'var(--amber)'}"></div>
                </div>
                <span class="mono">${(r.avgScore * 100).toFixed(1)}%</span>
              </td>
              <td class="mono">${best.slot.timeSec}s</td>
              <td class="mono">(${best.slot.x.toFixed(3)}, ${best.slot.y.toFixed(3)})</td>
              <td class="mono">${sampleCount}</td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>`;
  }
}
