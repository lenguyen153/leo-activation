const BASE = '/api';

export async function apiFetch(path, { body, method, ...rest } = {}) {
  const resolvedMethod = method ?? (body !== undefined ? 'POST' : 'GET');
  const res = await fetch(`${BASE}${path}`, {
    method: resolvedMethod,
    headers: { 'Content-Type': 'application/json' },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    ...rest,
  });
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status} ${msg}`);
  }
  return res.json();
}
