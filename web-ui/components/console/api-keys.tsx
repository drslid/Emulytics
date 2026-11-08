"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiError, api } from '../../lib/client-api';
import type { User } from '../../lib/console-types';
import { useLocale } from '../../lib/i18n';
import { apiKeyText, type APIKeyCopy } from '../../lib/personal-api-i18n';
import { keyActive, selectedKeyScopes, type PersonalAPIKey, type PersonalAPIKeys } from '../../lib/personal-api';
import { Dialog, date } from './shared';

export function APIKeys({ user }: { user: User }) {
  const { locale } = useLocale();
  const text = (key: APIKeyCopy) => apiKeyText(locale, key);
  const [data, setData] = useState<PersonalAPIKeys | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [revoking, setRevoking] = useState<PersonalAPIKey | null>(null);
  const [busy, setBusy] = useState(false);
  const [address, setAddress] = useState('');
  const sequence = useRef(0);
  const load = useCallback(async () => {
    const current = ++sequence.current;
    setLoading(true); setError(false);
    try {
      const value = await api<PersonalAPIKeys>(`console/account/api-keys?limit=20&offset=${offset}`);
      if (current === sequence.current) setData(value);
    } catch { if (current === sequence.current) setError(true); }
    finally { if (current === sequence.current) setLoading(false); }
  }, [offset, user.id]);
  useEffect(() => { void load(); return () => { sequence.current += 1; }; }, [load]);
  useEffect(() => { setAddress(`${window.location.origin}/api/v1`); }, []);
  async function revoke() {
    if (!revoking || busy) return;
    setBusy(true); setError(false);
    try { await api(`console/account/api-keys/${revoking.id}`, {}, 'DELETE'); setRevoking(null); await load(); }
    catch { setError(true); }
    finally { setBusy(false); }
  }
  return <section className="surface tw:min-w-0 tw:p-5" aria-busy={loading}>
    <div className="tw:flex tw:flex-wrap tw:items-start tw:justify-between tw:gap-4">
      <div className="tw:min-w-0 tw:flex-1"><h2>{text('title')}</h2><p>{text('intro')}</p></div>
      <button className="button button--primary" onClick={() => setCreating(true)} disabled={!data}>{text('create')}</button>
    </div>
    <div className="tw:mt-4 tw:rounded-xl tw:bg-slate-50 tw:p-4"><code className="tw:break-all">{address}</code><p className="tw:mt-2 tw:text-sm">{text('instructions')}</p></div>
    {error && <div className="notice notice--error tw:mt-4" role="alert"><span>{text('failed')}</span><button className="button button--secondary" onClick={() => void load()} disabled={loading}>{text('retry')}</button></div>}
    {!data ? <p role="status" className="tw:mt-4">{loading ? text('loading') : text('failed')}</p> : <>
      {data.items.length === 0 ? <p className="tw:py-6">{text('empty')}</p> : <ul className="tw:mt-4 tw:grid tw:list-none tw:gap-3 tw:p-0">
        {data.items.map((key) => <li key={key.id} className="tw:min-w-0 tw:rounded-xl tw:border tw:border-slate-200 tw:p-4">
          <div className="tw:flex tw:flex-wrap tw:items-center tw:justify-between tw:gap-3"><div className="tw:min-w-0"><strong className="tw:break-words">{key.name}</strong><span className={`status-badge tw:ms-2 ${keyActive(key) ? 'status-badge--green' : 'status-badge--neutral'}`}>{key.revoked_at ? text('revoked') : keyActive(key) ? text('active') : text('expired')}</span></div>
            {keyActive(key) && <button className="button button--secondary" onClick={() => setRevoking(key)}>{text('revoke')}</button>}</div>
          <p className="tw:mt-2 tw:text-sm"><code>{key.token_prefix}…</code> · {text('validUntil')} {date(key.expires_at, locale)} · {text('lastUsed')} {key.last_used_at ? date(key.last_used_at, locale) : text('never')}</p>
          <details className="tw:mt-2 tw:text-sm"><summary className="tw:cursor-pointer">{text('scopes')}</summary><code className="tw:block tw:break-all tw:pt-2">{key.scopes.join(', ')}</code></details>
        </li>)}
      </ul>}
      {data.total > 20 && <nav className="tw:mt-4 tw:flex tw:flex-wrap tw:items-center tw:justify-between tw:gap-3" aria-label={text('title')}>
        <button className="button button--secondary" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - 20))}>{text('previous')}</button>
        <span>{offset + 1}–{offset + data.items.length} / {data.total}</span>
        <button className="button button--secondary" disabled={offset + data.items.length >= data.total || loading} onClick={() => setOffset(offset + 20)}>{text('next')}</button>
      </nav>}
    </>}
    {creating && data && <CreateKey key={user.id} permissions={data.available_scopes} onClose={() => { setCreating(false); void load(); }} />}
    {revoking && <Dialog title={`${text('revoke')} — ${revoking.name}`} description={text('revokeHelp')} onClose={() => { if (!busy) setRevoking(null); }}>
      {error && <p role="alert">{text('failed')}</p>}<div className="dialog-actions"><button className="button button--secondary" onClick={() => setRevoking(null)} disabled={busy}>{text('cancel')}</button><button className="button button--danger" onClick={() => void revoke()} disabled={busy}>{busy ? text('loading') : text('revoke')}</button></div>
    </Dialog>}
  </section>;
}

