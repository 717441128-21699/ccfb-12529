/**
 * 全局类型定义：课程包、授权、密钥、水印、分片加密信息。
 * 所有二进制字段在 IndexedDB 中以 Uint8Array 保存，在 .cpkg 导出时转 base64url。
 */

/** 分片（segment）级加密信息，打包页面逐片展示 */
export interface SegmentCryptoInfo {
  /** 分片序号，从 0 开始 */
  index: number;
  /** 初始化分片(init)还是媒体分片 */
  kind: 'init' | 'media';
  /** 文件名，例如 init.mp4 / seg-0001.m4s */
  fileName: string;
  /** 原始（加密前）字节数 */
  clearSize: number;
  /** 加密后字节数 */
  encryptedSize: number;
  /** 加密方案，固定 cbc1 风格 cbcs */
  scheme: 'cbcs';
  /** KID（十六进制） */
  kid: string;
  /** 常量 IV（十六进制，cbcs 每分片恒定） */
  iv: string;
  /** 该片包含的样本数（init 分片为 0） */
  sampleCount: number;
  /** 加密样本数（受 pattern 保护的样本数） */
  encryptedSamples: number;
  /** 子样本总数（视频按 NAL 拆 subsample） */
  subsampleCount: number;
  /** 实际被 AES-CBC 加密的字节总数（crypt_byte_block 覆盖部分） */
  encryptedBytes: number;
  /** SHA-256 哈希（十六进制），播放前校验，篡改一个字节即不匹配 */
  sha256: string;
}

/** 媒体轨道元数据 */
export interface TrackMeta {
  kind: 'video' | 'audio';
  codec: string;
  /** 视频专用 */
  width?: number;
  height?: number;
  /** 音频专用 */
  sampleRate?: number;
  channels?: number;
  /** MSE 用 codec 字符串，例如 avc1.640028 / mp4a.40.2 */
  mseCodec: string;
}

/** 课程包清单 manifest.json */
export interface PackageManifest {
  format: 'courseguard-pkg';
  version: 1;
  courseId: string;
  title: string;
  createdAt: number;
  /** 每课程随机生成的 KID */
  kid: string; // hex
  /** cbcs 常量 IV */
  iv: string; // hex
  /** 水印调度随机种子（base64），溯源时重建同一漂移序列 */
  watermarkSeed: string;
  /** 水印位置序列参数 */
  watermark: WatermarkConfig;
  tracks: TrackMeta[];
  /** 分片清单（含 init） */
  segments: SegmentCryptoInfo[];
  /** 打包素材来源描述 */
  source: string;
  /** 时长（秒，估算） */
  durationSec: number;
}

export interface WatermarkConfig {
  /** 漂移间隔（秒），每隔该时长换一次位置 */
  moveIntervalSec: number;
  /** 透明度 0~1 */
  opacity: number;
  /** 主水印字号（px，基于视频高度比例另算） */
  fontSizeRatio: number;
  /** 四角固定微水印（防裁剪） */
  cornerWatermarks: boolean;
}

/** 导出 .cpkg 时的单文件结构 */
export interface PackageFile {
  manifest: PackageManifest;
  /** key = 分片文件名，value = base64url 编码的加密字节 */
  blobs: Record<string, string>;
}

/** 学员授权文件（.lic） */
export interface LicenseFile {
  format: 'courseguard-license';
  version: 1;
  studentId: string;
  studentName: string;
  courseId: string;
  /** KID 与课程包一致，用于 EME ClearKey */
  kid: string; // hex
  /** 授权生效时间（epoch ms） */
  issuedAt: number;
  /** 授权到期时间（epoch ms） */
  expiresAt: number;
  /** 是否吊销（本地许可证服务保留撤销列表；离线文件自身带吊销号） */
  revocationVersion: number;
  /** 播放端约束信息（仅展示/审计用） */
  scope: {
    allowSpeed: number[];
    allowSeek: boolean;
  };
  /** 发行方 ECDSA-P256 签名（base64url，raw r||s 或 DER），对 canonical JSON 签名 */
  signature: string;
  /** 发行方公钥 id */
  issuerKeyId: string;
}

/** 密钥库中的课程密钥记录 */
export interface KeyRecord {
  courseId: string;
  kid: string; // hex
  /** 内容加密密钥 CEK，16 字节 */
  key: Uint8Array;
  iv: Uint8Array; // 16 字节常量 IV
  watermarkSeed: Uint8Array; // 32 字节
  createdAt: number;
}

/** 学员记录 */
export interface StudentRecord {
  studentId: string;
  name: string;
  createdAt: number;
  /** 吊销版本，授权文件里的 revocationVersion 小于该值即视为已吊销 */
  revocationVersion: number;
  revoked: boolean;
  note?: string;
}

/** 素材记录（IndexedDB 存原始生成/导入的分片前数据） */
export interface MaterialRecord {
  materialId: string;
  name: string;
  kind: 'demo-generated' | 'imported-fmp4' | 'imported-mp4';
  createdAt: number;
  durationSec: number;
  hasAudio: boolean;
  width: number;
  height: number;
  /** 原始媒体字节（未加密 fMP4，单文件，含 init+moofs） */
  bytes: Uint8Array;
}

/** 打包记录（课程包元数据 + 分片存 blob store） */
export interface PackageRecord {
  courseId: string;
  title: string;
  manifest: PackageManifest;
  createdAt: number;
}

/** 溯源命中结果 */
export interface TraceHit {
  studentId: string;
  studentName: string;
  /** 匹配到的水印槽位时间（秒） */
  timeSec: number;
  /** 位置归一化坐标 x/y（0~1） */
  x: number;
  y: number;
  /** 匹配分数 0~1，1 为完全匹配 */
  score: number;
}

export interface TraceResult {
  /** 用户在截图上点选的归一化坐标 */
  query: { x: number; y: number; timeSec?: number };
  hits: TraceHit[];
}
