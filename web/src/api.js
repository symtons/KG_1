const BASE = "http://127.0.0.1:8000";

async function getJSON(path) {
  const res = await fetch(BASE + path);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

export const api = {
  stats: () => getJSON("/api/stats"),
  candidates: (limit = 100, offset = 0) =>
    getJSON(`/api/candidates?limit=${limit}&offset=${offset}`),
  candidateDetail: (a, c) =>
    getJSON(`/api/candidates/${encodeURIComponent(a)}/${encodeURIComponent(c)}`),
  bridgeGraph: (a, c) =>
    getJSON(`/api/graph/bridge?a=${encodeURIComponent(a)}&c=${encodeURIComponent(c)}`),
  entity: (id) => getJSON(`/api/entity/${encodeURIComponent(id)}`),
};
