'use client';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import Link from 'next/link';

export default function Nav() {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState(null);

  useEffect(() => {
    fetch('/api/py/auth/me')
      .then((r) => (r.ok ? r.json() : null))
      .then(setUser)
      .catch(() => setUser(null));
  }, [pathname]);

  if (pathname === '/login') return null;

  const logout = async () => {
    await fetch('/api/py/auth/logout', { method: 'POST' });
    router.push('/login');
  };

  const links = [
    { href: '/', label: 'Compile' },
    { href: '/reports', label: 'Reports' },
    { href: '/audit', label: 'Audit Trail' },
  ];
  if (user?.role === 'admin') links.push({ href: '/admin', label: 'Administration' });

  return (
    <header className="topbar">
      <div className="brand">
        HMIS Report Compiler
        <small>Jinja Regional Referral Hospital</small>
      </div>
      <nav>
        {links.map((l) => (
          <Link key={l.href} href={l.href} className={pathname === l.href ? 'active' : ''}>
            {l.label}
          </Link>
        ))}
      </nav>
      {user && (
        <span className="user">
          {user.email} · {String(user.role || '').replace('_', ' ')}{' '}
          <a style={{ color: '#dbe5ee', marginLeft: 8, cursor: 'pointer' }} onClick={logout}>
            Sign out
          </a>
        </span>
      )}
    </header>
  );
}
