/**
 * 学员水印：半透明、定时漂移、四角微水印。
 * 位置序列由 (课程 watermarkSeed, 学员编号) 派生的确定性 PRNG 生成，
 * 同课程每个学员的漂移轨迹不同；溯源时用相同种子重建轨迹做匹配。
 */

import { WatermarkConfig } from '../../types';
import { sha256, utf8 } from '../util';

/** mulberry32 —— 32bit 种子确定性 PRNG，足够做位置调度（非安全场景） */
export class Mulberry32 {
  private state: number;
  constructor(seed: number) {
    this.state = seed >>> 0;
  }
  next(): number {
    this.state = (this.state + 0x6d2b79f5) >>> 0;
    let t = this.state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }
  /** [min, max) */
  range(min: number, max: number): number {
    return min + this.next() * (max - min);
  }
}

/** 由课程种子 + 学员编号派生 32bit PRNG 种子 */
export async function watermarkRngSeed(courseSeed: Uint8Array, studentId: string): Promise<number> {
  const merged = new Uint8Array(courseSeed.length + utf8(studentId).length);
  merged.set(courseSeed, 0);
  merged.set(utf8(studentId), courseSeed.length);
  const digest = await sha256(merged);
  const view = new DataView(digest.buffer, digest.byteOffset, 4);
  return view.getUint32(0, true);
}

export interface WatermarkSlot {
  /** 槽位起始时间（秒） */
  timeSec: number;
  /** 主水印归一化中心坐标 0~1（相对视频显示区域） */
  x: number;
  y: number;
  /** 旋转角度（度），增加裁剪/遮挡对抗性 */
  rotation: number;
  /** 四角微水印开关位图（左上/右上/左下/右下） */
  corners: boolean[];
}

/**
 * 生成整门课的水印槽位序列。
 * 位置在安全边距内随机，且与上一槽位保持最小距离，保证肉眼可感知“漂移”。
 */
export async function buildWatermarkSchedule(
  courseSeed: Uint8Array,
  studentId: string,
  durationSec: number,
  cfg: WatermarkConfig,
): Promise<WatermarkSlot[]> {
  const seed = await watermarkRngSeed(courseSeed, studentId);
  const rng = new Mulberry32(seed);
  const slotCount = Math.max(1, Math.ceil(durationSec / cfg.moveIntervalSec) + 1);
  const margin = 0.12;
  const slots: WatermarkSlot[] = [];
  let prevX = 0.5;
  let prevY = 0.5;
  for (let i = 0; i < slotCount; i++) {
    let x = rng.range(margin, 1 - margin);
    let y = rng.range(margin, 1 - margin);
    // 与上一槽位至少 22% 对角距离，避免视觉上“没动”
    for (let tries = 0; tries < 8 && Math.hypot(x - prevX, y - prevY) < 0.22; tries++) {
      x = rng.range(margin, 1 - margin);
      y = rng.range(margin, 1 - margin);
    }
    const rotation = rng.range(-18, 18);
    const corners = [rng.next() > 0.5, rng.next() > 0.5, rng.next() > 0.5, rng.next() > 0.5];
    slots.push({ timeSec: i * cfg.moveIntervalSec, x, y, rotation, corners });
    prevX = x;
    prevY = y;
  }
  return slots;
}

export function slotAtTime(slots: WatermarkSlot[], timeSec: number): WatermarkSlot {
  let cur = slots[0];
  for (const s of slots) {
    if (s.timeSec <= timeSec) cur = s;
    else break;
  }
  return cur;
}

export interface TraceCandidate {
  studentId: string;
  studentName: string;
}

export interface TraceMatch {
  studentId: string;
  studentName: string;
  slot: WatermarkSlot;
  /** 归一化欧氏距离 0~1 */
  distance: number;
  score: number;
}

/**
 * 溯源反查：对每个候选学员重建水印序列，在截图时间点（未知则全序列）找最近槽位。
 * @param queryX/queryY 截图上水印中心的归一化坐标
 * @param queryTimeSec 截图对应的视频时间（可从播放器画面/进度条估计；未知给 undefined 做全序列匹配）
 */
export async function traceLeak(
  candidates: TraceCandidate[],
  courseSeed: Uint8Array,
  durationSec: number,
  cfg: WatermarkConfig,
  queryX: number,
  queryY: number,
  queryTimeSec?: number,
): Promise<TraceMatch[]> {
  const matches: TraceMatch[] = [];
  for (const c of candidates) {
    const slots = await buildWatermarkSchedule(courseSeed, c.studentId, durationSec, cfg);
    let considered = slots;
    if (queryTimeSec !== undefined) {
      // 时间不确定 ±1 个槽位窗口
      const lo = queryTimeSec - cfg.moveIntervalSec;
      const hi = queryTimeSec + cfg.moveIntervalSec;
      considered = slots.filter((s) => s.timeSec >= lo && s.timeSec <= hi);
      if (considered.length === 0) considered = [slotAtTime(slots, queryTimeSec)];
    }
    let best: TraceMatch | null = null;
    for (const slot of considered) {
      const distance = Math.hypot(slot.x - queryX, slot.y - queryY) / Math.SQRT2;
      const score = Math.max(0, 1 - distance * 2.2); // 经验权重：同位置≈1，半屏外≈0
      if (!best || score > best.score) {
        best = { studentId: c.studentId, studentName: c.studentName, slot, distance, score };
      }
    }
    if (best) matches.push(best);
  }
  return matches.sort((a, b) => b.score - a.score);
}

/** 溯源用文字水印内容（主水印 + 角标统一格式） */
export function watermarkText(studentId: string, studentName: string): string {
  return `${studentName} ${studentId}`;
}
