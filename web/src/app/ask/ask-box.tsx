"use client";

import { AskChat, type AskScope } from "./ask-chat";

// Scoped "Ask about this candidate / this hustings" card, embedded on the
// candidate profile and hustings event pages. Retrieval is constrained to the
// given candidate/event by the scope passed through to /api/ask.

export function AskBox({
  title,
  subtitle,
  scope,
  suggestions = [],
  placeholder = "Ask a question…",
}: {
  title: string;
  subtitle: string;
  scope: AskScope;
  suggestions?: string[];
  placeholder?: string;
}) {
  return (
    <section className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-lg p-5">
      <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100 mb-1">
        {title}
      </h2>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">{subtitle}</p>
      <AskChat
        scope={scope}
        suggestions={suggestions}
        variant="box"
        placeholder={placeholder}
      />
    </section>
  );
}
