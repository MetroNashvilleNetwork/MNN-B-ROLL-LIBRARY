"use strict";

const state = {
  q: "", shooter: "", shot: "", ext: "", from: "", to: "",
  category: "", categoryLabel: "", sort: "relevance",
  offset: 0, limit: 60, total: 0, loading: false, done: false, items: [],
};
const el = (id) => document.getElementById(id);
const grid = el("grid");
const itemIndex = new Map();           // id -> item (for collection + stars)

/* ---------- formatting ---------- */
const fmtDuration = (sec) => {
  if (!sec) return ""; sec = Math.round(sec);
  const m = Math.floor(sec / 60), s = sec % 60, h = Math.floor(m / 60);
  return h ? `${h}:${String(m % 60).padStart(2,"0")}:${String(s).padStart(2,"0")}` : `${m}:${String(s).padStart(2,"0")}`;
};
const fmtSize = (n) => { if (!n) return ""; const u=["B","KB","MB","GB","TB"]; let i=0; n=Number(n); while(n>=1024&&i<u.length-1){n/=1024;i++;} return `${i===0?n:n.toFixed(1)} ${u[i]}`; };
const fmtDate = (iso) => { if(!iso) return ""; const d=new Date(iso); return isNaN(d)?iso:d.toLocaleDateString(undefined,{year:"numeric",month:"short",day:"numeric"}); };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,(c)=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

/* ---------- toast ---------- */
let toastTimer;
function toast(msg){ const t=el("toast"); t.textContent=msg; t.classList.remove("hidden"); clearTimeout(toastTimer); toastTimer=setTimeout(()=>t.classList.add("hidden"),2200); }

/* ---------- collection (localStorage) ---------- */
const COLL_KEY = "mnn_collection_v1";
let collection = new Map();
function loadColl(){ try { (JSON.parse(localStorage.getItem(COLL_KEY))||[]).forEach((it)=>collection.set(it.id,it)); } catch(e){} }
function saveColl(){ localStorage.setItem(COLL_KEY, JSON.stringify([...collection.values()])); }
function inColl(id){ return collection.has(Number(id)); }
function toggleColl(id){
  id = Number(id);
  if (collection.has(id)) collection.delete(id);
  else { const it = itemIndex.get(id); if (it) collection.set(id, {id:it.id,filename:it.filename,path:it.path,shooter:it.shooter,month:it.month}); }
  saveColl(); refreshCollUI();
}
function refreshCollUI(){
  el("collCount").textContent = collection.size;
  document.querySelectorAll(".tile-star").forEach((b)=>{
    const on = inColl(b.dataset.id); b.classList.toggle("on", on); b.textContent = on ? "✓" : "★";
  });
  const cb = el("collectBtn");
  if (cb && cb.dataset.id){ const on=inColl(cb.dataset.id); cb.classList.toggle("on",on); cb.textContent = on ? "✓ In collection" : "★ Add to collection"; }
}

/* ---------- filters ---------- */
function chip(group, value, label){
  const c=document.createElement("div"); c.className="chip"; c.textContent=label??value; c.dataset.value=value;
  c.addEventListener("click",()=>{ state[group]= state[group]===value ? "" : value;
    document.querySelectorAll(`#f-${group} .chip`).forEach((x)=>x.classList.toggle("active",x.dataset.value===state[group]));
    applyState(); });
  return c;
}
async function loadFilters(){
  const data = await fetch("/api/filters").then((r)=>r.json());
  const fill=(id,group,values)=>{ const box=el(id); box.innerHTML=""; values.forEach((v)=>box.appendChild(chip(group,v))); };
  fill("f-shooter","shooter",data.shooters);
  fill("f-shot","shot",data.shot_types);
  const extBox=el("f-ext"); extBox.innerHTML=""; data.extensions.forEach((e)=>extBox.appendChild(chip("ext",e.toLowerCase(),e.toUpperCase())));
  const from=el("f-from"),to=el("f-to");
  data.months.forEach((m)=>{ from.appendChild(new Option(m.label,m.date)); to.appendChild(new Option(m.label,m.date)); });
  from.addEventListener("change",()=>{ state.from=from.value; applyState(); });
  to.addEventListener("change",()=>{ state.to=to.value; applyState(); });
  el("heroStat").innerHTML=`<b>${data.total.toLocaleString()}</b> clips ready to browse`;
  if(!data.has_ffmpeg) el("ffmpegNote").classList.remove("hidden");
  return data;
}

