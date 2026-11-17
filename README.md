# CourseGuard — 浏览器本地 CENC/cbcs 视频加密课件打包与授权播放

全流程在浏览器本地完成的课程视频版权保护方案：把 fMP4 课件用 **CENC cbcs（AES-128-CBC）**
分片加密，打包成含课程密钥/学员水印种子的课程包；播放端通过 **EME ClearKey** 本地模拟
许可证发放，配合带学员编号的漂移水印、授权到期/吊销校验与逐分片 SHA-256 哈希校验。

## 快速开始

```bash
npm install
npm run gen-samples   # 用 ffmpeg 生成内置 fMP4 演示素材（public/samples）
npm run dev           # 启动开发服务器（必须 http(s)/localhost，EME 才可用）
npm test              # 单元测试（box 解析、加密、签名授权、水印溯源）
npm run build         # 类型检查 + 生产构建
```

用 Chrome/Edge 打开后，五个页面依次对应：素材库 → 加密打包 → 密钥管理 → 学员授权 → 播放端 → 水印溯源。

## 加密方案（关键技术细节）

- **标准**：ISO 23001-7 CENC，scheme = `cbcs`，AES-128-CBC，常量 IV（写在 tenc）。
- **盒子结构**：
  - init 段 `stsd` 内 `avc1/mp4a` → `encv/enca`，新增 `sinf(frma, schm, schi(tenc v1))`。
  - tenc v1 字段经 shaka-packager 权威输出 + Chrome ClearKey 实测逐字节对齐：
    `reserved | crypt/skip | is_protected=1 | per_sample_iv_size=0 | KID | constant_IV_size=16 | IV`。
  - 媒体分片 `moof/traf` **不放置 senc/saio/saiz**，加密边界完全由 init 段 tenc 驱动，
    NAL 长度前缀与 NAL header 由解复用器按 cbcs 规则自动保留明文。
- **全块加密（crypt=1, skip=0）**：每个 16 字节块都做 AES-CBC。
  实测 Chrome/Edge 的 ClearKey CDM 在 fMP4 分片场景对 crypt/skip 块跳过模式（如 1/9）
  支持不完整，且不接受 moof 内的 senc 辅助 box（会触发
  `CHUNK_DEMUXER_ERROR_APPEND_FAILED`）；全块 cbcs（tenc pattern 字节 0x00、无 moof senc）
  可稳定解密播放，且不降低加密强度。
- **EME 能力声明**：`requestMediaKeySystemAccess` 的 video/audio capability 必须显式带
  `encryptionScheme: 'cbcs'`，否则 CDM 按默认 cenc 解析而拒绝分片。
- **尾块**：不足 16 字节的残块保持明文（CENC 规定 AES 只作用于完整块）。

### 浏览器实测验证

`tests/eme-cbcs-playback.mts`（puppeteer + 系统 Chrome）端到端验证：ClearKey 密钥状态
`usable`、无解码错误、`readyState=4`、画面尺寸正确、播放时间推进到视频结尾，全部断言通过。

## 其他安全机制

- **密钥管理**：ECDSA P-256 发行方签名密钥对存浏览器 IndexedDB；课程 CEK 随机生成，
  仅以加密形式随 `.cpkg` 分发（包内不含明文 CEK）。
- **授权 .lic**：ECDSA 签名（canonical JSON），绑定学员 + 课程 + 到期时间（毫秒 epoch），
  支持吊销版本号；播放端验签通过才放行。
- **水印**：每个学员的漂移轨迹由 `课程水印种子 + 学员编号` 确定性生成（Mulberry32 PRNG），
  同学员同课程轨迹可复现；半透明学员编号水印定时漂移 + 四角微水印。溯源页用标注点反查学员。
- **完整性**：每个分片独立 SHA-256，播放前校验，任一字节被篡改即拒绝该分片并报损坏，
  而不是把错误数据送解码器导致花屏。

## 目录

```
src/lib/mp4/      ISO-BMFF box 解析/序列化、fMP4 解析、NAL/subsample、CENC cbcs 加密器
src/lib/crypto/   ECDSA 密钥库、ECDSA 授权签名/验签、ClearKey 许可证
src/lib/storage/  IndexedDB（素材、课程包、分片 blob、学员、吊销表）
src/lib/watermark/ 确定性水印调度 + 截图位置反查
src/lib/player.ts EME ClearKey + MSE 播放引擎（含授权闸门、逐分片校验）
src/pages/        五个功能页面
tests/            单元测试 + 浏览器 EME 端到端测试
```
