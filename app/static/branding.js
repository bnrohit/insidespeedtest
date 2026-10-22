/* The logo is sanitized and stored only inside this browser. Nothing is uploaded. */
'use strict';
(() => {
  const STORAGE_KEY = 'gmcs-inside-speed-test:client-logo:v1';
  const DEFAULT_LOGO = '/static/gmcs-logo.png';
  const MAX_FILE_BYTES = 2 * 1024 * 1024;
  const MAX_STORED_LENGTH = 400000;
  const logo = document.getElementById('brand-logo');
  const uploadButton = document.getElementById('brand-upload-button');
  const fileInput = document.getElementById('brand-logo-file');
  const resetButton = document.getElementById('brand-reset-button');
  const message = document.getElementById('brand-message');
  if (!logo || !uploadButton || !fileInput || !resetButton || !message) return;

  function showCustom(data) {
    logo.src = data;
    logo.alt = 'Custom client logo';
    resetButton.hidden = false;
  }
  function showDefault() {
    logo.src = DEFAULT_LOGO;
    logo.alt = 'Gallup-McKinley County Schools logo';
    resetButton.hidden = true;
  }
  function permittedDataUrl(data) {
    return typeof data === 'string' && data.length < MAX_STORED_LENGTH &&
      /^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/.test(data);
  }
  showDefault();
  try {
    const existing = localStorage.getItem(STORAGE_KEY);
    if (permittedDataUrl(existing)) showCustom(existing);
  } catch (_) { /* Cookie and storage restrictions should not block speed tests. */ }

  uploadButton.addEventListener('click', () => fileInput.click());
  resetButton.addEventListener('click', () => {
    try { localStorage.removeItem(STORAGE_KEY); } catch (_) {}
    showDefault();
    message.textContent = 'Default GMCS logo restored for this browser.';
  });

  fileInput.addEventListener('change', async () => {
    const file = fileInput.files && fileInput.files[0];
    fileInput.value = '';
    if (!file) return;
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
      message.textContent = 'Use a PNG, JPEG, or WebP image. SVG and GIF are not allowed.';
      return;
    }
    if (file.size === 0 || file.size > MAX_FILE_BYTES) {
      message.textContent = 'Logo files must be 2 MB or smaller.';
      return;
    }
    uploadButton.disabled = true;
    message.textContent = 'Preparing logo…';
    let objectUrl;
    try {
      objectUrl = URL.createObjectURL(file);
      const picture = new Image();
      picture.src = objectUrl;
      await picture.decode();
      if (!picture.naturalWidth || !picture.naturalHeight ||
          picture.naturalWidth > 4096 || picture.naturalHeight > 4096 ||
          picture.naturalWidth * picture.naturalHeight > 12000000) {
        throw new Error('Image dimensions must be within 4096 × 4096 pixels and 12 megapixels.');
      }
      const scale = Math.min(360 / picture.naturalWidth, 170 / picture.naturalHeight, 1);
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(picture.naturalWidth * scale));
      canvas.height = Math.max(1, Math.round(picture.naturalHeight * scale));
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('This browser cannot prepare the image.');
      ctx.drawImage(picture, 0, 0, canvas.width, canvas.height);
      const safeImage = canvas.toDataURL('image/png'); // Removes metadata and any SVG/script content.
      if (!permittedDataUrl(safeImage)) throw new Error('Logo is too complex to save. Try a simpler image.');
      try {
        localStorage.setItem(STORAGE_KEY, safeImage);
        message.textContent = 'Custom logo saved in this browser only.';
      } catch (_) {
        message.textContent = 'Logo is shown temporarily. Browser storage is unavailable.';
      }
      showCustom(safeImage);
    } catch (error) {
      message.textContent = 'Could not use logo: ' + (error.message || 'invalid image');
    } finally {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      uploadButton.disabled = false;
    }
  });
})();