/* ---------- tiles ---------- */
const PLAY='<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>';
function tileHTML(item,w,h){
  itemIndex.set(item.id,item);
  const dur=item.duration?`<div class="tile-dur">${fmtDuration(item.duration)}</div>`:"";
  const badge=item.ext?`<div class="tile-badge">${esc(item.ext.toUpperCase())}</div>`:"";
  const tags=[item.shooter,item.month,item.shot_type].filter(Boolean).map(esc).join(" · ");
  const on=inColl(item.id);
  return `<div class="tile" data-id="${item.id}" style="width:${w}px;height:${h}px">
    <img loading="lazy" src="/thumb/${item.id}" alt="${esc(item.filename)}" />
    <video muted loop preload="none" playsinline></video>
    <div class="tile-scrim"></div>
    <button class="tile-star ${on?"on":""}" data-id="${item.id}" title="Add to collection">${on?"✓":"★"}</button>
    ${badge}${dur}
    <div class="tile-play">${PLAY}</div>
    <div class="tile-info"><div class="tile-name">${esc(item.filename)}</div><div class="tile-tags">${tags}</div></div>
  </div>`;
}
let hoverTimer;
function wireTile(tile){
  const id=tile.dataset.id, video=tile.querySelector("video");
  tile.addEventListener("mouseenter",()=>{ hoverTimer=setTimeout(()=>{ if(!video.src) video.src=`/preview/${id}`; tile.classList.add("playing"); video.play().catch(()=>{}); },170); });
  tile.addEventListener("mouseleave",()=>{ clearTimeout(hoverTimer); tile.classList.remove("playing"); video.pause(); });
  tile.addEventListener("click",(e)=>{ if(e.target.closest(".tile-star")) return; openModal(id); });
  const star=tile.querySelector(".tile-star");
  if(star) star.addEventListener("click",(e)=>{ e.stopPropagation(); toggleColl(star.dataset.id); });
}

/* ---------- HOME (category rows) ---------- */
async function loadHome(){
  const rowsEl=el("rows"); rowsEl.innerHTML="";
  const cats=(await fetch("/api/categories").then((r)=>r.json())).categories || [];
  const sections=[{key:"",label:"Recently added",sort:"modified"}].concat(cats.map((c)=>({key:c.key,label:c.label,count:c.count,sort:"modified"})));
  for(const sec of sections){
    const params=new URLSearchParams({sort:sec.sort,limit:14});
    if(sec.key) params.set("category",sec.key);
    const data=await fetch("/api/search?"+params).then((r)=>r.json());
    if(!data.items.length) continue;
    const tiles=data.items.map((it)=>tileHTML(it,256,144)).join("");
    const section=document.createElement("div"); section.className="row-section";
    section.innerHTML=`<div class="row-head">
        <h3 class="row-title">${esc(sec.label)}</h3>
        <span class="row-count">${data.total.toLocaleString()}</span>
        <button class="row-seeall" data-cat="${sec.key}" data-label="${esc(sec.label)}">See all →</button>
      </div><div class="row-scroller">${tiles}</div>`;
    rowsEl.appendChild(section);
    section.querySelectorAll(".tile").forEach(wireTile);
    section.querySelector(".row-seeall").addEventListener("click",(e)=>{
      openCategory(e.target.dataset.cat, e.target.dataset.label);
    });
  }
  refreshCollUI();
}

/* ---------- views ---------- */
function showHome(){
  document.body.classList.remove("browsing");
  el("browse").classList.add("hidden");
  el("home").classList.remove("hidden"); el("top").classList.remove("hidden");
  onScroll();
  window.scrollTo({top:0,behavior:"auto"});
}
function showBrowse(){
  document.body.classList.add("browsing");
  el("home").classList.add("hidden"); el("top").classList.add("hidden");
  el("browse").classList.remove("hidden");
  el("toolbar").classList.add("visible");
  window.scrollTo({top:0,behavior:"auto"});
}
function openCategory(key,label){
  Object.assign(state,{category:key,categoryLabel:label,q:"",shooter:"",shot:"",ext:"",from:"",to:""});
  el("search").value=""; el("miniSearch").value=""; el("f-from").value=""; el("f-to").value="";
  document.querySelectorAll(".chip.active").forEach((c)=>c.classList.remove("active"));
  showBrowse(); resetAndSearch();
}

