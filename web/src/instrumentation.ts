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
    // single LOGFIRE_TOKEN is enough. The token encodes its region
    // (pylf_v1_eu_… vs pylf_v1_us_…); EU tokens MUST use the EU endpoint or the
    // data silently never arrives. LOGFIRE_OTLP_ENDPOINT overrides if needed.
    const isEu = token.includes("_eu_");
    const defaultEndpoint = isEu
      ? "https://logfire-eu.pydantic.dev"
      : "https://logfire-api.pydantic.dev";
    if (!process.env.OTEL_EXPORTER_OTLP_ENDPOINT) {
      process.env.OTEL_EXPORTER_OTLP_ENDPOINT =
        process.env.LOGFIRE_OTLP_ENDPOINT || defaultEndpoint;
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
