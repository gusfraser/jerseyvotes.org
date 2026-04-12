"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

type Question = {
  divisionId: number;
  title: string;
  summary: string | null;
  extendedSummary: string | null;
  topic: string;
  reference: string;
  sourceUrl: string;
  date: string;
  pourCount: number;
  contreCount: number;
  passed: boolean;
};

type Answer = {
  divisionId: number;
  vote: "pour" | "contre";
};

type MatchResult = {
  name: string;
  displayName: string;
  position: string;
  agreementPct: number;
  agreed: number;
  total: number;
};

function slugify(name: string): string {
  return name
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}

const STORAGE_KEY = "jerseyvotes-quiz";

function loadSavedState() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) return JSON.parse(saved);
  } catch {}
  return null;
}

function saveState(currentIdx: number, answers: Answer[], skipped: number[]) {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ currentIdx, answers, skipped, savedAt: Date.now() })
    );
  } catch {}
}

function clearSavedState() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {}
}

export function QuizClient() {
  const [questions, setQuestions] = useState<Question[]>([]);
  const [currentIdx, setCurrentIdx] = useState(0);
  const [answers, setAnswers] = useState<Answer[]>([]);
  const [skipped, setSkipped] = useState<Set<number>>(new Set());
  const [results, setResults] = useState<MatchResult[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [showResume, setShowResume] = useState(false);

  useEffect(() => {
    fetch("/api/quiz")
      .then((r) => r.json())
      .then((d) => {
        setQuestions(d.questions);

        // Check for saved progress
        const saved = loadSavedState();
        if (saved && saved.answers?.length > 0) {
          // Only resume if saved less than 7 days ago
          if (Date.now() - saved.savedAt < 7 * 24 * 60 * 60 * 1000) {
            setShowResume(true);
          }
        }

        setLoading(false);
      });
  }, []);

  function resumeQuiz() {
    const saved = loadSavedState();
    if (saved) {
      setCurrentIdx(saved.currentIdx || 0);
      setAnswers(saved.answers || []);
      setSkipped(new Set(saved.skipped || []));
    }
    setShowResume(false);
  }

  function dismissResume() {
    clearSavedState();
    setShowResume(false);
  }

  // Save progress whenever answers or position change
  useEffect(() => {
    if (answers.length > 0 || skipped.size > 0) {
      saveState(currentIdx, answers, Array.from(skipped));
    }
  }, [currentIdx, answers, skipped]);

  function handleVote(vote: "pour" | "contre") {
    const q = questions[currentIdx];
    // Remove any existing answer for this question (in case of going back)
    const filtered = answers.filter((a) => a.divisionId !== q.divisionId);
    setAnswers([...filtered, { divisionId: q.divisionId, vote }]);
    // Remove from skipped if it was skipped before
    const newSkipped = new Set(skipped);
    newSkipped.delete(q.divisionId);
    setSkipped(newSkipped);
    advance();
  }

  function handleSkip() {
    const q = questions[currentIdx];
    // Remove any existing answer for this question
    setAnswers(answers.filter((a) => a.divisionId !== q.divisionId));
    setSkipped(new Set([...skipped, q.divisionId]));
    advance();
  }

  function advance() {
    if (currentIdx + 1 < questions.length) {
      setCurrentIdx(currentIdx + 1);
    } else {
      submitResults();
    }
  }

  function goBack() {
    if (currentIdx > 0) {
      setCurrentIdx(currentIdx - 1);
    }
  }

  function resetQuiz() {
    setCurrentIdx(0);
    setAnswers([]);
    setSkipped(new Set());
    setResults(null);
    clearSavedState();
  }

  function submitResults() {
    const finalAnswers = answers.length > 0 ? answers : [];
    // Include any answer added in the current handleVote call
    // (state may not have updated yet, so we pass via the submit flow)
    setLoading(true);
    // Small timeout to let state settle
    setTimeout(() => {
      fetch("/api/quiz", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answers: finalAnswers }),
      })
        .then((r) => r.json())
        .then((d) => {
          setResults(d.results);
          setLoading(false);
          clearSavedState();
        });
    }, 100);
  }

  // Submit early
  function finishEarly() {
    setLoading(true);
    fetch("/api/quiz", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answers }),
    })
      .then((r) => r.json())
      .then((d) => {
        setResults(d.results);
        setLoading(false);
      });
  }

  if (loading && !results) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        Loading questions...
      </div>
    );
  }

  // Show resume prompt
  if (showResume) {
    const saved = loadSavedState();
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-8 text-center">
        <p className="text-lg font-semibold text-gray-900 mb-2">
          Welcome back!
        </p>
        <p className="text-gray-500 mb-6">
          You have {saved?.answers?.length || 0} answers saved from a previous session.
        </p>
        <div className="flex gap-4 justify-center">
          <button
            onClick={resumeQuiz}
            className="px-6 py-3 bg-red-700 text-white rounded-lg hover:bg-red-800 font-semibold"
          >
            Continue where I left off
          </button>
          <button
            onClick={dismissResume}
            className="px-6 py-3 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 font-semibold"
          >
            Start fresh
          </button>
        </div>
      </div>
    );
  }

  // Show results
  if (results) {
    return <QuizResults results={results} answerCount={answers.length} onReset={resetQuiz} />;
  }

  // Show question
  const q = questions[currentIdx];
  if (!q) return null;

  const progress = ((currentIdx) / questions.length) * 100;
  const previousAnswer = answers.find((a) => a.divisionId === q.divisionId);
  const wasSkipped = skipped.has(q.divisionId);

  return (
    <div>
      {/* Progress bar */}
      <div className="mb-6">
        <div className="flex justify-between text-sm text-gray-500 mb-1">
          <span>
            Question {currentIdx + 1} of {questions.length}
          </span>
          <span>{answers.length} answered</span>
        </div>
        <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
          <div
            className="h-full bg-red-700 transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* Question card */}
      <div className="bg-white rounded-xl border border-gray-200 p-8 mb-6">
        <div className="flex items-center gap-2 mb-4">
          <span className="bg-gray-100 text-gray-600 text-xs px-2 py-1 rounded">
            {q.topic}
          </span>
          <span className="text-xs text-gray-400">{q.reference}</span>
          <span className="text-xs text-gray-400">
            {new Date(q.date).toLocaleDateString("en-GB", {
              month: "short",
              year: "numeric",
            })}
          </span>
        </div>

        {q.summary ? (
          <>
            <h2 className="text-xl font-semibold text-gray-900 mb-3">
              {q.summary}
            </h2>
            <p className="text-sm text-gray-500 mb-3">
              {q.title}
            </p>
          </>
        ) : (
          <h2 className="text-xl font-semibold text-gray-900 mb-3">
            {q.title}
          </h2>
        )}

        {q.extendedSummary && (
          <ExpandableSummary key={`ext-${q.divisionId}`} text={q.extendedSummary} />
        )}

        <div className="flex items-center gap-3 text-xs text-gray-400 mb-6">
          {q.sourceUrl && (
            <a
              href={q.sourceUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-red-700 hover:underline"
            >
              Read the full proposition
            </a>
          )}
          <QuizResultReveal
            key={q.divisionId}
            divisionId={q.divisionId}
            pourCount={q.pourCount}
            contreCount={q.contreCount}
            passed={q.passed}
          />
        </div>

        <p className="text-gray-700 font-medium mb-6">
          How would you have voted?
        </p>

        <div className="flex gap-4">
          <button
            onClick={() => handleVote("pour")}
            className={`flex-1 py-4 px-6 rounded-lg border-2 font-semibold text-lg transition-all ${
              previousAnswer?.vote === "pour"
                ? "border-green-500 bg-green-100 text-green-900 ring-2 ring-green-300"
                : "border-green-200 bg-green-50 text-green-800 hover:border-green-400 hover:bg-green-100"
            }`}
          >
            Pour
            <span className="block text-sm font-normal text-green-600 mt-1">
              Support this
            </span>
          </button>
          <button
            onClick={() => handleVote("contre")}
            className={`flex-1 py-4 px-6 rounded-lg border-2 font-semibold text-lg transition-all ${
              previousAnswer?.vote === "contre"
                ? "border-red-500 bg-red-100 text-red-900 ring-2 ring-red-300"
                : "border-red-200 bg-red-50 text-red-800 hover:border-red-400 hover:bg-red-100"
            }`}
          >
            Contre
            <span className="block text-sm font-normal text-red-600 mt-1">
              Oppose this
            </span>
          </button>
        </div>

        <button
          onClick={handleSkip}
          className="w-full mt-3 py-2 text-sm text-gray-400 hover:text-gray-600 transition-colors"
        >
          {wasSkipped ? "Skipped — click to skip again or vote above" : "Skip this question"}
        </button>
      </div>

      {/* Navigation */}
      <div className="flex items-center justify-between">
        <button
          onClick={goBack}
          disabled={currentIdx === 0}
          className={`px-4 py-2 text-sm rounded-lg transition-colors ${
            currentIdx === 0
              ? "text-gray-300 cursor-not-allowed"
              : "text-gray-500 hover:text-gray-700 hover:bg-gray-100"
          }`}
        >
          &larr; Previous question
        </button>
        <button
          onClick={resetQuiz}
          className="px-4 py-2 text-sm text-gray-400 hover:text-red-700 transition-colors"
        >
          Start over
        </button>
      </div>

      {/* Finish early */}
      {answers.length >= 10 && (
        <button
          onClick={finishEarly}
          className="w-full py-3 text-sm text-gray-500 hover:text-red-700 transition-colors"
        >
          See results with {answers.length} answers &rarr;
        </button>
      )}
    </div>
  );
}