/* go to home vs browse based on whether anything is active */
function applyState(){
  const active = state.q || state.category || state.shooter || state.shot || state.ext || state.from || state.to;
  if(active){ if(el("browse").classList.contains("hidden")) showBrowse(); resetAndSearch(); }
  else showHome();
}

/* ---------- search (browse grid) ---------- */
async function search(append=false){
  if(state.loading || (append && state.done)) return;
  state.loading=true; el("loader").classList.remove("hidden");
  const params=new URLSearchParams({q:state.q,shooter:state.shooter,shot:state.shot,ext:state.ext,from:state.from,to:state.to,category:state.category,sort:state.sort,limit:state.limit,offset:state.offset});
  let data;
  try { data=await fetch("/api/search?"+params).then((r)=>r.json()); }
  catch(e){ state.loading=false; el("loader").classList.add("hidden"); toast("Search failed."); return; }
  state.total=data.total;
  if(!append) state.items=[];
  state.items.push(...data.items);
  state.offset+=data.items.length;
  state.done = state.offset>=state.total || data.items.length===0;
  layout();
  el("browseTitle").textContent = state.category ? state.categoryLabel : (state.q ? `“${state.q}”` : "All footage");
  el("count").textContent = `${state.total.toLocaleString()} clip${state.total===1?"":"s"}`;
  el("empty").classList.toggle("hidden", state.total!==0);
  updateActiveFilters();
  el("loader").classList.add("hidden"); state.loading=false;
}
function resetAndSearch(){ state.offset=0; state.done=false; search(false); }
function updateActiveFilters(){
  const bits=[];
  if(state.shooter) bits.push(state.shooter);
  if(state.shot) bits.push(state.shot);
  if(state.ext) bits.push(state.ext.toUpperCase());
  if(state.from||state.to) bits.push([state.from,state.to].filter(Boolean).join("→"));
  el("activeFilters").textContent = bits.length ? "· "+bits.join(" · ") : "";
}

/* ---------- justified layout ---------- */
function targetRowHeight(){ const w=window.innerWidth; if(w<700) return 150; if(w<1200) return 200; return 240; }
function layout(){
  const containerW=grid.clientWidth || (window.innerWidth-56);
  const gap=8, targetH=targetRowHeight();
  let html="", row=[], sumAR=0;
  const flush=(isLast)=>{ if(!row.length) return;
    let h=(containerW-gap*(row.length-1))/sumAR; if(isLast) h=Math.min(h,targetH*1.18);
    let cells=""; row.forEach((r)=>{ cells+=tileHTML(r.item,Math.floor(r.ar*h),Math.floor(h)); });
    html+=`<div class="row">${cells}</div>`; row=[]; sumAR=0; };
  for(const item of state.items){ const ar=(item.width&&item.height)?item.width/item.height:16/9; row.push({item,ar}); sumAR+=ar;
    if(sumAR*targetH+gap*(row.length-1)>=containerW) flush(false); }
  flush(true);
  grid.innerHTML=html; grid.querySelectorAll(".tile").forEach(wireTile); refreshCollUI();
}

