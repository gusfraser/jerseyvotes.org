"use client";

import { useEffect } from "react";

/**
 * Minimal client component that fires a GA event on mount. Use inside an
 * otherwise-server component when you want to record a view-level fact
 * beyond the default pageview (e.g. candidate slug, methodology section).
 *
 *   <TrackView event="candidate_profile_viewed" params={{ slug, role }} />
 *
 * Renders nothing. Cheap to drop into a server page.
 */
export function TrackView({
  event,
  params,
}: {
  event: string;
  params?: Record<string, string | number | boolean>;
}) {
  useEffect(() => {
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
    // Only fire once per mount — intentional.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return null;
}
