"""Single-file web gallery served to phones and other devices on the LAN."""

PAGE = r"""<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Home Archive Lab</title>
<style>
:root{--bg:#0f1115;--panel:#171a21;--line:#262a35;--text:#e8eaf0;--muted:#8a90a2;--accent:#7c5cff;--accent2:#22d3ee}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{position:sticky;top:0;z-index:5;display:flex;gap:12px;align-items:center;padding:14px 16px;background:rgba(15,17,21,.85);backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}
.logo{width:30px;height:30px;border-radius:9px;background:linear-gradient(135deg,var(--accent),var(--accent2))}
h1{font-size:16px;margin:0;font-weight:650}#dev{color:var(--muted);font-size:13px}
.sp{flex:1}.btn{border:0;border-radius:10px;padding:9px 14px;background:var(--accent);color:#fff;font-weight:600;cursor:pointer}
.btn.ghost{background:var(--panel);border:1px solid var(--line);color:var(--text)}
#crumbs{padding:12px 16px;display:flex;flex-wrap:wrap;gap:6px;color:var(--muted)}#crumbs a{color:var(--text);text-decoration:none;padding:3px 9px;border-radius:8px;background:var(--panel)}
#grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;padding:0 16px 40px}
.card{position:relative;aspect-ratio:1;border-radius:14px;overflow:hidden;background:var(--panel);border:1px solid var(--line);cursor:pointer}
.card img{width:100%;height:100%;object-fit:cover;display:block}
.card .cap{position:absolute;left:0;right:0;bottom:0;padding:6px 8px;font-size:12px;background:linear-gradient(transparent,rgba(0,0,0,.75));white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.folder{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;color:var(--text)}
.folder svg{width:48px;height:48px;color:var(--accent)}
.badge{position:absolute;top:8px;right:8px;background:rgba(0,0,0,.6);border-radius:7px;padding:2px 7px;font-size:11px}
#viewer{position:fixed;inset:0;background:rgba(0,0,0,.94);display:none;flex-direction:column;z-index:10}
#viewer .stage{flex:1;display:flex;align-items:center;justify-content:center;min-height:0}
#viewer img,#viewer video{max-width:100%;max-height:100%}
#viewer .bar{display:flex;gap:8px;padding:12px 16px;align-items:center}
#pin{position:fixed;inset:0;display:none;align-items:center;justify-content:center;background:var(--bg);z-index:20}
#pin .box{background:var(--panel);padding:24px;border-radius:16px;border:1px solid var(--line);width:280px;text-align:center}
#pin input{width:100%;padding:12px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--text);font-size:20px;text-align:center;letter-spacing:6px;margin:14px 0}
#toast{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:var(--panel);border:1px solid var(--line);padding:10px 16px;border-radius:12px;display:none}
.empty{color:var(--muted);padding:40px;text-align:center;grid-column:1/-1}
</style></head><body>
<header><div class="logo"></div><div><h1>Home Archive Lab</h1><div id="dev"></div></div><div class="sp"></div>
<label class="btn" id="upbtn" style="display:none">Загрузить<input type="file" id="up" multiple accept="image/*,video/*" hidden></label></header>
<div id="crumbs"></div><div id="grid"></div>
<div id="viewer"><div class="stage" id="stage"></div><div class="bar"><span id="vname" style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></span>
<button class="btn ghost" id="prev">◀</button><button class="btn ghost" id="next">▶</button><a class="btn" id="dl">Скачать</a><button class="btn ghost" id="close">✕</button></div></div>
<div id="pin"><div class="box"><div class="logo" style="margin:0 auto 12px;width:44px;height:44px"></div><b>Введите PIN</b><input id="pinv" inputmode="numeric" autocomplete="off"><button class="btn" style="width:100%" id="pinok">Войти</button></div></div>
<div id="toast"></div>
<script>
let cur="",files=[],idx=0;
const $=s=>document.querySelector(s);
const enc=encodeURIComponent;
const fsz=n=>n>1<<30?(n/(1<<30)).toFixed(1)+" ГБ":n>1<<20?(n/(1<<20)).toFixed(1)+" МБ":Math.round(n/1024)+" КБ";
function toast(t){const e=$("#toast");e.textContent=t;e.style.display="block";clearTimeout(e._t);e._t=setTimeout(()=>e.style.display="none",2500)}
async function api(u,o){const r=await fetch(u,o);if(r.status==401){$("#pin").style.display="flex";throw "pin"}return r.json()}
async function info(){const i=await (await fetch("/api/info")).json();$("#dev").textContent=i.name+" · v"+i.version;$("#upbtn").style.display=i.upload?"":"none"}
async function load(p){cur=p;location.hash=enc(p);const d=await api("/api/list?path="+enc(p));files=d.files;
 const c=$("#crumbs");c.innerHTML="";let acc="";
 const crumb=(t,v)=>{const a=document.createElement("a");a.href="#";a.textContent=t;a.onclick=e=>{e.preventDefault();load(v)};c.appendChild(a)};
 crumb("Архив","");(d.path?d.path.split("/"):[]).forEach(s=>{acc+=(acc?"/":"")+s;c.append(" / ");crumb(s,acc)});
 const g=$("#grid");g.innerHTML="";
 d.folders.forEach(f=>{const e=document.createElement("div");e.className="card folder";
  e.innerHTML='<svg viewBox="0 0 24 24" fill="currentColor"><path d="M10 4l2 2h8a2 2 0 012 2v10a2 2 0 01-2 2H4a2 2 0 01-2-2V6a2 2 0 012-2h6z"/></svg><div class="cap" style="background:none;position:static;text-align:center"></div>';
  e.querySelector(".cap").textContent=f;e.onclick=()=>load((p?p+"/":"")+f);g.appendChild(e)});
 d.files.forEach((f,i)=>{const e=document.createElement("div");e.className="card";
  e.innerHTML='<img loading="lazy"><div class="cap"></div>'+(f.kind=="video"?'<span class="badge">▶ видео</span>':'');
  e.querySelector("img").src="/api/thumb?path="+enc((p?p+"/":"")+f.name);e.querySelector(".cap").textContent=f.name+" · "+fsz(f.size);
  e.onclick=()=>show(i);g.appendChild(e)});
 if(!d.folders.length&&!d.files.length)g.innerHTML='<div class="empty">Здесь пока пусто</div>'}
function rel(f){return (cur?cur+"/":"")+f.name}
function show(i){idx=(i+files.length)%files.length;const f=files[idx],u="/api/file?path="+enc(rel(f));
 $("#stage").innerHTML=f.kind=="video"?'<video controls autoplay playsinline src="'+u+'"></video>':'<img src="'+u+'">';
 $("#vname").textContent=f.name;$("#dl").href=u+"&dl=1";$("#viewer").style.display="flex"}
$("#close").onclick=()=>{$("#viewer").style.display="none";$("#stage").innerHTML=""};
$("#prev").onclick=()=>show(idx-1);$("#next").onclick=()=>show(idx+1);
document.onkeydown=e=>{if($("#viewer").style.display!="flex")return;if(e.key=="Escape")$("#close").click();if(e.key=="ArrowLeft")show(idx-1);if(e.key=="ArrowRight")show(idx+1)};
$("#pinok").onclick=()=>{document.cookie="hal_pin="+enc($("#pinv").value)+";path=/;max-age=31536000";$("#pin").style.display="none";load(cur)};
$("#pinv").onkeydown=e=>{if(e.key=="Enter")$("#pinok").click()};
$("#up").onchange=async e=>{const fs=[...e.target.files];let n=0;
 for(const f of fs){toast("Загрузка "+(++n)+"/"+fs.length+": "+f.name);
  const r=await fetch("/api/upload?path="+enc(cur),{method:"POST",headers:{"X-Filename":enc(f.name)},body:f});
  if(!r.ok){toast("Ошибка: "+f.name);return}}
 toast("Готово: "+fs.length+" файл(ов)");load(cur)};
info();load(decodeURIComponent(location.hash.slice(1)||"")).catch(()=>{});
</script></body></html>
"""
