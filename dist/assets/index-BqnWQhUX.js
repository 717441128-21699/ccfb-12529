(function(){const t=document.createElement("link").relList;if(t&&t.supports&&t.supports("modulepreload"))return;for(const a of document.querySelectorAll('link[rel="modulepreload"]'))n(a);new MutationObserver(a=>{for(const r of a)if(r.type==="childList")for(const i of r.addedNodes)i.tagName==="LINK"&&i.rel==="modulepreload"&&n(i)}).observe(document,{childList:!0,subtree:!0});function s(a){const r={};return a.integrity&&(r.integrity=a.integrity),a.referrerPolicy&&(r.referrerPolicy=a.referrerPolicy),a.crossOrigin==="use-credentials"?r.credentials="include":a.crossOrigin==="anonymous"?r.credentials="omit":r.credentials="same-origin",r}function n(a){if(a.ep)return;a.ep=!0;const r=s(a);fetch(a.href,r)}})();const Qe="courseguard",Ze=1,w={materials:"materials",packages:"packages",segmentBlobs:"segmentBlobs",keys:"keys",students:"students",revocation:"revocation"};let se=null;function et(){return se||(se=new Promise((e,t)=>{const s=indexedDB.open(Qe,Ze);s.onupgradeneeded=()=>{const n=s.result;n.objectStoreNames.contains(w.materials)||n.createObjectStore(w.materials,{keyPath:"materialId"}),n.objectStoreNames.contains(w.packages)||n.createObjectStore(w.packages,{keyPath:"courseId"}),n.objectStoreNames.contains(w.segmentBlobs)||n.createObjectStore(w.segmentBlobs),n.objectStoreNames.contains(w.keys)||n.createObjectStore(w.keys,{keyPath:"courseId"}),n.objectStoreNames.contains(w.students)||n.createObjectStore(w.students,{keyPath:"studentId"}),n.objectStoreNames.contains(w.revocation)||n.createObjectStore(w.revocation,{keyPath:"courseId"})},s.onsuccess=()=>e(s.result),s.onerror=()=>t(s.error)}),se)}function ce(e,t,s){return et().then(n=>new Promise((a,r)=>{const i=n.transaction(e,t),o=s(i.objectStore(e));o.onsuccess=()=>a(o.result),o.onerror=()=>r(o.error)}))}async function O(e,t,s){await ce(e,"readwrite",n=>n.put(t,s))}async function R(e,t){return ce(e,"readonly",s=>s.get(t))}async function ne(e){return ce(e,"readonly",t=>t.getAll())}async function re(e,t){await ce(e,"readwrite",s=>s.delete(t))}const y={listMaterials:()=>ne(w.materials),getMaterial:e=>R(w.materials,e),putMaterial:e=>O(w.materials,e),deleteMaterial:e=>re(w.materials,e),listPackages:()=>ne(w.packages),getPackage:e=>R(w.packages,e),putPackage:e=>O(w.packages,e),deletePackage:async e=>{const t=await R(w.packages,e);if(t)for(const s of t.segments)await re(w.segmentBlobs,`${e}/${s.fileName}`);await re(w.packages,e)},putSegment:(e,t,s)=>O(w.segmentBlobs,s,`${e}/${t}`),getSegment:(e,t)=>R(w.segmentBlobs,`${e}/${t}`),listKeys:()=>ne(w.keys),getKey:e=>R(w.keys,e),putKey:e=>O(w.keys,e),listStudents:()=>ne(w.students),getStudent:e=>R(w.students,e),putStudent:e=>O(w.students,e),deleteStudent:e=>re(w.students,e),async getRevocation(e){return(await R(w.revocation,e))?.version??0},async bumpRevocation(e){const s=await y.getRevocation(e)+1;return await O(w.revocation,{courseId:e,version:s,updatedAt:Date.now()}),s}},tt=new Set(["moov","trak","mdia","minf","stbl","mvex","moof","traf","edts","dinf","sinf","schi"]),st={avc1:78,avc3:78,hvc1:78,hev1:78,encv:78,mp4a:28,enca:28,"ac-3":28,"ec-3":28},nt=new Set(["avcC","hvcC","esds","sinf","btrt","pasp","colr","clap","d263","dfLa","dfLa","ac-3","dec3","dOps","dtsc","mhaC","vpcC","av1C"]),rt=new Set(["mvhd","tkhd","mdhd","hdlr","vmhd","smhd","dref","stsd","stts","stsc","stsz","stco","co64","stss","ctts","elst","mehd","trex","mfhd","tfhd","trun","tfdt","sdtp","senc","saiz","saio","pdin","schm","tenc"]);function be(e,t=0){return String.fromCharCode(e[t],e[t+1],e[t+2],e[t+3])}function at(e){return new Uint8Array([e.charCodeAt(0),e.charCodeAt(1),e.charCodeAt(2),e.charCodeAt(3)])}function it(e,t,s,n){const a=t+8,r=t+s;for(let i=n;i+8<=s;i+=2){const o=_(e,a+i),c=be(e,a+i+4);if(nt.has(c)&&o>=8&&a+i+o<=r)return i}return n}function Q(e,t=0,s=e.length){const n=[];let a=t;for(;a+8<=s;){let r=_(e,a);const i=be(e,a+4);let o=8;if(r===1?(r=Number(He(e,a+8)),o=16):r===0&&(r=s-a),r<o||a+r>s)throw new Error(`box ${i} 长度非法 @${a}: size=${r}, 剩余=${s-a}`);n.push(ot(e,a,r,i,o)),a+=r}if(a!==s)throw new Error(`box 流解析后剩余 ${s-a} 字节未消费`);return n}function ot(e,t,s,n,a){const r=e.subarray(t,t+s),i={type:n,raw:r.slice(),start:t,size:s};if(n==="stsd"){i.version=e[t+a],i.flags=Ce(e,t+a+1);const o=_(e,t+a+4),c=[];let u=t+a+8;for(let l=0;l<o;l++){const p=_(e,u),f=be(e,u+4),d=st[f];if(!d)throw new Error(`不支持的 sample entry: ${f}`);const m=it(e,u,p,d),g={type:f,raw:e.subarray(u,u+p).slice(),rawHeader:e.subarray(u+8,u+8+m).slice(),children:Q(e,u+8+m,u+p),start:u,size:p};c.push(g),u+=p}return i.children=c,i}return tt.has(n)?(i.children=Q(e,t+a,t+s),i):rt.has(n)?(i.version=e[t+a],i.flags=Ce(e,t+a+1),i.payload=e.subarray(t+a+4,t+s).slice(),i):(i.payload=e.subarray(t+a,t+s).slice(),i)}function me(e){const t=[];for(const s of e)t.push(ke(s));return P(t)}function ke(e){if(e.type==="stsd"){const t=P(e.children.map(xe)),s=P([Ae(e.version??0),ye(e.flags??0),le(e.children.length),t]);return Y(e.type,s)}return e.rawHeader?xe(e):e.children?Y(e.type,P(e.children.map(ke))):e.flags!==void 0?Y(e.type,P([Ae(e.version??0),ye(e.flags),e.payload??new Uint8Array(0)])):Y(e.type,e.payload??new Uint8Array(0))}function xe(e){const t=P((e.children??[]).map(ke)),s=P([e.rawHeader,t]);return Y(e.type,s)}function ct(e,t){return{type:e,payload:t,raw:new Uint8Array(0),start:-1,size:t.length+8}}function Ue(e,t,s,n){return{type:e,version:t,flags:s,payload:n,raw:new Uint8Array(0),start:-1,size:n.length+12}}function Y(e,t){return P([le(t.length+8),at(e),t])}function F(e,t){let s=e,n;for(const a of t){if(n=s?.find(r=>r.type===a),!n)return;s=n.children}return n}function lt(e,t){const s=[],n=a=>{if(a)for(const r of a)r.type===t&&s.push(r),r.children&&n(r.children)};return n(e),s}function _(e,t){return e[t]*16777216+(e[t+1]<<16|e[t+2]<<8|e[t+3])}function Ce(e,t){return e[t]<<16|e[t+1]<<8|e[t+2]}function He(e,t){let s=0n;for(let n=0;n<8;n++)s=s<<8n|BigInt(e[t+n]);return s}function Ae(e){return new Uint8Array([e&255])}function dt(e){return new Uint8Array([e>>8&255,e&255])}function ye(e){return new Uint8Array([e>>16&255,e>>8&255,e&255])}function le(e){return new Uint8Array([e>>>24&255,e>>>16&255,e>>>8&255,e&255])}function ut(e){const t=new Uint8Array(8);let s=e;for(let n=7;n>=0;n--)t[n]=Number(s&0xffn),s>>=8n;return t}function P(e){let t=0;for(const a of e)t+=a.length;const s=new Uint8Array(t);let n=0;for(const a of e)s.set(a,n),n+=a.length;return s}class D{off=0;d;constructor(t){this.d=t}u8(){return this.d[this.off++]}u16(){const t=this.d[this.off]<<8|this.d[this.off+1];return this.off+=2,t>>>0}u24(){const t=this.d[this.off]<<16|this.d[this.off+1]<<8|this.d[this.off+2];return this.off+=3,t>>>0}u32(){const t=_(this.d,this.off);return this.off+=4,t}u64(){const t=He(this.d,this.off);return this.off+=8,t}bytes(t){const s=this.d.subarray(this.off,this.off+t).slice();return this.off+=t,s}get eof(){return this.off>=this.d.length}}class pt{parts=[];len=0;u8(t){return this.push(new Uint8Array([t&255])),this}u16(t){return this.push(dt(t)),this}u24(t){return this.push(ye(t)),this}u32(t){return this.push(le(t)),this}u64(t){return this.push(ut(t)),this}bytes(t){return this.push(t),this}push(t){this.parts.push(t),this.len+=t.length}result(){return P(this.parts)}get length(){return this.len}}const ft=1,Le=4,ht=256,mt=512,yt=1024,gt=2048,vt=1,wt=2,bt=8,kt=16,St=32;function Re(e){const t=Q(e),s=t.find(l=>l.type==="moov");if(!s)throw new Error("未找到 moov，输入必须是 fMP4（分片 MP4）");if(!F(s.children,["mvex","trex"]))throw new Error("moov 内缺少 mvex/trex，输入不是分片 MP4（fMP4）。请先用 ffmpeg -f dash 或 -movflags frag_keyframe+empty_moov 转换。");const n=new Map;for(const l of lt(s.children,"trex")){const p=new D(l.payload),f=p.u32();p.u32(),n.set(f,{duration:p.u32(),size:p.u32(),flags:p.u32()})}const a=$t(s),r=[],i=[],o=new Map;for(const l of a)o.set(l.trackId,l.samples);let c=e.length;for(let l=0;l<t.length;l++){if(t[l].type!=="moof")continue;i.length===0&&(c=t[l].start);const p=t[l],f=t[l+1];if(!f||f.type!=="mdat")throw new Error(`moof@${p.start} 后缺少 mdat`);i.push(p.start);for(const d of p.children.filter(m=>m.type==="traf")){const m=d.children.find(T=>T.type==="tfhd"),g=new D(m.payload),b=g.u32();let v,k,E,I;const $=m.flags;$&vt&&(v=Number(g.u64())),$&wt&&g.u32(),$&bt&&(k=g.u32()),$&kt&&(E=g.u32()),$&St&&(I=g.u32());const x=n.get(b);if(!x)throw new Error(`tfhd 引用了未知 trackId=${b}`);const M=k??x.duration,C=E??x.size,K=I??x.flags,L=d.children.find(T=>T.type==="tfdt");let j=0;if(L){const T=new D(L.payload);j=L.version===1?Number(T.u64()):T.u32()}const B=d.children.find(T=>T.type==="trun");if(!B)throw new Error("traf 缺少 trun");const A=new D(B.payload),V=A.u32();let N=0;B.flags&ft&&(N=A.u32());let q=0;B.flags&Le&&(q=A.u32());let W=(v??p.start)+N,G=j;const $e=o.get(b),Xe=$e.length;for(let T=0;T<V;T++){const Ee=B.flags&ht?A.u32():M,pe=B.flags&mt?A.u32():C;let fe=K;B.flags&yt?fe=A.u32():T===0&&B.flags&Le&&(fe=q);let Ie=0;B.flags&gt&&(Ie=(B.version===1,A.u32()|0)),$e.push({trackId:b,index:Xe+T,moofStart:p.start,start:W,end:W+pe,size:pe,flags:fe,duration:Ee,cts:Ie,dts:G}),W+=pe,G+=Ee}r.push({index:i.length-1,moofStart:p.start,moofEnd:p.start+p.size,mdatStart:f.start,mdatEnd:f.start+f.size,moof:p,mdat:f,trackId:b})}}let u=0;for(const l of a){const p=l.samples[l.samples.length-1];p&&(u=Math.max(u,(p.dts+p.duration)/l.timescale))}return{bytes:e,initSegment:e.subarray(0,c).slice(),initEnd:c,tracks:a,fragments:r,moofGroups:i,durationSec:u}}function $t(e){const t=[];for(const s of e.children.filter(n=>n.type==="trak")){const n=F(s.children,["tkhd"]),a=Et(n),r=F(s.children,["mdia","mdhd"]),i=new D(r.payload).u32(),o=new D(r.payload);r.version===1?(o.u64(),o.u64()):(o.u32(),o.u32());const c=o.u32(),u=F(s.children,["mdia","hdlr"]),p=(u?It(u.payload):"")==="soun"?"audio":"video",d=F(s.children,["mdia","minf","stbl","stsd"]).children[0],m=d.type==="encv"||d.type==="enca"?xt(d):d.type;let g,b,v,k,E;if(p==="video")b=d.rawHeader[24]<<8|d.rawHeader[25],v=d.rawHeader[26]<<8|d.rawHeader[27],g=Ct(m,d.children??[]);else{const I=d.rawHeader,$=I[8]<<8|I[9];$!==0?(E=$,k=_(I,16)>>>16):(E=I[16]<<8|I[17],k=I[24]<<8|I[25]),g=Lt(m,d.children??[])}t.push({trackId:a,kind:p,timescale:c??i,codecFourcc:m,mseCodec:g,width:b,height:v,sampleRate:k,channels:E,samples:[]})}return t}function Et(e){const t=new D(e.payload);return e.version===1?(t.u64(),t.u64()):(t.u32(),t.u32()),t.u32()}function It(e){return String.fromCharCode(e[4],e[5],e[6],e[7])}function xt(e){const t=e.children.find(n=>n.type==="frma");if(!t)throw new Error("encv/enca 缺少 frma");const s=t.payload;return String.fromCharCode(s[0],s[1],s[2],s[3])}function Ct(e,t){if(e==="avc1"||e==="avc3"){const s=t.find(n=>n.type==="avcC");if(s){const n=s.payload,a=r=>r.toString(16).padStart(2,"0");return`avc1.${a(n[1])}${a(n[2])}${a(n[3])}`}return"avc1.42E01E"}if(e==="hvc1"||e==="hev1"){const s=t.find(n=>n.type==="hvcC");return s?At(s.payload):"hvc1.1.6.L93.B0"}return e}function At(e){const t=e,s=t[1],n=s>>6,a=s>>5&1,r=s&31,i=t[12];return`hvc1.${n===0?"":String.fromCharCode(65+n-1)}${r}.${a?"H":"L"}${i}.B0`}function Lt(e,t){return e==="mp4a"?"mp4a.40.2":e}const Te="0123456789abcdef";function U(e){let t="";for(let s=0;s<e.length;s++)t+=Te[e[s]>>4]+Te[e[s]&15];return t}function Tt(e){const t=e.startsWith("0x")?e.slice(2):e;if(t.length%2!==0)throw new Error("hex 长度必须为偶数");const s=new Uint8Array(t.length/2);for(let n=0;n<s.length;n++){const a=parseInt(t[n*2],16),r=parseInt(t[n*2+1],16);if(Number.isNaN(a)||Number.isNaN(r))throw new Error("非法 hex 字符");s[n]=a<<4|r}return s}function Z(e){let t="";for(let n=0;n<e.length;n++)t+=String.fromCharCode(e[n]);return btoa(t).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,"")}function Se(e){const t=e.replace(/-/g,"+").replace(/_/g,"/"),s=t.length%4===0?"":"=".repeat(4-t.length%4),n=atob(t+s),a=new Uint8Array(n.length);for(let r=0;r<n.length;r++)a[r]=n.charCodeAt(r);return a}function Mt(e){let t="";for(let s=0;s<e.length;s++)t+=String.fromCharCode(e[s]);return btoa(t)}async function Fe(e){const t=await crypto.subtle.digest("SHA-256",e);return new Uint8Array(t)}async function de(e){return U(await Fe(e))}function ae(e){const t=new Uint8Array(e);return crypto.getRandomValues(t),t}function ee(e){if(e===null||typeof e!="object")return JSON.stringify(e);if(Array.isArray(e))return"["+e.map(ee).join(",")+"]";const t=e;return"{"+Object.keys(t).sort().filter(n=>t[n]!==void 0).map(n=>JSON.stringify(n)+":"+ee(t[n])).join(",")+"}"}function z(e){return new TextEncoder().encode(e)}function H(e){return e<1024?`${e} B`:e<1024*1024?`${(e/1024).toFixed(1)} KB`:`${(e/1024/1024).toFixed(2)} MB`}function X(e){const t=new Date(e),s=(n,a=2)=>String(n).padStart(a,"0");return`${t.getFullYear()}-${s(t.getMonth()+1)}-${s(t.getDate())} ${s(t.getHours())}:${s(t.getMinutes())}:${s(t.getSeconds())}`}function ge(e){const t=Math.floor(e/60),s=Math.floor(e%60);return`${t}:${String(s).padStart(2,"0")}`}const Me=[{file:"samples/demo-av.mp4",name:"演示课·视频+音频（12s 双轨）"},{file:"samples/demo-video-only.mp4",name:"演示课·纯视频（8s）"},{file:"samples/demo-slide.mp4",name:"演示课·PPT 静态画面（6s）"}];async function Bt(e){e.innerHTML=`
    <div class="grid cols-2">
      <div class="card">
        <h3>① 内置演示素材（ffmpeg 生成的真实 fMP4）</h3>
        <div class="stack">
          ${Me.map((r,i)=>`
            <div class="row" style="justify-content:space-between">
              <div>
                <div>${h(r.name)}</div>
                <div class="file-hint mono">${h(r.file)}</div>
              </div>
              <button class="small primary" data-load="${i}">入库</button>
            </div>`).join("")}
        </div>
      </div>
      <div class="card">
        <h3>② 导入外部素材</h3>
        <p class="file-hint" style="margin-top:0">
          要求分片 MP4（fMP4，含 mvex/trex）。普通 MP4 可用
          <span class="mono">ffmpeg -movflags frag_keyframe+empty_moov+default_base_moof</span> 转换。
        </p>
        <input type="file" id="mat-import" accept=".mp4,.m4s,.m4v,video/mp4" />
        <div id="mat-import-status" class="file-hint" style="margin-top:8px"></div>
      </div>
    </div>
    <div class="card">
      <h3>素材库（IndexedDB）</h3>
      <div id="mat-list"><div class="empty"><div class="icon">📂</div>暂无素材，请先入库或导入</div></div>
    </div>`;const t=e.querySelector("#mat-list"),s=async()=>{const r=await y.listMaterials();if(r.length===0){t.innerHTML='<div class="empty"><div class="icon">📂</div>暂无素材，请先入库或导入</div>';return}t.innerHTML=`
      <table>
        <thead><tr><th>名称</th><th>类型</th><th>分辨率/声道</th><th>时长</th><th>大小</th><th>materialId</th><th></th></tr></thead>
        <tbody>
          ${r.map(i=>`
            <tr>
              <td><strong>${h(i.name)}</strong></td>
              <td><span class="badge blue">${h(i.kind)}</span></td>
              <td class="mono">${i.width}×${i.height}${i.hasAudio?" · 含音频":""}</td>
              <td class="mono">${ge(i.durationSec)}</td>
              <td class="mono">${H(i.bytes.length)}</td>
              <td class="mono tiny">${h(i.materialId)}</td>
              <td class="row">
                <button class="small" data-dl="${h(i.materialId)}">下载</button>
                <button class="small danger" data-del="${h(i.materialId)}">删除</button>
              </td>
            </tr>`).join("")}
        </tbody>
      </table>`,t.querySelectorAll("[data-del]").forEach(i=>i.addEventListener("click",async()=>{await y.deleteMaterial(i.dataset.del),S("素材已删除","ok"),s()})),t.querySelectorAll("[data-dl]").forEach(i=>i.addEventListener("click",async()=>{const o=r.find(c=>c.materialId===i.dataset.dl);te(`${o.materialId}.mp4`,new Blob([o.bytes],{type:"video/mp4"}))}))};s(),e.querySelectorAll("[data-load]").forEach(r=>r.addEventListener("click",async()=>{const i=Me[Number(r.dataset.load)];r.setAttribute("disabled","true");try{const o=await fetch(i.file),c=new Uint8Array(await o.arrayBuffer()),u=await Be(c,i.name,"demo-generated");S(`已入库：${u.name}（${u.durationSec.toFixed(1)}s）`,"ok"),s()}catch(o){S(`入库失败：${o.message}`,"err")}finally{r.removeAttribute("disabled")}}));const n=e.querySelector("#mat-import"),a=e.querySelector("#mat-import-status");n.addEventListener("change",async()=>{const r=n.files?.[0];if(r){a.textContent=`解析中：${r.name} …`;try{const i=await Ts(r),o=await Be(i,r.name,"imported-fmp4");a.innerHTML=`<span class="badge green">解析成功</span> ${o.durationSec.toFixed(1)}s · ${H(o.bytes.length)}`,S(`导入成功：${r.name}`,"ok"),s()}catch(i){a.innerHTML=`<span class="badge red">导入失败</span> ${h(i.message)}`,S(i.message,"err")}}})}async function Be(e,t,s){const n=Re(e),a=n.tracks.find(o=>o.kind==="video"),r=n.tracks.find(o=>o.kind==="audio"),i={materialId:`mat-${Date.now().toString(36)}-${Math.floor(Math.random()*1e5).toString(36)}`,name:t,kind:s,createdAt:Date.now(),durationSec:Math.round(n.durationSec*10)/10,hasAudio:!!r,width:a?.width??0,height:a?.height??0,bytes:e};return await y.putMaterial(i),i}function Nt(e,t){const s=[];let n=0;for(;n+4<=e.length;){const a=e[n]<<24|e[n+1]<<16|e[n+2]<<8|e[n+3];if(a<=0||n+4+a>e.length)throw new Error(`AVCC NAL 长度非法: len=${a} off=${n} sample=${e.length}`);const r=n+4,i=r+a,o=e[r];let c,u;t==="avc"?(c=o&31,u=c===1||c===5):(c=o>>1&63,u=c<=31),s.push({type:c,start:n,end:i,nalStart:r,nalEnd:i,isVcl:u}),n=i}if(n!==e.length)throw new Error("AVCC sample 尾部有残余字节");return s}function Pt(e){const t=[];let s=0;const n=a=>{t.push({clearBytes:s,encryptedBytes:a}),s=0};for(const a of e){const r=a.nalEnd-a.nalStart,i=a.nalStart-a.start;if(!a.isVcl){s+=i+r;continue}const o=i+1,c=Math.max(0,r-1);s+=o,c>0&&n(c)}return(s>0||t.length===0)&&t.push({clearBytes:s,encryptedBytes:0}),t}function Dt(e){return[{clearBytes:0,encryptedBytes:e}]}function Kt(e,t,s){let n=0,a=0;for(const r of e){if(r.encryptedBytes===0)continue;const i=Math.floor(r.encryptedBytes/16);let o=0;if(t===0)o=i;else{const c=t+s,u=Math.floor(i/c),l=i-u*c;o=u*t+Math.min(l,t)}a+=o,n+=o*16}return{encryptedBytes:n,blocks:a}}const Ne={crypt:1,skip:0},Pe={crypt:1,skip:0};async function jt(e,t,s,n,a){const r=e.slice(t,t+s),i=await crypto.subtle.encrypt({name:"AES-CBC",iv:a},n,r),o=new Uint8Array(i);if(o.length!==s+16)throw new Error("AES-CBC 输出长度异常");e.set(o.subarray(0,s),t)}function qt(e){return ct("frma",new Uint8Array([e.charCodeAt(0),e.charCodeAt(1),e.charCodeAt(2),e.charCodeAt(3)]))}function Ut(){return Ue("schm",0,0,P([new Uint8Array([99,98,99,115]),le(65536)]))}function Ht(e){const t=new pt;return t.u8(0),t.u8(e.cryptBlocks<<4|e.skipBlocks&15),t.u8(1),t.u8(0),t.bytes(e.kid),t.u8(16),t.bytes(e.iv),Ue("tenc",1,0,t.result())}function Rt(e,t){const s=e.type==="mp4a"||e.type==="enca"?"enca":"encv",n={type:"schi",raw:new Uint8Array(0),start:-1,size:0,children:[Ht(t)]},a={type:"sinf",raw:new Uint8Array(0),start:-1,size:0,children:[qt(e.type),Ut(),n]};return{type:s,raw:new Uint8Array(0),start:-1,size:0,rawHeader:e.rawHeader,children:[...e.children??[],a]}}function Ft(e,t){const s=Q(e),n=s.find(a=>a.type==="moov");if(!n)throw new Error("init 段缺少 moov");for(const a of n.children.filter(r=>r.type==="trak")){const r=F(a.children,["mdia","minf","stbl","stsd"]);if(!r||!r.children?.length)continue;const i=Ot(F(a.children,["tkhd"])),o=t.find(c=>c.trackId===i);o&&(r.children=r.children.map(c=>Rt(c,o)))}return me(s)}function Ot(e){const t=new D(e.payload);return e.version===1?(t.u64(),t.u64()):(t.u32(),t.u32()),t.u32()}async function _t(e,t,s,n){const a=e.moofGroups[t];if(a===void 0)throw new Error(`分片 ${t} 不存在`);const r=e.fragments.filter(C=>C.moofStart===a),i=Math.max(...r.map(C=>C.moofEnd)),o=Math.min(...r.map(C=>C.mdatStart)),c=Math.max(...r.map(C=>C.mdatEnd)),u=e.bytes.slice(),l=await crypto.subtle.importKey("raw",n,{name:"AES-CBC"},!1,["encrypt"]),p=Q(e.bytes.subarray(a,i));if(p.length!==1||p[0].type!=="moof")throw new Error("片段顶层不是单个 moof");const f=p[0],d=f.children.filter(C=>C.type==="traf");if(d.length!==r.length)throw new Error(`moof 内 traf 数(${d.length}) 与解析到的轨道数(${r.length}) 不一致`);const m=[],g=[];let b=0,v=0,k=0;for(let C=0;C<d.length;C++){const K=d[C],L=zt(K),j=s.find(N=>N.trackId===L);if(!j)throw new Error(`traf 引用未知 trackId=${L}`);const B=e.tracks.find(N=>N.trackId===L),A=Wt(e,a,B,j);if(A.length===0)throw new Error(`分片 ${t} track ${L} 无 sample`);let V=0;for(const N of A){let q=N.sample.start;for(const J of N.subs)q+=J.clearBytes,J.encryptedBytes>0&&Vt(J.encryptedBytes,j,(W,G)=>{g.push(jt(u,q+W*16,G*16,l,j.iv)),V+=G*16}),q+=J.encryptedBytes;v+=N.subs.length}m.push({traf:K,trackId:L,params:j,plans:A,encryptedBytes:V,subsampleCount:A.reduce((N,q)=>N+q.subs.length,0)}),b+=V,k+=A.length}await Promise.all(g);let E=me([f]);for(const C of m){const K=C.traf.children.find(L=>L.type==="trun");Jt(K,E.length+8)}const I=me([f]),$=e.bytes.subarray(o,o+8),x=u.subarray(o+8,c),M=P([I,$,x]);return{fileName:`seg-${String(t+1).padStart(4,"0")}.m4s`,kind:"media",index:t,bytes:M,clearSize:c-(o+8),sampleCount:k,encryptedSamples:m.reduce((C,K)=>C+K.plans.filter(L=>L.encryptedBytes>0).length,0),subsampleCount:v,encryptedBytes:b}}function zt(e){const t=e.children.find(s=>s.type==="tfhd");return new D(t.payload).u32()}function Vt(e,t,s){const n=Math.floor(e/16);if(t.cryptBlocks===0){s(0,n);return}const a=t.cryptBlocks+t.skipBlocks;for(let r=0;r<n;r+=a)s(r,Math.min(t.cryptBlocks,n-r))}function Jt(e,t){if(!(e.flags&1))return;const s=e.payload;s[4]=t>>>24&255,s[5]=t>>>16&255,s[6]=t>>>8&255,s[7]=t&255}function Wt(e,t,s,n){const a=[],r=s.samples.filter(i=>i.moofStart===t);for(const i of r){let o,c=[];if(s.kind==="video"&&n.codecFamily!=="other"){const l=e.bytes.subarray(i.start,i.end);c=Nt(l,n.codecFamily==="hevc"?"hevc":"avc"),o=Pt(c)}else o=Dt(i.size);const{encryptedBytes:u}=Kt(o,n.cryptBlocks,n.skipBlocks);a.push({sample:i,subs:o,nals:c,encryptedBytes:u})}return a}async function Gt(e){const t=e.fmp4.tracks.map(r=>({trackId:r.trackId,kind:r.kind,codecFamily:r.codecFourcc.startsWith("avc")?"avc":r.codecFourcc.startsWith("hvc")||r.codecFourcc.startsWith("hev")?"hevc":"other",kid:e.kid,iv:e.iv,cryptBlocks:r.kind==="video"?Ne.crypt:Pe.crypt,skipBlocks:r.kind==="video"?Ne.skip:Pe.skip,perSampleIv:!1})),n={fileName:"init.mp4",kind:"init",index:-1,bytes:Ft(e.fmp4.initSegment,t),clearSize:e.fmp4.initSegment.length,sampleCount:0,encryptedSamples:0,subsampleCount:0,encryptedBytes:0},a=[];for(let r=0;r<e.fmp4.moofGroups.length;r++)a.push(await _t(e.fmp4,r,t,e.key));return{initSegment:n,mediaSegments:a,tracks:t}}const De="issuer-p256-local",Ke="courseguard.issuer.jwk";async function Yt(){const e=localStorage.getItem(Ke);if(e){const a=JSON.parse(e),r=await crypto.subtle.importKey("jwk",a,{name:"ECDSA",namedCurve:"P-256"},!0,["sign"]),i={...a};delete i.d,i.key_ops=["verify"];const o=await crypto.subtle.importKey("jwk",i,{name:"ECDSA",namedCurve:"P-256"},!0,["verify"]);return{keyId:De,privateKey:r,publicKey:o,publicJwk:i}}const t=await crypto.subtle.generateKey({name:"ECDSA",namedCurve:"P-256"},!0,["sign","verify"]),s=await crypto.subtle.exportKey("jwk",t.privateKey);localStorage.setItem(Ke,JSON.stringify(s));const n=await crypto.subtle.exportKey("jwk",t.publicKey);return{keyId:De,privateKey:t.privateKey,publicKey:t.publicKey,publicJwk:n}}let he=null;async function Oe(){return he||(he=await Yt()),he}async function ue(){return(await Oe()).publicJwk}async function Xt(){const e=await ue();return(await de(z(ee(e)))).slice(0,16)}async function Qt(e){const t=await Oe(),s=z(ee(e)),n=new Uint8Array(await crypto.subtle.sign({name:"ECDSA",hash:"SHA-256"},t.privateKey,s)),a=n.length===64&&n[0]!==48?n:es(n);return{signature:Z(a),issuerKeyId:t.keyId}}async function Zt(e,t,s){try{const n=await crypto.subtle.importKey("jwk",s,{name:"ECDSA",namedCurve:"P-256"},!1,["verify"]),a=ns(t),r=ts(a),i=z(ee(e));return await crypto.subtle.verify({name:"ECDSA",hash:"SHA-256"},n,r,i).catch(()=>!1)?!0:crypto.subtle.verify({name:"ECDSA",hash:"SHA-256"},n,a,i).catch(()=>!1)}catch{return!1}}function es(e){let t=1;e[t]&128?t+=1+(e[t]&127):t+=1;const s=()=>{if(e[t++]!==2)throw new Error("DER 缺少 INTEGER");const i=e[t++],o=e.subarray(t,t+i);return t+=i,o.length>32?o.subarray(o.length-32):o},n=s(),a=s(),r=new Uint8Array(64);return r.set(n,32-n.length),r.set(a,64-a.length),r}function ts(e){if(e.length!==64)throw new Error("raw 签名必须为 64 字节");const t=r=>{let i=0;for(;i<r.length-1&&r[i]===0;)i++;let o=r.subarray(i);return o[0]&128&&(o=new Uint8Array([0,...o])),new Uint8Array([2,o.length,...o])},s=t(e.subarray(0,32)),n=t(e.subarray(32,64)),a=new Uint8Array(s.length+n.length);return a.set(s,0),a.set(n,s.length),a.length<128?new Uint8Array([48,a.length,...a]):new Uint8Array([48,129,a.length,...a])}function ss(){return{kid:ae(16),key:ae(16),iv:ae(16),watermarkSeed:ae(32)}}const ns=Se,ie={moveIntervalSec:8,opacity:.35,fontSizeRatio:.055,cornerWatermarks:!0};async function rs(e,t,s){const n=s.courseId??`course-${Date.now().toString(36)}-${Math.floor(Math.random()*1e6).toString(36)}`,a=s.watermark??ie,r=s.onProgress??(()=>{});r({phase:"解析 fMP4 盒子结构",current:0,total:4});const i=Re(e);if(i.fragments.length===0)throw new Error("素材中没有任何媒体分片（moof/mdat）");const o=ss();r({phase:"CENC cbcs 加密分片",current:1,total:4});const c=await Gt({fmp4:i,key:o.key,kid:o.kid,iv:o.iv});r({phase:"计算分片 SHA-256",current:2,total:4});const u=[],l=[c.initSegment,...c.mediaSegments];for(const m of l)u.push(await as(m,U(o.kid),U(o.iv)));const p=i.tracks.map(m=>({kind:m.kind,codec:m.codecFourcc,width:m.width,height:m.height,sampleRate:m.sampleRate,channels:m.channels,mseCodec:m.mseCodec})),f={format:"courseguard-pkg",version:1,courseId:n,title:s.title,createdAt:Date.now(),kid:U(o.kid),iv:U(o.iv),watermarkSeed:Z(o.watermarkSeed),watermark:a,tracks:p,segments:u,source:t,durationSec:Math.round(i.durationSec*10)/10},d={courseId:n,kid:f.kid,key:o.key,iv:o.iv,watermarkSeed:o.watermarkSeed,createdAt:f.createdAt};r({phase:"写入本地库",current:3,total:4}),await y.putPackage(f),await y.putKey(d);for(const m of l)await y.putSegment(n,m.fileName,m.bytes);return r({phase:"完成",current:4,total:4}),{manifest:f,keyRecord:d,segments:l}}async function as(e,t,s){return{index:e.kind==="init"?-1:e.index,kind:e.kind,fileName:e.fileName,clearSize:e.clearSize,encryptedSize:e.bytes.length,scheme:"cbcs",kid:t,iv:s,sampleCount:e.sampleCount,encryptedSamples:e.encryptedSamples,subsampleCount:e.subsampleCount,encryptedBytes:e.encryptedBytes,sha256:await de(e.bytes)}}async function _e(e){const t={};for(const s of e.segments){const n=await y.getSegment(e.courseId,s.fileName);if(!n)throw new Error(`本地缺少分片 ${s.fileName}`);t[s.fileName]=Mt(n)}return{manifest:e,blobs:t}}async function is(e){const t=await y.listMaterials(),s=await y.listPackages();e.innerHTML=`
    <div class="card">
      <h3>① 选择素材并打包</h3>
      ${t.length===0?'<div class="empty">请先到「课程素材」页入库或导入 fMP4 素材</div>':`<div class="grid cols-2">
             <div>
               <label>素材</label>
               <select id="pkg-material">
                 ${t.map(c=>`<option value="${h(c.materialId)}">${h(c.name)}（${H(c.bytes.length)}）</option>`).join("")}
               </select>
             </div>
             <div>
               <label>课程标题</label>
               <input id="pkg-title" value="职业培训课程 ${new Date().toLocaleDateString()}" />
             </div>
             <div>
               <label>水印漂移间隔（秒）</label>
               <input id="pkg-interval" type="number" min="3" max="60" value="${ie.moveIntervalSec}" />
             </div>
             <div>
               <label>水印透明度（0~1）</label>
               <input id="pkg-opacity" type="number" min="0.1" max="0.9" step="0.05" value="${ie.opacity}" />
             </div>
           </div>
           <div class="row end" style="margin-top:14px">
             <button class="primary" id="pkg-run">🔐 开始 CENC cbcs 加密打包</button>
           </div>
           <div id="pkg-progress" style="display:none">
             <div class="progress-bar"><div id="pkg-bar" style="width:0%"></div></div>
             <div id="pkg-phase" class="file-hint"></div>
           </div>
           <div class="log" id="pkg-log" style="display:none;margin-top:12px"></div>`}
    </div>
    <div class="card">
      <h3>② 已打包课程（${s.length}）</h3>
      <div id="pkg-existing">${qe(s)}</div>
    </div>
    <div class="card" id="pkg-detail-card" style="display:none">
      <h3>③ 分片加密信息（sinf/tenc/senc/saiz/saio 已写入，逐片 SHA-256）</h3>
      <div id="pkg-detail"></div>
    </div>`;const n=e.querySelector("#pkg-log"),a=(c,u="dim")=>{if(!n)return;n.style.display="block";const l=document.createElement("div");l.className=u,l.textContent=`[${new Date().toLocaleTimeString()}] ${c}`,n.appendChild(l),n.scrollTop=n.scrollHeight},r=e.querySelector("#pkg-run");r?.addEventListener("click",async()=>{const c=e.querySelector("#pkg-material").value,u=t.find(v=>v.materialId===c),l=e.querySelector("#pkg-title").value||u.name,p=Number(e.querySelector("#pkg-interval").value),f=Number(e.querySelector("#pkg-opacity").value);r.disabled=!0;const d=e.querySelector("#pkg-progress"),m=e.querySelector("#pkg-bar"),g=e.querySelector("#pkg-phase");d.style.display="block",n&&(n.innerHTML=""),a(`开始打包：${u.name}`,"info");const b=v=>{m.style.width=`${v.current/v.total*100}%`,g.textContent=`${v.phase}（${v.current}/${v.total}）`,a(v.phase)};try{const v=await rs(u.bytes,u.name,{title:l,watermark:{...ie,moveIntervalSec:p,opacity:f},onProgress:b});m.style.width="100%",a(`打包完成：courseId=${v.manifest.courseId}`,"ok"),a(`分片数=${v.manifest.segments.length}（1 init + ${v.manifest.segments.length-1} 媒体）`,"ok");const k=v.manifest.segments.reduce((E,I)=>E+I.encryptedBytes,0);a(`AES-CBC 实际加密字节=${H(k)}，方案=cbcs，视频 pattern=1/9`,"ok"),S("加密打包完成","ok"),i(v.manifest),setTimeout(()=>void o(),600)}catch(v){a(`打包失败：${v.message}`,"err"),S(v.message,"err")}finally{r.disabled=!1}});function i(c){const u=e.querySelector("#pkg-detail-card"),l=e.querySelector("#pkg-detail");u.style.display="block",l.innerHTML=ze(c),l.querySelector("#pkg-export")?.addEventListener("click",async()=>{const p=await _e(c);te(`${c.courseId}.cpkg`,JSON.stringify(p),"application/json"),S("已导出 .cpkg（不含 CEK，播放仍需授权）","ok")})}async function o(){const c=await y.listPackages();e.querySelector("#pkg-existing").innerHTML=qe(c),je(e)}je(e)}function je(e){e.querySelectorAll("[data-view]").forEach(t=>t.addEventListener("click",async()=>{const s=await y.getPackage(t.dataset.view);if(s){const n=e.querySelector("#pkg-detail-card");n.style.display="block",n.scrollIntoView({behavior:"smooth"}),e.querySelector("#pkg-detail").innerHTML=ze(s),e.querySelector("#pkg-export")?.addEventListener("click",async()=>{const a=await _e(s);te(`${s.courseId}.cpkg`,JSON.stringify(a),"application/json")})}})),e.querySelectorAll("[data-del-pkg]").forEach(t=>t.addEventListener("click",async()=>{confirm(`确认删除课程包 ${t.dataset.delPkg}？其分片将一并清除（密钥保留）`)&&(await y.deletePackage(t.dataset.delPkg),S("课程包已删除","ok"),location.reload())}))}function qe(e){return e.length===0?'<div class="empty"><div class="icon">📦</div>尚无已打包课程</div>':`<table>
    <thead><tr><th>课程</th><th>courseId</th><th>分片</th><th>时长</th><th>创建时间</th><th></th></tr></thead>
    <tbody>${e.map(t=>`
      <tr>
        <td><strong>${h(t.title)}</strong></td>
        <td class="mono tiny">${h(t.courseId)}</td>
        <td><span class="badge blue">${t.segments.length}</span></td>
        <td class="mono">${t.durationSec}s</td>
        <td class="mono">${X(t.createdAt)}</td>
        <td class="row">
          <button class="small" data-view="${h(t.courseId)}">分片详情</button>
          <button class="small danger" data-del-pkg="${h(t.courseId)}">删除</button>
        </td>
      </tr>`).join("")}
    </tbody></table>`}function ze(e){const t=e.segments.reduce((s,n)=>s+n.encryptedSize,0);return`
    <dl class="kv" style="margin-bottom:14px">
      <dt>courseId</dt><dd class="mono">${h(e.courseId)}</dd>
      <dt>KID</dt><dd class="mono">${h(e.kid)}</dd>
      <dt>常量 IV</dt><dd class="mono">${h(e.iv)}</dd>
      <dt>水印种子</dt><dd class="mono tiny">${h(e.watermarkSeed)}</dd>
      <dt>轨道</dt><dd>${e.tracks.map(s=>`<span class="badge purple">${h(s.kind)} ${h(s.mseCodec)}</span>`).join(" ")}</dd>
      <dt>加密方案</dt><dd><span class="badge green">cbcs</span> 视频 crypt=1/skip=9，音频全 sample，常量 IV</dd>
      <dt>总大小</dt><dd class="mono">${H(t)}</dd>
    </dl>
    <div class="table-wrap" style="overflow-x:auto">
    <table>
      <thead><tr>
        <th>#</th><th>文件</th><th>类型</th><th>明文→密文</th><th>样本</th>
        <th>加密样本</th><th>子样本</th><th>加密字节</th><th>SHA-256（篡改 1 字节即不匹配）</th>
      </tr></thead>
      <tbody>${e.segments.map(s=>`
        <tr>
          <td class="mono">${s.index<0?"init":s.index+1}</td>
          <td class="mono">${h(s.fileName)}</td>
          <td><span class="badge ${s.kind==="init"?"amber":"blue"}">${s.kind}</span></td>
          <td class="mono">${H(s.clearSize)} → ${H(s.encryptedSize)}</td>
          <td class="mono">${s.sampleCount}</td>
          <td class="mono">${s.encryptedSamples}</td>
          <td class="mono">${s.subsampleCount}</td>
          <td class="mono">${H(s.encryptedBytes)}</td>
          <td class="mono tiny" title="${h(s.sha256)}">${h(s.sha256.slice(0,24))}…</td>
        </tr>`).join("")}
      </tbody>
    </table>
    </div>
    <div class="row end" style="margin-top:14px">
      <button class="primary" id="pkg-export">⬇️ 导出 .cpkg 课程包</button>
    </div>`}async function os(e){const t=await y.listKeys(),s=await y.listPackages(),n=await Xt(),a=await ue();e.innerHTML=`
    <div class="card">
      <h3>发行方签名密钥（ECDSA P-256，本地生成，用于 .lic 签名）</h3>
      <dl class="kv">
        <dt>keyId</dt><dd class="mono">issuer-p256-local</dd>
        <dt>公钥指纹</dt><dd class="mono">${h(n)}</dd>
        <dt>算法</dt><dd>ECDSA P-256 / SHA-256，签名输出 raw r||s（存储 base64url）</dd>
      </dl>
      <div class="row" style="margin-top:10px">
        <button id="keys-pub">查看/导出公钥 JWK</button>
      </div>
    </div>
    <div class="card">
      <h3>课程内容密钥（每课程独立，AES-128 CEK + cbcs 常量 IV）</h3>
      ${t.length===0?'<div class="empty"><div class="icon">🗝️</div>尚无课程密钥，完成「加密打包」后自动生成</div>':`<div class="table-wrap" style="overflow-x:auto"><table>
            <thead><tr><th>课程</th><th>KID</th><th>CEK（仅本机）</th><th>常量 IV</th><th>水印种子</th><th>创建时间</th></tr></thead>
            <tbody>${t.map(r=>`
              <tr>
                <td><strong>${h(s.find(i=>i.courseId===r.courseId)?.title??r.courseId)}</strong>
                    <div class="file-hint mono">${h(r.courseId)}</div></td>
                <td class="mono tiny">${h(r.kid)}</td>
                <td class="mono tiny" title="ClearKey k 字段值">${h(U(r.key))}<div class="file-hint">ck:${h(Z(r.key))}</div></td>
                <td class="mono tiny">${h(U(r.iv))}</td>
                <td class="mono tiny">${h(U(r.watermarkSeed).slice(0,32))}…</td>
                <td class="mono">${X(r.createdAt)}</td>
              </tr>`).join("")}
            </tbody></table></div>
        <p class="file-hint" style="margin-top:10px">
          ⚠️ CEK 仅存在浏览器 IndexedDB，导出的 .cpkg 不含密钥；学员拿到课程包后，必须凭 .lic 由本地许可证服务换取 ClearKey 才能播放。
        </p>`}
    </div>`,e.querySelector("#keys-pub")?.addEventListener("click",()=>{const r=JSON.stringify(a,null,2);te("issuer-public.jwk.json",r,"application/json"),S("公钥 JWK 已导出（可随播放端分发验签）","ok")})}async function cs(e){const t={format:"courseguard-license",version:1,studentId:e.studentId,studentName:e.studentName,courseId:e.courseId,kid:e.kid,issuedAt:Date.now(),expiresAt:e.expiresAt,revocationVersion:e.revocationVersion,scope:{allowSpeed:e.allowSpeed??[.75,1,1.25,1.5,2],allowSeek:e.allowSeek??!0}},{signature:s,issuerKeyId:n}=await Qt(t);return{...t,signature:s,issuerKeyId:n}}async function Ve(e,t,s=Date.now()){const n=[];(e.format!=="courseguard-license"||e.version!==1)&&n.push("授权文件格式/版本不识别");const{signature:a,issuerKeyId:r,...i}=e;return await Zt(i,a,t)||n.push("授权签名无效（文件可能被篡改）"),s<e.issuedAt-5*60*1e3&&n.push("授权尚未生效（系统时间早于签发时间）"),s>=e.expiresAt&&n.push(`授权已于 ${new Date(e.expiresAt).toLocaleString()} 到期`),/^[0-9a-f]{32}$/i.test(e.kid)||n.push("KID 字段非法"),n}function ve(e,t){return e.revocationVersion<t?`授权已被吊销（授权版本 v${e.revocationVersion} < 当前版本 v${t}）`:null}function ls(e){return new Blob([JSON.stringify(e,null,2)],{type:"application/json"})}function ds(e){const t=JSON.parse(e);if(t.format!=="courseguard-license")throw new Error("不是 CourseGuard 授权文件");return t}function us(e,t){return{keys:[{kty:"oct",kid:Z(Tt(e)),k:Z(t)}],type:"temporary"}}function ps(e){const t=new TextDecoder().decode(e),s=JSON.parse(t);return{kids:s.kids??[],type:s.type??""}}function fs(e){return z(JSON.stringify(e)).buffer}async function hs(e){await oe(e)}async function oe(e){const t=await y.listStudents(),s=await y.listPackages(),n=await ue();e.innerHTML=`
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
        ${t.length===0||s.length===0?'<div class="empty">需要先有学员和已打包课程</div>':`<div class="stack">
               <div><label>学员</label>
                 <select id="lic-student">${t.map(r=>`<option value="${h(r.studentId)}">${h(r.studentId)} · ${h(r.name)}</option>`).join("")}</select></div>
               <div><label>课程</label>
                 <select id="lic-course">${s.map(r=>`<option value="${h(r.courseId)}">${h(r.title)}</option>`).join("")}</select></div>
               <div class="grid cols-2">
                 <div><label>有效天数</label><input id="lic-days" type="number" min="1" value="30" /></div>
                 <div><label>或指定到期日</label><input id="lic-date" type="datetime-local" /></div>
               </div>
               <div class="row end"><button class="primary" id="lic-issue">🎫 签发并下载 .lic</button></div>
             </div>`}
      </div>
    </div>

    <div class="card">
      <h3>③ 学员与吊销状态（${t.length}）</h3>
      ${t.length===0?'<div class="empty"><div class="icon">👥</div>暂无学员</div>':`<div class="table-wrap" style="overflow-x:auto"><table>
            <thead><tr><th>编号</th><th>姓名</th><th>状态</th><th>吊销版本</th><th>备注</th><th>创建时间</th><th>操作</th></tr></thead>
            <tbody>${t.map(r=>`
              <tr>
                <td class="mono"><strong>${h(r.studentId)}</strong></td>
                <td>${h(r.name)}</td>
                <td>${r.revoked?'<span class="badge red">已吊销</span>':'<span class="badge green">正常</span>'}</td>
                <td class="mono">v${r.revocationVersion}</td>
                <td>${h(r.note??"")}</td>
                <td class="mono">${X(r.createdAt)}</td>
                <td class="row">
                  <button class="small danger" data-revoke="${h(r.studentId)}" ${r.revoked?"disabled":""}>吊销</button>
                  <button class="small danger" data-remove="${h(r.studentId)}">删除</button>
                </td>
              </tr>`).join("")}
            </tbody></table></div>`}
    </div>

    <div class="card">
      <h3>④ 校验 .lic 文件（验签 / 到期 / 吊销）</h3>
      <input type="file" id="lic-verify" accept=".lic,application/json" />
      <div id="lic-verify-result" style="margin-top:12px"></div>
    </div>`,e.querySelector("#st-add")?.addEventListener("click",async()=>{const r=e.querySelector("#st-id").value.trim(),i=e.querySelector("#st-name").value.trim(),o=e.querySelector("#st-note").value.trim();if(!r||!i)return S("编号和姓名必填","err");if(await y.getStudent(r))return S("该学员编号已存在","err");await y.putStudent({studentId:r,name:i,createdAt:Date.now(),revocationVersion:0,revoked:!1,note:o||void 0}),S(`学员 ${r} 已添加`,"ok"),oe(e)}),e.querySelectorAll("[data-revoke]").forEach(r=>r.addEventListener("click",async()=>{const i=r.dataset.revoke;if(!confirm(`吊销学员 ${i}？其所有已签发 .lic 在下次校验/播放时立即失效（版本号递增）`))return;const o=await y.getStudent(i),c=o.revocationVersion+1;await y.putStudent({...o,revoked:!0,revocationVersion:c}),S(`已吊销，当前版本 v${c}`,"ok"),oe(e)})),e.querySelectorAll("[data-remove]").forEach(r=>r.addEventListener("click",async()=>{confirm("确认删除该学员记录？")&&(await y.deleteStudent(r.dataset.remove),oe(e))})),e.querySelector("#lic-issue")?.addEventListener("click",async()=>{const r=e.querySelector("#lic-student").value,i=e.querySelector("#lic-course").value,o=Number(e.querySelector("#lic-days").value),c=e.querySelector("#lic-date").value,u=await y.getStudent(r),l=await y.getPackage(i);if(!l)return S("课程不存在","err");const p=c?new Date(c).getTime():Date.now()+o*864e5,f=await y.getRevocation(i),d=await cs({studentId:r,studentName:u.name,courseId:i,kid:l.kid,expiresAt:p,revocationVersion:Math.max(u.revocationVersion,f)});te(`${r}.${i}.lic`,ls(d)),S(`授权已签发，到期 ${new Date(p).toLocaleString()}`,"ok")});const a=e.querySelector("#lic-verify");a?.addEventListener("change",async()=>{const r=a.files?.[0],i=e.querySelector("#lic-verify-result");if(r)try{const o=JSON.parse(await Ye(r)),c=await Ve(o,n),u=await y.getStudent(o.studentId),l=u?ve(o,u.revocationVersion):"本地无该学员记录",p=[...c];u&&u.revoked&&l&&p.push(l),u||p.push(String(l)),i.innerHTML=`
        <dl class="kv">
          <dt>学员</dt><dd>${h(o.studentName)}（${h(o.studentId)}）</dd>
          <dt>课程</dt><dd class="mono">${h(o.courseId)}</dd>
          <dt>KID</dt><dd class="mono tiny">${h(o.kid)}</dd>
          <dt>有效期</dt><dd class="mono">${X(o.issuedAt)} → ${X(o.expiresAt)}</dd>
          <dt>吊销版本</dt><dd class="mono">v${o.revocationVersion}</dd>
          <dt>结论</dt><dd>${p.length===0?'<span class="badge green">✓ 授权有效</span>':p.map(f=>`<span class="badge red">✗ ${h(f)}</span>`).join("<br/>")}</dd>
        </dl>`}catch(o){i.innerHTML=`<span class="badge red">文件解析失败：${h(o.message)}</span>`}})}async function ms(e,t={}){const s=[];let n=!0;for(let a=0;a<e.segments.length;a++){const r=e.segments[a];t.onProgress?.(a,e.segments.length,r);const i=await y.getSegment(e.courseId,r.fileName);if(!i){n=!1,s.push({info:r,ok:!1,error:"本地缺少该分片文件"});continue}const o=await de(i),c=o===r.sha256;c||(n=!1),s.push({info:r,ok:c,actualSha256:o,...c?{}:{error:`哈希不匹配：期望 ${r.sha256.slice(0,16)}… 实际 ${o.slice(0,16)}…`}})}return{ok:n,results:s,checkedAt:Date.now()}}async function ys(e,t){const s=e.segments.find(i=>i.fileName===t);if(!s)throw new Error(`清单中不存在分片 ${t}`);const n=await y.getSegment(e.courseId,t);if(!n)return{info:s,ok:!1,error:"本地缺少该分片文件"};const a=await de(n),r=a===s.sha256;return{info:s,ok:r,actualSha256:a,...r?{}:{error:`分片 ${t} 已损坏或被篡改（SHA-256 不匹配），已阻止解码`}}}const gs="org.w3.clearkey";class vs{video;manifest;license;resolveKey;gate;emit;mediaSource=null;sourceBuffer=null;objectUrl=null;sessions=[];appendQueue=Promise.resolve();stopped=!1;appendIndex=0;timer=null;constructor(t){this.video=t.video,this.manifest=t.manifest,this.license=t.license,this.resolveKey=t.resolveKey,this.gate=t.gate,this.emit=t.onEvent??(()=>{})}async start(){this.stopped=!1;const t=this.gate.checkPlaybackAllowed();if(t)throw new Error(t);await this.setupEme(),await this.setupMse(),this.startTimeGate(),this.emit({type:"state",state:"ready"})}async setupEme(){if(!navigator.requestMediaKeySystemAccess)throw new Error("当前浏览器不支持 EME（Encrypted Media Extensions）");const t=this.manifest.tracks.find(c=>c.kind==="video")?.mseCodec??"avc1.42E01E",s=this.manifest.tracks.find(c=>c.kind==="audio"),n={initDataTypes:["keyids"],audioCapabilities:s?[{contentType:`audio/mp4; codecs="${s.mseCodec}"`,encryptionScheme:"cbcs"}]:[],videoCapabilities:[{contentType:`video/mp4; codecs="${t}"`,encryptionScheme:"cbcs"}],distinctiveIdentifier:"not-allowed",persistentState:"not-allowed",sessionTypes:["temporary"]};let a;try{a=await navigator.requestMediaKeySystemAccess(gs,[n])}catch(c){throw new Error(`ClearKey CDM 不可用：${c.message}。请使用 Chrome/Edge 并通过 http(s) 或 localhost 打开。`)}const r=await a.createMediaKeys();await this.video.setMediaKeys(r),this.emit({type:"log",message:"已创建 ClearKey MediaKeys"});const i=r.createSession("temporary");this.sessions.push(i),i.addEventListener("message",async c=>{try{await this.handleLicenseMessage(i,c)}catch(u){this.emit({type:"error",message:`许可证处理失败：${u.message}`,fatal:!0})}}),i.addEventListener("keystatuseschange",()=>{const c=[];i.keyStatuses.forEach(u=>c.push(u)),this.emit({type:"license",message:`密钥状态：${c.join(", ")||"无"}`})});const o=this.buildKeyIdsInitData(this.manifest.kid);await i.generateRequest("keyids",o),this.emit({type:"log",message:"已发送 ClearKey license request（本地模拟）"})}buildKeyIdsInitData(t){const s=JSON.stringify({kids:[ws(t)],type:"temporary"});return new TextEncoder().encode(s)}async handleLicenseMessage(t,s){const{kids:n}=ps(s.message);if(n.length===0)throw new Error("license request 中没有 KID");const a=this.gate.checkPlaybackAllowed();if(a){this.emit({type:"error",message:`许可证发放被拒绝：${a}`,fatal:!0}),await this.stop();return}const r=n[0],i=bs(r);if(i.toLowerCase()!==this.license.kid.toLowerCase())throw new Error(`请求的 KID ${i} 与授权课程 ${this.license.kid} 不一致`);const o=await this.resolveKey(i),c=us(i,o),u=fs(c);await t.update(u),this.emit({type:"license",message:"本地许可证服务已下发 ClearKey 密钥（KID 匹配授权）"})}async setupMse(){const s=`video/mp4; codecs="${this.manifest.tracks.map(a=>a.mseCodec).filter(Boolean).join(", ")}"`;if(!window.MediaSource||!MediaSource.isTypeSupported(s))throw new Error(`MSE 不支持该编码组合：${s}`);const n=new MediaSource;this.mediaSource=n,this.objectUrl=URL.createObjectURL(n),this.video.src=this.objectUrl,await new Promise((a,r)=>{n.addEventListener("sourceopen",()=>a(),{once:!0}),n.addEventListener("sourceended",()=>this.emit({type:"state",state:"ended"})),setTimeout(()=>r(new Error("MediaSource 打开超时")),1e4)}),this.sourceBuffer=n.addSourceBuffer(s),this.sourceBuffer.mode="sequence",this.sourceBuffer.addEventListener("error",()=>{this.emit({type:"error",message:"SourceBuffer 解码错误（分片可能损坏）",fatal:!0})}),this.emit({type:"log",message:`SourceBuffer 已创建：${s}`}),this.pumpSegments()}pumpSegments(){const t=this.manifest.segments,s=()=>{if(this.stopped)return;if(this.appendIndex>=t.length){if(this.mediaSource?.readyState==="open")try{this.mediaSource.endOfStream()}catch{}this.emit({type:"state",state:"fully-buffered"});return}const n=t[this.appendIndex];this.appendQueue=this.appendQueue.then(async()=>{if(this.stopped||!this.sourceBuffer)return;const a=await ys(this.manifest,n.fileName);if(this.emit({type:"verify",fileName:n.fileName,ok:a.ok}),!a.ok){this.emit({type:"error",message:a.error??`${n.fileName} 校验失败`,fatal:!0}),await this.stop();return}const r=this.gate.checkPlaybackAllowed();if(r){this.emit({type:"error",message:r,fatal:!0}),await this.stop();return}const i=await y.getSegment(this.manifest.courseId,n.fileName);if(!i){this.emit({type:"error",message:`缺少分片 ${n.fileName}`,fatal:!0}),await this.stop();return}if(await this.waitForUpdate(),!this.stopped){try{this.sourceBuffer.appendBuffer(i.slice().buffer)}catch(o){this.emit({type:"error",message:`appendBuffer 失败：${o.message}`,fatal:!0}),await this.stop();return}await this.waitForUpdate(),this.appendIndex++,this.emit({type:"progress",bufferedSec:this.video.buffered.length?this.video.buffered.end(this.video.buffered.length-1):0,durationSec:this.manifest.durationSec}),s()}})};s()}waitForUpdate(){const t=this.sourceBuffer;return!t||!t.updating?Promise.resolve():new Promise((s,n)=>{const a=()=>{t.removeEventListener("update",a),t.removeEventListener("error",r),s()},r=()=>{t.removeEventListener("update",a),t.removeEventListener("error",r),n(new Error("SourceBuffer 更新失败"))};t.addEventListener("update",a),t.addEventListener("error",r)})}startTimeGate(){this.timer=window.setInterval(()=>{if(this.stopped)return;const t=this.gate.checkPlaybackAllowed();t&&(this.emit({type:"error",message:t,fatal:!0}),this.stop())},2e3)}setPlaybackRate(t){this.video.playbackRate=t}seekTo(t){const s=this.gate.checkPlaybackAllowed();if(s){this.emit({type:"error",message:s,fatal:!1});return}this.video.currentTime=Math.min(Math.max(0,t),this.manifest.durationSec)}async stop(){this.stopped=!0,this.timer!==null&&(clearInterval(this.timer),this.timer=null);try{this.video.pause(),this.video.removeAttribute("src"),this.video.load()}catch{}this.objectUrl&&URL.revokeObjectURL(this.objectUrl),this.objectUrl=null;for(const t of this.sessions)try{await t.close()}catch{}if(this.sessions=[],this.mediaSource&&this.mediaSource.readyState==="open")try{this.mediaSource.endOfStream()}catch{}this.mediaSource=null,this.sourceBuffer=null,this.emit({type:"state",state:"stopped"})}}function ws(e){const t=new Uint8Array(e.length/2);for(let n=0;n<t.length;n++)t[n]=parseInt(e.slice(n*2,n*2+2),16);let s="";for(const n of t)s+=String.fromCharCode(n);return btoa(s).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,"")}function bs(e){const t=atob(e.replace(/-/g,"+").replace(/_/g,"/"));let s="";for(let n=0;n<t.length;n++)s+=t.charCodeAt(n).toString(16).padStart(2,"0");return s}class ks{state;constructor(t){this.state=t>>>0}next(){this.state=this.state+1831565813>>>0;let t=this.state;return t=Math.imul(t^t>>>15,t|1),t^=t+Math.imul(t^t>>>7,t|61),((t^t>>>14)>>>0)/4294967296}range(t,s){return t+this.next()*(s-t)}}async function Ss(e,t){const s=new Uint8Array(e.length+z(t).length);s.set(e,0),s.set(z(t),e.length);const n=await Fe(s);return new DataView(n.buffer,n.byteOffset,4).getUint32(0,!0)}async function Je(e,t,s,n){const a=await Ss(e,t),r=new ks(a),i=Math.max(1,Math.ceil(s/n.moveIntervalSec)+1),o=.12,c=[];let u=.5,l=.5;for(let p=0;p<i;p++){let f=r.range(o,1-o),d=r.range(o,1-o);for(let b=0;b<8&&Math.hypot(f-u,d-l)<.22;b++)f=r.range(o,1-o),d=r.range(o,1-o);const m=r.range(-18,18),g=[r.next()>.5,r.next()>.5,r.next()>.5,r.next()>.5];c.push({timeSec:p*n.moveIntervalSec,x:f,y:d,rotation:m,corners:g}),u=f,l=d}return c}function We(e,t){let s=e[0];for(const n of e)if(n.timeSec<=t)s=n;else break;return s}async function $s(e,t,s,n,a,r,i){const o=[];for(const c of e){const u=await Je(t,c.studentId,s,n);let l=u;if(i!==void 0){const f=i-n.moveIntervalSec,d=i+n.moveIntervalSec;l=u.filter(m=>m.timeSec>=f&&m.timeSec<=d),l.length===0&&(l=[We(u,i)])}let p=null;for(const f of l){const d=Math.hypot(f.x-a,f.y-r)/Math.SQRT2,m=Math.max(0,1-d*2.2);(!p||m>p.score)&&(p={studentId:c.studentId,studentName:c.studentName,slot:f,distance:d,score:m})}p&&o.push(p)}return o.sort((c,u)=>u.score-c.score)}function Es(e,t){return`${t} ${e}`}async function Is(e){const t=await y.listPackages();e.innerHTML=`
    <div class="card">
      <h3>① 选择课程并加载学员授权</h3>
      <div class="grid cols-2">
        <div><label>本地课程包</label>
          <select id="pl-course">
            ${t.map(l=>`<option value="${h(l.courseId)}">${h(l.title)}（${l.segments.length} 分片）</option>`).join("")}
          </select></div>
        <div><label>学员授权文件 .lic</label>
          <input type="file" id="pl-lic" accept=".lic,application/json" />
          <div id="pl-lic-status" class="file-hint"></div></div>
      </div>
      <div class="row end" style="margin-top:14px">
        <button id="pl-verify">② 校验授权与全分片哈希</button>
        <button class="primary" id="pl-play" disabled>③ 开始播放</button>
        <button class="danger" id="pl-stop" disabled>停止</button>
      </div>
      <div id="pl-gate" style="margin-top:12px"></div>
    </div>

    <div class="card">
      <h3>播放（EME ClearKey · 原生 MSE，支持拖动与倍速）</h3>
      <div class="video-wrap">
        <video id="pl-video" controls playsinline></video>
        <div class="wm-layer" id="pl-wm"></div>
      </div>
      <div class="row" style="margin-top:12px">
        <label style="margin:0">倍速</label>
        <select id="pl-rate" style="width:auto">
          ${[.75,1,1.25,1.5,2].map(l=>`<option value="${l}" ${l===1?"selected":""}>${l}x</option>`).join("")}
        </select>
        <button class="small" data-seek="0">开头</button>
        <button class="small" data-seek="0.25">25%</button>
        <button class="small" data-seek="0.5">50%</button>
        <button class="small" data-seek="0.75">75%</button>
        <span id="pl-time" class="mono file-hint" style="margin-left:auto"></span>
      </div>
      <div class="log" id="pl-log" style="display:none;margin-top:12px"></div>
    </div>`;let s=null,n=null,a=null,r=null,i=[];const o=e.querySelector("#pl-log"),c=(l,p="dim")=>{o.style.display="block";const f=document.createElement("div");f.className=p,f.textContent=`[${new Date().toLocaleTimeString()}] ${l}`,o.appendChild(f),o.scrollTop=o.scrollHeight},u=e.querySelector("#pl-lic");u?.addEventListener("change",async()=>{const l=u.files?.[0],p=e.querySelector("#pl-lic-status");if(l)try{s=ds(await Ye(l)),p.innerHTML=`<span class="badge blue">已加载</span> ${h(s.studentName)} · ${h(s.studentId)} · 到期 ${new Date(s.expiresAt).toLocaleString()}`}catch(f){p.innerHTML=`<span class="badge red">${h(f.message)}</span>`,s=null}}),e.querySelector("#pl-verify")?.addEventListener("click",async()=>{const l=e.querySelector("#pl-course").value;n=await y.getPackage(l)??null;const p=e.querySelector("#pl-gate");if(!n)return S("课程包不存在","err");if(!s)return S("请先加载 .lic 授权文件","err");const f=await ue(),d=await Ve(s,f),m=await y.getStudent(s.studentId),g=m?ve(s,m.revocationVersion):"本地无学员记录";m&&g&&d.push(g),s.courseId!==n.courseId&&d.push("授权课程与所选课程包不匹配"),s.kid.toLowerCase()!==n.kid.toLowerCase()&&d.push("授权 KID 与课程包 KID 不一致"),c("开始逐分片 SHA-256 校验…","info"),a=await ms(n,{onProgress:(k,E)=>{(k%5===0||k===E-1)&&c(`哈希校验 ${k+1}/${E}`)}});const b=a.results.filter(k=>!k.ok);c(a.ok?`全部 ${a.results.length} 个分片哈希通过`:`${b.length} 个分片损坏/被篡改`,a.ok?"ok":"err");const v=d.length===0&&a.ok;p.innerHTML=`
      <div class="card" style="margin:0">
        <div class="row" style="justify-content:space-between">
          <strong>授权校验</strong>
          ${d.length===0?'<span class="badge green">✓ 签名/有效期/吊销/KID 全部通过</span>':d.map(k=>`<span class="badge red">✗ ${h(k)}</span>`).join(" ")}
        </div>
        <div class="row" style="justify-content:space-between;margin-top:8px">
          <strong>完整性校验</strong>
          ${a.ok?`<span class="badge green">✓ ${a.results.length} 个分片 SHA-256 全部匹配</span>`:`<span class="badge red">✗ ${b.length} 个分片损坏：${h(b.map(k=>k.info.fileName).join(", "))}</span>`}
        </div>
      </div>`,e.querySelector("#pl-play").disabled=!v,v?S("校验通过，可以播放","ok"):S("校验未通过，已禁止播放","err")}),e.querySelector("#pl-play")?.addEventListener("click",async()=>{if(!n||!s)return;const l=e.querySelector("#pl-video"),p=await y.getKey(n.courseId);if(!p)return S("本地缺少该课程 CEK，无法发放 ClearKey 许可证","err");const f={checkPlaybackAllowed:()=>Date.now()>=s.expiresAt?`授权已过期（${new Date(s.expiresAt).toLocaleString()}），播放已中止`:null};r=new vs({video:l,manifest:n,license:s,resolveKey:async d=>{if(d.toLowerCase()!==p.kid.toLowerCase())throw new Error("KID 不匹配");const m=await y.getStudent(s.studentId);if(m){const g=ve(s,m.revocationVersion);if(g)throw new Error(g)}return p.key},gate:f,onEvent:d=>{d.type==="error"?c(d.message,"err"):d.type==="verify"?c(`分片校验 ${d.ok?"通过":"失败"}：${d.fileName}`,d.ok?"ok":"err"):d.type==="license"||d.type==="log"?c(d.message,"info"):d.type==="state"?c(d.state,"info"):d.type==="progress"&&c(`已缓冲 ${d.bufferedSec.toFixed(1)}s / ${d.durationSec}s`)}});try{await r.start(),e.querySelector("#pl-stop").disabled=!1,e.querySelector("#pl-play").disabled=!0,await l.play();const d=Se(n.watermarkSeed);i=await Je(d,s.studentId,n.durationSec,n.watermark),xs(e,l,i,n,s),S("播放已启动，水印按学员编号独立漂移","ok")}catch(d){c(`播放失败：${d.message}`,"err"),S(d.message,"err")}}),e.querySelector("#pl-stop")?.addEventListener("click",()=>{r?.stop(),e.querySelector("#pl-wm").innerHTML="",e.querySelector("#pl-stop").disabled=!0,e.querySelector("#pl-play").disabled=!1}),e.querySelector("#pl-rate")?.addEventListener("change",l=>{r?.setPlaybackRate(Number(l.target.value))}),e.querySelectorAll("[data-seek]").forEach(l=>l.addEventListener("click",()=>{const p=e.querySelector("#pl-video");n?r?.seekTo(Number(l.dataset.seek)*n.durationSec):p.currentTime=0}))}function xs(e,t,s,n,a){const r=e.querySelector("#pl-wm"),i=Es(a.studentId,a.studentName),o=n.watermark.opacity,c=()=>{const l=We(s,t.currentTime),p=t.getBoundingClientRect(),f=Math.max(13,p.height*n.watermark.fontSizeRatio);r.innerHTML=`
      <div class="wm-main" style="
        left:${l.x*100}%; top:${l.y*100}%;
        font-size:${f}px; opacity:${o};
        transform:translate(-50%,-50%) rotate(${l.rotation}deg);">
        ${h(i)}
      </div>
      ${n.watermark.cornerWatermarks?`
        <div class="wm-corner" style="left:10px;top:8px;opacity:${o*.9}">${h(a.studentId)}</div>
        <div class="wm-corner" style="right:10px;top:8px;opacity:${o*.9}">${h(a.studentId)}</div>
        <div class="wm-corner" style="left:10px;bottom:8px;opacity:${o*.9}">${h(a.studentId)}</div>
        <div class="wm-corner" style="right:10px;bottom:8px;opacity:${o*.9}">${h(a.studentId)}</div>`:""}`,e.querySelector("#pl-time").textContent=`${ge(t.currentTime)} / ${ge(n.durationSec)} · 槽位 t=${l.timeSec}s 坐标(${(l.x*100).toFixed(0)}%,${(l.y*100).toFixed(0)}%)`};c();const u=window.setInterval(c,500);t.addEventListener("seeked",c),e.querySelector("#pl-video")._wmTimer=u}async function Cs(e){const t=await y.listPackages(),s=await y.listStudents();e.innerHTML=`
    <div class="card">
      <h3>① 选择泄露课程并上传截图</h3>
      <div class="grid cols-2">
        <div><label>课程（提供水印种子与漂移参数）</label>
          <select id="tr-course">${t.map(f=>`<option value="${h(f.courseId)}">${h(f.title)}</option>`).join("")}</select>
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
      <div class="file-hint">在册候选学员：${s.length} 人</div>
    </div>`;let n=[],a=null;const r=e.querySelector("#tr-file"),i=e.querySelector("#tr-canvas-wrap"),o=e.querySelector("#tr-marks"),c=e.querySelector("#tr-run");r?.addEventListener("change",()=>{const f=r.files?.[0];if(!f)return;const d=URL.createObjectURL(f);a=document.createElement("img"),a.src=d,a.style.maxWidth="100%",a.style.display="block",a.style.cursor="crosshair",i.classList.remove("empty"),i.innerHTML="",i.appendChild(a),n=[],a.addEventListener("load",()=>u())});function u(){a.addEventListener("click",f=>{const d=a.getBoundingClientRect(),m=(f.clientX-d.left)/d.width,g=(f.clientY-d.top)/d.height;n.push({x:m,y:g}),l()})}function l(){o.innerHTML=n.map((f,d)=>`<span class="badge blue">#${d+1} (${f.x.toFixed(3)}, ${f.y.toFixed(3)})</span>`).join(""),c.disabled=n.length===0}e.querySelector("#tr-clear")?.addEventListener("click",()=>{n=[],l()}),c.addEventListener("click",async()=>{const f=e.querySelector("#tr-course").value,d=await y.getPackage(f);if(!d)return S("课程包不存在","err");const m=await y.listStudents();if(m.length===0)return S("没有在册学员可比对","err");const g=e.querySelector("#tr-time").value,b=g===""?void 0:Number(g),v=Se(d.watermarkSeed);c.disabled=!0,c.textContent="反查中…";const k=[];for(const $ of n){const x=await $s(m.map(M=>({studentId:M.studentId,studentName:M.name})),v,d.durationSec,d.watermark,$.x,$.y,b);k.push(x)}const E=new Map;for(const $ of k)for(const x of $){const M=E.get(x.studentId)??{studentId:x.studentId,studentName:x.studentName,scores:[],slots:[]};M.scores.push(x.score),M.slots.push(x),E.set(x.studentId,M)}const I=[...E.values()].map($=>({...$,avgScore:$.scores.reduce((x,M)=>x+M,0)/$.scores.length})).sort(($,x)=>x.avgScore-$.avgScore);p(I,n.length),c.disabled=!1,c.textContent="③ 开始反查学员"});function p(f,d){const m=e.querySelector("#tr-result"),g=f[0];m.innerHTML=`
      <div style="margin-bottom:14px">
        ${g&&g.avgScore>.6?`<span class="badge green" style="font-size:13px">🎯 最可能泄露者：${h(g.studentName)}（${h(g.studentId)}）平均置信度 ${(g.avgScore*100).toFixed(1)}%</span>`:`<span class="badge amber">置信度偏低（最高分 ${(g?.avgScore??0*100).toFixed(1)}%），建议增加标注点或核对截图时间</span>`}
      </div>
      <table>
        <thead><tr><th>排名</th><th>学员</th><th>平均置信度</th><th>最佳槽位时间</th><th>槽位坐标(x,y)</th><th>标注点数</th></tr></thead>
        <tbody>
          ${f.slice(0,10).map((b,v)=>{const k=b.slots.reduce((E,I)=>I.score>E.score?I:E);return`<tr style="${v===0?"background:rgba(63,185,80,0.08)":""}">
              <td><strong>#${v+1}</strong></td>
              <td>${h(b.studentName)}<div class="file-hint mono">${h(b.studentId)}</div></td>
              <td>
                <div class="progress-bar" style="width:120px;display:inline-block;vertical-align:middle">
                  <div style="width:${b.avgScore*100}%;background:${b.avgScore>.6?"var(--green)":"var(--amber)"}"></div>
                </div>
                <span class="mono">${(b.avgScore*100).toFixed(1)}%</span>
              </td>
              <td class="mono">${k.slot.timeSec}s</td>
              <td class="mono">(${k.slot.x.toFixed(3)}, ${k.slot.y.toFixed(3)})</td>
              <td class="mono">${d}</td>
            </tr>`}).join("")}
        </tbody>
      </table>`}}const we=[{id:"materials",label:"课程素材",icon:"🎬",desc:"生成或导入 fMP4 分片素材"},{id:"packager",label:"加密打包",icon:"🔐",desc:"CENC cbcs 加密、哈希、分片清单"},{id:"keys",label:"密钥管理",icon:"🗝️",desc:"每课程 KID/CEK/IV 与水印种子"},{id:"students",label:"学员授权",icon:"🎫",desc:"学员、到期时间、吊销与 .lic 签发"},{id:"player",label:"播放端",icon:"▶️",desc:"ClearKey EME 授权播放与漂移水印"},{id:"trace",label:"水印溯源",icon:"🔍",desc:"泄露截图按水印位置反查学员"}];function As(){const e=location.hash.replace("#/","").split("?")[0];return we.some(t=>t.id===e)?e:"materials"}function Ls(e){location.hash=`#/${e}`}function Ge(){const e=As(),t=we.find(r=>r.id===e),s=document.getElementById("app");s.innerHTML=`
    <div class="layout">
      <aside class="sidebar">
        <div class="brand">CourseGuard<small>本地 CENC/cbcs · ClearKey</small></div>
        ${we.map(r=>`
          <div class="nav-item ${r.id===e?"active":""}" data-route="${r.id}">
            <span>${r.icon}</span><span>${r.label}</span>
          </div>`).join("")}
        <div style="margin-top:24px; padding:10px; font-size:11px; color:var(--text-faint); line-height:1.7">
          全流程浏览器本地完成<br/>密钥与分片不离开本机
        </div>
      </aside>
      <main class="main">
        <h1 class="page-title">${t.icon} ${t.label}</h1>
        <p class="page-sub">${t.desc}</p>
        <div id="page-root"></div>
      </main>
    </div>
    <div class="toast-wrap" id="toast-wrap"></div>
  `,s.querySelectorAll(".nav-item").forEach(r=>{r.addEventListener("click",()=>Ls(r.dataset.route))});const n=document.getElementById("page-root");({materials:Bt,packager:is,keys:os,students:hs,player:Is,trace:Cs})[e](n)}function S(e,t="info",s=3200){const n=document.getElementById("toast-wrap");if(!n)return;const a=document.createElement("div");a.className=`toast ${t}`,a.textContent=e,n.appendChild(a),setTimeout(()=>{a.style.opacity="0",a.style.transition="opacity 0.3s",setTimeout(()=>a.remove(),320)},s)}function te(e,t,s="application/octet-stream"){const n=typeof t=="string"?new Blob([t],{type:s}):t,a=URL.createObjectURL(n),r=document.createElement("a");r.href=a,r.download=e,r.click(),setTimeout(()=>URL.revokeObjectURL(a),1e3)}function Ts(e){return e.arrayBuffer().then(t=>new Uint8Array(t))}function Ye(e){return e.text()}function h(e){return String(e??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")}Ge();window.addEventListener("hashchange",Ge);
//# sourceMappingURL=index-BqnWQhUX.js.map
