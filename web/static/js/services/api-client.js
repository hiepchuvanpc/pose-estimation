export class ApiClient {
  constructor(options = {}) {
    this.onSessionMissing = typeof options.onSessionMissing === "function"
      ? options.onSessionMissing
      : () => {};
    this.baseUrl = this.resolveBaseUrl(options.baseUrl);
  }

  resolveBaseUrl(explicitBaseUrl) {
    if (typeof explicitBaseUrl === "string" && explicitBaseUrl.trim()) {
      return explicitBaseUrl.replace(/\/$/, "");
    }

    // Support opening the UI directly from file:// or from a different host.
    if (window.location.protocol === "file:") {
      return "http://127.0.0.1:8000";
    }

    const host = String(window.location.hostname || "").toLowerCase();
    if (!host) {
      return "http://127.0.0.1:8000";
    }

    return "";
  }

  buildUrl(path) {
    const normalizedPath = String(path || "").startsWith("/") ? String(path) : `/${String(path || "")}`;
    return `${this.baseUrl}${normalizedPath}`;
  }

  isMissingWorkoutSessionError(payload) {
    if (!payload || typeof payload !== "object") {
      return false;
    }
    const detail = typeof payload.detail === "string" ? payload.detail.toLowerCase() : "";
    return detail.includes("workout session not found");
  }

  async request(path, method = "GET", body = null) {
    const options = { method, headers: { "Content-Type": "application/json" } };
    if (body) {
      options.body = JSON.stringify(body);
    }

    const res = await fetch(this.buildUrl(path), options);
    const txt = await res.text();
    let data = txt;
    try {
      data = JSON.parse(txt);
    } catch (_) {
      // Keep plain text payload as-is.
    }

    if (!res.ok) {
      if (this.isMissingWorkoutSessionError(data)) {
        this.onSessionMissing();
        throw new Error("Workout session da het hoac server da restart. Hay bam Start Workout Session de tao phien moi.");
      }
      throw new Error(typeof data === "string" ? data : JSON.stringify(data));
    }
    return data;
  }

  async uploadVideo(file) {
    const form = new FormData();
    form.append("video", file);
    const res = await fetch(this.buildUrl("/v1/library/upload-video"), { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(JSON.stringify(data));
    }
    return data;
  }
}
