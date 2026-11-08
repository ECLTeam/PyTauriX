(() => {
  const pyInvoke = (command, payload = null, options) =>
    window.__TAURI__.core.invoke("python_command", { command, payload }, options);
  const legacyPyInvoke = (command, body, options) => {
    const encoded = body === undefined || body instanceof ArrayBuffer || body instanceof Uint8Array
      ? body : new TextEncoder().encode(JSON.stringify(body));
    const headers = new Headers(options?.headers);
    headers.set("pyfunc", command);
    return window.__TAURI__.core.invoke("plugin:pytauri|pyfunc", encoded, { ...options, headers });
  };
  window.__TAURI__.pytaruix = Object.freeze({ pyInvoke });
  window.__TAURI__.pytauri = Object.freeze({ pyInvoke: legacyPyInvoke });
})();
