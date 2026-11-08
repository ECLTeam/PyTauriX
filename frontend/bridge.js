(() => {
  const core = () => window.__TAURI__.core;
  const session = (() => {
    const bytes = new Uint8Array(8);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  })();
  let sequence = 0;

  // 带 signal 的调用按请求编号登记，abort 时先本地拒绝，再通知原生归还应答权。
  const pyInvoke = (command, payload = null, options) => {
    const signal = options?.signal;
    if (!signal) return core().invoke("python_command", { command, payload }, options);
    if (signal.aborted) {
      return Promise.reject(new DOMException("Invoked command was aborted", "AbortError"));
    }
    const requestId = `${session}-${++sequence}`;
    const settings = { ...options };
    delete settings.signal;
    delete settings.onCancelResult;
    const pending = core().invoke("python_command", { command, payload, request_id: requestId }, settings);
    return new Promise((resolve, reject) => {
      const onAbort = () => {
        // 原生是否真的应答了这次取消；false 表示登记项已结束或不存在。
        core()
          .invoke("pytaruix_cancel", { request_id: requestId })
          .then(
            (value) => options?.onCancelResult?.(value),
            (error) => options?.onCancelResult?.(error),
          );
        reject(new DOMException("Invoked command was aborted", "AbortError"));
      };
      signal.addEventListener("abort", onAbort, { once: true });
      pending.then(
        (value) => {
          signal.removeEventListener("abort", onAbort);
          resolve(value);
        },
        (error) => {
          signal.removeEventListener("abort", onAbort);
          reject(error);
        },
      );
    });
  };

  // 处理完一条消息后归还流控配额；capacity > 0 的原生通道依赖这个 ack。
  const createChannel = (onmessage) => {
    const channel = new core().Channel(async (message) => {
      try {
        await onmessage(message);
      } finally {
        core().invoke("pytaruix_channel_ack", { channel_id: channel.id }).catch(() => {});
      }
    });
    return channel;
  };

  const legacyPyInvoke = (command, body, options) => {
    const encoded = body === undefined || body instanceof ArrayBuffer || body instanceof Uint8Array
      ? body : new TextEncoder().encode(JSON.stringify(body));
    const headers = new Headers(options?.headers);
    headers.set("pyfunc", command);
    return core().invoke("plugin:pytauri|pyfunc", encoded, { ...options, headers });
  };
  window.__TAURI__.pytaruix = Object.freeze({ pyInvoke, createChannel });
  window.__TAURI__.pytauri = Object.freeze({ pyInvoke: legacyPyInvoke });
})();
