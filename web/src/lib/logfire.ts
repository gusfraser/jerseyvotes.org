import { trace, SpanStatusCode, type Span } from "@opentelemetry/api";

// Thin wrapper over the OpenTelemetry API. When instrumentation.ts has wired up
// an exporter (LOGFIRE_TOKEN present), these spans are sent to Logfire. When it
// hasn't, @opentelemetry/api hands back a no-op tracer, so `span()` still runs
// the work and just doesn't emit anything — the app never depends on Logfire
// being configured.

const tracer = trace.getTracer("jerseyvotes-ask");

export async function span<T>(
  name: string,
  attributes: Record<string, unknown>,
  fn: (span: Span) => Promise<T>,
): Promise<T> {
  return tracer.startActiveSpan(name, async (s) => {
    setAttrs(s, attributes);
    try {
      const out = await fn(s);
      s.setStatus({ code: SpanStatusCode.OK });
      return out;
    } catch (e) {
      s.recordException(e as Error);
      s.setStatus({ code: SpanStatusCode.ERROR, message: (e as Error).message });
      throw e;
    } finally {
      s.end();
    }
  });
}

export function setAttrs(s: Span | undefined, attrs: Record<string, unknown>) {
  if (!s) return;
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null) continue;
    // OTel attributes accept primitives or homogeneous arrays. Arrays/objects
    // are stringified to sidestep the homogeneous-array constraint.
    if (typeof v === "object") {
      s.setAttribute(k, JSON.stringify(v));
    } else {
      s.setAttribute(k, v as string | number | boolean);
    }
  }
}
