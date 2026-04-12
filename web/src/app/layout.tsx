import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Nav } from "./nav";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const siteDescription =
  "Explore 22 years of Jersey States Assembly voting data. Analyse politician voting patterns, find aligned representatives, and understand how your Assembly votes.";

export const metadata: Metadata = {
  metadataBase: new URL("https://jerseyvotes.org"),
  title: {
    template: "%s | Jersey Votes",
    default: "Jersey Votes",
  },
  description: siteDescription,
  openGraph: {
    siteName: "Jersey Votes",
    locale: "en_GB",
    type: "website",
    url: "https://jerseyvotes.org",
    title: "Jersey Votes",
    description: siteDescription,
    images: [{ url: "/opengraph-image", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    site: "@jerseyvotes",
    title: "Jersey Votes",
    description: siteDescription,
    images: ["/opengraph-image"],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-gray-50 text-gray-900 dark:bg-gray-950 dark:text-gray-100">
        <Nav />
        <main className="flex-1">{children}</main>
        <footer className="bg-white dark:bg-zinc-900 border-t border-gray-200 dark:border-zinc-800 py-8 mt-auto">
          <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 text-center text-sm text-gray-500">
            <p>
              Data sourced from{" "}
              <a
                href="https://statesassembly.je/votes"
                className="text-red-700 hover:underline"
                target="_blank"
                rel="noopener noreferrer"
              >
                States Assembly of Jersey
              </a>
              . Covering 2004&ndash;2026.
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
