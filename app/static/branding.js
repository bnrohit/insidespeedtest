/* Read-only district branding. Only authenticated administrators can change it. */
'use strict';
(async () => {
  try {
    const res = await fetch('/api/branding', {cache:'no-store'});
    if (!res.ok) return;
    const b = await res.json();
    const replace = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
    replace('public-org-name', b.org_name);
    replace('public-tagline', b.tagline);
    replace('public-heading', b.heading);
    replace('public-description', b.description);
    document.title = b.site_name;
    const image = document.getElementById('brand-logo');
    if (image) image.src = '/api/branding/logo';
  } catch (_) { /* Keep the bundled branding when offline. */ }
})();
