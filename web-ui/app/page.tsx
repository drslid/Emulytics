"use client";

import { ChangeEvent, useEffect, useState } from "react";

type Message = {
  id: string;
  role: "assistant" | "user";
  content: string;
};

type RuntimeStatus = {
  available: boolean;
  container_name: string;
  container_exists: boolean;
  running: boolean;
  status: string;
  reason: string | null;
  embed_url: string | null;
  stream_provider?: string | null;
  visual_available?: boolean;
};

type UploadedApk = {
  name: string;
  size: number;
  updated_at: string;
  path: string;
};

type SessionStatus = {
  session: {
    id: string;
    name: string;
    status: string;
    selected_model?: string | null;
  };
  runtime: RuntimeStatus;
  uploaded_apks: UploadedApk[];
  installed_packages: string[];
  package_error: string | null;
};

type ModelOption = {
  id: string;
  label: string;
  tier: string;
  default: boolean;
  reasoning: string;
};

const DEFAULT_API_URL = process.env.NEXT_PUBLIC_ORCHESTRATOR_API_URL ?? "http://localhost:8010";

function rewriteUrlForBrowser(rawUrl: string): string {
  if (typeof window === "undefined") {
    return rawUrl;
  }

  try {
    const parsed = new URL(rawUrl);
    if (["localhost", "127.0.0.1", "android-runtime"].includes(parsed.hostname)) {
      parsed.hostname = window.location.hostname;
    }
    return parsed.toString();
  } catch {
    return rawUrl;
  }
}

function runtimeEmbedUrl(runtime: RuntimeStatus | null): string | null {
  if (!runtime?.embed_url) {
    return null;
  }

  return rewriteUrlForBrowser(runtime.embed_url);
}

