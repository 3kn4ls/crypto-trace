// Thin fetch wrapper around the backend API.
const BASE = "/api";

async function handle(res: Response) {
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

export const api = {
  get: (path: string) => fetch(`${BASE}${path}`).then(handle),
  post: (path: string, body?: unknown) =>
    fetch(`${BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then(handle),
  upload: (path: string, form: FormData) =>
    fetch(`${BASE}${path}`, { method: "POST", body: form }).then(handle),
};
