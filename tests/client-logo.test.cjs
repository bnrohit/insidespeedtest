'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const script = fs.readFileSync('app/static/branding.js', 'utf8');
const elements = new Map();
const el = id => {
  if (!elements.has(id)) elements.set(id, {id, textContent:'', src:''});
  return elements.get(id);
};
const context={document: {getElementById:el,title:''}, fetch: async (url) => {
  assert.equal(url, '/api/branding');
  return {ok:true, json: async()=>({org_name:'School Name',site_name:'Custom Speed Test',
    tagline:'IT Division',heading:'External + Internal Diagnostics',description:'Updated by administrator only'})};
}};
vm.runInNewContext(script, context, {filename:'branding.js'});
setImmediate(()=>{
  assert.equal(el('public-org-name').textContent, 'School Name');
  assert.equal(el('public-tagline').textContent, 'IT Division');
  assert.equal(el('public-heading').textContent, 'External + Internal Diagnostics');
  assert.equal(el('public-description').textContent, 'Updated by administrator only');
  assert.equal(context.document.title, 'Custom Speed Test');
  assert.equal(el('brand-logo').src, '/api/branding/logo');
  assert(!script.includes('localStorage'));
  assert(!script.includes('addEventListener'));
  console.log('Public branding is read-only and reflects administrator settings.');
});
