import { createServer } from 'vite';
import puppeteer from 'puppeteer-core';
const PORT = 5900;
const vite = await createServer({ server: { port: PORT, strictPort: true }, logLevel: 'silent' });
await vite.listen();
const browser = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true, args: ['--no-sandbox','--autoplay-policy=no-user-gesture-required'] });
try {
  const page = await browser.newPage();
  await page.goto(`http://localhost:${PORT}/`, { waitUntil: 'networkidle0' });
  const r = await page.evaluate(async () => {
    const [{ parseFmp4 }, { encryptCenc }] = await Promise.all([import('/src/lib/mp4/fmp4.ts'), import('/src/lib/mp4/cenc.ts')]);
    const b64 = (u: Uint8Array) => btoa(String.fromCharCode(...u)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
    const fmp4 = parseFmp4(new Uint8Array(await (await fetch('/samples/demo-video-only.mp4')).arrayBuffer()));
    const enc = await encryptCenc({ fmp4, key:new Uint8Array(16).fill(9), kid:new Uint8Array(16).fill(7), iv:new Uint8Array(16).fill(3) });
    const mk = await (await navigator.requestMediaKeySystemAccess('org.w3.clearkey', [{
      initDataTypes:['keyids'], videoCapabilities:[{contentType:`video/mp4; codecs="${fmp4.tracks[0].mseCodec}"`, encryptionScheme:'cbcs'}],
      distinctiveIdentifier:'not-allowed', persistentState:'not-allowed', sessionTypes:['temporary'],
    }])).createMediaKeys();
    const session = mk.createSession('temporary');
    const ready = new Promise<void>((res,rej)=>{const t=setTimeout(()=>rej(new Error('to')),5000);
      session.addEventListener('message',async()=>{await session.update(new TextEncoder().encode(JSON.stringify({keys:[{kty:'oct',kid:b64(new Uint8Array(16).fill(7)),k:b64(new Uint8Array(16).fill(9))}],type:'temporary'})));clearTimeout(t);res();});});
    await session.generateRequest('keyids', new TextEncoder().encode(JSON.stringify({kids:[b64(new Uint8Array(16).fill(7))],type:'temporary'})));
    await ready;
    const video=document.createElement('video');video.muted=true;document.body.appendChild(video);
    await video.setMediaKeys(mk);
    const ms=new MediaSource();video.src=URL.createObjectURL(ms);
    await new Promise<void>((r)=>ms.addEventListener('sourceopen',()=>r(),{once:true}));
    const sb=ms.addSourceBuffer(`video/mp4; codecs="${fmp4.tracks[0].mseCodec}"`);
    const waitIdle = () => new Promise<void>((resolve) => {
      if (!sb.updating) { resolve(); return; }
      const handler = () => { if (!sb.updating) { sb.removeEventListener('updateend', handler); resolve(); } };
      sb.addEventListener('updateend', handler);
    });
    let failed = false;
    sb.addEventListener('error', () => { failed = true; });
    const ap = async (seg: Uint8Array) => {
      if (failed) return false;
      sb.appendBuffer(seg.slice().buffer);
      await waitIdle();
      return !failed;
    };
    await ap(enc.initSegment.bytes);
    // 喂全部 4 个分片
    for (const s of enc.mediaSegments) await ap(s.bytes);
    if(ms.readyState==='open') ms.endOfStream();
    await video.play().catch(()=>{});
    await new Promise(r=>setTimeout(r,4000));
    return { t:Number(video.currentTime.toFixed(2)), rs:video.readyState, w:video.videoWidth, paused:video.paused, verr:video.error?.code??null, keyStatus:[...session.keyStatuses.values()][0] };
  });
  console.log('CBCSPLAY ' + JSON.stringify(r));
  // 权威断言：ClearKey 密钥可用、无解码错误、readyState=4（HAVE_ENOUGH_DATA）、画面尺寸正确、时间已推进
  if (r.keyStatus !== 'usable') throw new Error('ClearKey key not usable');
  if (r.verr !== null) throw new Error(`video decode error code=${r.verr}`);
  if (r.rs !== 4) throw new Error(`readyState=${r.rs}, expected 4`);
  if (r.w !== 480) throw new Error(`videoWidth=${r.w}, expected 480`);
  if (!(r.t > 1)) throw new Error(`playback time ${r.t} did not advance`);
  console.log('EME_CBCS_PLAYBACK_ASSERTIONS_PASSED');
} finally { await browser.close(); await vite.close(); }
process.exit(0);
