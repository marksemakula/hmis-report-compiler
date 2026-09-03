import './globals.css';
import { Ubuntu } from 'next/font/google';
import Nav from './nav';

/* Ubuntu, which is what this application has always been set in. Tabler's own
   stack is Inter; only the typeface differs, and globals.css reads
   --font-ubuntu as the head of --tblr-font-sans-serif so nothing else has to
   know which face is loaded.

   Ubuntu ships 300/400/500/700 and has no 600, so the headings weight is
   declared as 700 in globals.css rather than Tabler's 600 - CSS font matching
   would resolve 600 to 700 anyway, and saying so is better than leaving a
   weight that only renders correctly by accident. */
const ubuntu = Ubuntu({
  subsets: ['latin'],
  weight: ['300', '400', '500', '700'],
  variable: '--font-ubuntu',
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
