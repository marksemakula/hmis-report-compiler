'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

export default function Audit() {
  const router = useRouter();
  const [entries, setEntries] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    fetch('/api/py/audit')
      .then(async (r) => {
        if (r.status === 401) return router.push('/login');
        const body = await r.json();
        if (!r.ok) throw new Error(body.detail || 'Could not load the audit trail');
        setEntries(body.entries);
      })
      .catch((e) => setError(e.message));
  }, [router]);

  return (
    <>
      <h1>Audit Trail</h1>
      {error && <div className="alert error">{error}</div>}
      <div className="card">
        {!entries ? 'Loading…' : entries.length === 0 ? 'No activity has been recorded yet.' : (
          <table>
            <thead><tr><th>When</th><th>User</th><th>Action</th><th>Details</th></tr></thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id}>
                  <td style={{ whiteSpace: 'nowrap' }}>{new Date(e.timestamp).toLocaleString('en-GB')}</td>
                  <td>{e.user}</td>
                  <td>{e.action}</td>
                  <td style={{ fontSize: '.8rem', color: 'var(--muted)' }}>{JSON.stringify(e.details)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
