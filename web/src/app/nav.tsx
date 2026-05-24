"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

type NavItem =
  | { kind: "link"; href: string; label: string; highlight?: boolean }
  | { kind: "group"; label: string; items: { href: string; label: string }[] };

// Top-level nav. Election-cycle items (Candidates / Quiz / Hustings) are
// flat so voters see them straight away. Assembly voting-record analysis
// is collapsed under one dropdown to keep the top bar from cramping.
const navLinks: NavItem[] = [
  { kind: "link", href: "/candidates", label: "Candidates", highlight: true },
  { kind: "link", href: "/candidates/quiz", label: "Voting Quiz" },
  { kind: "link", href: "/hustings", label: "Hustings" },
  {
    kind: "group",
    label: "Assembly",
    items: [
      { href: "/members", label: "Members" },
      { href: "/votes", label: "Votes" },
      { href: "/divisive", label: "Divisive" },
      { href: "/alignment", label: "Alignment" },
      { href: "/blocs", label: "Blocs" },
    ],
  },
  { kind: "link", href: "/about", label: "About" },
];

// Flatten to all hrefs so activeHref can scan them.
function allLinks(items: NavItem[]): { href: string; label: string }[] {
  const out: { href: string; label: string }[] = [];
  for (const it of items) {
    if (it.kind === "link") out.push({ href: it.href, label: it.label });
    else out.push(...it.items);
  }
  return out;
}

// Pick the single most-specific link to highlight for a given pathname.
function activeHref(pathname: string): string | null {
  let best: string | null = null;
  for (const { href } of allLinks(navLinks)) {
    if (pathname === href || pathname.startsWith(href + "/")) {
      if (best === null || href.length > best.length) best = href;
    }
  }
  return best;
}

function useTheme() {
  const [theme, setTheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    const stored = localStorage.getItem("theme");
    if (stored === "dark") {
      setTheme("dark");
    }
    // Default to light - only go dark if user explicitly chose it
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem("theme", theme);
  }, [theme]);

  const toggle = () => setTheme(theme === "dark" ? "light" : "dark");

  return { theme, toggle };
}