function QuizResults({
  results,
  answerCount,
  onReset,
}: {
  results: MatchResult[];
  answerCount: number;
  onReset: () => void;
}) {
  if (results.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-8 text-center">
        <p className="text-gray-500">
          Not enough answers to calculate alignment. Try answering at least 5
          questions.
        </p>
        <button
          onClick={onReset}
          className="mt-4 px-6 py-2 bg-red-700 text-white rounded-lg hover:bg-red-800"
        >
          Try again
        </button>
      </div>
    );
  }

  const top = results[0];

  return (
    <div>
      <div className="bg-white rounded-xl border border-gray-200 p-8 mb-8 text-center">
        <p className="text-sm text-gray-500 mb-2">
          Based on {answerCount} answers, your closest match is
        </p>
        <Link
          href={`/members/${slugify(top.name)}`}
          className="text-3xl font-bold text-red-700 hover:underline"
        >
          {top.displayName}
        </Link>
        <p className="text-gray-500 mt-1">{top.position}</p>
        <p className="text-5xl font-bold text-green-600 mt-4">
          {(top.agreementPct * 100).toFixed(0)}%
        </p>
        <p className="text-sm text-gray-500 mt-1">
          agreement ({top.agreed}/{top.total} shared votes)
        </p>

        {/* Share button */}
        <div className="mt-6 flex justify-center gap-3">
          <ShareButton
            name={top.displayName}
            position={top.position}
            pct={Math.round(top.agreementPct * 100)}
          />
        </div>
      </div>

      {/* Full rankings */}
      <h2 className="text-xl font-bold mb-4">All Members Ranked</h2>
      <div className="space-y-2">
        {results.map((m, i) => (
          <Link
            key={m.name}
            href={`/members/${slugify(m.name)}`}
            className="flex items-center gap-4 bg-white rounded-lg border border-gray-200 p-3 hover:border-red-300 transition-colors"
          >
            <span className="w-8 text-center text-sm font-bold text-gray-400">
              {i + 1}
            </span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-medium text-gray-900">
                  {m.displayName}
                </span>
                <span className="text-xs text-gray-400">{m.position}</span>
              </div>
              {/* Alignment bar */}
              <div className="mt-1 h-2 bg-gray-100 rounded-full overflow-hidden w-full max-w-xs">
                <div
                  className={`h-full rounded-full ${
                    m.agreementPct >= 0.8
                      ? "bg-green-500"
                      : m.agreementPct >= 0.6
                      ? "bg-yellow-500"
                      : "bg-red-500"
                  }`}
                  style={{ width: `${m.agreementPct * 100}%` }}
                />
              </div>
            </div>
            <div className="text-right">
              <span
                className={`text-lg font-bold ${
                  m.agreementPct >= 0.8
                    ? "text-green-600"
                    : m.agreementPct >= 0.6
                    ? "text-yellow-600"
                    : "text-red-600"
                }`}
              >
                {(m.agreementPct * 100).toFixed(0)}%
              </span>
              <p className="text-xs text-gray-400">
                {m.agreed}/{m.total}
              </p>
            </div>
          </Link>
        ))}
      </div>

      {/* Retake */}
      <div className="mt-8 text-center">
        <button
          onClick={onReset}
          className="px-6 py-3 bg-red-700 text-white rounded-lg hover:bg-red-800 font-semibold"
        >
          Retake Quiz
        </button>
      </div>
    </div>
  );
}

