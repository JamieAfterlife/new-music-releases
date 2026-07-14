(function () {
  const databaseName = 'new-music-tracker-auth';
  const storeName = 'connections';
  const storagePrefix = 'new-music-tracker:trusted-v2:';

  function toBase64(bytes) {
    let binary = '';
    for (const value of bytes) binary += String.fromCharCode(value);
    return btoa(binary);
  }

  function fromBase64(value) {
    return Uint8Array.from(atob(value), character => character.charCodeAt(0));
  }

  function openDatabase() {
    return new Promise((resolve, reject) => {
      if (!window.indexedDB || !window.crypto?.subtle) {
        reject(new Error('Trusted-device storage is not available in this browser'));
        return;
      }
      const request = indexedDB.open(databaseName, 1);
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains(storeName)) {
          request.result.createObjectStore(storeName, { keyPath: 'id' });
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error('Could not open trusted-device storage'));
    });
  }

  async function transaction(mode, action) {
    const database = await openDatabase();
    try {
      return await new Promise((resolve, reject) => {
        const tx = database.transaction(storeName, mode);
        const request = action(tx.objectStore(storeName));
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error || new Error('Trusted-device storage failed'));
        tx.onabort = () => reject(tx.error || new Error('Trusted-device storage was interrupted'));
      });
    } finally {
      database.close();
    }
  }

  async function save(id, token, repository) {
    if (!window.crypto?.subtle || !window.localStorage) throw new Error('Trusted-device storage is unavailable');
    const key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt', 'decrypt']);
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, new TextEncoder().encode(token));
    const exportedKey = new Uint8Array(await crypto.subtle.exportKey('raw', key));
    localStorage.setItem(`${storagePrefix}${id}`, JSON.stringify({
      version: 2,
      repository,
      key: toBase64(exportedKey),
      iv: toBase64(iv),
      ciphertext: toBase64(new Uint8Array(ciphertext)),
    }));
    try { await transaction('readwrite', store => store.delete(id)); } catch (_) {}
  }

  async function load(id) {
    const raw = localStorage.getItem(`${storagePrefix}${id}`);
    if (raw) {
      try {
        const saved = JSON.parse(raw);
        const key = await crypto.subtle.importKey('raw', fromBase64(saved.key), { name: 'AES-GCM' }, false, ['decrypt']);
        const clear = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: fromBase64(saved.iv) }, key, fromBase64(saved.ciphertext));
        return { repository: saved.repository, token: new TextDecoder().decode(clear) };
      } catch (_) {
        localStorage.removeItem(`${storagePrefix}${id}`);
      }
    }
    try {
      const saved = await transaction('readonly', store => store.get(id));
      if (!saved?.key || !saved?.ciphertext) return null;
      const clear = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: saved.iv }, saved.key, saved.ciphertext);
      return { repository: saved.repository, token: new TextDecoder().decode(clear) };
    } catch (_) {
      return null;
    }
  }

  async function remove(id) {
    try { localStorage.removeItem(`${storagePrefix}${id}`); } catch (_) {}
    try { await transaction('readwrite', store => store.delete(id)); } catch (_) {}
  }

  window.DeviceAuth = { load, save, remove };
}());
