"use strict";
const form=document.getElementById('admin-login');
form.addEventListener('submit',async(event)=>{
 event.preventDefault();
 const button=document.getElementById('login-btn');
 const message=document.getElementById('login-status');
 button.disabled=true; message.textContent='Signing in…';
 try{
   const response=await fetch('/api/admin/login',{
     method:'POST',cache:'no-store',headers:{'Content-Type':'application/json'},
     body:JSON.stringify({username:document.getElementById('username').value.trim(),password:document.getElementById('password').value})
   });
   if(!response.ok){
     const info=await response.json().catch(()=>({}));
     throw Error(info.detail || `Sign in failed (${response.status})`);
   }
   document.getElementById('password').value='';
   window.location.replace('/admin');
 }catch(error){message.textContent=error.message;button.disabled=false;}
});
