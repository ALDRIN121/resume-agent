const API_BASE = import.meta.env?.VITE_API_BASE || "";

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
    const error = new Error(Array.isArray(detail) ? detail.map(d => d.msg).join(", ") : typeof detail === "string" ? detail : JSON.stringify(detail));
    error.status = response.status;
    throw error;
  }
  if (response.status === 204) return null;
  return response.json();
}

export const createRun = ({ jdText, jdUrl, jdFileId, jobLocation, workMode, maxPages } = {}) => request("/api/runs", {
  method: "POST",
  body: JSON.stringify({ jd_text: jdText, jd_url: jdUrl, jd_file_id: jdFileId, job_location: jobLocation, work_mode: workMode, max_pages: maxPages }),
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
  body: JSON.stringify(typeof kind === "object" ? kind : { kind, ...payload }),
});
export const cancelRun = (threadId) => request(`/api/runs/${threadId}/cancel`, { method: "POST" });

export const uploadResume = (file) => {
  const body = new FormData();
  body.append("file", file);
  return request("/api/resume/upload", { method: "POST", body });
};

export const getResume = () => request("/api/resume");
export const getResumeRaw = () => fetch(`${API_BASE}/api/resume/raw`).then(r => r.ok ? r.text() : Promise.reject(new Error(r.statusText)));
export const updateResume = (resume, expectedRevision) => request("/api/resume", {
  method: "PUT",
  headers: expectedRevision ? { "If-Match": expectedRevision } : {},
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
export const detectProviders = () => request("/api/settings/detect");
export const exchangeOpenRouter = ({ code, codeVerifier }) => request("/api/auth/openrouter/exchange", {
  method: "POST",
  body: JSON.stringify({ code, code_verifier: codeVerifier }),
});

export const pdfUrl = (threadId) => `${API_BASE}/api/runs/${threadId}/pdf`;

export const downloadPdf = (threadId) => {
  const link = document.createElement("a");
  link.href = pdfUrl(threadId);
  link.download = "";
  document.body.appendChild(link);
  link.click();
  link.remove();
};

// ── Résumé library (companies + filed resumes, persisted in library.sqlite) ──
export const listCompanies = () => request("/api/library/companies");
export const listLibraryResumes = (company) =>
  request(`/api/library/resumes${company ? `?company=${encodeURIComponent(company)}` : ""}`);
export const deleteLibraryResume = (threadId) =>
  request(`/api/library/resumes/${threadId}`, { method: "DELETE" });

export const getReadiness = () => request("/api/readiness");
export const getProfile = () => request("/api/profile");
export const reviewProfile = expected_revision => request("/api/profile/review", {method:"POST",body:JSON.stringify({expected_revision})});
export const getImport = id => request(`/api/profile/imports/${encodeURIComponent(id)}`);
export const importSourceUrl = id => `${API_BASE}/api/profile/imports/${encodeURIComponent(id)}/source`;
export const decideImport = (id, decision, action) => request(`/api/profile/imports/${encodeURIComponent(id)}/${decision}`, {method:"POST",body:JSON.stringify(action)});
export const contentPreview = (id, body) => request(`/api/runs/${id}/content-preview`, {method:"POST",body:JSON.stringify(body)});
export const previewUrl = id => `${API_BASE}/api/runs/${id}/preview`;
export const reexportRun = async (id, body) => {
  await request(`/api/runs/${id}/reexport`, {method:"POST",body:JSON.stringify(body)});
  return getRun(id);
};
export const recoverRun = id => request(`/api/runs/${id}/recover`, {method:"POST"});
