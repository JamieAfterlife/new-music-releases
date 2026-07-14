(function () {
  const databaseName = 'new-music-tracker-auth';
  const storeName = 'connections';

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
    const key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, new TextEncoder().encode(token));
    await transaction('readwrite', store => store.put({ id, repository, key, iv, ciphertext }));
  }

  async function load(id) {
    const saved = await transaction('readonly', store => store.get(id));
    if (!saved?.key || !saved?.ciphertext) return null;
    const clear = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: saved.iv }, saved.key, saved.ciphertext);
    return { repository: saved.repository, token: new TextDecoder().decode(clear) };
  }

  async function remove(id) {
    await transaction('readwrite', store => store.delete(id));
  }

  window.DeviceAuth = { load, save, remove };
}());
