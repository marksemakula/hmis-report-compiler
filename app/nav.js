'use client';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  IconDashboard, IconUpload, IconTerminal, IconEye,
  IconReport, IconHistory, IconSettings, IconLogout,
} from './icons';

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

  /* The Dashboard is the landing page for every role. Preview, Reports and the
     Audit Trail are read-only and open to Viewers as they always were; Compile
     and the extraction scripts are Data Officer tools, and until the role is
     known nothing role-gated is drawn, so a Viewer never sees a Compile link
     flash and disappear. */
  const links = [
    { href: '/', label: 'Dashboard', Icon: IconDashboard },
    { href: '/preview', label: 'Preview', Icon: IconEye },
    { href: '/reports', label: 'Reports', Icon: IconReport },
    { href: '/audit', label: 'Audit Trail', Icon: IconHistory },
  ];
  if (user && user.role !== 'viewer') {
    links.splice(1, 0,
      { href: '/compile', label: 'Compile', Icon: IconUpload },
      { href: '/extract', label: 'Extraction Scripts', Icon: IconTerminal });
  }
  if (user?.role === 'admin') links.push({ href: '/admin', label: 'Administration', Icon: IconSettings });

  const initials = (user?.name || user?.email || '?')
    .split(/[\s@._-]+/).filter(Boolean).slice(0, 2).map((s) => s[0]).join('').toUpperCase();

  return (
    <>
      <header className="navbar">
        <div className="container-xl">
          <Link href="/" className="navbar-brand">
            <img src="/logo.png" alt="Jinja Regional Referral Hospital" />
            <span>
              HMIS Report Compiler
              <small>Jinja Regional Referral Hospital</small>
            </span>
          </Link>
          {user && (
            <div className="navbar-user">
              <div className="navbar-user-meta">
                <strong>{user.name || user.email}</strong>
                <span>{String(user.role || '').replace('_', ' ')}</span>
              </div>
              <span className="avatar sm" aria-hidden="true">{initials}</span>
              <button type="button" className="btn ghost sm" onClick={logout} title="Sign out">
                <IconLogout size={16} />
                Sign out
              </button>
            </div>
          )}
        </div>
      </header>

      <div className="navbar-secondary">
        <div className="container-xl">
          <nav className="navbar-nav" aria-label="Main">
            {links.map(({ href, label, Icon }) => (
              <Link
                key={href}
                href={href}
                className={`nav-link ${pathname === href ? 'active' : ''}`}
                aria-current={pathname === href ? 'page' : undefined}
              >
                <Icon size={18} />
                {label}
              </Link>
            ))}
          </nav>
        </div>
      </div>
    </>
  );
}