function QuizResultReveal({
  divisionId,
  pourCount,
  contreCount,
  passed,
}: {
  divisionId: number;
  pourCount: number;
  contreCount: number;
  passed: boolean;
}) {
  const [revealed, setRevealed] = useState(false);

  if (revealed) {
    return (
      <span className="text-gray-500">
        The Assembly voted {pourCount}-{contreCount} (
        {passed ? "adopted" : "rejected"}) &middot;{" "}
        <a
          href={`/votes/${divisionId}`}
          target="_blank"
          rel="noopener noreferrer"
          className="text-red-700 hover:underline"
        >
          See full breakdown
        </a>
      </span>
    );
  }

  return (
    <button
      onClick={() => setRevealed(true)}
      className="text-gray-400 hover:text-gray-600 transition-colors"
    >
      Reveal how the Assembly voted
    </button>
  );
}

function RenderMarkdown({ text }: { text: string }) {
  return (
    <>
      {text.split("\n").map((line, i) => {
        if (!line.trim()) return null;
        const parts = line.split(/\*\*(.*?)\*\*/g);
        return (
          <p key={i} className="mb-2 last:mb-0">
            {parts.map((part, j) =>
              j % 2 === 1 ? (
                <strong key={j}>{part}</strong>
              ) : (
                <span key={j}>{part}</span>
              )
            )}
          </p>
        );
      })}
    </>
  );
}

