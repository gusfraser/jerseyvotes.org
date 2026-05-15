import { ImageResponse } from "next/og";
import { daysUntilElection } from "@/lib/db";

export const runtime = "edge";
// OG images are statically optimized by default. force-dynamic is the only
// opt-out that works under edge runtime (the `revalidate` export is ignored
// there per Next 16 docs) — without it the "X days until you vote" headline
// stays pinned to whatever the build-time value was.
export const dynamic = "force-dynamic";
export const alt = "Jersey Votes — Find your candidate for the 2026 election";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function Image() {
  const days = daysUntilElection();
  return new ImageResponse(
    (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          width: "1200px",
          height: "630px",
          backgroundColor: "#7f1d1d",
          color: "white",
          fontFamily: "sans-serif",
          padding: "60px",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column" }}>
          <span style={{ fontSize: "44px", fontWeight: "bold", marginBottom: "16px" }}>
            Jersey Votes
          </span>
          <span style={{ fontSize: "72px", fontWeight: "bold", lineHeight: "1.05" }}>
            {days > 0 ? `${days} days until you vote` : "Polling day is here"}
          </span>
          <span
            style={{
              fontSize: "32px",
              fontWeight: "500",
              color: "#fca5a5",
              marginTop: "24px",
              lineHeight: "1.4",
            }}
          >
            Find the candidates whose priorities match yours.
            Free, independent, transparent.
          </span>
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-end",
          }}
        >
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: "6px",
              fontSize: "22px",
              fontWeight: "500",
              color: "#fca5a5",
            }}
          >
            <span>92 candidates analysed</span>
            <span>16 policy topics, transparent scoring</span>
            <span>jerseyvotes.org/candidates</span>
          </div>
          <div
            style={{ display: "flex", flexDirection: "column", alignItems: "flex-end" }}
          >
            <span
              style={{
                fontSize: "22px",
                fontWeight: "600",
                color: "#fca5a5",
                letterSpacing: "0.05em",
                textTransform: "uppercase",
              }}
            >
              General Election
            </span>
            <span style={{ fontSize: "44px", fontWeight: "bold" }}>
              Sunday 7 June 2026
            </span>
          </div>
        </div>
      </div>
    ),
    { width: 1200, height: 630 },
  );
}
