'use strict';
const el=id=>document.getElementById(id);
const cell=(row,value,className)=>{const td=document.createElement('td');td.textContent=String(value??'—');if(className)td.className=className;row.append(td);};
const req=async url=>{const response=await fetch(url,{cache:'no-store'});if(!response.ok)throw Error(`HTTP ${response.status}`);return response.json();};
async function refresh(){
  el('admin-status').textContent='Loading…';
  try{
    const query=new URLSearchParams({limit:'200'});
    if(el('school-filter').value.trim())query.set('school',el('school-filter').value.trim());
    if(el('vlan-filter').value.trim())query.set('vlan',el('vlan-filter').value.trim());
    const [summary,results]=await Promise.all([req('/api/admin/summary'),req('/api/admin/results?'+query)]);
    el('total-tests').textContent=summary.total_tests;
    el('school-count').textContent=summary.schools.filter(s=>s.school!=='Unknown').length;
    el('emails-sent').textContent=summary.emails.find(v=>v.email_status==='sent')?.count||0;
    el('rows').replaceChildren();
    if(!results.results.length){const tr=document.createElement('tr');cell(tr,'No matching results');el('rows').append(tr);}
    for(const r of results.results){
      const tr=document.createElement('tr');
      cell(tr,new Date(r.completed_at*1000).toISOString().replace('T',' ').slice(0,19));
      cell(tr,r.school,'tag'+(r.school==='Unknown'?' unknown':''));
      cell(tr,r.vlan);cell(tr,r.agent_id || 'Browser');cell(tr,r.client_ip);cell(tr,Number(r.download_mbps).toFixed(1)+' Mbps');
      cell(tr,Number(r.upload_mbps).toFixed(1)+' Mbps');
      cell(tr,Number(r.latency_ms).toFixed(1)+' ms');cell(tr,Number(r.jitter_ms).toFixed(1)+' ms');
      cell(tr,r.email_status);el('rows').append(tr);
    }
    el('schools').replaceChildren();
    for(const r of summary.schools){const tr=document.createElement('tr');cell(tr,r.school);cell(tr,r.tests);cell(tr,r.avg_down+' Mbps');cell(tr,r.avg_up+' Mbps');el('schools').append(tr);}
    el('admin-status').textContent=`Showing ${results.results.length} most recent matching tests. Email status is updated after SMTP attempt.`;
  }catch(err){el('admin-status').textContent='Unable to load admin results: '+err.message;}
}
el('refresh').addEventListener('click',refresh);
el('school-filter').addEventListener('keydown',e=>{if(e.key==='Enter')refresh();});
el('vlan-filter').addEventListener('keydown',e=>{if(e.key==='Enter')refresh();});
refresh();


