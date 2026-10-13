'use strict';
const $ = id => document.getElementById(id);
let token = '', config = null, tasks = [], submissions = [];
const urls = new Set();
const percent = value => value == null ? 'Pending' : (100 * value).toFixed(1) + '%';
function el(tag, text, cls) { const node = document.createElement(tag); if (text != null) node.textContent = text; if (cls) node.className = cls; return node; }
function message(text, error = false) { $('message').textContent = text; $('message').classList.toggle('error', error); }
async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { Authorization: 'Bearer ' + token, ...(options.body ? {'Content-Type':'application/json'} : {}), ...options.headers } });
  if (!response.ok) { let detail; try { detail = (await response.json()).error; } catch { detail = response.statusText; } throw new Error(detail || 'Request failed'); }
  return response;
}
async function json(path, options) { return (await api(path, options)).json(); }
async function asset(path) { const url = URL.createObjectURL(await (await api(path)).blob()); urls.add(url); return url; }
function clearUrls() { for (const url of urls) URL.revokeObjectURL(url); urls.clear(); }
function view(name) { for (const node of document.querySelectorAll('.view')) node.hidden = node.id !== name; for (const button of document.querySelectorAll('.nav')) button.classList.toggle('active', button.dataset.view === name); $('title').textContent = {overview:'Challenge overview',tasks:'Challenge tasks',experiments:'Your experiments'}[name]; }
for (const button of document.querySelectorAll('.nav')) button.addEventListener('click', () => view(button.dataset.view));
function drawWeights() {
  const canvas = $('weights-chart'), ctx = canvas.getContext('2d'); ctx.clearRect(0,0,canvas.width,canvas.height);
  const colors = ['#6549dd','#a78bfa','#33a89c','#d6a446']; const weights = Object.entries(config.weights);
  weights.forEach(([key,value],i) => { const y = i*48+10; ctx.font='13px system-ui';ctx.fillStyle='#4b5d74';ctx.fillText(key[0].toUpperCase()+key.slice(1),0,y+16);ctx.fillStyle='#f0eef8';ctx.fillRect(125,y,340,22);ctx.fillStyle=colors[i];ctx.fillRect(125,y,340*value/Object.values(config.weights).reduce((a,b)=>a+b,0),22);ctx.fillStyle='#4b5d74';ctx.fillText((100*value/Object.values(config.weights).reduce((a,b)=>a+b,0)).toFixed(0)+'%',485,y+16); });
  $('weights-description').textContent = weights.map(([k,v]) => k+': '+v).join(' · ');
}
async function refreshBoard() {
  const split = $('split').value, mode = $('mode').value;
  const board = await json(`/api/leaderboard?split=${split}&mode=${mode}`);
  $('leaderboard').replaceChildren(); $('breakdowns').replaceChildren(); $('run-count').textContent = board.length;
  board.forEach((row,i) => { const tr = el('tr'); tr.append(el('td',row.score == null ? '—' : i+1));const identity=el('td',row.team);identity.append(el('small',row.run));tr.append(identity,el('td',percent(row.score)),el('td',percent(row.metrics.iou)),el('td',percent(row.metrics.editing)),el('td',percent(row.metrics.preservation)),el('td',`${row.completed} / ${row.total}`));$('leaderboard').append(tr);
    const details=el('details'), summary=el('summary',row.team+' · '+row.run+' breakdown');details.append(summary,el('pre',JSON.stringify({task_types:row.task_types,difficulties:row.difficulties,measured_total_time_ms:row.measured_total_time_ms},null,2)));$('breakdowns').append(details);
  });
  $('board-note').textContent = board.length ? (mode==='quality' ? 'Quality scores omit efficiency. Only the selected run, or latest run if none is selected, is shown per team.' : 'Measured results use '+config.hardware_profile+'. Tasks without verified runtime count as missing.') : 'No selected runs in this split yet. Submit an experiment to get started.';
}
async function refreshExperiments() {
  submissions = await json('/api/submissions'); $('experiment-table').replaceChildren(); const current = submissions.filter(s=>s.split===$('split').value); $('submission-count').textContent=current.length;
  for (const row of current) { const tr=el('tr');tr.append(el('td',row.run),el('td',row.task),el('td',row.metadata.model_name||'—'),el('td',row.metrics?percent(row.metrics.score):'Private test evaluation'),el('td',row.measured_ms?row.measured_ms.toFixed(0)+' ms verified':((row.metadata.localization_time_ms||0)+(row.metadata.editing_time_ms||0))+' ms reported'));const actions=el('td');const inspect=el('button','Inspect');inspect.addEventListener('click',()=>guard(()=>inspectSubmission(row)));const select=el('button','Select run');select.addEventListener('click',()=>guard(async()=>{await json('/api/select-run',{method:'POST',body:JSON.stringify({run_id:row.run,split:row.split,student_id:row.team})});message('Selected '+row.run+' for '+row.split+'.');await refreshBoard();}));actions.append(inspect,select);tr.append(actions);$('experiment-table').append(tr); }
  if (!current.length) { const tr=el('tr'), td=el('td','No experiments in this split.');td.colSpan=6;tr.append(td);$('experiment-table').append(tr); }
}
async function loadTasks() {
  tasks=await json('/api/tasks?split='+$('split').value);$('task-count').textContent=tasks.length; $('task-grid').replaceChildren();$('submit-task').replaceChildren();
  for (const task of tasks) { const option=el('option',task.task_id);option.value=task.task_id;$('submit-task').append(option); const card=el('article',null,'card'); const img=el('img');img.alt='Source for '+task.source_prompt;img.src=await asset(task.image_url);const title=el('h3',task.task_id);const source=el('p');source.append(el('b','Locate: '),el('span',task.source_prompt));const target=el('p');target.append(el('b','Edit: '),el('span',task.target_prompt));const use=el('button','Use this task');use.addEventListener('click',()=>{$('submit-task').value=task.task_id;$('submit-form').scrollIntoView({behavior:'smooth'});});card.append(img,title,el('span',task.difficulty+' · '+task.task_type,'badge'),source,target,use);$('task-grid').append(card); }
}
function loadImage(url) { return new Promise((resolve,reject)=>{const img=new Image();img.onload=()=>resolve(img);img.onerror=()=>reject(new Error('Could not decode preview'));img.src=url;}); }
async function inspectSubmission(row) {
  const task=tasks.find(t=>t.task_id===row.task); if(!task) throw new Error('Task is unavailable in this split');
  const [sourceUrl,editedUrl,maskUrl]=await Promise.all([asset(task.image_url),asset(`/api/submissions/${row.id}/edited`),asset(`/api/submissions/${row.id}/mask`)]);
  const [source,edited,mask]=await Promise.all([loadImage(sourceUrl),loadImage(editedUrl),loadImage(maskUrl)]);
  $('source-preview').src=sourceUrl;$('edited-preview').src=editedUrl;
  const scratch=document.createElement('canvas');scratch.width=source.width;scratch.height=source.height;const ctx=scratch.getContext('2d',{willReadFrequently:true});ctx.drawImage(source,0,0);const a=ctx.getImageData(0,0,source.width,source.height);ctx.drawImage(edited,0,0);const b=ctx.getImageData(0,0,source.width,source.height);ctx.drawImage(mask,0,0);const m=ctx.getImageData(0,0,source.width,source.height);
  for (const id of ['overlay-preview','difference-preview']) {$(id).width=source.width;$(id).height=source.height;}
  const overlay=$('overlay-preview').getContext('2d').createImageData(source.width,source.height), diff=$('difference-preview').getContext('2d').createImageData(source.width,source.height);
  for(let i=0;i<a.data.length;i+=4) {const alpha=m.data[i]/255*.5;for(let c=0;c<3;c++){overlay.data[i+c]=a.data[i+c]*(1-alpha)+[139,92,246][c]*alpha;diff.data[i+c]=Math.min(255,Math.abs(a.data[i+c]-b.data[i+c])*4);}overlay.data[i+3]=diff.data[i+3]=255;}
  $('overlay-preview').getContext('2d').putImageData(overlay,0,0);$('difference-preview').getContext('2d').putImageData(diff,0,0);
  $('truth-panel').hidden=!task.mask_url;if(task.mask_url)$('truth-preview').src=await asset(task.mask_url);
  $('comparison-title').textContent=row.run+' · '+row.task;$('comparison-metrics').textContent=row.metrics?JSON.stringify(row.metrics,null,2):'Test metrics and reference masks are private. See aggregate leaderboard results.';$('comparison').hidden=false;
}
async function guard(work) {try{await work();}catch(error){message(error.message,true);}}
async function refreshAll() {clearUrls();$('comparison').hidden=true;await loadTasks();await refreshExperiments();await refreshBoard();}
$('login-form').addEventListener('submit',event=>{event.preventDefault();guard(async()=>{token=$('token').value.trim();config=await json('/api/config');$('token').value='';$('login').hidden=true;$('workspace').hidden=true;$('logout').hidden=false;$('identity').textContent=config.identity+(config.admin?' · organizer':'');$('dataset-version').textContent=config.dataset_version;drawWeights();await refreshAll();$('workspace').hidden=false;message('Connected to '+config.name+'.');});});
$('logout').addEventListener('click',()=>{token='';config=null;tasks=[];submissions=[];clearUrls();$('leaderboard').replaceChildren();$('experiment-table').replaceChildren();$('task-grid').replaceChildren();$('submit-result').hidden=true;$('comparison').hidden=true;$('login').hidden=false;$('workspace').hidden=true;$('logout').hidden=true;$('identity').textContent='Not connected';message('Disconnected.');});
$('split').addEventListener('change',()=>{if(token)guard(refreshAll);});$('mode').addEventListener('change',()=>guard(refreshBoard));$('refresh').addEventListener('click',()=>guard(refreshBoard));$('refresh-experiments').addEventListener('click',()=>guard(refreshExperiments));
function base64File(file) {return new Promise((resolve,reject)=>{if(!file||file.size>12*1024*1024)return reject(new Error('Each PNG must be at most 12 MB'));const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(new Error('Could not read file'));reader.readAsDataURL(file);});}
$('submit-form').addEventListener('submit',event=>{event.preventDefault();guard(async()=>{const button=event.submitter;button.disabled=true;try{if(config.admin)throw new Error('Use a team token to upload experiments; organizers can inspect all teams.');const metadata={run_id:$('run-id').value,model_name:$('model-name').value};for(const [id,key] of [['localization-time','localization_time_ms'],['editing-time','editing_time_ms']])if($(id).value!=='')metadata[key]=Number($(id).value);const result=await json('/api/submissions',{method:'POST',body:JSON.stringify({task_id:$('submit-task').value,student_id:config.identity,edited_image:await base64File($('edited-file').files[0]),predicted_mask:await base64File($('mask-file').files[0]),metadata})});$('submit-result').textContent=JSON.stringify(result,null,2);$('submit-result').hidden=false;message('Submission accepted.');await refreshExperiments();await refreshBoard();}finally{button.disabled=false;}});});
