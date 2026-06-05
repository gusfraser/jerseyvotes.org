"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

// Shared chat client used by both the site-wide /ask page and the scoped
// "Ask about this candidate / hustings" box. Talks to /api/ask, which streams
// newline-delimited JSON events: meta → (token* for refusals | answer) → done.

export type AnswerItem = {
  candidate: string | null;
  candidateSlug: string | null;
  sourceType: string; // 'manifesto' | 'hustings'
  quote: string; // verbatim, verified server-side
  gist: string; // optional neutral context
  url: string; // link to the original source
};

export type AskScope = { candidateSlug?: string; eventSlug?: string };

type Msg = {
  role: "user" | "assistant";
  text: string; // refusals / no-results / errors
  intro?: string; // structured answer framing
  items?: AnswerItem[]; // verbatim quote listing
  caveat?: string;
  status?: string;
  error?: boolean;
  retrieved?: number; // # passages retrieved (from the meta event)
  candidates?: number; // # distinct candidates retrieved
};

export function AskChat({
  scope,
  suggestions = [],
  variant = "page",
  placeholder = "Ask a question about the candidates…",
  searchingLabel,
}: {
  scope?: AskScope;
  suggestions?: string[];
  variant?: "page" | "box";
  placeholder?: string;
  searchingLabel?: string;
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
            update((a) => ({
              ...a,
              status: String(evt.status || ""),
              retrieved:
                typeof evt.retrieved === "number" ? (evt.retrieved as number) : a.retrieved,
              candidates:
                typeof evt.candidates === "number" ? (evt.candidates as number) : a.candidates,
            }));
          } else if (evt.type === "token") {
            update((a) => ({ ...a, text: a.text + String(evt.text || "") }));
          } else if (evt.type === "answer") {
            // The grounded, verbatim-quote listing (sent once synthesis is done).
            update((a) => ({
              ...a,
              intro: typeof evt.intro === "string" ? (evt.intro as string) : "",
              items: (evt.items as AnswerItem[]) || [],
              caveat: typeof evt.caveat === "string" ? (evt.caveat as string) : "",
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
                  <AssistantMessage m={m} searchingLabel={searchingLabel} scope={scope} />
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

function AssistantMessage({
  m,
  searchingLabel,
  scope,
}: {
  m: Msg;
  searchingLabel?: string;
  scope?: AskScope;
}) {
  const hasStructured = (m.items && m.items.length > 0) || !!m.intro || !!m.caveat;

  // Nothing yet (waiting on the server) → animated, informative indicator.
  if (!hasStructured && !m.text && !m.error) {
    return <SearchingIndicator m={m} searchingLabel={searchingLabel} scope={scope} />;
  }

  // Refusals / no-results / errors come through as plain text.
  if (!hasStructured) {
    return (
      <RichText text={m.text} className={m.error ? "text-red-700 dark:text-red-400" : ""} />
    );
  }

  return (
    <div>
      {m.intro && <RichText text={m.intro} />}
      {m.items && m.items.length > 0 && (
        <div className={m.intro ? "mt-3" : ""}>
          <AnswerItems items={m.items} />
        </div>
      )}
      {m.caveat && (
        <p className="mt-3 pt-2 border-t border-gray-200 dark:border-zinc-800 text-xs text-gray-500 dark:text-gray-400 italic">
          {m.caveat}
        </p>
      )}
    </div>
  );
}

// Verbatim quotes grouped by candidate, each linked to its original source
// (the YouTube moment for hustings, the manifesto URL otherwise).
// Animated loading state. Before the server's `meta` event it shows the
// scope-aware "Searching N manifestos…" label; once passages are retrieved it
// switches to the real "Reading N passages from M candidates…" count, with a
// pulsing dot + skeleton shimmer so the ~15-25s synthesis wait feels alive.
function SearchingIndicator({
  m,
  searchingLabel,
  scope,
}: {
  m: Msg;
  searchingLabel?: string;
  scope?: AskScope;
}) {
  let label: string;
  if (typeof m.retrieved === "number") {
    const n = m.retrieved;
    const p = n === 1 ? "passage" : "passages";
    if (scope?.candidateSlug) {
      label = `Reading ${n} of their ${n === 1 ? "statement" : "statements"}…`;
    } else if (scope?.eventSlug) {
      label = `Reading ${n} ${p} from this hustings…`;
    } else {
      const c = m.candidates ?? 0;
      label = `Reading ${n} ${p} from ${c} ${c === 1 ? "candidate" : "candidates"}…`;
    }
  } else {
    label = searchingLabel || "Searching the manifestos & hustings…";
  }

  return (
    <div className="space-y-2.5">
      <div className="flex items-center gap-2 text-gray-600 dark:text-gray-300">
        <span className="relative flex h-2.5 w-2.5 shrink-0">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-500 opacity-75" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-red-600" />
        </span>
        <span className="text-sm">{label}</span>
      </div>
      <div className="space-y-1.5 pt-0.5" aria-hidden="true">
        <div className="h-3 w-2/5 rounded bg-gray-200 dark:bg-zinc-800 animate-pulse" />
        <div className="h-3 w-11/12 rounded bg-gray-200 dark:bg-zinc-800 animate-pulse" />
        <div className="h-3 w-3/4 rounded bg-gray-200 dark:bg-zinc-800 animate-pulse" />
      </div>
    </div>
  );
}

function AnswerItems({ items }: { items: AnswerItem[] }) {
  type Group = {
    candidate: string | null;
    candidateSlug: string | null;
    sourceType: string;
    items: AnswerItem[];
  };
  // Group all of a candidate's quotes together (by candidate + medium),
  // preserving the order each candidate first appears.
  const groups: Group[] = [];
  const byKey = new Map<string, Group>();
  for (const it of items) {
    const key = `${it.candidateSlug ?? it.candidate ?? ""}|${it.sourceType}`;
    let g = byKey.get(key);
    if (!g) {
      g = {
        candidate: it.candidate,
        candidateSlug: it.candidateSlug,
        sourceType: it.sourceType,
        items: [],
      };
      byKey.set(key, g);
      groups.push(g);
    }
    g.items.push(it);
  }

  return (
    <div className="space-y-4">
      {groups.map((g, gi) => (
        <div key={gi}>
          <div className="flex items-baseline gap-2 mb-1.5 flex-wrap">
            {g.candidateSlug ? (
              <Link
                href={`/candidates/${g.candidateSlug}`}
                className="font-semibold text-gray-900 dark:text-gray-100 hover:text-red-700"
              >
                {g.candidate || "Candidate"}
              </Link>
            ) : (
              <span className="font-semibold text-gray-900 dark:text-gray-100">
                {g.candidate || "Candidate"}
              </span>
            )}
            <span className="text-xs text-gray-400">
              · {g.sourceType === "hustings" ? "at hustings" : "manifesto"}
            </span>
          </div>
          <div className="space-y-2">
            {g.items.map((it, ii) => (
              <div key={ii}>
                {it.quote ? (
                  <blockquote className="border-l-2 border-gray-200 dark:border-zinc-700 pl-3 text-sm text-gray-800 dark:text-gray-200">
                    <span className="italic">&ldquo;{it.quote}&rdquo;</span>{" "}
                    <SourceLink url={it.url} />
                  </blockquote>
                ) : (
                  <p className="text-sm text-gray-700 dark:text-gray-300 pl-3">
                    {it.gist} <SourceLink url={it.url} />
                  </p>
                )}
                {it.quote && it.gist && (
                  <p className="text-xs text-gray-500 dark:text-gray-400 pl-3 mt-0.5">
                    {it.gist}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function SourceLink({ url }: { url: string }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="text-xs text-red-700 dark:text-red-400 hover:underline whitespace-nowrap"
    >
      source&nbsp;↗
    </a>
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
