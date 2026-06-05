// Next.js instrumentation entrypoint. Wires OpenTelemetry → Logfire so every
// /api/ask stage (gate → embed → retrieve → synthesize) is traced.
//
// Single-knob config: set LOGFIRE_TOKEN and traces flow to Logfire's OTLP
// endpoint. With no token this is a complete no-op (the OTel API falls back to
// a no-op tracer), so the feature works fine without observability configured.
//
// Everything is wrapped in try/catch — a misconfigured exporter must never stop
// the server from booting.

export async function register() {
  // OTel Node SDK only runs in the Node.js runtime, not Edge.
  if (process.env.NEXT_RUNTIME !== "nodejs") return;

  const token = process.env.LOGFIRE_TOKEN;
  if (!token) return; // observability not configured — no-op

  try {
    // Default the standard OTLP env vars to Logfire when not already set, so a
    // single LOGFIRE_TOKEN is enough. Both can still be overridden explicitly
    // (e.g. LOGFIRE_OTLP_ENDPOINT for the EU region).
    if (!process.env.OTEL_EXPORTER_OTLP_ENDPOINT) {
      process.env.OTEL_EXPORTER_OTLP_ENDPOINT =
        process.env.LOGFIRE_OTLP_ENDPOINT || "https://logfire-api.pydantic.dev";
    }
    if (!process.env.OTEL_EXPORTER_OTLP_HEADERS) {
      process.env.OTEL_EXPORTER_OTLP_HEADERS = `Authorization=${token}`;
    }

    const { registerOTel } = await import("@vercel/otel");
    registerOTel({ serviceName: "jerseyvotes-web" });
  } catch (e) {
    console.error("[instrumentation] Logfire/OTel setup failed (continuing without tracing):", e);
  }
}
