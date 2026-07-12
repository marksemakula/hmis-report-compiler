import './globals.css';
import { Urbanist } from 'next/font/google';
import Nav from './nav';

const urbanist = Urbanist({ subsets: ['latin'], variable: '--font-urbanist' });

export const metadata = {
  title: 'HMIS Report Compiler — Jinja Regional Referral Hospital',
  description: 'Compilation and submission of eHMIS 105 (OPD) and 108 (IPD) monthly reports to the Uganda National DHIS2.',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en-GB" className={urbanist.variable}>
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