/* ---------- modal ---------- */
async function openModal(id){
  const data=await fetch(`/api/clip/${id}`).then((r)=>r.json());
  if(data.error) return; itemIndex.set(data.id,data);
  el("modalTitle").textContent=data.filename;
  const rows=[["Shooter",data.shooter],["Month",data.month],["Shot type",data.shot_type],["Type",(data.ext||"").toUpperCase()],
    ["Duration",fmtDuration(data.duration)],["Resolution",data.width&&data.height?`${data.width}×${data.height}`:""],
    ["Size",fmtSize(data.size)],["Modified",fmtDate(data.modified)],["Folder",data.folder]].filter(([,v])=>v);
  el("modalMeta").innerHTML=rows.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");
  const video=el("modalVideo"),noPrev=el("modalNoPreview");
  if(data.has_preview){ video.src=`/preview/${id}`; video.poster=`/thumb/${id}`; video.classList.remove("hidden"); noPrev.classList.add("hidden"); }
  else { video.classList.add("hidden"); video.removeAttribute("src"); noPrev.classList.remove("hidden"); }
  const cb=el("collectBtn"); cb.dataset.id=id; cb.onclick=()=>{ toggleColl(id); };
  el("revealBtn").onclick=()=>reveal(id);
  el("copyBtn").onclick=()=>{ navigator.clipboard?.writeText(data.path); toast("Path copied."); };
  el("modal").classList.remove("hidden"); refreshCollUI();
}
function closeModal(){ el("modal").classList.add("hidden"); const v=el("modalVideo"); v.pause(); v.removeAttribute("src"); }
async function reveal(id){
  try { const r=await fetch("/api/reveal",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:Number(id)})}).then((r)=>r.json());
    toast(r.ok?"Opening in File Explorer…":"Could not open location."); } catch(e){ toast("Could not open location."); }
}

/* ---------- collection drawer ---------- */
function openDrawer(){ renderDrawer(); el("drawer").classList.remove("hidden"); }
function closeDrawer(){ el("drawer").classList.add("hidden"); }
function renderDrawer(){
  const items=[...collection.values()]; el("drawerCount").textContent=items.length?`(${items.length})`:"";
  el("drawerEmpty").classList.toggle("hidden", items.length>0);
  el("drawerItems").innerHTML=items.map((it)=>`
    <div class="coll-item" data-id="${it.id}">
      <img class="coll-thumb" src="/thumb/${it.id}" data-open="${it.id}" alt="" />
      <div class="coll-meta"><div class="coll-name">${esc(it.filename)}</div>
        <div class="coll-sub">${[it.shooter,it.month].filter(Boolean).map(esc).join(" · ")}</div></div>
      <button class="coll-x" data-remove="${it.id}" title="Remove">✕</button>
    </div>`).join("");
  el("drawerItems").querySelectorAll("[data-remove]").forEach((b)=>b.addEventListener("click",()=>{ toggleColl(b.dataset.remove); renderDrawer(); }));
  el("drawerItems").querySelectorAll("[data-open]").forEach((b)=>b.addEventListener("click",()=>{ closeDrawer(); openModal(b.dataset.open); }));
}

/* ---------- re-index ---------- */
let statusTimer;
async function pollStatus(){
  const s=await fetch("/api/status").then((r)=>r.json()); const btn=el("reindexBtn");
  if(s.indexing){ btn.disabled=true; btn.innerHTML='<span class="ic">↻</span> Indexing…'; if(s.message) el("count").textContent=s.message; }
  else { if(btn.disabled){ btn.disabled=false; btn.innerHTML='<span class="ic">↻</span> Re-index'; applyState(); } clearInterval(statusTimer); statusTimer=null; }
}
async function reindex(){
  const r=await fetch("/api/reindex",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({full:false})}).then((r)=>r.json());
  if(!r.ok){ toast(r.error||"Already running."); return; }
  toast("Re-indexing the footage drive…"); if(!statusTimer) statusTimer=setInterval(pollStatus,1200);
}

/* ---------- hero cycling blurred video ---------- */
let heroIds=[], heroIdx=0, heroActive=0, heroTimer;
function startHero(ids){
  heroIds=ids.filter(Boolean); if(!heroIds.length) return;
  heroNext(); clearInterval(heroTimer); heroTimer=setInterval(heroNext,9000);
}
function heroNext(){
  if(!heroIds.length) return;
  const vids=[el("heroV1"),el("heroV2")];
  const next=vids[1-heroActive], cur=vids[heroActive];
  const id=heroIds[heroIdx % heroIds.length]; heroIdx++;
  next.muted=true; next.loop=true;
  next.src=`/preview/${id}`;
  next.load();                       // force buffering (preload="none" won't otherwise)
  const go=()=>{
    next.classList.add("show");
    next.play().catch(()=>{});
    cur.classList.remove("show");
    heroActive=1-heroActive;
  };
  // loadeddata = first frame ready; fall back to a timer if it never fires.
  next.addEventListener("loadeddata", go, {once:true});
}

