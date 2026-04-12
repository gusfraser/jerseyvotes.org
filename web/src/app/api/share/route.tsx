import { ImageResponse } from "next/og";

export const runtime = "edge";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const name = searchParams.get("name") || "Unknown";
  const position = searchParams.get("position") || "Member";
  const pct = searchParams.get("pct") || "0";

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
        }}
      >
        {/* Top bar */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: "40px",
          }}
        >
          <span style={{ fontSize: "36px", fontWeight: "bold" }}>
            Jersey Votes
          </span>
          <span style={{ fontSize: "20px", color: "#fca5a5" }}>
            jerseyvotes.org
          </span>
        </div>

        {/* Main content */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            flex: 1,
            justifyContent: "center",
          }}
        >
          <span
            style={{
              fontSize: "24px",
              color: "#fca5a5",
              marginBottom: "12px",
            }}
          >
            My closest match in the States Assembly is
          </span>
          <span
            style={{
              fontSize: "64px",
              fontWeight: "bold",
              marginBottom: "8px",
            }}
          >
            {name}
          </span>
          <span
            style={{ fontSize: "28px", color: "#fca5a5", marginBottom: "30px" }}
          >
            {position}
          </span>

          {/* Agreement bar */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "20px",
            }}
          >
            <span style={{ fontSize: "72px", fontWeight: "bold" }}>
              {pct}%
            </span>
            <span style={{ fontSize: "24px", color: "#fca5a5" }}>
              agreement on key votes
            </span>
          </div>
        </div>

        {/* Bottom CTA */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-end",
          }}
        >
          <span style={{ fontSize: "22px", color: "#fca5a5" }}>
            Take the Voter Quiz at jerseyvotes.org/quiz
          </span>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "flex-end",
            }}
          >
            <span style={{ fontSize: "18px", color: "#fca5a5" }}>
              Jersey General Election
            </span>
            <span style={{ fontSize: "28px", fontWeight: "bold" }}>
              Sunday 7 June 2026
            </span>
          </div>
        </div>
      </div>
    ),
    {
      width: 1200,
      height: 630,
    }
  );
}
