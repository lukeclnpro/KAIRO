
const $=s=>document.querySelector(s);
let state={models:[],chats:[],current:null};

function esc(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]))}
async function api(url,opt){const r=await fetch(url,opt);let d;try{d=await r.json()}catch{throw new Error("Réponse serveur invalide")};if(!r.ok||d.error)throw new Error(d.error||("HTTP "+r.status));return d}
function show(page){document.querySelectorAll(".page").forEach(x=>x.classList.add("hidden"));$("#"+page).classList.remove("hidden");document.querySelectorAll(".nav").forEach(x=>x.classList.toggle("active",x.dataset.page===page));if(page==="chat")refreshChats()}

async function refresh(){
 try{
  const [s,m,c,ci]=await Promise.all([api("/api/status"),api("/api/models"),api("/api/chats"),api("/api/config-info")]);
  state.models=m.installed||[];state.chats=c.chats||[];
  $("#status").textContent=s.ok?"Ollama connecté":"Ollama inaccessible";
  $("#status").className=s.ok?"ok":"error";
  $("#ollama").textContent=s.ollama;
  $("#defaultModel").textContent=s.model||"Aucun";
  $("#modelCount").textContent=state.models.length;
  $("#chatCount").textContent=state.chats.length;
  renderModels();renderModelSelect();renderChats();renderConfig(ci);
 }catch(e){$("#status").textContent="Serveur disponible, Ollama inaccessible";$("#status").className="error";console.error(e)}
}
function renderModels(){ $("#modelsList").innerHTML=state.models.length?state.models.map(m=>`<div class="model"><b>${esc(m.name)}</b><div class="muted">${m.size?Math.round(m.size/1024/1024/10)/100+" GB":"Taille inconnue"}</div></div>`).join(""):"<p class='muted'>Aucun modèle installé. Utilisez main.py pour en installer un.</p>"}
function renderModelSelect(){const el=$("#modelSelect");el.innerHTML=state.models.map(m=>`<option value="${esc(m.name)}">${esc(m.name)}</option>`).join("");if(!state.models.length)el.innerHTML="<option>Aucun modèle installé</option>"}
function renderChats(){
 const el=$("#chatList");
 if(!state.chats.length){el.innerHTML="<div class=\"muted\">Aucune conversation</div>";return}
 el.innerHTML=state.chats.map(c=>{
   const count=Array.isArray(c.messages)?c.messages.length:0;
   const title=c.summary||c.topic||(`Conversation #${c.id}`);
   return `<button class="chat-item ${state.current&&String(state.current.id)===String(c.id)?"active":""}" data-id="${c.id}"><b>${esc(title)}</b><span>${count} message${count>1?"s":""}</span></button>`;
 }).join("");
 el.querySelectorAll(".chat-item").forEach(b=>b.onclick=async()=>{
  try{if(state.current&&String(state.current.id)!==b.dataset.id)await closeChatSession(state.current.id);const d=await api("/api/chats/"+b.dataset.id);state.current=d.chat;renderChats();renderMessages(state.current)}catch(x){alert(x.message)}
 });
}
function renderConfig(c){$("#configInfo").innerHTML=`Modèle configuré : <b>${esc(c.model||"Aucun")}</b><br>Ollama : <b>${esc(c.ollama_url||"—")}</b><br>Langue : <b>${esc(c.language||"français")}</b>`}
async function closeChatSession(chatId){if(chatId!=null)await api(`/api/chats/${chatId}/close`,{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"})}
function renderMessages(chat){const box=$("#messages");if(!chat||!chat.messages?.length){box.innerHTML="<p class='muted'>Commencez une conversation.</p>";return}box.innerHTML=chat.messages.map(m=>`<div class="msg ${m.role==="user"?"user":"assistant"}"><div class="role">${m.role==="user"?"Vous":"IA"}</div>${esc(m.content)}</div>`).join("");box.scrollTop=box.scrollHeight}
let chatsRefreshToken=0;
async function refreshChats(keepCurrent=true){
 const token=++chatsRefreshToken;
 try{
  const d=await api("/api/chats");
  if(token!==chatsRefreshToken)return;
  state.chats=d.chats||[];
  if(keepCurrent && state.current){
   const fresh=state.chats.find(c=>String(c.id)===String(state.current.id));
   if(fresh) state.current=fresh;
  }
  renderChats();
  if(state.current) renderMessages(state.current);
 }catch(e){console.error("refreshChats",e)}
}
$("#newChat").onclick=async()=>{try{if(state.current)await closeChatSession(state.current.id);const d=await api("/api/chats/new",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});state.current=d.chat;localStorage.setItem("local_ia_current_chat",String(d.chat.id));await refreshChats(false);show("chat");renderMessages(state.current)}catch(e){alert(e.message)}}
$("#chatForm").onsubmit=async e=>{
 e.preventDefault();
 const text=$("#message").value.trim();
 if(!text||!state.current)return;
 if(!$("#modelSelect").value||$("#modelSelect").value==="Aucun modèle installé"){alert("Installez d'abord un modèle via main.py.");return}
 $("#send").disabled=true; $("#message").value="";
 const chatId=state.current.id;
 try{
  const d=await api("/api/chat",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({chat_id:chatId,model:$("#modelSelect").value,message:text})});
  // La réponse du serveur contient la conversation complète : on l'utilise
  // directement au lieu de lancer un second GET qui pouvait créer une course.
  state.current=d.chat;
  localStorage.setItem("local_ia_current_chat",String(state.current.id));
  const i=state.chats.findIndex(c=>String(c.id)===String(state.current.id));
  if(i>=0) state.chats[i]=state.current; else state.chats.unshift(state.current);
  renderChats(); renderMessages(state.current);
 }catch(x){alert(x.message)}finally{$("#send").disabled=false}
}
document.querySelectorAll(".nav").forEach(b=>b.onclick=()=>show(b.dataset.page));
window.addEventListener("pagehide",()=>{if(state.current)navigator.sendBeacon(`/api/chats/${state.current.id}/close`,new Blob(["{}"],{type:"application/json"}))});
refresh().then(async()=>{
 const saved=localStorage.getItem("local_ia_current_chat");
 if(saved){
  try{const d=await api("/api/chats/"+saved); if(d.chat){state.current=d.chat; renderChats(); renderMessages(state.current); return;}}catch(e){}
 }
 await refreshChats(false);
}).catch(console.error);
