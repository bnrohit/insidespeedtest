'use strict';
const el=id=>document.getElementById(id);
let csrfToken='';
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
      cell(tr,r.email_status);cell(tr,r.client_email_status);
      const detail=document.createElement('td');const open=document.createElement('button');
      open.type='button';open.className='secondary-btn';open.textContent='Diagnose #'+r.id;
      open.addEventListener('click',()=>openDiagnostics(r.id));detail.append(open);tr.append(detail);
      el('rows').append(tr);
    }
    el('schools').replaceChildren();
    for(const r of summary.schools){const tr=document.createElement('tr');cell(tr,r.school);cell(tr,r.tests);cell(tr,r.avg_down+' Mbps');cell(tr,r.avg_up+' Mbps');el('schools').append(tr);}
    el('admin-status').textContent=`Showing ${results.results.length} most recent matching tests. Email status is updated after SMTP attempt.`;
  }catch(err){el('admin-status').textContent='Unable to load admin results: '+err.message;}
}
el('refresh').addEventListener('click',refresh);
el('school-filter').addEventListener('keydown',e=>{if(e.key==='Enter')refresh();});
el('vlan-filter').addEventListener('keydown',e=>{if(e.key==='Enter')refresh();});


const postConfig=async (url, method, body)=>{
  const response=await fetch(url,{method,cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':csrfToken},body:JSON.stringify(body)});
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
      try{const res=await fetch('/api/admin/config/agents/'+encodeURIComponent(item.agent_id),{method:'DELETE',headers:{'X-CSRF-Token':csrfToken}});
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

// Query the exact, active mapping without touching production networking.
el('lookup-btn').addEventListener('click',async()=>{
  const ip=el('lookup-ip').value.trim();
  if(!ip){el('lookup-result').textContent='Enter a client IP first.';return;}
  try{
    const response=await fetch('/api/admin/config/lookup?ip='+encodeURIComponent(ip),{cache:'no-store'});
    const data=await response.json();
    if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Lookup failed');
    el('lookup-result').textContent=`${data.client_ip} → ${data.school} / VLAN ${data.vlan} — ${data.network_label}`;
  }catch(err){el('lookup-result').textContent='Lookup failed: '+err.message;}
});
const csvEscape=(s)=>'"'+s.replaceAll('"','""')+'"';
el('append-mapping').addEventListener('click',()=>{
  const scope=el('mapping-scope').value;
  const school=el('mapping-school').value.trim();
  const vlan=scope==='vlan'?el('mapping-vlan').value.trim():'';
  const cidr=el('mapping-cidr').value.trim();
  const label=el('mapping-label').value.trim();
  if(!school||!cidr||(scope==='vlan' && !(Number.isInteger(Number(vlan)) && +vlan>=1 && +vlan<=4094))){
    el('append-mapping-status').textContent='Enter school, valid VLAN (when applicable), and exact CIDR.';return;
  }
  if([school,label,cidr].some(x=>/[\r\n\0]/.test(x))){
    el('append-mapping-status').textContent='Line breaks are not allowed in CSV cells.';return;
  }
  const row=[scope,school,vlan,cidr,label].map(csvEscape).join(',');
  const editor=el('network-csv');
  const current=editor.value.trimEnd();
  editor.value=(current ? current+'\n' : 'scope,school,vlan,cidr,label\n')+row+'\n';
  el('append-mapping-status').textContent='Added to editor. Now select Validate & save inventory. Existing settings are unchanged until saved.';
  editor.focus();
});

// Website branding: authenticated admin only; uses the same CSRF token as other settings.
async function loadBranding(){
  const b=await req('/api/admin/branding');
  for(const [id,val] of [['brand-org',b.org_name],['brand-site',b.site_name],
    ['brand-tagline',b.tagline],['brand-heading',b.heading],['brand-description',b.description]])el(id).value=val;
  el('brand-preview').src='/api/branding/logo?ts='+Date.now();
  el('branding-status').textContent=b.custom_logo?'Custom logo active for all visitors.':'Official GMCS logo active.';
}
el('brand-save').addEventListener('click',async()=>{
  const button=el('brand-save');button.disabled=true;
  try{
    await postConfig('/api/admin/branding','PUT',{
      org_name:el('brand-org').value,site_name:el('brand-site').value,
      tagline:el('brand-tagline').value,heading:el('brand-heading').value,
      description:el('brand-description').value});
    el('branding-status').textContent='Site name and text saved for all clients. Refresh the speed-test page to view.';
  }catch(e){el('branding-status').textContent='Save failed: '+e.message;}
  finally{button.disabled=false;}
});
el('brand-upload').addEventListener('change',async()=>{
  const file=el('brand-upload').files?.[0];el('brand-upload').value='';if(!file)return;
  if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>2*1024*1024||file.size<1){
    el('branding-status').textContent='Select a PNG, JPEG or WebP smaller than 2 MB.';return;
  }
  let temp;
  try{
    temp=URL.createObjectURL(file);const image=new Image();image.src=temp;await image.decode();
    if(image.naturalWidth>4096||image.naturalHeight>4096||image.naturalWidth*image.naturalHeight>12000000)throw Error('Image dimensions too large');
    const scale=Math.min(480/image.naturalWidth,220/image.naturalHeight,1);
    const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(scale*image.naturalWidth));canvas.height=Math.max(1,Math.round(scale*image.naturalHeight));
    canvas.getContext('2d').drawImage(image,0,0,canvas.width,canvas.height);
    const data=canvas.toDataURL('image/png');
    if(data.length>620000)throw Error('Processed logo exceeds the 450 KB server limit');
    await postConfig('/api/admin/branding/logo','PUT',{png_data:data});
    el('brand-preview').src='/api/branding/logo?ts='+Date.now();
    el('branding-status').textContent='District logo saved for all clients.';
  }catch(e){el('branding-status').textContent='Logo not saved: '+e.message;}
  finally{if(temp)URL.revokeObjectURL(temp);}
});
el('brand-reset').addEventListener('click',async()=>{
  if(!confirm('Restore the official GMCS logo for every user?'))return;
  try{
    const r=await fetch('/api/admin/branding/logo',{method:'DELETE',headers:{'X-CSRF-Token':csrfToken}});
    if(!r.ok)throw Error('HTTP '+r.status);
    el('brand-preview').src='/api/branding/logo?ts='+Date.now();
    el('branding-status').textContent='Official GMCS logo restored for all users.';
  }catch(e){el('branding-status').textContent='Reset failed: '+e.message;}
});
async function refreshEgress(){
  try{
    const x=await req('/api/admin/diagnostics/egress');el('egress-rows').replaceChildren();
    for(const r of x.samples){const tr=document.createElement('tr');
      for(const v of [new Date(r.at*1000).toISOString().replace('T',' ').slice(0,19),r.status,r.dns_ms,r.tls_ms,r.download_mbps,r.upload_mbps])cell(tr,v);el('egress-rows').append(tr);
    }
    if(!x.samples.length)el('egress-result').textContent='No VM Internet checks recorded yet.';
  }catch(e){el('egress-result').textContent='Could not load checks: '+e.message;}
}
el('egress-refresh').addEventListener('click',refreshEgress);
el('egress-run').addEventListener('click',async()=>{
  const button=el('egress-run');button.disabled=true;el('egress-result').textContent='Checking NOC VM Internet egress…';
  try{
    const result=await postConfig('/api/admin/diagnostics/egress','POST',{});
    el('egress-result').textContent=result.status==='ok'
      ? `NOC VM → ${result.target}: DNS ${result.dns_ms} ms, HTTPS ${result.tls_ms} ms, ↓ ${result.download_mbps} Mbps, ↑ ${result.upload_mbps} Mbps (4 MiB down / 1 MiB up).`
      : 'Internet test failed: '+result.detail;
    await refreshEgress();
  }catch(e){el('egress-result').textContent='Test not accepted: '+e.message;}
  finally{button.disabled=false;}
});

async function initializeAdmin(){
  try{
    const session=await req('/api/admin/session');
    csrfToken=session.csrf_token;
    await Promise.all([refresh(),loadConfig(),loadBranding(),refreshEgress(),loadRouterSites()]);
  }catch(err){
    window.location.replace('/admin');
  }
}
el('logout').addEventListener('click',async()=>{
  const button=el('logout');button.disabled=true;
  try{
    const response=await fetch('/api/admin/logout',{
      method:'POST',cache:'no-store',headers:{'X-CSRF-Token':csrfToken}
    });
    if(!response.ok)throw Error(`HTTP ${response.status}`);
    window.location.replace('/admin');
  }catch(err){
    button.disabled=false;
    el('admin-status').textContent='Unable to log out: '+err.message;
  }
});
initializeAdmin();

async function openDiagnostics(id){
  el('diag-result-id').value=String(id);
  el('diag-status').textContent='Loading result #'+id+'…';el('diag-summary').hidden=true;
  try{
    const r=await req('/api/admin/results/'+encodeURIComponent(id)+'/diagnostics');
    el('diag-summary').hidden=false;
    el('diag-context').textContent=`Result #${r.id} • ${r.school} VLAN ${r.vlan} • ${r.client_ip} • ${r.agent_id||'Browser'} • ${r.download_mbps} Mbps down / ${r.upload_mbps} Mbps up`;
    el('diag-findings').replaceChildren();
    for(const finding of r.assessment){
      const box=document.createElement('div');box.className='diag-finding';
      const title=document.createElement('strong');title.textContent=finding.severity.toUpperCase()+': '+finding.area;
      const note=document.createElement('p');note.textContent=finding.observation;
      const next=document.createElement('p');next.textContent='Next check: '+finding.next_step;
      box.append(title,note,next);el('diag-findings').append(box);
    }
    el('diag-browser').textContent=JSON.stringify(r.browser,null,2);
    el('diag-native').replaceChildren();
    if(!r.advanced){el('diag-native').textContent='No advanced client report uploaded. Browser sandbox cannot run ipconfig, ping, netstat, ARP or read MAC addresses.';}
    else {
      const line=document.createElement('p');line.textContent=`User-approved ${r.advanced.platform} report from ${r.advanced.hostname||'unnamed client'} uploaded at ${new Date(r.advanced_at*1000).toISOString()}`;
      el('diag-native').append(line);
      for(const [name,output] of Object.entries(r.advanced.commands)){
        const section=document.createElement('details');section.className='diag-native';
        const summary=document.createElement('summary');summary.textContent=name;
        const pre=document.createElement('pre');pre.className='diag-output';pre.textContent=output;
        section.append(summary,pre);el('diag-native').append(section);
      }
    }
    el('diag-status').textContent='Evidence and possible causes loaded. Treat suggestions as hypotheses until verified on VyOS/Nexus and client.';
    el('diagnostics-panel').scrollIntoView({behavior:'smooth',block:'start'});
  }catch(e){el('diag-status').textContent='Could not open diagnostics: '+e.message;}
}
el('diag-open').addEventListener('click',()=>{
  const id=Number(el('diag-result-id').value);
  if(!Number.isSafeInteger(id)||id<1){el('diag-status').textContent='Enter a valid result number.';return;}
  openDiagnostics(id);
});

// Authenticated, read-only visualization: no remote commands and no user-defined targets.
const routerSvgNS='http://www.w3.org/2000/svg';
function routerSvg(name,attr={}){const n=document.createElementNS(routerSvgNS,name);for(const [k,v] of Object.entries(attr))n.setAttribute(k,String(v));return n;}
function routerDraw(result){
  const root=el('router-graph');root.replaceChildren();
  const data=result.points||[];
  if(!data.length){root.textContent='No hourly measurements for this time range.';return;}
  const svg=routerSvg('svg',{viewBox:'0 0 900 250',role:'img','aria-label':'Download teal, upload blue; time left to right'});
  const pad=40,left=pad,top=12,width=820,height=190;
  const first=data[0].at,last=data[data.length-1].at;
  const nums=data.flatMap(p=>[p.down_mbps,p.up_mbps]).filter(v=>v!==null && Number.isFinite(v));
  const max=Math.max(1,...nums)*1.15;
  const x=(at)=>left+(at-first)/Math.max(last-first,3600)*width;
  const y=(value)=>top+height-value/max*height;
  for(const val of [0,0.5,1]){
    const gy=top+height*(1-val);
    svg.append(routerSvg('line',{x1:left,y1:gy,x2:left+width,y2:gy,stroke:'#64748b','stroke-opacity':0.35}));
    const t=routerSvg('text',{x:0,y:gy+5,fill:'currentColor','font-size':12});t.textContent=(max*val).toFixed(1);svg.append(t);
  }
  function addLine(field,color){
    // Break at missing/failed samples so gaps are never presented as zero or continuous.
    let segments=[],current=[];
    for(const p of data){
      if(p[field]===null || !Number.isFinite(p[field])){if(current.length)segments.push(current);current=[];continue;}
      current.push(`${x(p.at).toFixed(1)},${y(p[field]).toFixed(1)}`);
    }
    if(current.length)segments.push(current);
    for(const pts of segments){
      if(pts.length>1)svg.append(routerSvg('polyline',{points:pts.join(' '),fill:'none',stroke:color,'stroke-width':2.5}));
      else {const [cx,cy]=pts[0].split(',');svg.append(routerSvg('circle',{cx,cy,r:3,fill:color}));}
    }
  }
  addLine('down_mbps','#14b8a6');addLine('up_mbps','#60a5fa');
  for(const [p,label] of [[first,'Start'],[last,'Latest']]){
    const t=routerSvg('text',{x:x(p),y:230,fill:'currentColor','font-size':12,'text-anchor':p===first?'start':'end'});
    t.textContent=label+' '+new Date(p*1000).toISOString().slice(0,16).replace('T',' ');svg.append(t);
  }
  root.append(svg);
  const legend=document.createElement('p');legend.className='caption';legend.textContent='Teal = download, blue = upload. Samples are throughput capped on the VyOS test.';root.append(legend);
}
async function loadRouterSites(){
  try {
    const result=await req('/api/admin/router-hourly');
    const selector=el('router-school');const existing=selector.value;
    selector.replaceChildren();
    for(const site of result.sites){
      const opt=document.createElement('option');opt.value=site.site;opt.textContent=site.site+' — '+site.name;selector.append(opt);
    }
    if(result.sites.some(s=>s.site===existing))selector.value=existing;
    const rows=el('router-rows');rows.replaceChildren();
    for(const r of result.sites){const tr=document.createElement('tr');
      for(const v of [r.site,new Date(r.at*1000).toISOString().slice(0,16),r.status,r.router_ip,r.down_mbps,r.up_mbps,r.latency_ms])cell(tr,v);
      rows.append(tr);
    }
    if(!result.sites.length){el('router-status').textContent='No hourly samples yet. Run the opt-in collector first.';return;}
    await loadRouterGraph();
  }catch(e){el('router-status').textContent='Unable to retrieve WAN history: '+e.message;}
}
async function loadRouterGraph(){
  const site=el('router-school').value;
  if(!site){el('router-graph').replaceChildren();return;}
  try{
    const result=await req('/api/admin/router-hourly/'+encodeURIComponent(site)+'?window='+encodeURIComponent(el('router-range').value));
    const valid=result.points.reduce((n,p)=>n+(p.down_mbps!==null?1:0),0);
    el('router-status').textContent=`${site}: ${result.points.length} time buckets; ${valid} include throughput. Capped test (not full ISP rate).`;
    routerDraw(result);
  }catch(e){el('router-status').textContent='WAN chart unavailable: '+e.message;}
}
el('router-school').addEventListener('change',loadRouterGraph);
el('router-range').addEventListener('change',loadRouterGraph);
el('router-refresh').addEventListener('click',loadRouterSites);
