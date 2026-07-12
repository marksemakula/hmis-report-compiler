'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

export default function Admin() {
  const router = useRouter();
  const [users, setUsers] = useState(null);
  const [meta, setMeta] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [form, setForm] = useState({ email: '', full_name: '', password: '', role: 'data_officer' });
  const [testResult, setTestResult] = useState(null);

  const load = () => {
    fetch('/api/py/users')
      .then(async (r) => {
        if (r.status === 401) return router.push('/login');
        const body = await r.json();
        if (!r.ok) throw new Error(body.detail || 'Access denied');
        setUsers(body.users);
      })
      .catch((e) => setError(e.message));
    fetch('/api/py/meta').then((r) => r.ok && r.json().then(setMeta));
  };
  useEffect(load, [router]);

  const createUser = async (e) => {
    e.preventDefault();
    setError(''); setNotice('');
    const r = await fetch('/api/py/users', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form),
    });
    const body = await r.json();
    if (!r.ok) return setError(body.detail || 'Could not create the user');
    setNotice('User account created.');
    setForm({ email: '', full_name: '', password: '', role: 'data_officer' });
    load();
  };

  const removeUser = async (id) => {
    if (!confirm('Delete this user account?')) return;
    await fetch(`/api/py/users/${id}`, { method: 'DELETE' });
    load();
  };

  const testDhis2 = async () => {
    setTestResult({ pending: true });
    const r = await fetch('/api/py/dhis2/test');
    const body = await r.json();
    setTestResult(r.ok ? body : { error: body.detail || 'Connection failed' });
  };

  return (
    <>
      <h1>Administration</h1>
      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert success">{notice}</div>}

      <div className="grid cols-2">
        <div className="card">
          <h2>System configuration</h2>
          {meta && (
            <table>
              <tbody>
                <tr><td>DHIS2 instance</td><td>{meta.instance}</td></tr>
                <tr><td>Facility</td><td>{meta.orgUnit.name} ({meta.orgUnit.id})</td></tr>
                <tr><td>105:01 data set</td><td>{meta.dataSets.HMIS105_01.id}</td></tr>
                <tr><td>108 data set</td><td>{meta.dataSets.HMIS108.id}</td></tr>
                <tr><td>Database</td><td><span className={`badge ${meta.db_configured ? 'ok' : 'bad'}`}>{meta.db_configured ? 'Configured' : 'Not configured'}</span></td></tr>
                <tr><td>DHIS2 credentials</td><td><span className={`badge ${meta.dhis2_configured ? 'ok' : 'bad'}`}>{meta.dhis2_configured ? 'Configured' : 'Not configured'}</span></td></tr>
              </tbody>
            </table>
          )}
          <div style={{ marginTop: 14 }}>
            <button className="btn secondary" onClick={testDhis2}>Test DHIS2 connection</button>
            {testResult?.pending && <span style={{ marginLeft: 10 }}>Testing…</span>}
            {testResult?.ok && <div className="alert success">Connected as {testResult.username}.</div>}
            {testResult?.error && <div className="alert error">{testResult.error}</div>}
          </div>
        </div>

        <div className="card">
          <h2>Create user account</h2>
          <form onSubmit={createUser}>
            <label>Email address</label>
            <input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            <div style={{ height: 10 }} />
            <label>Full name</label>
            <input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
            <div style={{ height: 10 }} />
            <label>Password (minimum 8 characters)</label>
            <input type="password" required minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
            <div style={{ height: 10 }} />
            <label>Role</label>
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              <option value="admin">System Admin</option>
              <option value="data_officer">Data Officer</option>
              <option value="viewer">Supervisor (Viewer)</option>
            </select>
            <div style={{ marginTop: 14 }}>
              <button className="btn">Create user</button>
            </div>
          </form>
        </div>
      </div>

      <div className="card">
        <h2>User accounts</h2>
        {!users ? 'Loading…' : (
          <table>
            <thead><tr><th>Email</th><th>Name</th><th>Role</th><th>Created</th><th /></tr></thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>{u.email}</td>
                  <td>{u.full_name}</td>
                  <td><span className="badge muted">{u.role.replace('_', ' ')}</span></td>
                  <td>{new Date(u.created_at).toLocaleDateString('en-GB')}</td>
                  <td><a style={{ color: 'var(--bad)', cursor: 'pointer' }} onClick={() => removeUser(u.id)}>Delete</a></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
