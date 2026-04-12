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

export const metadata: Metadata = {
  title: "Jersey Votes",
  description:
    "Explore 22 years of Jersey States Assembly voting data. Analyse politician voting patterns, find aligned representatives, and understand how your Assembly votes.",
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
      <body className="min-h-full flex flex-col bg-gray-50 text-gray-900">
        <Nav />
        <main className="flex-1">{children}</main>
        <footer className="bg-white border-t border-gray-200 py-8 mt-auto">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center text-sm text-gray-500">
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
