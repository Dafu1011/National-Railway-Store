export type ApiErrorPayload = {
  code: string;
  message: string;
  details: Record<string, unknown>;
  request_id: string;
};

type RequestOptions = {
  token?: string;
};

type FetchOptions = RequestInit & RequestOptions;

export async function apiGet<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    credentials: "include",
    headers: makeHeaders(options.token),
  });
  return parseJson<T>(response);
}

export async function apiPost<T>(path: string, body?: unknown, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    method: "POST",
    credentials: "include",
    headers: makeHeaders(options.token, true),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return parseJson<T>(response);
}

export async function apiDownload(path: string, options: RequestOptions = {}): Promise<Blob> {
  const response = await fetch(`/api/v1${path}`, {
    credentials: "include",
    headers: makeHeaders(options.token),
  });
  if (!response.ok) {
    await throwApiError(response);
  }
  return await response.blob();
}

export async function apiPutRaw(uploadUrl: string, body: Blob, headers: HeadersInit = {}): Promise<void> {
  const response = await fetch(uploadUrl, {
    method: "PUT",
    credentials: "include",
    headers,
    body,
  });
  if (!response.ok) {
    await throwApiError(response);
  }
}

async function parseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    await throwApiError(response);
  }
  return (await response.json()) as T;
}

async function throwApiError(response: Response): Promise<never> {
  const text = await response.text();
  let payload: ApiErrorPayload | { detail?: { code?: string; message?: string } } | null = null;
  if (text.trim()) {
    try {
      payload = JSON.parse(text) as ApiErrorPayload | { detail?: { code?: string; message?: string } };
    } catch {
      throw new Error(`HTTP_${response.status}: ${text}`);
    }
  }
  if (!payload) {
    throw new Error(`HTTP_${response.status}: ${response.statusText || "Request failed"}`);
  }
  if ("detail" in payload && payload.detail?.code) {
    throw new Error(`${payload.detail.code}: ${payload.detail.message}`);
  }
  if ("code" in payload) {
    throw new Error(`${payload.code}: ${payload.message}`);
  }
  throw new Error(`HTTP_${response.status}`);
}

function makeHeaders(token?: string, json = false): HeadersInit {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (json) {
    headers["Content-Type"] = "application/json; charset=utf-8";
  }
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}