export default function Page() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "m-1",
      role: "assistant",
      content:
        "Le viewport Android est vide tant que le runtime n'est pas lancé. Ici, je te montre l'état réel du runtime et je peux préparer les actions APK / packages / chat OpenAI."
    }
  ]);
  const [status, setStatus] = useState("Bootstrapping session...");
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [uploadedApks, setUploadedApks] = useState<UploadedApk[]>([]);
  const [installedPackages, setInstalledPackages] = useState<string[]>([]);
  const [packageError, setPackageError] = useState<string | null>(null);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [selectedModel, setSelectedModel] = useState("gpt-5.4");
  const [reasoningEffort, setReasoningEffort] = useState("medium");
  const [openAiApiKey, setOpenAiApiKey] = useState("");
  const [apkFile, setApkFile] = useState<File | null>(null);
  const [packageToRemove, setPackageToRemove] = useState("");
  const [busy, setBusy] = useState(false);

  const apiUrl = rewriteUrlForBrowser(DEFAULT_API_URL);
  const embedUrl = runtimeEmbedUrl(runtime);

  useEffect(() => {
    let mounted = true;

    async function bootstrap() {
      try {
        const created = await fetch(`${apiUrl}/sessions`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: "Demo session" })
        });
        const session = await created.json();
        if (!mounted) {
          return;
        }

        setSessionId(session.id);
        setStatus("Session created. Refreshing runtime and AI status...");

        const [statusData, modelsData] = await Promise.all([
          fetch(`${apiUrl}/sessions/${session.id}/status`).then((response) => response.json()),
          fetch(`${apiUrl}/ai/models`).then((response) => response.json())
        ]);

        if (!mounted) {
          return;
        }

        applySessionStatus(statusData);
        applyModels(modelsData);
      } catch {
        if (mounted) {
          setStatus("API unavailable. The UI is running, but Emulytix services are not reachable.");
        }
      }
    }

    void bootstrap();
    return () => {
      mounted = false;
    };
  }, []);

  function applySessionStatus(data: SessionStatus) {
    setRuntime(data.runtime);
    setUploadedApks(data.uploaded_apks ?? []);
    setInstalledPackages(data.installed_packages ?? []);
    setPackageError(data.package_error ?? null);

    if (data.runtime?.available) {
      setStatus("Android runtime is online. Viewport and ADB actions are available.");
    } else if (data.runtime?.visual_available) {
      setStatus("Android visual stream is online. ADB is still booting.");
    } else {
      setStatus(data.runtime?.reason ?? "Android runtime is offline.");
    }
  }

  function applyModels(data: { default_model?: string; models?: ModelOption[]; configured?: boolean }) {
    const list = Array.isArray(data.models) ? data.models : [];
    setModels(list);
    if (data.default_model) {
      setSelectedModel(data.default_model);
    }

    if (!data.configured) {
      setMessages((current) => {
        const alreadyPresent = current.some((message) => message.id === "m-openai-warning");
        if (alreadyPresent) {
          return current;
        }
        return [
          ...current,
          {
            id: "m-openai-warning",
            role: "assistant",
            content:
              "Aucune clé OpenAI n'est configurée côté backend. Tu peux en saisir une temporairement dans l'interface pour activer le vrai planning OpenAI."
          }
        ];
      });
    }
  }

  async function refreshStatus(currentSessionId: string) {
    const response = await fetch(`${apiUrl}/sessions/${currentSessionId}/status`);
    const data = await response.json();
    applySessionStatus(data);
  }

  async function sendPrompt() {
    const prompt = input.trim();
    if (!prompt || !sessionId) {
      return;
    }

    setBusy(true);
    setMessages((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        role: "user",
        content: prompt
      }
    ]);
    setInput("");

    try {
      const response = await fetch(`${apiUrl}/sessions/${sessionId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt,
          model: selectedModel,
          reasoning_effort: reasoningEffort,
          execute: true,
          openai_api_key: openAiApiKey || null
        })
      });

      const data = await response.json();
      const summary = data?.plan?.summary ?? "No plan summary returned.";
      const provider = data?.plan?.provider ?? "unknown-provider";
      const executionSummary = Array.isArray(data?.execution)
        ? data.execution.map((item: { tool: string; status: string; detail: string }) => `${item.tool}: ${item.status}`).join(" | ")
        : "no execution";

      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: `${summary}\nProvider: ${provider}\nExecution: ${executionSummary}`
        }
      ]);

      await refreshStatus(sessionId);
    } catch {
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: "Le chat n'a pas pu joindre l'API Emulytix."
        }
      ]);
    } finally {
      setBusy(false);
    }
  }

  async function uploadApk() {
    if (!sessionId || !apkFile) {
      return;
    }

    setBusy(true);
    try {
      const formData = new FormData();
      formData.append("file", apkFile);

      await fetch(`${apiUrl}/sessions/${sessionId}/apk/upload`, {
        method: "POST",
        body: formData
      });

      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: `APK '${apkFile.name}' uploaded.`
        }
      ]);
      setApkFile(null);
      await refreshStatus(sessionId);
    } finally {
      setBusy(false);
    }
  }

  async function installLatestApk() {
    if (!sessionId) {
      return;
    }

    setBusy(true);
    try {
      const response = await fetch(`${apiUrl}/sessions/${sessionId}/apk/install`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({})
      });
      const data = await response.json();
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: data.detail ?? "APK install requested."
        }
      ]);
      await refreshStatus(sessionId);
    } finally {
      setBusy(false);
    }
  }

  async function uninstallPackage() {
    if (!sessionId || !packageToRemove.trim()) {
      return;
    }

    setBusy(true);
    try {
      const response = await fetch(`${apiUrl}/sessions/${sessionId}/device/uninstall-app`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ package_name: packageToRemove.trim() })
      });
      const data = await response.json();
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: data.detail ?? `Uninstall requested for ${packageToRemove.trim()}.`
        }
      ]);
      setPackageToRemove("");
      await refreshStatus(sessionId);
    } finally {
      setBusy(false);
    }
  }

  async function sendKey(keycode: string) {
    if (!sessionId) {
      return;
    }

    setBusy(true);
    try {
      const response = await fetch(`${apiUrl}/sessions/${sessionId}/device/key`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keycode })
      });
      const data = await response.json();
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: data.detail ?? `${keycode} sent.`
        }
      ]);
    } finally {
      setBusy(false);
    }
  }

  async function captureScreenshot() {
    if (!sessionId) {
      return;
    }

    setBusy(true);
    try {
      const response = await fetch(`${apiUrl}/sessions/${sessionId}/device/screenshot`, {
        method: "POST"
      });
      const data = await response.json();
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: data.detail ?? "Screenshot requested."
        }
      ]);
    } finally {
      setBusy(false);
    }
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setApkFile(file);
  }

  return (
    <main className="shell">
      <aside className="rail">
        <div className="brand">
          <span className="brand__eyebrow">Emulytix</span>
          <h1>Android operator workspace</h1>
          <p>{status}</p>
        </div>

        <div className="card">
          <span className="card__label">Session</span>
          <strong>{sessionId ?? "Pending"}</strong>
          <p>API: {apiUrl}</p>
        </div>

        <div className="card">
          <span className="card__label">Android runtime</span>
          <strong className={runtime?.available ? "ok" : "ko"}>{runtime?.available ? "Online" : "Offline"}</strong>
          <p>{runtime?.reason ?? "Runtime ready."}</p>
        </div>

        <div className="card">
          <span className="card__label">OpenAI</span>
          <label>
            Model
            <select value={selectedModel} onChange={(event) => setSelectedModel(event.target.value)}>
              {models.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.label} ({model.tier})
                </option>
              ))}
            </select>
          </label>
          <label>
            Reasoning
            <select value={reasoningEffort} onChange={(event) => setReasoningEffort(event.target.value)}>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
            </select>
          </label>
          <label>
            Temporary API key
            <input
              type="password"
              placeholder="sk-..."
              value={openAiApiKey}
              onChange={(event) => setOpenAiApiKey(event.target.value)}
            />
          </label>
        </div>

        <div className="card">
          <span className="card__label">APK</span>
          <input type="file" accept=".apk" onChange={onFileChange} />
          <button type="button" disabled={!apkFile || busy} onClick={uploadApk}>
            Upload APK
          </button>
          <button type="button" disabled={!uploadedApks.length || busy} onClick={installLatestApk}>
            Install latest APK
          </button>
        </div>

        <div className="card">
          <span className="card__label">Packages</span>
          <input
            type="text"
            placeholder="com.example.app"
            value={packageToRemove}
            onChange={(event) => setPackageToRemove(event.target.value)}
          />
          <button type="button" disabled={!packageToRemove || busy} onClick={uninstallPackage}>
            Uninstall package
          </button>
          {packageError ? <p>{packageError}</p> : null}
        </div>
      </aside>

      <section className="chat">
        <div className="chat__header">
          <h2>Mission control</h2>
          <span>Chat OpenAI vers plan d'action vers exécution Android</span>
        </div>

        <div className="chat__stream">
          <section className="chat__viewport">
            <div className="chat__viewport-header">
              <strong>Android live view</strong>
              <span>
                {runtime?.available || runtime?.visual_available
                  ? `Connected via ${runtime.stream_provider ?? "browser stream"}`
                  : "Runtime unavailable"}
              </span>
            </div>

            {embedUrl ? (
              <iframe className="chat__viewport-frame" src={embedUrl} title="Android runtime in chat" />
            ) : (
              <div className="chat__runtime-note">
                <strong>Vue Android indisponible</strong>
                <p>{runtime?.reason ?? "Le runtime Android n'est pas disponible."}</p>
              </div>
            )}
          </section>

          {messages.map((message) => (
            <article key={message.id} className={`bubble bubble--${message.role}`}>
              <span>{message.role === "assistant" ? "Assistant" : "You"}</span>
              <p>{message.content}</p>
            </article>
          ))}
        </div>

        <div className="composer">
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Exemple: installe le dernier APK, ouvre com.example.app, prends une capture, puis reviens à l'accueil."
          />
          <button type="button" disabled={busy || !sessionId} onClick={sendPrompt}>
            {busy ? "Working..." : "Send"}
          </button>
        </div>
      </section>

      <section className="device">
        <div className="device__header">
          <h2>Android controls</h2>
          <span>
            {runtime?.available
              ? "Runtime connected"
              : runtime?.visual_available
                ? "Visual stream connected"
                : "Runtime unavailable on this server"}
          </span>
        </div>

        <div className="device__meta">
          <div className="card">
            <span className="card__label">Uploaded APKs</span>
            {uploadedApks.length ? (
              uploadedApks.map((apk) => <p key={apk.name}>{apk.name}</p>)
            ) : (
              <p>No APK uploaded yet.</p>
            )}
          </div>
          <div className="card">
            <span className="card__label">Installed packages</span>
            {installedPackages.length ? (
              installedPackages.slice(0, 10).map((pkg) => <p key={pkg}>{pkg}</p>)
            ) : (
              <p>{packageError ?? "No package data available."}</p>
            )}
          </div>
        </div>

        <div className="device__footer">
          <button type="button" disabled={busy} onClick={() => void sendKey("KEYCODE_HOME")}>
            Home
          </button>
          <button type="button" disabled={busy} onClick={() => void sendKey("KEYCODE_BACK")}>
            Back
          </button>
          <button type="button" disabled={busy} onClick={() => void sendKey("KEYCODE_APP_SWITCH")}>
            Recent
          </button>
          <button type="button" disabled={busy} onClick={captureScreenshot}>
            Screenshot
          </button>
        </div>
      </section>
    </main>
  );
}