export function Nav() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const { theme, toggle } = useTheme();
  const activeLink = activeHref(pathname);

  return (
    <header className="bg-white dark:bg-zinc-900 border-b border-gray-200 dark:border-zinc-800 sticky top-0 z-50">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <Link href="/" className="flex items-center gap-2 text-xl font-bold text-red-700">
            <svg viewBox="0 0 32 32" className="w-7 h-7">
              <rect width="32" height="32" rx="6" fill="#991b1b"/>
              <path d="M9 16.5l4.5 4.5L23 11" fill="none" stroke="white" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            JerseyVotes.org
          </Link>

          {/* Desktop nav */}
          <nav className="hidden md:flex items-center gap-1">
            {navLinks.map((item) => {
              if (item.kind === "link") {
                const isActive = activeLink === item.href;
                const inSection =
                  activeLink !== null &&
                  (activeLink === item.href || activeLink.startsWith(item.href + "/"));
                const baseHighlight = item.highlight && !inSection
                  ? "text-white bg-red-700 hover:bg-red-800 hover:text-white"
                  : "text-gray-600 dark:text-gray-300 hover:text-red-700 hover:bg-gray-50 dark:hover:bg-gray-800";
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`px-3 py-2 text-sm font-medium rounded-md transition-colors ${
                      isActive
                        ? "text-red-700 bg-red-50 dark:bg-red-900/30"
                        : baseHighlight
                    }`}
                  >
                    {item.label}
                  </Link>
                );
              }
              // dropdown group
              return (
                <NavGroup
                  key={item.label}
                  label={item.label}
                  items={item.items}
                  activeLink={activeLink}
                />
              );
            })}

            {/* Theme toggle */}
            <button
              onClick={toggle}
              className="ml-2 p-2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition-colors"
              aria-label="Toggle dark mode"
            >
              {theme === "dark" ? (
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm1.414 8.486l-.707.707a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414zM4 11a1 1 0 100-2H3a1 1 0 000 2h1z" clipRule="evenodd" />
                </svg>
              ) : (
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                  <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z" />
                </svg>
              )}
            </button>
          </nav>

          {/* Mobile: theme toggle + burger */}
          <div className="flex items-center gap-2 md:hidden">
            <button
              onClick={toggle}
              className="p-2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
              aria-label="Toggle dark mode"
            >
              {theme === "dark" ? (
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm1.414 8.486l-.707.707a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414zM4 11a1 1 0 100-2H3a1 1 0 000 2h1z" clipRule="evenodd" />
                </svg>
              ) : (
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                  <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z" />
                </svg>
              )}
            </button>
            <button
              onClick={() => setOpen(!open)}
              className="p-2 text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white"
              aria-label="Toggle menu"
            >
              {open ? (
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              ) : (
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                </svg>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile menu */}
      {open && (
        <nav className="md:hidden border-t border-gray-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
          <div className="px-4 py-2 space-y-1">
            {navLinks.map((item) => {
              if (item.kind === "link") {
                const isActive = activeLink === item.href;
                const inSection =
                  activeLink !== null &&
                  (activeLink === item.href || activeLink.startsWith(item.href + "/"));
                const baseHighlight = item.highlight && !inSection
                  ? "text-white bg-red-700 hover:bg-red-800"
                  : "text-gray-600 dark:text-gray-300 hover:text-red-700 hover:bg-gray-50 dark:hover:bg-gray-800";
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => setOpen(false)}
                    className={`block px-3 py-2 text-sm font-medium rounded-md transition-colors ${
                      isActive
                        ? "text-red-700 bg-red-50 dark:bg-red-900/30"
                        : baseHighlight
                    }`}
                  >
                    {item.label}
                  </Link>
                );
              }
              // mobile: render the group as a heading + indented items
              return (
                <div key={item.label} className="pt-2 first:pt-0">
                  <p className="px-3 py-1 text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                    {item.label}
                  </p>
                  {item.items.map((sub) => {
                    const isActive = activeLink === sub.href;
                    return (
                      <Link
                        key={sub.href}
                        href={sub.href}
                        onClick={() => setOpen(false)}
                        className={`block px-3 py-2 text-sm font-medium rounded-md transition-colors ${
                          isActive
                            ? "text-red-700 bg-red-50 dark:bg-red-900/30"
                            : "text-gray-600 dark:text-gray-300 hover:text-red-700 hover:bg-gray-50 dark:hover:bg-gray-800"
                        }`}
                      >
                        {sub.label}
                      </Link>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </nav>
      )}
    </header>
  );
}

function NavGroup({
  label,
  items,
  activeLink,
}: {
  label: string;
  items: { href: string; label: string }[];
  activeLink: string | null;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Click-outside closes the dropdown.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  // Highlight when active route is within the group.
  const groupActive =
    activeLink !== null && items.some((i) => activeLink === i.href);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`px-3 py-2 text-sm font-medium rounded-md transition-colors inline-flex items-center gap-1 ${
          groupActive
            ? "text-red-700 bg-red-50 dark:bg-red-900/30"
            : "text-gray-600 dark:text-gray-300 hover:text-red-700 hover:bg-gray-50 dark:hover:bg-gray-800"
        }`}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        {label}
        <svg
          className="w-3 h-3 transition-transform"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          style={{ transform: open ? "rotate(180deg)" : undefined }}
          aria-hidden="true"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div
          role="menu"
          className="absolute top-full right-0 mt-1 min-w-[140px] bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-md shadow-lg z-50 py-1"
        >
          {items.map((sub) => {
            const isActive = activeLink === sub.href;
            return (
              <Link
                key={sub.href}
                href={sub.href}
                onClick={() => setOpen(false)}
                role="menuitem"
                className={`block px-4 py-2 text-sm transition-colors ${
                  isActive
                    ? "text-red-700 bg-red-50 dark:bg-red-900/30"
                    : "text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 hover:text-red-700"
                }`}
              >
                {sub.label}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
