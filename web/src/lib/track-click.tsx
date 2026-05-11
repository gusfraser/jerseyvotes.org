"use client";

import Link from "next/link";

/**
 * <TrackedLink> — drop-in replacement for next/link's <Link> that also fires
 * a GA event on click. Use inside server components when you want both the
 * server-rendered href AND a click-tracking event without the full
 * client-side state of the quiz client. Renders a normal <Link> server-side.
 */
export function TrackedLink({
  href,
  event,
  params,
  className,
  children,
}: {
  href: string;
  event: string;
  params?: Record<string, string | number | boolean>;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className={className}
      onClick={() => {
        if (
          typeof window !== "undefined" &&
          typeof (window as unknown as { gtag?: unknown }).gtag === "function"
        ) {
          (window as unknown as { gtag: (...args: unknown[]) => void }).gtag(
            "event",
            event,
            params ?? {},
          );
        }
      }}
    >
      {children}
    </Link>
  );
}
