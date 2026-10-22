'use strict';
const el = (id) => document.getElementById(id);
const start = el('start');
let running = false;
let emailReceipt = null;
let diagnosticReceipt = null;
let latestMbps = 0;
const sleep = ms => new Promise(resolve => setTimeout(resolve,ms));
const fmt = n => Number(n).toFixed(1);
const nonce = () => Array.from(crypto.getRandomValues(new Uint8Array(12)), b => b.toString(16).padStart(2,'0')).join('');

async function jsonApi(url, options = {}) {
  const response = await fetch(url, {cache:'no-store', ...options});
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `Server error ${response.status}`);
  }
  return response.json();
}
function setIdentity(identity) {
  el('school').textContent = identity.school || 'Unknown';
  el('vlan').textContent = identity.vlan || 'Unknown';
  el('ip').textContent = identity.client_ip || 'Unknown';
}
async function init(){
  try {setIdentity(await jsonApi('/api/identity'));}
  catch(err) {el('school').textContent='Unavailable';el('result-message').textContent=err.message;start.disabled=true;}
}
function updateProgress(pct,text,phase) {
  el('progress').style.width = `${Math.min(100,Math.max(0,pct))}%`;
  el('status').textContent=text;
  el('phase').textContent=phase;
}
async function pingTest(token) {
  const readings=[];
  let failed=0;
  for(let i=0;i<10;i++) {
    const t=performance.now();
    try {
      const controller=new AbortController();
      const timeout=setTimeout(()=>controller.abort(),2000);
      try {const response=await fetch(`/api/ping?n=${nonce()}`,{cache:'no-store',signal:controller.signal,headers:{'X-Speedtest-Token':token}});if(!response.ok)throw Error('Ping failed');}
      finally {clearTimeout(timeout);}
      readings.push(performance.now()-t);
    } catch {failed++;}
    updateProgress(3+i*1.5,`Measuring latency (${i+1}/10)`,'PING');
    await sleep(50);
  }
  if(!readings.length)throw new Error('Latency test failed. Check school-to-server access.');
  const avg=readings.reduce((a,b)=>a+b,0)/readings.length;
  const jitter=readings.length>1?readings.slice(1).reduce((acc,val,i)=>acc+Math.abs(val-readings[i]),0)/(readings.length-1):0;
  el('latency').textContent=fmt(avg);
  el('jitter').textContent=fmt(jitter);
  return {latency_ms:avg,jitter_ms:jitter,packet_loss_pct:failed*10};
}
async function throughput(mode,seconds,streams,onValue,token) {
  const deadline=performance.now()+seconds*1000;
  const began=performance.now();
  let bytes=0;
  let failureCount=0;
  let allowanceExhausted=false;
  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),seconds*1000);
  let payload=null;
  if(mode==='upload') {
    payload=new Uint8Array(4*1024*1024);
    for(let i=0;i<payload.length;i+=65536){crypto.getRandomValues(payload.subarray(i,Math.min(i+65536,payload.length)));}
  }
  const sample=setInterval(()=>{
    const elapsed=Math.max((performance.now()-began)/1000,.001);
    latestMbps=bytes*8/elapsed/1e6;
    onValue(latestMbps,Math.min(1,(performance.now()-began)/(seconds*1000)));
  },200);
  async function worker() {
    while(performance.now()<deadline&&!controller.signal.aborted&&!allowanceExhausted){
      try {
        if(mode==='download') {
          const response=await fetch(`/api/download?bytes=33554432&n=${nonce()}`,{signal:controller.signal,cache:'no-store',headers:{'X-Speedtest-Token':token}});
          if(response.status===429){allowanceExhausted=true;break;}
          if(!response.ok||!response.body)throw Error('Download failed');
          const reader=response.body.getReader();
          for(;;){const {done,value}=await reader.read();if(done)break;bytes+=value.byteLength;if(performance.now()>=deadline)break;}
          await reader.cancel().catch(()=>{});
        } else {
          const response=await fetch(`/api/upload?n=${nonce()}`,{method:'POST',body:payload,signal:controller.signal,cache:'no-store',headers:{'Content-Type':'application/octet-stream','X-Speedtest-Token':token}});
          if(response.status===429){allowanceExhausted=true;break;}
          if(!response.ok)throw Error('Upload failed');
          const result=await response.json();
          bytes+=result.bytes_received;
        }
        failureCount=0;
      }catch(err){if(controller.signal.aborted)break;if(++failureCount>=3)throw err;await sleep(150);}
    }
  }
  try {await Promise.all(Array.from({length:streams},()=>worker()));}
  finally {clearTimeout(timeout);clearInterval(sample);controller.abort();}
  const secondsElapsed=(performance.now()-began)/1000;
  const mbps=bytes*8/Math.max(secondsElapsed,.001)/1e6;
  onValue(mbps,1);
  return {mbps,bytes};
}
start.addEventListener('click',async()=>{
  if(running)return;
  running=true;start.disabled=true;
  emailReceipt=null;diagnosticReceipt=null;el('send-email-panel').hidden=true;
  el('diagnostic-send').disabled=true;
  el('diagnostic-pair').disabled=true;
  el('diagnostic-pair-code').value='';
  el('diagnostic-status').textContent='Finish a speed test to enable optional diagnostics upload.';
  el('result-message').textContent='';el('download').textContent='—';el('upload').textContent='—';
  el('latency').textContent='—';el('jitter').textContent='—';el('live-value').textContent='0.0';
  try {
    updateProgress(1,'Opening authenticated test session…','STARTING');
    let session;
    // If many classrooms run tests at once, wait for a transfer slot instead
    // of flooding the school-to-NOC WAN link. This is not a login restriction.
    for (let attempt = 0; attempt < 60; attempt++) {
      const response=await fetch('/api/session',{method:'POST',cache:'no-store'});
      if(response.ok){session=await response.json();break;}
      const detail=await response.json().catch(()=>({}));
      if(response.status!==429 || !(detail.detail||'').includes('server is busy')) {
        throw new Error(detail.detail||`Server error ${response.status}`);
      }
      updateProgress(1,`Server busy. Waiting for capacity (${attempt+1}/60)…`,'QUEUED');
      await sleep(10000 + Math.random()*2000);
    }
    if(!session)throw new Error('The test server is busy. Try again shortly.');
    setIdentity(session.identity);
    const ping=await pingTest(session.token);
    updateProgress(20,'Testing download to GMCS server…','DOWNLOAD');
    const down=await throughput('download',8,4,(mbps,pct)=>{
      el('live-value').textContent=fmt(mbps);el('download').textContent=fmt(mbps);
      updateProgress(20+pct*37,'Testing download to GMCS server…','DOWNLOAD');
    },session.token);
    updateProgress(58,'Testing upload to GMCS server…','UPLOAD');
    const up=await throughput('upload',8,2,(mbps,pct)=>{
      el('live-value').textContent=fmt(mbps);el('upload').textContent=fmt(mbps);
      updateProgress(58+pct*40,'Testing upload to GMCS server…','UPLOAD');
    },session.token);
    // Browser APIs do NOT expose NIC MAC, hostname, local routes or command output.
    // Only coarse OS/browser and best-effort network estimates accompany the test.
    const ua=navigator.userAgent||'';
    const browser=ua.includes('Firefox')?'Firefox':ua.includes('Edg/')?'Edge':ua.includes('Chrome')?'Chrome':ua.includes('Safari')?'Safari':'Other';
    const platform=(navigator.userAgentData?.platform||navigator.platform||'Unknown').slice(0,45);
    const network=navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    let httpsRtt=null;
    try{const started=performance.now();const r=await fetch('/api/identity',{cache:'no-store'});if(r.ok)httpsRtt=performance.now()-started;}catch(_){/* best effort */}
    const browserDiag={platform,browser,network_type:String(network?.effectiveType||'Unknown').slice(0,20),
      network_estimated_rtt_ms:Number.isInteger(network?.rtt)?Math.min(network.rtt,100000):null,
      online:navigator.onLine===true,https_rtt_ms:httpsRtt===null?null:Math.min(30000,httpsRtt)};
    const answer=await jsonApi('/api/results',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:session.token,download_mbps:down.mbps,upload_mbps:up.mbps,download_bytes:down.bytes,upload_bytes:up.bytes,...ping,browser_diagnostics:browserDiag})});
    diagnosticReceipt={resultId:answer.result_id,token:session.token};
    el('diagnostic-send').disabled=false;
    el('diagnostic-pair').disabled=false;
    el('diagnostic-status').textContent='Result #'+answer.result_id+' ready. Optional: review your locally generated JSON before uploading. Sensitive sections require explicit consent.';
    updateProgress(100,'Completed • Result #' + answer.result_id,'COMPLETE');
    el('result-message').textContent=`Recorded for ${answer.school}, VLAN ${answer.vlan}. Automatic notification: ${answer.email_notification}.`;
    if(answer.client_email_available){
      el('send-email-panel').hidden=false;
      if(answer.client_email_already_notified){
        emailReceipt=null;
        el('send-email').disabled=true;
        el('send-email').textContent='Result already sent to admin queue';
        el('send-email-status').textContent='The automatic admin notification is already queued. No need to send another copy.';
      }else{
        emailReceipt={resultId:answer.result_id,token:session.token};
        el('send-email').disabled=false;
        el('send-email').textContent='Email my results to GMCS admins';
        el('send-email-status').textContent='Optional: send this completed test to GMCS administrators. One request per result; limits apply.';
      }
    }
  }catch(err){
    updateProgress(0,'Test did not complete','ERROR');el('result-message').textContent=err.message;
  }finally{running=false;start.disabled=false;}
});
init();