function ExpandableSummary({ text }: { text: string }) {
  const [showMore, setShowMore] = useState(false);

  // Split into sections by bold headings like **What it proposed**, **Why...**, **Key arguments**
  const sections: { title: string; body: string }[] = [];
  const lines = text.split("\n").filter((l) => l.trim());

  let currentTitle = "";
  let currentBody: string[] = [];

  for (const line of lines) {
    const headingMatch = line.match(/^\*\*(.+?)\*\*\s*(.*)/);
    if (headingMatch) {
      if (currentTitle || currentBody.length > 0) {
        sections.push({ title: currentTitle, body: currentBody.join("\n") });
      }
      currentTitle = headingMatch[1];
      currentBody = headingMatch[2] ? [headingMatch[2]] : [];
    } else {
      currentBody.push(line);
    }
  }
  if (currentTitle || currentBody.length > 0) {
    sections.push({ title: currentTitle, body: currentBody.join("\n") });
  }

  // If we couldn't parse sections, fall back to showing all text
  if (sections.length === 0) {
    return (
      <div className="mb-4 p-4 bg-gray-50 rounded-lg text-sm text-gray-700 leading-relaxed">
        <RenderMarkdown text={text} />
      </div>
    );
  }

  const firstSection = sections[0];
  const restSections = sections.slice(1);

  return (
    <div className="mb-4 space-y-2">
      {/* First section always visible */}
      <div className="p-4 bg-gray-50 rounded-lg text-sm text-gray-700 leading-relaxed">
        {firstSection.title && (
          <p className="font-semibold text-gray-900 mb-1">{firstSection.title}</p>
        )}
        <RenderMarkdown text={firstSection.body} />
      </div>

      {/* More sections expandable */}
      {restSections.length > 0 && (
        <>
          {!showMore ? (
            <button
              onClick={() => setShowMore(true)}
              className="flex items-center gap-2 text-sm text-red-700 hover:text-red-900 font-medium transition-colors px-4 py-2 bg-gray-50 rounded-lg w-full hover:bg-gray-100"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
              Why was this brought forward? Key arguments...
            </button>
          ) : (
            <>
              {restSections.map((section, i) => (
                <div
                  key={i}
                  className="p-4 bg-gray-50 rounded-lg text-sm text-gray-700 leading-relaxed"
                >
                  {section.title && (
                    <p className="font-semibold text-gray-900 mb-1">
                      {section.title}
                    </p>
                  )}
                  <RenderMarkdown text={section.body} />
                </div>
              ))}
              <button
                onClick={() => setShowMore(false)}
                className="text-xs text-gray-400 hover:text-gray-600 px-4"
              >
                Show less
              </button>
            </>
          )}
        </>
      )}
    </div>
  );
}

function ShareButton({
  name,
  position,
  pct,
}: {
  name: string;
  position: string;
  pct: number;
}) {
  const [copied, setCopied] = useState(false);

  const shareUrl = typeof window !== "undefined"
    ? `${window.location.origin}/quiz`
    : "https://jerseyvotes.org/quiz";

  const shareText = `My closest match in the Jersey States Assembly is ${name} (${pct}% agreement). Take the Voter Quiz before the election on 7 June! ${shareUrl}`;

  const imageUrl = typeof window !== "undefined"
    ? `${window.location.origin}/api/share?name=${encodeURIComponent(name)}&position=${encodeURIComponent(position)}&pct=${pct}`
    : "";

  async function handleShare() {
    if (navigator.share) {
      try {
        await navigator.share({ title: "Jersey Votes - My Quiz Result", text: shareText, url: shareUrl });
        return;
      } catch {}
    }
    await navigator.clipboard.writeText(shareText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="flex flex-col items-center gap-3">
      <button
        onClick={handleShare}
        className="px-6 py-3 bg-red-700 text-white rounded-lg hover:bg-red-800 font-semibold flex items-center gap-2"
      >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" />
        </svg>
        {copied ? "Copied!" : "Share your result"}
      </button>
      {imageUrl && (
        <a
          href={imageUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-gray-400 hover:text-gray-600"
        >
          Download share image
        </a>
      )}
    </div>
  );
}