const postConfig=async (url, method, body)=>{
  const response=await fetch(url,{method,cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  let data;try{data=await response.json();}catch(_){data={detail:'Unexpected server response'};}
  if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||`HTTP ${response.status}`));
  return data;
};
async function loadConfig(){
  try{
    const [s,n,a]=await Promise.all([
      req('/api/admin/config/smtp'),req('/api/admin/config/networks'),req('/api/admin/config/agents')]);
    el('smtp-host').value=s.host;
    el('smtp-port').value=s.port;
    el('smtp-tls').value=s.tls_mode;
    el('smtp-user').value=s.username;
    el('smtp-from').value=s.sender;
    el('smtp-to').value=s.recipients;
    el('smtp-hours').value=Math.round(s.dedupe_seconds/3600);
    el('smtp-browser').checked=s.email_browser_results;
    el('smtp-agent').checked=s.email_agent_results;
    el('smtp-pass').value='';
    el('smtp-status').textContent=s.password_configured?'An SMTP password is configured (not shown).':'No SMTP password saved.';
    el('network-csv').value=n.csv_text;
    el('network-status').textContent=`${n.count} school/VLAN records loaded from private VM storage.`;
    drawAgents(a.agents);
  }catch(err){el('smtp-status').textContent='Failed loading settings: '+err.message;}
}
el('save-smtp').addEventListener('click',async()=>{
  const btn=el('save-smtp');btn.disabled=true;
  try{
    const s=await postConfig('/api/admin/config/smtp','PUT',{
      host:el('smtp-host').value.trim(),port:Number(el('smtp-port').value),
      tls_mode:el('smtp-tls').value,username:el('smtp-user').value.trim(),
      password:el('smtp-pass').value || null,clear_password:el('smtp-clear-pass').checked,
      sender:el('smtp-from').value.trim(),recipients:el('smtp-to').value.trim(),
      dedupe_seconds:Number(el('smtp-hours').value)*3600,
      email_browser_results:el('smtp-browser').checked,email_agent_results:el('smtp-agent').checked
    });
    el('smtp-pass').value='';el('smtp-clear-pass').checked=false;
    el('smtp-status').textContent=`Saved on VM. Password configured: ${s.password_configured?'yes':'no'}. No email sent.`;
  }catch(err){el('smtp-status').textContent='NOT saved: '+err.message;}
  finally{btn.disabled=false;}
});
el('test-smtp').addEventListener('click',async()=>{
  const btn=el('test-smtp');btn.disabled=true;
  try{const s=await postConfig('/api/admin/config/smtp/test','POST',{});
      el('smtp-status').textContent=s.message;}
  catch(err){el('smtp-status').textContent='Test failed: '+err.message;}
  finally{btn.disabled=false;}
});
el('save-networks').addEventListener('click',async()=>{
  const btn=el('save-networks');btn.disabled=true;
  try{const out=await postConfig('/api/admin/config/networks','PUT',{csv_text:el('network-csv').value});
    el('network-status').textContent=`Saved ${out.count} mapping entries. All new client tests use these mappings.`;}
  catch(err){el('network-status').textContent='NOT saved: '+err.message;}
  finally{btn.disabled=false;}
});
function drawAgents(rows){
  el('agents-list').replaceChildren();
  if(!rows.length){const tr=document.createElement('tr');cell(tr,'No scheduled agents registered');el('agents-list').append(tr);}
  for(const item of rows){
    const tr=document.createElement('tr');cell(tr,item.agent_id);cell(tr,item.allowed_cidr);
    const td=document.createElement('td');const button=document.createElement('button');
    button.type='button';button.textContent='Revoke';button.className='secondary-btn';
    button.addEventListener('click',async()=>{
      if(!confirm(`Revoke token for ${item.agent_id}? This server will no longer authenticate.`))return;
      try{const res=await fetch('/api/admin/config/agents/'+encodeURIComponent(item.agent_id),{method:'DELETE'});
        if(!res.ok)throw Error('HTTP '+res.status);
        el('agents-status').textContent='Revoked '+item.agent_id;
        drawAgents((await req('/api/admin/config/agents')).agents);
      }catch(err){el('agents-status').textContent='Could not revoke: '+err.message;}
    });td.append(button);tr.append(td);el('agents-list').append(tr);
  }
}
el('add-agent').addEventListener('click',async()=>{
  const btn=el('add-agent');btn.disabled=true;
  try{
    const item=await postConfig('/api/admin/config/agents','POST',{
      agent_id:el('agent-id').value.trim(),allowed_cidr:el('agent-cidr').value.trim()});
    el('agent-secret-box').hidden=false;
    el('agent-secret').value=item.one_time_token;
    el('agents-status').textContent=`Registered ${item.agent_id}. Store its token on that school cache server NOW.`;
    drawAgents((await req('/api/admin/config/agents')).agents);
  }catch(err){el('agents-status').textContent='Could not register server: '+err.message;}
  finally{btn.disabled=false;}
});
el('copy-agent').addEventListener('click',async()=>{
  try{await navigator.clipboard.writeText(el('agent-secret').value);el('agents-status').textContent='Token copied; protect clipboard and paste directly into school server secret file.';}
  catch(err){el('agents-status').textContent='Select and copy token manually.';}
});
loadConfig();
