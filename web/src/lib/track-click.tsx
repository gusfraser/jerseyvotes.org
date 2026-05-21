import Link from "next/link";

/**
 * <TrackedLink> previously fired a Google Analytics event on click in
 * addition to navigating. GA was removed for cookie-compliance reasons;
 * this is now a thin wrapper around next/link's <Link> so call sites don't
 * need to change. If cookieless event analytics is added later, hook the
 * onClick in here.
 */
export function TrackedLink({
  href,
  event: _event,
  params: _params,
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
    <Link href={href} className={className}>
      {children}
    </Link>
  );
}
