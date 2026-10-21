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
