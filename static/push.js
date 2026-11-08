// SE7EN push notifications (i-load sa tanang pages gikan sa app.py)
(function () {
  if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) return;

  function b64ToUint8(b64) {
    const pad = '='.repeat((4 - (b64.length % 4)) % 4);
    const raw = atob((b64 + pad).replace(/-/g, '+').replace(/_/g, '/'));
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  async function getKey() {
    try {
      const r = await fetch('/push/public-key', { credentials: 'same-origin' });
      if (!r.ok) return null;                 // wala naka-login, o wala pa naka-set ang keys
      return (await r.json()).key;
    } catch (e) { return null; }
  }

  async function subscribe(key) {
    const reg = await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: b64ToUint8(key)
      });
    }
    await fetch('/push/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(sub)
    });
  }

  function showBell(key) {
    if (document.getElementById('se7en-bell')) return;
    const b = document.createElement('button');
    b.id = 'se7en-bell';
    b.textContent = '🔔 Enable notifications';
    b.style.cssText = 'position:fixed;left:50%;bottom:20px;transform:translateX(-50%);z-index:99999;' +
      'background:#0ea5e9;color:#fff;border:none;padding:12px 20px;border-radius:999px;' +
      'font:800 12px system-ui,sans-serif;letter-spacing:.08em;text-transform:uppercase;' +
      'box-shadow:0 10px 30px rgba(14,165,233,.4);cursor:pointer;';
    b.onclick = async function () {
      const perm = await Notification.requestPermission();
      if (perm === 'granted') {
        try { await subscribe(key); } catch (e) { console.error(e); }
      }
      b.remove();
    };
    document.body.appendChild(b);
  }

  async function init() {
    const key = await getKey();
    if (!key) return;

    if (Notification.permission === 'granted') {
      // I-refresh ang subscription kausa kada tab session
      if (!sessionStorage.getItem('se7en_push_ok')) {
        try { await subscribe(key); sessionStorage.setItem('se7en_push_ok', '1'); }
        catch (e) { console.error(e); }
      }
    } else if (Notification.permission === 'default') {
      showBell(key);
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