/* ---------- wiring ---------- */
let searchDebounce;
function onSearchInput(val,other){ state.q=val; state.category=""; if(other&&other.value!==val) other.value=val; clearTimeout(searchDebounce); searchDebounce=setTimeout(applyState,220); }
el("search").addEventListener("input",(e)=>onSearchInput(e.target.value,el("miniSearch")));
el("miniSearch").addEventListener("input",(e)=>onSearchInput(e.target.value,el("search")));
el("sort").addEventListener("change",(e)=>{ state.sort=e.target.value; if(!el("browse").classList.contains("hidden")) resetAndSearch(); });
el("reindexBtn").addEventListener("click",reindex);
el("clearBtn").addEventListener("click",()=>{ Object.assign(state,{q:"",shooter:"",shot:"",ext:"",from:"",to:"",category:""});
  el("search").value=""; el("miniSearch").value=""; el("f-from").value=""; el("f-to").value="";
  document.querySelectorAll(".chip.active").forEach((c)=>c.classList.remove("active")); showHome(); });
el("backHome").addEventListener("click",()=>{ Object.assign(state,{q:"",shooter:"",shot:"",ext:"",from:"",to:"",category:""});
  el("search").value=""; el("miniSearch").value=""; document.querySelectorAll(".chip.active").forEach((c)=>c.classList.remove("active")); showHome(); });
document.querySelectorAll(".suggest").forEach((b)=>b.addEventListener("click",()=>{ el("search").value=b.dataset.q; onSearchInput(b.dataset.q,el("miniSearch")); }));
document.querySelectorAll("[data-home]").forEach((b)=>b.addEventListener("click",(e)=>{ e.preventDefault(); Object.assign(state,{q:"",shooter:"",shot:"",ext:"",from:"",to:"",category:""}); el("search").value=""; el("miniSearch").value=""; document.querySelectorAll(".chip.active").forEach((c)=>c.classList.remove("active")); showHome(); }));
el("collectionBtn").addEventListener("click",openDrawer);
el("copyAllBtn").addEventListener("click",()=>{ const paths=[...collection.values()].map((it)=>it.path).join("\n"); if(!paths){ toast("Collection is empty."); return; } navigator.clipboard?.writeText(paths); toast(`Copied ${collection.size} path(s).`); });
el("clearCollBtn").addEventListener("click",()=>{ collection.clear(); saveColl(); refreshCollUI(); renderDrawer(); });
document.querySelectorAll("[data-drawer-close]").forEach((x)=>x.addEventListener("click",closeDrawer));
document.querySelectorAll("[data-close]").forEach((x)=>x.addEventListener("click",closeModal));
document.addEventListener("keydown",(e)=>{ if(e.key==="Escape"){ closeModal(); closeDrawer(); } });

const toolbar=el("toolbar");
function onScroll(){ if(!el("browse").classList.contains("hidden")) return; const h=el("top").offsetHeight; toolbar.classList.toggle("visible",window.scrollY>h-70); }
window.addEventListener("scroll",onScroll,{passive:true});
let resizeT; window.addEventListener("resize",()=>{ clearTimeout(resizeT); resizeT=setTimeout(()=>{ if(!el("browse").classList.contains("hidden")) layout(); },150); });
new IntersectionObserver((entries)=>{ if(entries[0].isIntersecting && !state.loading && !state.done && !el("browse").classList.contains("hidden")) search(true); },{rootMargin:"700px"}).observe(el("sentinel"));

/* ---------- boot ---------- */
loadColl();
(async function boot(){
  await loadFilters();
  await loadHome();
  refreshCollUI();
  // Hero montage = NATURE clips, only stable framings (no handheld/pan/tilt/tracking/zoom).
  try {
    const unstable = ["Handheld","Pan","Tilt","Tracking","Zoom"];
    const d = await fetch("/api/search?category=nature&sort=modified&limit=40").then((r)=>r.json());
    const stable = d.items.filter((i)=>!unstable.includes(i.shot_type));
    const pool = (stable.length>=4 ? stable : d.items).map((i)=>i.id);
    startHero(pool.slice(0,10));
  } catch(e){}
})();