function CreateKey({ permissions, onClose }: { permissions: string[]; onClose: () => void }) {
  const { locale } = useLocale();
  const text = (key: APIKeyCopy) => apiKeyText(locale, key);
  const [name, setName] = useState('');
  const [purpose, setPurpose] = useState<'read' | 'run' | 'publish'>('read');
  const [days, setDays] = useState(90);
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [secret, setSecret] = useState('');
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<APIKeyCopy | null>(null);
  const [uncertain, setUncertain] = useState(false);
  const requestId = useRef(crypto.randomUUID());
  const submitting = useRef(false);
  function close() { if (!busy && (!secret || saved)) onClose(); }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (submitting.current || uncertain) return;
    submitting.current = true; setBusy(true); setError(null);
    try {
      const created = await api<{ secret: string }>('console/account/api-keys', {
        request_id: requestId.current, name, scopes: selectedKeyScopes(purpose, permissions), expires_days: days,
        current_password: password, code, recovery: false,
      });
      setSecret(created.secret);
    } catch (failure) {
      const status = failure instanceof ApiError ? failure.status : 503;
      const unknown = status === 0 || status >= 500 || status === 409;
      setUncertain(unknown); setError(unknown ? 'uncertain' : 'rejected');
    } finally { setPassword(''); setCode(''); setBusy(false); submitting.current = false; }
  }
  async function copySecret() { try { await navigator.clipboard.writeText(secret); setCopied(true); } catch { setCopied(false); } }
  return <Dialog title={text('create')} description={secret ? text('once') : text('intro')} onClose={close}>
    {secret ? <div className="tw:grid tw:gap-4"><input className="tw:w-full tw:min-w-0 tw:font-mono" aria-label={text('title')} readOnly value={secret} dir="ltr" onFocus={(event) => event.currentTarget.select()} />
      <button className="button button--secondary" onClick={() => void copySecret()}>{copied ? text('copied') : text('copy')}</button>
      <label className="tw:flex tw:items-start tw:gap-2"><input type="checkbox" checked={saved} onChange={(event) => setSaved(event.target.checked)} />{text('saved')}</label>
      <div className="dialog-actions"><button className="button button--primary" disabled={!saved} onClick={close}>{text('close')}</button></div>
    </div> : <form onSubmit={(event) => void submit(event)} className="tw:grid tw:gap-4">
      {error && <div className="notice notice--error" role="alert">{text(error)}</div>}
      <fieldset className="tw:grid tw:min-w-0 tw:gap-4 tw:border-0 tw:p-0" disabled={busy || uncertain}>
        <label>{text('name')}<input required maxLength={80} value={name} onChange={(event) => setName(event.target.value)} autoComplete="off" /></label>
        <label>{text('purpose')}<select value={purpose} onChange={(event) => setPurpose(event.target.value as typeof purpose)}>
          <option value="read">{text('read')}</option>
          {permissions.includes('runs.execute') && <option value="run">{text('run')}</option>}
          {permissions.includes('workflows.publish') && <option value="publish">{text('publish')}</option>}
        </select></label>
        <details><summary className="tw:cursor-pointer">{text('scopes')}</summary><code className="tw:mt-2 tw:block tw:break-all">{selectedKeyScopes(purpose, permissions).join(', ')}</code></details>
        <label>{text('expires')}<select value={days} onChange={(event) => setDays(Number(event.target.value))}>{[7, 30, 90, 365].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
        <label>{text('password')}<input required type="password" autoComplete="current-password" maxLength={1024} value={password} onChange={(event) => setPassword(event.target.value)} /></label>
        <label>{text('code')}<input required inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))} dir="ltr" /></label>
      </fieldset>
      <div className="dialog-actions"><button type="button" className="button button--secondary" onClick={close} disabled={busy}>{text(uncertain ? 'close' : 'cancel')}</button><button className="button button--primary" type="submit" disabled={busy || uncertain || !name.trim()}>{text(busy ? 'loading' : 'create')}</button></div>
    </form>}
  </Dialog>;
}
