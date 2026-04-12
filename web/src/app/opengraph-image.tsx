import { ImageResponse } from "next/og";

export const runtime = "edge";
export const alt = "Jersey Votes - Explore how your Assembly votes";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function Image() {
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
          <span style={{ fontSize: "56px", fontWeight: "bold", marginBottom: "24px" }}>
            Jersey Votes
          </span>
          <span style={{ fontSize: "44px", fontWeight: "bold", lineHeight: "1.2" }}>
            How does your Assembly vote?
          </span>
          <span style={{ fontSize: "28px", fontWeight: "500", color: "#fca5a5", marginTop: "24px", lineHeight: "1.4" }}>
            Explore 22 years of voting data. See which politicians vote
            together, find representatives aligned with your views.
          </span>
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-end",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: "6px", fontSize: "22px", fontWeight: "500", color: "#fca5a5" }}>
            <span>49 Active Members</span>
            <span>5,423 Recorded Votes</span>
            <span>22 Years of Data</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
            <span style={{ fontSize: "22px", fontWeight: "600", color: "#fca5a5", letterSpacing: "0.05em", textTransform: "uppercase" }}>Jersey General Election</span>
            <span style={{ fontSize: "44px", fontWeight: "bold" }}>Sunday 7 June 2026</span>
          </div>
        </div>
      </div>
    ),
    { width: 1200, height: 630 }
  );
}
