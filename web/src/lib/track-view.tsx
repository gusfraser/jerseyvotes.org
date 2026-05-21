/**
 * Previously fired a Google Analytics event on mount. GA was removed for
 * cookie-compliance reasons; this is now a no-op wrapper so call sites
 * (server pages that want to flag a view-level fact) don't need to change.
 * If cookieless event analytics is added later, hook it in here.
 *
 *   <TrackView event="candidate_profile_viewed" params={{ slug, role }} />
 *
 * Renders nothing.
 */
export function TrackView(_props: {
  event: string;
  params?: Record<string, string | number | boolean>;
}) {
  return null;
}
