'use strict';
const $ = id => document.getElementById(id);
const fields = ['folder','days','minimum','maximum','workers','artist','album','codec','bitrate_min','bitrate_max','sample_min','sample_max','size_min','size_max','low_bitrate','health_filter','duplicates'];
let state, csrf='', rows=[], total=0, offset=0, sort='path', reverse=false, selected=new Set(), quarantineSelected=new Set(), quarantineRows=[], presets={}, confirmation='', action='', polling=false, first=true, scanId=null, lastPhase='', requestNumber=0, refreshNumber=0;
const limit=100, number=n=>Number(n).toLocaleString();
function toast(message) { $('toast').textContent=message; $('toast').hidden=false; clearTimeout(toast.timer); toast.timer=setTimeout(()=>$('toast').hidden=true,10000); }
async function api(path,data) {
  const response=await fetch(path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(data)});
  const value=await response.json(); if(!response.ok) throw new Error(value.error||'Request failed'); return value;
}
function safe(task) { return Promise.resolve().then(task).catch(e=>toast(e.message)); }
function query() { return new URLSearchParams({search:$('search').value,sort,reverse:reverse?'1':'0',duplicates:$('duplicatesOnly').checked?'1':'0'}); }
function formats() { return [...document.querySelectorAll('#formatOptions input:checked')].map(e=>e.value); }
function updateFormats() { const values=formats(); $('formatSummary').textContent=values.length===1?values[0].toUpperCase():`${values.length} formats selected`; }
function settings() { const value=Object.fromEntries(fields.map(id=>[id,$(id).value])); for(const id of ['days','minimum','maximum','workers']) value[id]=Number(value[id]); value.formats=formats(); value.deep_check=$('deep_check').checked; value.authenticity_check=$('authenticity_check').checked; return value; }
function applySettings(value) { for(const id of fields) $(id).value=value[id]??(id==='health_filter'?'any':id==='duplicates'?'off':''); $('deep_check').checked=!!value.deep_check; $('authenticity_check').checked=!!value.authenticity_check; document.querySelectorAll('#formatOptions input').forEach(e=>e.checked=value.formats?.includes(e.value)); updateFormats(); }
function updateSelection() {
  $('selectedCount').textContent=`${number(selected.size)} selected`;
  $('delete').disabled=$('quarantineSelected').disabled=!selected.size||!!state?.busy;
  $('restoreSelected').disabled=$('purgeSelected').disabled=!quarantineSelected.size||!!state?.busy;
  $('pageCheck').checked=rows.length>0&&rows.every(r=>selected.has(r.id)); $('pageCheck').indeterminate=rows.some(r=>selected.has(r.id))&&!$('pageCheck').checked;
  $('quarantineCount').textContent=`${number(quarantineSelected.size)} selected`;
}
function td(text, className='') { const cell=document.createElement('td'); cell.textContent=text; cell.className=className; return cell; }
function renderRows() {
  const body=$('rows'); body.replaceChildren();
  for(const row of rows) {
    const tr=document.createElement('tr'), check=document.createElement('input'), cell=document.createElement('td'); check.type='checkbox'; check.checked=selected.has(row.id); check.setAttribute('aria-label',`Select ${row.name}`);
    check.addEventListener('change',()=>{check.checked?selected.add(row.id):selected.delete(row.id);updateSelection();}); cell.append(check); tr.append(cell);
    const pathCell=document.createElement('td');
    for(const [text,cls] of [[row.name,'name'],[row.path,'path'],[`${row.artist||'No artist'} · ${row.album||'No album'} · ${row.codec||'?'} · ${Math.round((row.bitrate||0)/1000)} kbps · ${number(row.sample_rate||0)} Hz · ${(row.size/1048576).toFixed(2)} MiB`,'path']]) { const div=document.createElement('div'); div.className=cls; div.textContent=text; pathCell.append(div); }
    tr.append(pathCell,td(row.format,'type-cell'),td(row.duration==null?'Unknown':`${row.duration.toFixed(3)} s`,'duration'),td(new Date(row.modified*1000).toLocaleString(),'modified'));
    const health=td(row.health||'metadata-ok','health'); health.title=row.health_detail||''; const authenticity=td(row.authenticity||'not-scanned'); const evidence=document.createElement('div'); evidence.className='path'; evidence.textContent=row.authenticity_detail||''; authenticity.append(evidence); if(row.authenticity_folder_detail){const context=document.createElement('div'); context.className='folder-context'; context.textContent=row.authenticity_folder_detail; authenticity.append(context);} tr.append(health,authenticity,td(row.duplicate||'—','duplicate-cell')); body.append(tr);
  }
  $('empty').hidden=rows.length>0; $('empty').textContent=state?.progress.phase==='idle'?'Start a scan or load scan history.':'No matches. Check filters, selected formats, and the error log.';
  $('total').textContent=`(${number(total)})`; $('pageInfo').textContent=total?`${number(offset+1)}–${number(Math.min(offset+limit,total))} of ${number(total)}`:'0 results'; $('prevPage').disabled=offset===0; $('nextPage').disabled=offset+limit>=total; updateSelection();
}
async function loadRows() { const request=++requestNumber, params=query();params.set('offset',offset);params.set('limit',limit);const value=await api(`/api/results?${params}`);if(request!==requestNumber)return;rows=value.rows;total=value.total;if(offset>=total&&offset>0){offset=Math.max(0,Math.floor((total-1)/limit)*limit);return loadRows();}renderRows(); }
function showState() {
  const p=state.progress; $('phase').textContent=`v${state.version||'2.2.0'} · ${p.phase}`; for(const key of ['files','recent','read','cached','matches']) $(key).textContent=number(p[key]); $('root').textContent=state.root; $('message').textContent=p.message;
  $('timing').textContent=`${p.elapsed.toFixed(1)}s elapsed · ${number(p.folders)} folders · Listing ${p.listing_seconds.toFixed(1)}s · Analysis ${p.duration_seconds.toFixed(1)} worker-s`;
  $('scan').disabled=!!state.busy; $('cancel').disabled=!['scanning','duplicates'].includes(p.phase); for(const id of [...fields,'deep_check','authenticity_check','loadPreset']) $(id).disabled=!!state.busy;
  document.querySelectorAll('#formatOptions input, #allFormats, #noFormats').forEach(e=>e.disabled=!!state.busy);
  $('errorSummary').textContent=`Errors · ${number(p.errors)}${p.delete_failed?` (${p.delete_failed} file action failures)`:''}`; $('errorLog').textContent=state.errors.map(e=>`${e.path}\n  ${e.error}`).join('\n\n')||'No errors.';
  if(['Deletion complete','quarantine complete','restore complete','purge complete'].includes(p.message)) $('message').textContent=`${p.message}: ${p.deleted} succeeded, ${p.delete_failed} failed.`;
  $('quarantineRoot').textContent=`Storage: ${state.quarantine_root}. Restore never overwrites an existing file.`; $('scheduleStatus').textContent=state.schedule?.enabled?`Daily ${state.schedule.time} UTC · last run ${state.schedule.last_run||'not yet'}`:'Scheduled scans disabled'; $('retentionStatus').textContent=state.retention?.enabled?`Automatic permanent purge after ${state.retention.days} days`:'Automatic cleanup is disabled'; updateSelection();
}
async function poll() {
  if(polling)return;polling=true;
  try {
    state=await api('/api/state');csrf=state.csrf;
    if(first) {
      for(const format of state.formats){const label=document.createElement('label'), input=document.createElement('input');input.type='checkbox';input.value=format;input.addEventListener('change',updateFormats);label.append(input,document.createTextNode(format.toUpperCase()));$('formatOptions').append(label);}
      $('scheduleEnabled').checked=!!state.schedule?.enabled; $('scheduleTime').value=state.schedule?.time||'02:00'; $('retentionEnabled').checked=!!state.retention?.enabled; $('retentionDays').value=state.retention?.days||30;
      applySettings(state.settings); await refreshPresets(); first=false;
    }
    if(scanId!==state.scan_id){selected.clear();offset=0;scanId=state.scan_id;applySettings(state.settings);}
    if(lastPhase!==state.progress.phase&&!state.busy){selected.clear();await Promise.all([loadHistory(),loadQuarantine()]);}
    lastPhase=state.progress.phase;showState();await loadRows();
    if(++refreshNumber%10===0)await Promise.all([loadHistory(),loadQuarantine()]);
  } catch(error) { $('phase').textContent='Disconnected';$('message').textContent=error.message; }
  finally { polling=false; }
}
async function refreshPresets() {
  presets=(await api('/api/presets')).presets;
  for(const id of ['presetSelect','schedulePreset']){const old=$(id).value;$(id).replaceChildren(new Option('Choose a preset',''));for(const name of Object.keys(presets).sort())$(id).add(new Option(name,name));$(id).value=old||(id==='schedulePreset'?state.schedule?.preset||'':'');}
}
async function loadHistory() {
  const history=(await api('/api/history')).history, body=$('historyRows');body.replaceChildren();
  for(const run of history){const tr=document.createElement('tr'), cell=document.createElement('td'), button=document.createElement('button');button.textContent='Load results';button.disabled=!!state?.busy;button.addEventListener('click',()=>safe(async()=>{await api('/api/history/load',{id:run.id});await poll();}));cell.append(button);tr.append(td(new Date(run.started*1000).toLocaleString()),td(run.progress.phase),td(number(run.progress.matches)),td(`${run.settings.days||'All'} days · ${run.settings.minimum}–${run.settings.maximum}s · ${run.settings.formats.join(', ')}`),cell);body.append(tr);}
}
async function loadQuarantine() {
  quarantineRows=(await api('/api/quarantine')).rows;const current=new Set(quarantineRows.map(r=>r.id));quarantineSelected=new Set([...quarantineSelected].filter(id=>current.has(id)));renderQuarantine();
}
function renderQuarantine() {
  const body=$('quarantineRows');body.replaceChildren();for(const row of quarantineRows){const tr=document.createElement('tr'),cell=document.createElement('td'),check=document.createElement('input');check.type='checkbox';check.checked=quarantineSelected.has(row.id);check.disabled=row.state!=='quarantined';check.setAttribute('aria-label',`Select quarantined ${row.path}`);check.addEventListener('change',()=>{check.checked?quarantineSelected.add(row.id):quarantineSelected.delete(row.id);updateSelection();});cell.append(check);tr.append(cell,td(row.path),td(new Date(row.quarantined*1000).toLocaleString()),td(row.state+(row.error?`: ${row.error}`:'')));body.append(tr);}updateSelection();
}
async function preview(kind) {
  action=kind;const ids=[...(kind==='restore'||kind==='purge'?quarantineSelected:selected)];
  const result=await api(kind==='delete'?'/api/delete-preview':'/api/action-preview',kind==='delete'?{ids}:{ids,action:kind});confirmation=result.confirmation;
  const labels={delete:['Delete permanently','Permanently delete the selected library files. This cannot be undone.'],quarantine:['Quarantine files','Move selected files out of the library. You can restore them until they are purged.'],restore:['Restore files','Move quarantined files back to their original paths. Existing files are never overwritten.'],purge:['Purge quarantine','Permanently remove the selected quarantined files. This cannot be undone.']};
  $('actionTitle').textContent=labels[kind][0];$('actionDescription').textContent=labels[kind][1];$('deleteCount').textContent=`${number(result.count)} file(s)`;$('deletePaths').textContent=result.paths.join('\n');$('ack').checked=false;$('confirmDelete').disabled=true;$('confirmDelete').textContent=labels[kind][0];$('confirmDelete').className=['delete','purge'].includes(kind)?'danger':'primary';$('actionAcknowledgement').textContent=['delete','purge'].includes(kind)?'I understand these files will be permanently removed.':'I reviewed the selected paths.';$('deleteDialog').showModal();$('dismissDelete').focus();
}
$('scanForm').addEventListener('submit',e=>{e.preventDefault();safe(async()=>{if(!formats().length)throw new Error('Choose at least one audio format.');await api('/api/scan',settings());selected.clear();offset=0;await poll();});});
$('cancel').addEventListener('click',()=>safe(async()=>{await api('/api/cancel',{});await poll();}));
for(const [id,checked] of [['allFormats',true],['noFormats',false]])$(id).addEventListener('click',()=>{document.querySelectorAll('#formatOptions input').forEach(e=>e.checked=checked);updateFormats();});
$('loadPreset').addEventListener('click',()=>{const value=presets[$('presetSelect').value];if(value){applySettings(value);$('presetName').value=$('presetSelect').value;}});
$('savePreset').addEventListener('click',()=>safe(async()=>{await api('/api/preset',{name:$('presetName').value,settings:settings()});await refreshPresets();toast('Preset saved.');}));
$('removePreset').addEventListener('click',()=>safe(async()=>{await api('/api/preset',{name:$('presetSelect').value,remove:true});await refreshPresets();}));
$('saveSchedule').addEventListener('click',()=>safe(async()=>{await api('/api/schedule',{enabled:$('scheduleEnabled').checked,time:$('scheduleTime').value,preset:$('schedulePreset').value});await poll();toast('Schedule saved (UTC).');}));
$('saveRetention').addEventListener('click',()=>safe(async()=>{const enabled=$('retentionEnabled').checked;if(enabled&&!window.confirm('Enable automatic PERMANENT deletion of quarantined files older than this retention period? This also applies to files already quarantined.'))return;await api('/api/retention',{enabled,days:Number($('retentionDays').value),acknowledged:enabled});await poll();}));
$('refreshHistory').addEventListener('click',()=>safe(loadHistory));$('refreshQuarantine').addEventListener('click',()=>safe(loadQuarantine));
$('search').addEventListener('input',()=>{clearTimeout($('search').timer);$('search').timer=setTimeout(()=>{offset=0;safe(loadRows);},250);});$('duplicatesOnly').addEventListener('change',()=>{offset=0;safe(loadRows);});
document.querySelectorAll('.sort').forEach(button=>button.addEventListener('click',()=>{reverse=sort===button.dataset.sort?!reverse:false;sort=button.dataset.sort;offset=0;safe(loadRows);}));
$('prevPage').addEventListener('click',()=>{offset=Math.max(0,offset-limit);safe(loadRows);});$('nextPage').addEventListener('click',()=>{offset+=limit;safe(loadRows);});
$('pageCheck').addEventListener('change',()=>{for(const row of rows)$('pageCheck').checked?selected.add(row.id):selected.delete(row.id);renderRows();});$('clearSelection').addEventListener('click',()=>{selected.clear();renderRows();});$('selectAll').addEventListener('click',()=>safe(async()=>{selected=new Set((await api(`/api/selection?${query()}`)).ids);renderRows();}));
$('quarantineAll').addEventListener('change',()=>{quarantineSelected=$('quarantineAll').checked?new Set(quarantineRows.filter(r=>r.state==='quarantined').map(r=>r.id)):new Set();renderQuarantine();});
for(const [id,kind] of [['delete','delete'],['quarantineSelected','quarantine'],['restoreSelected','restore'],['purgeSelected','purge']])$(id).addEventListener('click',()=>safe(()=>preview(kind)));
$('ack').addEventListener('change',()=>$('confirmDelete').disabled=!$('ack').checked);$('dismissDelete').addEventListener('click',()=>$('deleteDialog').close());
$('confirmDelete').addEventListener('click',()=>safe(async()=>{if(!$('ack').checked)return;$('confirmDelete').disabled=true;try{await api(action==='delete'?'/api/delete':'/api/action',{confirmation});$('deleteDialog').close();selected.clear();quarantineSelected.clear();await poll();}finally{$('confirmDelete').disabled=false;}}));
$('export').addEventListener('click',()=>{window.location.href=`/api/export?${query()}`;});document.addEventListener('click',e=>{if(!$('formatPicker').contains(e.target))$('formatPicker').open=false;});
poll();setInterval(poll,1500);
