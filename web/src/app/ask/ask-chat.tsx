"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

// Shared streaming chat client used by both the site-wide /ask page and the
// scoped "Ask about this candidate / hustings" box. Talks to /api/ask, which
// streams newline-delimited JSON events: meta → token* → citations? → done.

export type Citation = {
  n: number;
  source_type: string;
  candidate_name: string | null;
  candidate_slug: string | null;
  role: string | null;
  constituency: string | null;
  source_url: string;
  source_label: string | null;
  event_slug: string | null;
  youtube_url: string | null;
  timestamp_seconds: number | null;
  segment_type: string | null;
  score: number;
};

export type AskScope = { candidateSlug?: string; eventSlug?: string };

type Msg = {
  role: "user" | "assistant";
  text: string;
  citations?: Citation[];
  status?: string;
  error?: boolean;
};

export function AskChat({
  scope,
  suggestions = [],
  variant = "page",
  placeholder = "Ask a question about the candidates…",
}: {
  scope?: AskScope;
  suggestions?: string[];
  variant?: "page" | "box";
  placeholder?: string;
}) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Keep the latest message in view inside the scroll area.
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  async function send(qRaw: string) {
    const q = qRaw.trim();
    if (!q || busy) return;
    setInput("");
    setBusy(true);
    setMessages((m) => [
      ...m,
      { role: "user", text: q },
      { role: "assistant", text: "", status: "loading" },
    ]);

    // Index of the assistant message we'll be updating.
    const update = (fn: (a: Msg) => Msg) =>
      setMessages((m) => {
        const next = [...m];
        for (let i = next.length - 1; i >= 0; i--) {
          if (next[i].role === "assistant") {
            next[i] = fn(next[i]);
            break;
          }
        }
        return next;
      });

    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, scope }),
      });

      if (!res.ok || !res.body) {
        const j = await res.json().catch(() => ({}));
        update((a) => ({
          ...a,
          text:
            j.error ||
            (j.disabled ? "Chat is currently unavailable." : "Something went wrong."),
          status: "error",
          error: true,
        }));
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() || "";
        for (const line of lines) {
          if (!line.trim()) continue;
          let evt: { type: string; [k: string]: unknown };
          try {
            evt = JSON.parse(line);
          } catch {
            continue;
          }
          if (evt.type === "meta") {
            update((a) => ({ ...a, status: String(evt.status || "") }));
          } else if (evt.type === "token") {
            update((a) => ({ ...a, text: a.text + String(evt.text || "") }));
          } else if (evt.type === "final") {
            // Server replaces the streamed text with a renumbered version and
            // sends the ordered, cited-only sources.
            update((a) => ({
              ...a,
              text: typeof evt.text === "string" ? (evt.text as string) : a.text,
              citations: (evt.items as Citation[]) || a.citations || [],
            }));
          } else if (evt.type === "error") {
            update((a) => ({
              ...a,
              text: a.text || String(evt.message || "Something went wrong."),
              error: true,
            }));
          }
        }
      }
    } catch {
      update((a) => ({
        ...a,
        text: a.text || "Network error. Please try again.",
        error: true,
      }));
    } finally {
      setBusy(false);
    }
  }

  const boxHeight = variant === "box" ? "max-h-80" : "max-h-[55vh]";
  const showSuggestions = messages.length === 0 && suggestions.length > 0;

  return (
    <div className="flex flex-col">
      {/* Message list */}
      {messages.length > 0 && (
        <div
          ref={scrollRef}
          className={`${boxHeight} overflow-y-auto space-y-4 mb-4 pr-1`}
        >
          {messages.map((m, i) =>
            m.role === "user" ? (
              <div key={i} className="flex justify-end">
                <div className="bg-red-700 text-white rounded-2xl rounded-br-sm px-4 py-2 text-sm max-w-[85%]">
                  {m.text}
                </div>
              </div>
            ) : (
              <div key={i} className="flex justify-start">
                <div className="bg-gray-50 dark:bg-zinc-950 border border-gray-200 dark:border-zinc-800 rounded-2xl rounded-bl-sm px-4 py-3 text-sm max-w-[92%] w-full">
                  {m.status === "loading" && !m.text ? (
                    <span className="text-gray-400">Thinking…</span>
                  ) : (
                    <RichText
                      text={m.text}
                      className={m.error ? "text-red-700 dark:text-red-400" : ""}
                    />
                  )}
                  {m.citations && m.citations.length > 0 && (
                    <Citations items={m.citations} />
                  )}
                </div>
              </div>
            ),
          )}
        </div>
      )}

      {/* Suggestions (only before the first question) */}
      {showSuggestions && (
        <div className="flex flex-wrap gap-2 mb-4">
          {suggestions.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => send(s)}
              className="text-left text-sm px-3 py-1.5 rounded-full border border-gray-200 dark:border-zinc-700 text-gray-700 dark:text-gray-300 hover:border-red-300 hover:text-red-700 transition-colors"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="flex items-end gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={placeholder}
          maxLength={500}
          disabled={busy}
          className="flex-1 rounded-lg border border-gray-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-red-300 disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          className="shrink-0 px-4 py-2 rounded-lg bg-red-700 text-white text-sm font-medium hover:bg-red-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {busy ? "…" : "Ask"}
        </button>
      </form>

      <p className="mt-2 text-xs text-gray-400 dark:text-gray-500">
        AI-generated from candidates&rsquo; published manifestos and hustings
        transcripts. Always verify against the linked sources. Not voting advice.
      </p>
    </div>
  );
}

function Citations({ items }: { items: Citation[] }) {
  return (
    <div className="mt-3 pt-3 border-t border-gray-200 dark:border-zinc-800">
      <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5">
        Sources
      </p>
      <ol className="space-y-1">
        {items.map((c) => {
          const onSite =
            c.source_type === "hustings" && c.event_slug
              ? `/hustings/${c.event_slug}`
              : c.candidate_slug
                ? `/candidates/${c.candidate_slug}`
                : null;
          const kind = c.source_type === "hustings" ? "hustings" : "manifesto";
          return (
            <li key={c.n} className="text-xs text-gray-600 dark:text-gray-400 flex gap-1.5">
              <span className="text-gray-400 shrink-0">[{c.n}]</span>
              <span className="flex-1">
                {onSite ? (
                  <Link href={onSite} className="text-red-700 dark:text-red-400 hover:underline font-medium">
                    {c.candidate_name || "Source"}
                  </Link>
                ) : (
                  <span className="font-medium">{c.candidate_name || "Source"}</span>
                )}{" "}
                <span className="text-gray-400">· {kind}</span>{" "}
                <a
                  href={c.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-gray-400 hover:text-red-700"
                  title="Open original source"
                >
                  ↗
                </a>
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

// Lightweight markdown rendering (no dependency): headings (#…), bold (**…**),
// bullet lines, and --- rules. Enough for the answers the model produces.
function RichText({ text, className = "" }: { text: string; className?: string }) {
  const lines = text.split("\n");
  return (
    <div className={`leading-relaxed text-gray-800 dark:text-gray-200 ${className}`}>
      {lines.map((line, i) => {
        const trimmed = line.trim();
        if (!trimmed) return <div key={i} className="h-2" />;
        // Horizontal rule
        if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
          return <hr key={i} className="my-3 border-gray-200 dark:border-zinc-800" />;
        }
        // ATX headings: #, ##, ### …
        const h = trimmed.match(/^(#{1,6})\s+(.*)$/);
        if (h) {
          return (
            <p
              key={i}
              className={`font-bold text-gray-900 dark:text-gray-100 mt-3 mb-1 first:mt-0 ${
                h[1].length <= 1 ? "text-base" : "text-sm"
              }`}
            >
              {renderInline(h[2])}
            </p>
          );
        }
        const bullet = /^\s*[-*•]\s+/.test(line);
        return (
          <p key={i} className={bullet ? "pl-4 -indent-3 mb-1" : "mb-1 last:mb-0"}>
            {renderInline(line)}
          </p>
        );
      })}
    </div>
  );
}

function renderInline(line: string) {
  const parts = line.split(/\*\*(.*?)\*\*/g);
  return parts.map((p, j) =>
    j % 2 === 1 ? <strong key={j}>{p}</strong> : <span key={j}>{p}</span>,
  );
}
