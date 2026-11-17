#!/usr/bin/env node
/**
 * 生成演示用 fMP4 素材到 public/samples/。
 * 输出均为 empty_moov 分片 MP4（含 ftyp+moov(mvex)+ 多个 moof/mdat），可直接被本项目解析加密。
 * 仅用于本地原型，不参与应用运行时逻辑。
 */
import { execFileSync } from 'node:child_process';
import { mkdirSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const outDir = join(here, '..', 'public', 'samples');
mkdirSync(outDir, { recursive: true });

const FRAG = '-movflags +frag_keyframe+empty_moov+default_base_moof';
const common = ['-y', '-f', 'lavfi'];

function run(args: string[]): void {
  console.log('ffmpeg', args.map((a) => (a.includes(' ') ? `"${a}"` : a)).join(' '));
  execFileSync('ffmpeg', args, { stdio: 'inherit' });
}

// 1) 视频 + 音频主素材：测试图案 + 正弦音，12 秒，24fps，2 秒一个 GOP
run([
  ...common,
  '-i', 'testsrc2=size=640x360:rate=24:duration=12',
  '-f', 'lavfi',
  '-i', 'sine=frequency=880:duration=12',
  '-c:v', 'libx264', '-profile:v', 'baseline', '-level', '3.0', '-pix_fmt', 'yuv420p',
  '-g', '48', '-keyint_min', '48', '-sc_threshold', '0',
  '-c:a', 'aac', '-b:a', '64k', '-ar', '44100', '-ac', '2',
  ...FRAG.split(' '),
  join(outDir, 'demo-av.mp4'),
]);

// 2) 纯视频素材（验证无音频轨道路径）
run([
  ...common,
  '-i', 'testsrc=size=480x270:rate=15:duration=8',
  '-c:v', 'libx264', '-profile:v', 'main', '-pix_fmt', 'yuv420p',
  '-g', '30', '-keyint_min', '30', '-sc_threshold', '0',
  ...FRAG.split(' '),
  join(outDir, 'demo-video-only.mp4'),
]);

// 3) 静态画面素材（模拟 PPT 录屏课，体积小）
run([
  ...common,
  '-i', 'color=c=0x1f3a5f:size=640x360:rate=12:duration=6',
  '-vf', "drawtext=text='CourseGuard Demo':fontcolor=white:fontsize=36:x=(w-text_w)/2:y=(h-text_h)/2",
  '-c:v', 'libx264', '-profile:v', 'baseline', '-pix_fmt', 'yuv420p',
  '-g', '24', ...FRAG.split(' '),
  join(outDir, 'demo-slide.mp4'),
]);

// 4) 非 fMP4 的普通 MP4（用于测试导入时的错误提示路径）
run([
  ...common,
  '-i', 'testsrc=size=320x180:rate=10:duration=3',
  '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-g', '30',
  join(outDir, 'not-fragmented.mp4'),
]);

console.log('素材生成完成 ->', outDir);
console.log(existsSync(outDir) ? 'OK' : 'FAIL');
