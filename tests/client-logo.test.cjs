'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const js = fs.readFileSync('app/static/branding.js', 'utf8');

function environment(sharedStorage = new Map()) {
  const elements = new Map();
  function element(name) {
    if (!elements.has(name)) {
      const el = {
        id: name, hidden: false, disabled: false, value: '', textContent: '',
        listeners: {}, files: [], src: '', alt: '', clickCount: 0,
        addEventListener(event, handler) { this.listeners[event] = handler; },
        click() { this.clickCount++; },
      };
      elements.set(name, el);
    }
    return elements.get(name);
  }
  let currentFile = null;
  const store = {
    getItem(key) { return sharedStorage.has(key) ? sharedStorage.get(key) : null; },
    setItem(key, value) { sharedStorage.set(key, value); },
    removeItem(key) { sharedStorage.delete(key); },
  };
  const ctx = {
    document: {
      getElementById: element,
      createElement(kind) {
        assert.equal(kind, 'canvas');
        return {
          getContext(type) {
            assert.equal(type, '2d');
            return {drawImage(image, x, y, w, h) {
              assert.equal(image, ctx.__picture);
              assert(w > 0 && h > 0 && w <= 360 && h <= 170);
            }};
          },
          toDataURL(type) {
            assert.equal(type, 'image/png');
            return 'data:image/png;base64,YWJjZA==';
          },
        };
      },
    },
    localStorage: store,
    URL: {
      createObjectURL(file) { currentFile = file; return 'blob:gmcs-test'; },
      revokeObjectURL(url) { assert.equal(url, 'blob:gmcs-test'); },
    },
    Image: class {
      constructor() { this.naturalWidth = 640; this.naturalHeight = 320; ctx.__picture = this; }
      decode() { return Promise.resolve(); }
    },
  };
  vm.runInNewContext(js, ctx, {filename:'branding.js'});
  return {element, store, sharedStorage, getFile: () => currentFile};
}

async function run() {
  const saved = new Map();
  const first = environment(saved);
  assert.equal(first.element('brand-logo').src, '/static/gmcs-logo.png');
  first.element('brand-upload-button').listeners.click();
  assert.equal(first.element('brand-logo-file').clickCount, 1);
  let file = {name:'logo.svg',type:'image/svg+xml',size:100};
  first.element('brand-logo-file').files = [file];
  await first.element('brand-logo-file').listeners.change();
  assert.match(first.element('brand-message').textContent, /SVG and GIF are not allowed/);
  assert.equal(saved.size, 0);

  file = {name:'school.png',type:'image/png',size:1024};
  first.element('brand-logo-file').files = [file];
  await first.element('brand-logo-file').listeners.change();
  assert.equal(first.element('brand-logo').src,'data:image/png;base64,YWJjZA==');
  assert.equal(first.element('brand-reset-button').hidden, false);
  assert.equal(saved.size,1);
  assert.match(first.element('brand-message').textContent, /browser only/);

  const anotherBrowser = environment(new Map());
  assert.equal(anotherBrowser.element('brand-reset-button').hidden,true);
  assert.equal(anotherBrowser.element('brand-logo').src,'/static/gmcs-logo.png');
  const sameBrowser = environment(saved);
  assert.equal(sameBrowser.element('brand-logo').src,'data:image/png;base64,YWJjZA==');
  assert.equal(sameBrowser.element('brand-reset-button').hidden,false);
  sameBrowser.element('brand-reset-button').listeners.click();
  assert.equal(sameBrowser.element('brand-logo').src,'/static/gmcs-logo.png');
  assert.equal(sameBrowser.element('brand-reset-button').hidden,true);
  assert.equal(saved.size,0);

  const oversized = environment();
  oversized.element('brand-logo-file').files = [{name:'large.png',type:'image/png',size:2*1024*1024+1}];
  await oversized.element('brand-logo-file').listeners.change();
  assert.match(oversized.element('brand-message').textContent, /2 MB or smaller/);
  assert.equal(oversized.element('brand-upload-button').disabled,false);
  console.log('Client logo tests passed: validate, upload, isolate, persist, reset, size limit.');
}
run().catch(err => {console.error(err);process.exitCode=1;});
