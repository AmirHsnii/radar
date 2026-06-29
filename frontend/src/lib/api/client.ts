import axios from "axios";
import { clearToken, getToken } from "../auth";

// Collection roots registered as "/" on backend — must end with slash.
const COLLECTION_ROOT = /^\/(news|sources|dlq|settings)$/;

// در Docker: VITE_API_BASE_URL="" → BASE="/api/v1" (Vite به backend proxy می‌کند)
// در dev:    VITE_API_BASE_URL نداشته باشه → fallback به localhost:8000
const envBase = import.meta.env.VITE_API_BASE_URL as string | undefined;
const BASE =
  envBase === undefined || envBase === ""
    ? "/api/v1"
    : `${envBase.replace(/\/$/, "")}/api/v1`;

function normalizeApiPath(url: string | undefined): string | undefined {
  if (!url) return url;
  const qIndex = url.indexOf("?");
  const path = qIndex === -1 ? url : url.slice(0, qIndex);
  const query = qIndex === -1 ? "" : url.slice(qIndex);
  if (COLLECTION_ROOT.test(path)) {
    return `${path}/${query}`;
  }
  return url;
}

export const api = axios.create({
  baseURL: BASE,
  headers: { "Content-Type": "application/json" },
  timeout: 30_000,
});

api.interceptors.request.use((config) => {
  config.url = normalizeApiPath(config.url);
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  // FormData needs a multipart boundary — axios/browser set it only when
  // Content-Type is not forced (default application/json breaks uploads too).
  if (typeof FormData !== "undefined" && config.data instanceof FormData) {
    config.headers.delete("Content-Type");
  }
  return config;
});

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      clearToken();
      window.location.href = "/login";
      return Promise.reject(new Error("نشست منقضی شده. لطفاً دوباره وارد شوید."));
    }
    const msg =
      err.response?.data?.detail ??
      err.response?.data?.message ??
      err.message ??
      "خطای ناشناخته";
    return Promise.reject(new Error(typeof msg === "string" ? msg : JSON.stringify(msg)));
  },
);

export const publicApi = axios.create({
  baseURL: BASE,
  headers: { "Content-Type": "application/json" },
  timeout: 10_000,
});

publicApi.interceptors.request.use((config) => {
  config.url = normalizeApiPath(config.url);
  return config;
});
