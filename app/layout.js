import './globals.css';
import { Inter } from 'next/font/google';
import Nav from './nav';

/* Tabler is set in Inter throughout. The font was Ubuntu; --font-ubuntu is
   still defined in globals.css, aliased onto this stack, because a handful of
   inline styles across the pages read it directly. */
const inter = Inter({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-inter',
  display: 'swap',
});

export const metadata = {
  title: 'HMIS Report Compiler — Jinja Regional Referral Hospital',
  description: 'Compilation and submission of eHMIS 105 (OPD) and 108 (IPD) monthly reports to the Uganda National DHIS2.',
  icons: {
    icon: '/favicon.ico',
    apple: '/logo.png',
  },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en-GB" className={inter.variable}>
      <body>
        <div className="shell">
          <Nav />
          <main>{children}</main>
          <div className="footer">
            HMIS Report Compiler · Jinja Regional Referral Hospital · Republic of Uganda Ministry of Health eHMIS
          </div>
        </div>
      </body>
    </html>
  );
}
