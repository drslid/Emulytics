"use client";

import { useState, type FormEvent } from "react";
import { api } from "../../lib/client-api";
import type { User } from "../../lib/console-types";
import { ErrorNotice } from "./shared";
import { Icon } from "./icons";

type Step = "credentials" | "enroll" | "verify" | "recovery" | "codes";
type Enrollment = { secret: string; otpauth_uri: string };
export function LoginForm() {
  const [step, setStep] = useState<Step>("credentials");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  const [code, setCode] = useState("");
  const [enrollment, setEnrollment] = useState<Enrollment | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const headings: Record<Step, { title: string; copy: string }> = {
    credentials: { title: "Bienvenue dans votre tour de contrôle", copy: "Connectez-vous pour retrouver vos téléphones et vos automatisations." },
    enroll: { title: "Protégez votre compte", copy: "Ajoutez Emulytix à votre application d’authentification." },
    verify: { title: "Confirmez votre identité", copy: "Saisissez le code affiché dans votre application d’authentification." },
    recovery: { title: "Utiliser un code de secours", copy: "Saisissez un code conservé lors de l’activation. Il ne pourra servir qu’une fois." },
    codes: { title: "Gardez une porte de secours", copy: "Conservez ces codes avant de continuer. Ils ne seront affichés qu’une fois." }
  };
  async function getEnrollment() {
    setEnrollment(await api<Enrollment>("auth/enrollment"));
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      if (step === "credentials") {
        const result = await api<{ step: "enroll" | "verify" }>("auth/login", { username: username.trim(), password });
        setPassword(""); setCode(""); setStep(result.step);
        if (result.step === "enroll") await getEnrollment();
      } else {
        const result = await api<{ user: User; recovery_codes?: string[] }>(step === "recovery" ? "auth/recovery" : "auth/verify", { code });
        setCode(""); setEnrollment(null);
        if (result.recovery_codes?.length) { setRecoveryCodes(result.recovery_codes); setStep("codes"); }
        else window.location.assign("/");
      }
    } catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }
  function downloadCodes() {
    const file = new Blob([`Emulytix — codes de secours\nCompte : ${username}\nChaque code est à usage unique.\n\n${recoveryCodes.join("\n")}\n`], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(file);
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = "emulytix-codes-de-secours.txt"; anchor.click(); URL.revokeObjectURL(url);
  }
  function back() { setStep("credentials"); setPassword(""); setCode(""); setEnrollment(null); setError(""); }
  return <main className="login-page"><a className="login-brand" href="/connexion" aria-label="Emulytix, connexion"><span className="brand-mark"><Icon name="overview" size={23} /></span>Emulytix</a><section className="login-card" aria-labelledby="login-title"><div className="login-intro"><span className="login-symbol"><Icon name={step === "credentials" ? "phone" : "shield"} size={34} /></span><span className="eyebrow">{step === "credentials" ? "Votre espace opérateur" : step === "codes" ? "Dernière étape" : "Validation en deux étapes"}</span><h1 id="login-title">{headings[step].title}</h1><p>{headings[step].copy}</p>{step !== "credentials" && <span className="account-chip"><span className="avatar avatar--small">{username.slice(0, 1).toUpperCase()}</span>{username}</span>}<div className="login-security-note"><Icon name="shield" size={18} /><span>Mot de passe + application d’authentification</span></div></div><div className="login-form-side">
    {error && <ErrorNotice message={error} />}
    {step === "codes" ? <div className="recovery-codes-screen"><div className="recovery-code-grid">{recoveryCodes.map((item) => <code key={item}>{item}</code>)}</div><button className="button button--secondary" onClick={downloadCodes}>Télécharger les codes</button><label className="checkbox-label"><input type="checkbox" checked={saved} onChange={(event) => setSaved(event.target.checked)} /><span>J’ai conservé mes codes dans un endroit sûr.</span></label><button className="button button--primary" disabled={!saved} onClick={() => { setRecoveryCodes([]); window.location.assign("/"); }}>Ouvrir la console<Icon name="arrow" size={18} /></button></div> : <form onSubmit={submit} className="login-form">
      {step === "credentials" ? <><label>Identifiant<input name="username" value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" autoFocus required maxLength={64} placeholder="Votre identifiant" /></label><label>Mot de passe<div className="password-field"><input name="password" type={visible ? "text" : "password"} value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required maxLength={1024} /><button type="button" className="password-toggle" onClick={() => setVisible(!visible)} aria-label={visible ? "Masquer le mot de passe" : "Afficher le mot de passe"} aria-pressed={visible}>{visible ? "Masquer" : "Afficher"}</button></div></label><button className="button button--primary login-submit" disabled={busy}>{busy ? "Vérification…" : "Continuer"}<Icon name="arrow" size={18} /></button><p className="login-help">Votre compte est créé par l’administrateur de l’installation.</p></> : <>
        {step === "enroll" && <div className="enrollment-block"><p><strong>1.</strong> Dans Google Authenticator, 2FAS ou une application compatible, choisissez « Ajouter un compte » et scannez ce QR code.</p>{enrollment ? <><img className="enrollment-qr" src="/api/control/auth/enrollment/qr" alt="QR code pour ajouter votre compte Emulytix à une application d’authentification" width={180} height={180} /><details className="manual-secret"><summary>Je ne peux pas scanner le QR code</summary><p>Ajoutez un compte à code temporel (TOTP) et saisissez cette clé :</p><code>{enrollment.secret}</code><button type="button" className="text-button" onClick={async () => { try { await navigator.clipboard.writeText(enrollment.secret); setCopied(true); } catch { setError("La copie n’est pas disponible. Recopiez la clé affichée."); } }}>{copied ? "Clé copiée" : "Copier la clé"}</button></details></> : <button type="button" className="button button--secondary" onClick={() => void getEnrollment().catch((failure) => setError((failure as Error).message))}>Recharger le QR code</button>}<p><strong>2.</strong> Saisissez le code pour terminer l’activation.</p></div>}
        <label>{step === "recovery" ? "Code de secours" : "Code à 6 chiffres"}<input name="code" className={step === "recovery" ? "recovery-input" : "otp-input"} value={code} onChange={(event) => setCode(step === "recovery" ? event.target.value : event.target.value.replace(/\D/g, "").slice(0, 6))} autoComplete="one-time-code" inputMode={step === "recovery" ? "text" : "numeric"} pattern={step === "recovery" ? undefined : "[0-9]{6}"} maxLength={step === "recovery" ? 128 : 6} required autoFocus placeholder={step === "recovery" ? "Votre code de secours" : "000000"} /><span>{step === "recovery" ? "Un code ne peut être utilisé qu’une seule fois." : "Le code change régulièrement dans votre application."}</span></label>
        <button className="button button--primary login-submit" disabled={busy || (step === "enroll" && !enrollment)}>{busy ? "Vérification…" : step === "enroll" ? "Activer et continuer" : "Ouvrir la console"}<Icon name="arrow" size={18} /></button>
        {step === "verify" && <button type="button" className="text-button" onClick={() => { setStep("recovery"); setCode(""); setError(""); }}>Utiliser un code de secours</button>}{step === "recovery" && <button type="button" className="text-button" onClick={() => { setStep("verify"); setCode(""); setError(""); }}>Utiliser mon application d’authentification</button>}<button type="button" className="text-button login-back" disabled={busy} onClick={back}>← Revenir à la connexion</button>
      </>}
    </form>}
  </div></section><footer className="login-footer">Emulytix · Console de gestion Android</footer></main>;
}
