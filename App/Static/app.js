const filesEl = document.getElementById("files");
const drop = document.getElementById("drop");
const fileList = document.getElementById("fileList");
const run = document.getElementById("run");
const requestEl = document.getElementById("request");
const errorEl = document.getElementById("error");
const results = document.getElementById("results");
const recordsEl = document.getElementById("records");
const summaryEl = document.getElementById("summary");
const status = document.getElementById("status");
let lastResult = null;

async function health(){
  try{
    const r = await fetch("/api/health");
    const j = await r.json();
    status.textContent = j.api_key_configured ? "AI ready" : "API key not configured";
  }catch(e){ status.textContent = "Server offline"; }
}
health();

function showFiles(){
  fileList.innerHTML = "";
  [...filesEl.files].forEach(f=>{
    const d=document.createElement("div");
    d.className="file";
    d.textContent=`${f.name} • ${(f.size/1024/1024).toFixed(2)} MB`;
    fileList.appendChild(d);
  });
}
filesEl.addEventListener("change",showFiles);
drop.addEventListener("dragover",e=>{e.preventDefault();drop.style.borderColor="#64748b"});
drop.addEventListener("dragleave",()=>drop.style.borderColor="");
drop.addEventListener("drop",e=>{
  e.preventDefault();
  const dt=new DataTransfer();
  [...e.dataTransfer.files].forEach(f=>dt.items.add(f));
  filesEl.files=dt.files;
  showFiles();
  drop.style.borderColor="";
});

function esc(v){
  return String(v ?? "").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));
}
function value(v){
  if(v===null || v===undefined || v==="") return "—";
  if(typeof v==="object") return `<pre>${esc(JSON.stringify(v,null,2))}</pre>`;
  return esc(v);
}

function render(data){
  lastResult=data;
  results.classList.remove("hidden");
  summaryEl.textContent=`${data.summary?.documents_processed ?? 0} documents • ${data.summary?.records_found ?? data.records?.length ?? 0} records • ${data.summary?.warnings ?? 0} warnings`;
  recordsEl.innerHTML="";
  (data.records||[]).forEach((r,i)=>{
    const card=document.createElement("div");
    card.className="record";
    const fields=r.fields||{};
    let html=`<div class="record-title"><span>Record ${esc(r.record_id||i+1)} • ${esc(r.document_type||"other")}</span><span>${esc(r.confidence ?? "")}</span></div>`;
    html+=`<div class="record-body"><div class="grid">`;
    Object.entries(fields).forEach(([k,v])=>{
      const src=r.field_sources?.[k];
      html+=`<div class="field"><small>${esc(k)}</small><div>${value(v)}</div>${src?`<div class="source">Source: ${esc(src)}</div>`:""}</div>`;
    });
    html+=`</div>`;
    if((r.line_items||[]).length) html+=`<div class="field" style="margin-top:10px"><small>LINE ITEMS</small><div>${value(r.line_items)}</div></div>`;
    (r.warnings||[]).forEach(w=>html+=`<div class="warning">⚠ ${esc(w)}</div>`);
    html+=`<div class="source" style="margin-top:9px">Documents: ${esc((r.source_documents||[]).join(", "))}</div></div>`;
    card.innerHTML=html;
    recordsEl.appendChild(card);
  });
}

run.addEventListener("click",async()=>{
  errorEl.textContent="";
  if(!filesEl.files.length){errorEl.textContent="Please upload at least one document.";return}
  run.disabled=true; run.textContent="Extracting…";
  const fd=new FormData();
  fd.append("request",requestEl.value);
  [...filesEl.files].forEach(f=>fd.append("files",f));
  try{
    const r=await fetch("/api/extract",{method:"POST",body:fd});
    const j=await r.json();
    if(!r.ok) throw new Error(j.detail||"Extraction failed");
    render(j);
  }catch(e){errorEl.textContent=e.message}
  finally{run.disabled=false;run.textContent="Extract with AI"}
});

document.getElementById("jsonBtn").addEventListener("click",()=>{
  if(!lastResult)return;
  const blob=new Blob([JSON.stringify(lastResult,null,2)],{type:"application/json"});
  const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="invoice-extraction.json";a.click();
});
document.getElementById("xlsxBtn").addEventListener("click",async()=>{
  if(!lastResult)return;
  const r=await fetch("/api/export/xlsx",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(lastResult)});
  if(!r.ok){alert("Excel export failed");return}
  const blob=await r.blob();
  const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="invoice-extraction.xlsx";a.click();
});
