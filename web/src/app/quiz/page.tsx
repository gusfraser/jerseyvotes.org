import type { Metadata } from "next";
import { QuizClient } from "./quiz-client";

export const metadata: Metadata = {
  title: "Voter Quiz",
  description:
    "Find out which Jersey States Assembly members most closely align with your views. Answer questions on real divisive votes, get matched to your representatives.",
};

export default function QuizPage() {
  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <h1 className="text-3xl font-bold mb-2">Voter Alignment Quiz</h1>
      <p className="text-gray-600 mb-8">
        Tell us how you would have voted on key States Assembly decisions, and
        we&apos;ll show you which members most closely align with your views.
        Questions are drawn from the most divisive votes in the current term.
      </p>
      <QuizClient />
    </div>
  );
}
