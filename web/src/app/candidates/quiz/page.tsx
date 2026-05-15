import type { Metadata } from "next";
import Link from "next/link";
import { daysUntilElection } from "@/lib/db";
import { CandidateQuizClient } from "./quiz-client";

export const metadata: Metadata = {
  title: "Find your candidate — Jersey 2026 election quiz",
  description:
    "Rank your priorities and answer policy questions to see which 2026 Jersey election candidates best match your views. Every score is transparent and traceable to manifesto quotes.",
};

// Re-render at least hourly so the "days until polling day" header stays
// current. See web/src/app/page.tsx for the same rationale.
export const revalidate = 3600;

export default function CandidateQuizPage() {
  const days = daysUntilElection();
  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      <header className="mb-8">
        <div className="flex items-baseline justify-between gap-3 mb-2">
          <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100">
            Find your candidate
          </h1>
          {days > 0 && (
            <span className="text-sm text-gray-500 dark:text-gray-400">
              {days} {days === 1 ? "day" : "days"} until polling day
            </span>
          )}
        </div>
        <p className="text-gray-500 dark:text-gray-400">
          Tell us your priorities, answer some policy questions, and we&rsquo;ll
          show you the candidates whose manifestos most align with your views.{" "}
          <Link
            href="/candidates/methodology"
            className="text-red-700 underline hover:no-underline"
          >
            How scoring works &rarr;
          </Link>
        </p>
      </header>
      <CandidateQuizClient />
    </div>
  );
}