el('send-email').addEventListener('click',async()=>{
  if(!emailReceipt)return;
  const button=el('send-email');button.disabled=true;
  try{
    const response=await fetch(`/api/results/${emailReceipt.resultId}/email`,{
      method:'POST',cache:'no-store',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({token:emailReceipt.token})
    });
    const body=await response.json().catch(()=>({}));
    if(!response.ok)throw Error(body.detail||`HTTP ${response.status}`);
    el('send-email-status').textContent='Result queued for GMCS administrators. Email delivery is confirmed by the admin dashboard.';
    emailReceipt=null;
  }catch(err){
    el('send-email-status').textContent='Email request was not accepted: '+err.message;
    if(![409,429].includes(Number((err.message.match(/HTTP (\d+)/)||[])[1])))button.disabled=false;
  }
});

// Explicit local diagnostics upload; never runs commands or reads files automatically.
el('diagnostic-send').addEventListener('click',async()=>{
  const file=el('diagnostic-file').files?.[0];
  if(!diagnosticReceipt){el('diagnostic-status').textContent='Run a speed test first.';return;}
  if(!el('diagnostic-consent').checked){el('diagnostic-status').textContent='Review your report and check the consent box.';return;}
  if(!file || file.size>48000){el('diagnostic-status').textContent='Choose a reviewed JSON file smaller than 48 KB.';return;}
  const button=el('diagnostic-send');button.disabled=true;
  try{
    const content=JSON.parse(await file.text());
    if(!content||typeof content!=='object'||!content.commands)throw Error('Invalid diagnostic JSON file');
    const {resultId,token}=diagnosticReceipt;
    const response=await fetch(`/api/results/${resultId}/diagnostics/advanced`,{
      method:'POST',cache:'no-store',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({token,platform:content.platform,hostname:content.hostname,commands:content.commands})
    });
    const body=await response.json().catch(()=>({}));
    if(!response.ok)throw Error(body.detail||`HTTP ${response.status}`);
    diagnosticReceipt=null;
    el('diagnostic-file').value='';el('diagnostic-consent').checked=false;
    el('diagnostic-status').textContent='Report saved for GMCS admin troubleshooting. Result #'+resultId;
  }catch(err){button.disabled=false;el('diagnostic-status').textContent='Report not accepted: '+err.message;}
});

// User-initiated one-time pairing. Browsers never execute downloaded native scripts.
el('diagnostic-pair').addEventListener('click',async()=>{
  if(!diagnosticReceipt){el('diagnostic-status').textContent='Run a speed test first.';return;}
  if(!el('diagnostic-consent').checked){
    el('diagnostic-status').textContent='Please acknowledge which device/network details may be uploaded first.';
    return;
  }
  const button=el('diagnostic-pair');button.disabled=true;
  try{
    const {resultId,token}=diagnosticReceipt;
    const pair=await jsonApi(`/api/results/${resultId}/diagnostics/pair`,{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})
    });
    el('diagnostic-pair-code').value=pair.upload_code;
    el('diagnostic-status').textContent=`Code for test #${resultId} expires in 10 minutes. Copy it into the approved Windows script after launching it; the script saves the report, asks you to confirm, then uploads automatically. Browser-only uploads remain available.`;
  }catch(err){el('diagnostic-status').textContent='Could not create code: '+err.message;}
  finally{button.disabled=false;}
});
