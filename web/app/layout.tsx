import type { Metadata } from "next";
import Link from "next/link";
import { Source_Code_Pro, Source_Sans_3, Source_Serif_4 } from "next/font/google";
import "./globals.css";

const serif = Source_Serif_4({ variable: "--font-source-serif", subsets: ["latin"] });
const sans = Source_Sans_3({ variable: "--font-source-sans", subsets: ["latin"] });
const code = Source_Code_Pro({ variable: "--font-source-code", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "Ontario Injury Law Guide", template: "%s · Ontario Injury Law Guide" },
  description: "A research guide to Ontario personal-injury law for paralegals and law students.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${serif.variable} ${sans.variable} ${code.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 bg-paper px-3 py-2">
          Skip to content
        </a>
        <header className="border-b border-rule">
          <div className="mx-auto flex max-w-5xl items-baseline justify-between gap-4 px-4 py-4">
            <Link href="/" className="font-serif text-xl font-semibold text-ink no-underline">
              Ontario Injury Law Guide
            </Link>
            <nav aria-label="Main">
              <Link href="/laws">Law library</Link>
            </nav>
          </div>
        </header>
        <main id="main" className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">
          {children}
        </main>
        <footer className="border-t border-rule text-sm text-muted">
          <p className="mx-auto max-w-5xl px-4 py-4">
            A research guide for paralegals and law students — not legal advice. Law texts are unofficial copies; the
            official source is linked on every page.
          </p>
        </footer>
      </body>
    </html>
  );
}
