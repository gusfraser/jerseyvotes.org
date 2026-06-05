import type { Metadata } from "next";
import Link from "next/link";
import { isChatEnabled } from "@/lib/flags";
import { getCorpusStats } from "@/lib/db";
import { AskChat } from "./ask-chat";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Ask — Jersey Votes",
  description:
    "Ask questions about the Jersey 2026 election candidates and get answers grounded in their published manifestos and hustings transcripts, with sources.",
};

const SUGGESTIONS = [
  "What do candidates say about housing affordability?",
  "Which candidates have talked about GST?",
  "What was said about healthcare at the hustings?",
  "How do candidates want to tackle the cost of living?",
];

export default async function AskPage() {
  const enabled = await isChatEnabled();
  const stats = enabled ? await getCorpusStats() : null;
  const searchingLabel =
    stats && stats.manifestos > 0
      ? `Searching ${stats.manifestos} manifestos and ~${stats.hustingsHours} hours of hustings…`
      : undefined;

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      <header className="mb-8">
        <h1 className="text-4xl sm:text-5xl font-bold text-gray-900 dark:text-gray-100 tracking-tight mb-4">
          Ask about the election
        </h1>
        <p className="text-lg text-gray-600 dark:text-gray-400 leading-relaxed">
          Ask a question and get an answer drawn from candidates&rsquo; published
          manifestos and what they said at hustings. Every answer links to its
          sources so you can check the original.
        </p>
      </header>

      {enabled ? (
        <AskChat suggestions={SUGGESTIONS} variant="page" searchingLabel={searchingLabel} />
      ) : (
        <div className="bg-gray-50 dark:bg-zinc-950 border border-gray-200 dark:border-zinc-800 rounded-lg p-6 text-gray-600 dark:text-gray-400">
          <p className="font-medium text-gray-900 dark:text-gray-100 mb-1">
            Ask is temporarily unavailable
          </p>
          <p className="text-sm">
            This feature is currently switched off. In the meantime, browse{" "}
            <Link href="/candidates" className="text-red-700 dark:text-red-400 hover:underline">
              candidates
            </Link>{" "}
            and{" "}
            <Link href="/hustings" className="text-red-700 dark:text-red-400 hover:underline">
              hustings transcripts
            </Link>{" "}
            directly.
          </p>
        </div>
      )}

      <p className="mt-8 text-xs text-gray-400 dark:text-gray-500 leading-relaxed">
        This assistant only answers questions about the Jersey 2026 election. It
        does not recommend who to vote for. Answers are AI-generated and may
        contain mistakes &mdash; always verify against the linked sources. See our{" "}
        <Link href="/privacy" className="hover:text-red-700">
          privacy notice
        </Link>{" "}
        for how questions are handled.
      </p>
    </div>
  );
}
