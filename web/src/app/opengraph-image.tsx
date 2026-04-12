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
          <span style={{ fontSize: "48px", fontWeight: "bold", marginBottom: "20px" }}>
            Jersey Votes
          </span>
          <span style={{ fontSize: "36px", lineHeight: "1.3" }}>
            How does your Assembly vote?
          </span>
          <span style={{ fontSize: "24px", color: "#fca5a5", marginTop: "20px", lineHeight: "1.5" }}>
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
          <div style={{ display: "flex", gap: "30px", fontSize: "20px", color: "#fca5a5" }}>
            <span>49 Active Members</span>
            <span>5,423 Recorded Votes</span>
            <span>22 Years of Data</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
            <span style={{ fontSize: "18px", color: "#fca5a5" }}>Jersey General Election</span>
            <span style={{ fontSize: "28px", fontWeight: "bold" }}>Sunday 7 June 2026</span>
          </div>
        </div>
      </div>
    ),
    { width: 1200, height: 630 }
  );
}
