import './globals.css';
import { Ubuntu } from 'next/font/google';
import Nav from './nav';

const ubuntu = Ubuntu({ subsets: ['latin'], weight: ['300', '400', '500', '700'], variable: '--font-ubuntu' });

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
    <html lang="en-GB" className={ubuntu.variable}>
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
