const API_BASE = import.meta.env.VITE_API_BASE || "";

async function request(path, options = {}) {
  const headers = options.body instanceof FormData
    ? options.headers || {}
    : { "Content-Type": "application/json", ...(options.headers || {}) };
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = await response.json();
      detail = data.detail || detail;
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new Error(Array.isArray(detail) ? detail.map(d => d.msg).join(", ") : detail);
  }
  if (response.status === 204) return null;
  return response.json();
}

export const createRun = ({ jdText, jdUrl, jdFileId } = {}) => request("/api/runs", {
  method: "POST",
  body: JSON.stringify({ jd_text: jdText, jd_url: jdUrl, jd_file_id: jdFileId }),
});

export const uploadJdFile = (file) => {
  const body = new FormData();
  body.append("file", file);
  return request("/api/runs/jd-file", { method: "POST", body });
};

export const listRuns = () => request("/api/runs");
export const getRun = (threadId) => request(`/api/runs/${threadId}`);
export const resumeRun = (threadId, kind, payload) => request(`/api/runs/${threadId}/resume`, {
  method: "POST",
  body: JSON.stringify({ kind, payload }),
});
export const cancelRun = (threadId) => request(`/api/runs/${threadId}/cancel`, { method: "POST" });

export const uploadResume = (file) => {
  const body = new FormData();
  body.append("file", file);
  return request("/api/resume/upload", { method: "POST", body });
};

export const getResume = () => request("/api/resume");
export const getResumeRaw = () => fetch(`${API_BASE}/api/resume/raw`).then(r => r.ok ? r.text() : Promise.reject(new Error(r.statusText)));
export const updateResume = (resume) => request("/api/resume", {
  method: "PUT",
  body: JSON.stringify(resume),
});

export const getSettings = () => request("/api/settings");
export const updateSettings = (settings) => request("/api/settings", {
  method: "PUT",
  body: JSON.stringify(settings),
});
export const getProviders = () => request("/api/settings/providers");
export const testConnection = (settings) => request("/api/settings/test-connection", {
  method: "POST",
  body: JSON.stringify(settings),
});
export const runDoctor = () => request("/api/settings/doctor", { method: "POST" });

export const pdfUrl = (threadId) => `${API_BASE}/api/runs/${threadId}/pdf`;

// ── Résumé library (companies + filed resumes, persisted in library.sqlite) ──
export const listCompanies = () => request("/api/library/companies");
export const listLibraryResumes = (company) =>
  request(`/api/library/resumes${company ? `?company=${encodeURIComponent(company)}` : ""}`);
export const deleteLibraryResume = (threadId) =>
  request(`/api/library/resumes/${threadId}`, { method: "DELETE" });
