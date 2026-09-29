let csrf = '';
export class ApiError extends Error {
  constructor(message, code, status, fields = {}, requestId = '') {
    super(message); Object.assign(this, { code, status, fields, requestId });
  }
}
export function setCsrf(value) { csrf = value; }
export function getCsrf() { return csrf; }
export async function refreshCsrf() {
  const data = await api('/api/csrf'); csrf = data.csrf_token;
}
export async function api(path, { method = 'GET', body, key, signal, blob = false } = {}) {
  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), 12000);
  const abort = () => timeout.abort();
  signal?.addEventListener('abort', abort, { once: true });
  if (signal?.aborted) timeout.abort();
  try {
    const headers = { 'Accept': blob ? 'text/csv' : 'application/json' };
    if (method !== 'GET') headers['X-CSRF-Token'] = csrf;
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (key) headers['Idempotency-Key'] = key;
    const res = await fetch(path, { method, headers, credentials: 'same-origin',
      body: body === undefined ? undefined : JSON.stringify(body), signal: timeout.signal });
    const isJson = res.headers.get('Content-Type')?.includes('application/json');
    const data = isJson ? await res.json() : null;
    if (!res.ok) {
      const error = data?.error;
      throw new ApiError(error?.message || 'Serviço indisponível. Tente novamente em instantes.', error?.code || 'SERVICE_ERROR', res.status, error?.fields, error?.request_id);
    }
    if (blob) {
      if (!res.headers.get('Content-Type')?.includes('text/csv')) throw new ApiError('Resposta inesperada ao exportar.', 'BAD_RESPONSE', 502);
      return res.blob();
    }
    if (!isJson) throw new ApiError('Não foi possível interpretar a resposta. Tente novamente.', 'BAD_RESPONSE', 502);
    return data;
  } catch (error) {
    if (signal?.aborted) throw new DOMException('Requisição substituída', 'AbortError');
    if (error instanceof ApiError) throw error;
    throw new ApiError('Não foi possível conectar. Seu preenchimento foi mantido.', 'NETWORK_ERROR', 0);
  } finally {
    clearTimeout(timer); signal?.removeEventListener('abort', abort);
  }
}
