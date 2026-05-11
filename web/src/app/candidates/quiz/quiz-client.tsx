"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

type Question = {
  question_id: string;
  topic: string;
  statement: string;
  explainer: string | null;
  sort_order: number;
};

type QuizData = {
  topics: string[];
  questions: Question[];
  candidateCount: number;
  rankWeights: number[];
};

type Answer = "agree" | "disagree" | "neutral" | "skip";

type Result = {
  candidate_id: number;
  slug: string;
  name: string;
  role: string | null;
  constituency: string | null;
  party: string | null;
  photo_url: string | null;
  is_incumbent: boolean;
  manifesto_word_count: number | null;
  scrape_status: string;
  T: number;
  S: number;
  C: number;
  match: number;
  matched_questions: number;
  answered_questions: number;
  low_coverage: boolean;
};

type ResultsPayload = {
  results: Result[];
  priorities: string[];
  constituency: string | null;
};

const STORAGE_KEY = "jv-candidate-quiz-v1";

function trackEvent(name: string, params?: Record<string, string | number | boolean>) {
  if (
    typeof window !== "undefined" &&
    typeof (window as unknown as { gtag?: unknown }).gtag === "function"
  ) {
    (window as unknown as { gtag: (...args: unknown[]) => void }).gtag(
      "event",
      name,
      params ?? {},
    );
  }
}

type PersistedState = {
  step: number;
  priorities: string[];
  answers: Record<string, Answer>;
  constituency: string;
  savedAt: number;
};

function loadState(): PersistedState | null {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (!saved) return null;
    const parsed = JSON.parse(saved) as PersistedState;
    if (Date.now() - parsed.savedAt > 14 * 24 * 60 * 60 * 1000) return null;
    return parsed;
  } catch {
    return null;
  }
}

function saveState(s: PersistedState) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
  } catch {}
}

function clearState() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {}
}

export function CandidateQuizClient() {
  const [data, setData] = useState<QuizData | null>(null);
  const [loadingData, setLoadingData] = useState(true);
  const [step, setStep] = useState<0 | 1 | 2 | 3>(0); // 0 priorities, 1 stances, 2 constituency, 3 results
  const [priorities, setPriorities] = useState<string[]>([]);
  const [answers, setAnswers] = useState<Record<string, Answer>>({});
  const [constituency, setConstituency] = useState<string>("");
  const [resultsPayload, setResultsPayload] = useState<ResultsPayload | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetch("/api/candidates/quiz")
      .then((r) => r.json())
      .then((d: QuizData) => {
        setData(d);
        setLoadingData(false);
        const saved = loadState();
        if (saved) {
          setPriorities(saved.priorities ?? []);
          setAnswers(saved.answers ?? {});
          setConstituency(saved.constituency ?? "");
          setStep(Math.min(saved.step, 2) as 0 | 1 | 2);
          trackEvent("candidate_quiz_resumed", {
            answers_saved: Object.keys(saved.answers ?? {}).length,
            priorities_saved: (saved.priorities ?? []).length,
            resumed_at_step: Math.min(saved.step, 2),
          });
        } else {
          trackEvent("candidate_quiz_started");
        }
      });
  }, []);

  useEffect(() => {
    if (step === 0 && priorities.length === 0 && Object.keys(answers).length === 0)
      return;
    saveState({ step, priorities, answers, constituency, savedAt: Date.now() });
  }, [step, priorities, answers, constituency]);

  const questionsByTopic = useMemo(() => {
    const map = new Map<string, Question[]>();
    if (!data) return map;
    for (const q of data.questions) {
      if (!map.has(q.topic)) map.set(q.topic, []);
      map.get(q.topic)!.push(q);
    }
    return map;
  }, [data]);

  if (loadingData || !data) {
    return <p className="text-gray-500">Loading quiz&hellip;</p>;
  }

  if (data.candidateCount === 0) {
    return (
      <div className="bg-amber-50 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-800 rounded-xl p-6 text-amber-900 dark:text-amber-200">
        <p className="font-semibold mb-1">No classified candidates yet</p>
        <p className="text-sm">
          We&rsquo;re still scraping and classifying manifestos. Please check
          back soon. Until then,{" "}
          <Link href="/candidates/methodology" className="underline">
            see how this will work
          </Link>
          .
        </p>
      </div>
    );
  }

  if (step === 3 && resultsPayload) {
    return (
      <ResultsView
        payload={resultsPayload}
        onRetake={() => {
          trackEvent("candidate_quiz_retaken", {
            previous_top_match: resultsPayload.results[0]?.name ?? "",
          });
          clearState();
          setPriorities([]);
          setAnswers({});
          setConstituency("");
          setResultsPayload(null);
          setStep(0);
        }}
      />
    );
  }

  return (
    <div>
      <StepIndicator step={step} />

      {step === 0 && (
        <PriorityStep
          topics={data.topics}
          priorities={priorities}
          questionsByTopic={questionsByTopic}
          onChange={setPriorities}
          onNext={() => {
            trackEvent("candidate_quiz_priorities_set", {
              priorities: priorities.join(","),
            });
            setStep(1);
          }}
        />
      )}

      {step === 1 && (
        <StanceStep
          questionsByTopic={questionsByTopic}
          topics={data.topics}
          priorities={priorities}
          answers={answers}
          onAnswer={(qid, a) => setAnswers((prev) => ({ ...prev, [qid]: a }))}
          onBack={() => {
            trackEvent("candidate_quiz_back", { from_step: 1, to_step: 0 });
            setStep(0);
          }}
          onNext={() => {
            trackEvent("candidate_quiz_stances_set", {
              answered: Object.values(answers).filter((a) => a !== "skip").length,
            });
            setStep(2);
          }}
        />
      )}

      {step === 2 && (
        <ConstituencyStep
          value={constituency}
          onChange={setConstituency}
          onBack={() => {
            trackEvent("candidate_quiz_back", { from_step: 2, to_step: 1 });
            setStep(1);
          }}
          onSubmit={async () => {
            if (submitting) return;
            setSubmitting(true);
            try {
              const resp = await fetch("/api/candidates/quiz", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  priorities,
                  stances: answers,
                  constituency: constituency || null,
                }),
              });
              const body = (await resp.json()) as ResultsPayload;
              setResultsPayload(body);
              setStep(3);
              const answeredCount = Object.values(answers).filter(
                (a) => a !== "skip",
              ).length;
              trackEvent("candidate_quiz_completed", {
                results_returned: body.results.length,
                top_match: body.results[0]?.name ?? "",
                top_match_pct: body.results[0]
                  ? Math.round(body.results[0].match * 100)
                  : 0,
                top_match_low_coverage: body.results[0]?.low_coverage ?? false,
                constituency_filtered: !!constituency,
                constituency: constituency || "(none)",
                priorities_count: priorities.length,
                priority_topics: priorities.join("|"),
                stances_answered: answeredCount,
              });
            } finally {
              setSubmitting(false);
            }
          }}
          submitting={submitting}
        />
      )}
    </div>
  );
}

function StepIndicator({ step }: { step: number }) {
  const labels = ["Priorities", "Policies", "Constituency", "Results"];
  return (
    <nav aria-label="Quiz progress" className="mb-8">
      <ol className="flex items-center gap-1 sm:gap-2">
        {labels.map((label, i) => {
          const done = step > i;
          const active = step === i;
          const circleClasses = done
            ? "bg-green-600 text-white"
            : active
            ? "bg-red-700 text-white ring-4 ring-red-100 dark:ring-red-900/40"
            : "bg-gray-200 dark:bg-zinc-800 text-gray-500 dark:text-gray-400";
          const labelClasses = active
            ? "font-semibold text-gray-900 dark:text-gray-100"
            : done
            ? "text-gray-700 dark:text-gray-300"
            : "text-gray-400 dark:text-gray-500";
          return (
            <li key={label} className="flex items-center gap-2 flex-shrink-0">
              <span
                aria-current={active ? "step" : undefined}
                className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold leading-none select-none ${circleClasses}`}
              >
                {done ? (
                  <svg
                    className="w-3.5 h-3.5"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={3}
                    viewBox="0 0 24 24"
                    aria-hidden="true"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                ) : (
                  <span>{i + 1}</span>
                )}
              </span>
              <span className={`text-xs sm:text-sm whitespace-nowrap ${labelClasses}`}>
                {label}
              </span>
              {i < labels.length - 1 && (
                <span
                  aria-hidden="true"
                  className={`hidden sm:inline-block w-6 lg:w-10 h-px mx-1 ${
                    done ? "bg-green-600" : "bg-gray-300 dark:bg-zinc-700"
                  }`}
                />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function PriorityStep({
  topics,
  priorities,
  questionsByTopic,
  onChange,
  onNext,
}: {
  topics: string[];
  priorities: string[];
  questionsByTopic: Map<string, Question[]>;
  onChange: (p: string[]) => void;
  onNext: () => void;
}) {
  const max = 5;
  // Which topic's help tooltip is currently open. One at a time so things
  // don't get cluttered; mobile users tap to open, tap again to close.
  const [openHelp, setOpenHelp] = useState<string | null>(null);

  function toggle(topic: string) {
    if (priorities.includes(topic)) {
      onChange(priorities.filter((t) => t !== topic));
    } else if (priorities.length < max) {
      onChange([...priorities, topic]);
    }
  }
  function move(topic: string, dir: -1 | 1) {
    const idx = priorities.indexOf(topic);
    if (idx < 0) return;
    const newIdx = idx + dir;
    if (newIdx < 0 || newIdx >= priorities.length) return;
    const copy = [...priorities];
    [copy[idx], copy[newIdx]] = [copy[newIdx], copy[idx]];
    onChange(copy);
  }

  return (
    <div>
      <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100 mb-1">
        What matters most to you?
      </h2>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-5">
        Pick up to <strong>5</strong> topics, then drag them into your priority
        order. Topics ranked higher count more in the score. Not sure what
        a topic covers? Tap the{" "}
        <span className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-gray-200 dark:bg-zinc-700 text-[10px] font-bold text-gray-700 dark:text-gray-200 align-middle">?</span>{" "}
        icon for example statements.
      </p>

      {priorities.length > 0 && (
        <div className="mb-6">
          <p className="text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">
            Your priorities (highest first)
          </p>
          <ol className="space-y-2">
            {priorities.map((t, i) => (
              <li
                key={t}
                className="flex items-center gap-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg px-3 py-2"
              >
                <span className="text-sm font-bold w-6 text-center text-red-700 dark:text-red-300">
                  {i + 1}
                </span>
                <span className="flex-1 font-medium text-gray-900 dark:text-gray-100">
                  {t}
                </span>
                <button
                  type="button"
                  onClick={() => move(t, -1)}
                  disabled={i === 0}
                  className="text-xs text-gray-500 hover:text-red-700 disabled:opacity-30"
                  aria-label="Move up"
                >
                  ▲
                </button>
                <button
                  type="button"
                  onClick={() => move(t, 1)}
                  disabled={i === priorities.length - 1}
                  className="text-xs text-gray-500 hover:text-red-700 disabled:opacity-30"
                  aria-label="Move down"
                >
                  ▼
                </button>
                <button
                  type="button"
                  onClick={() => toggle(t)}
                  className="text-xs text-gray-400 hover:text-red-700"
                  aria-label="Remove"
                >
                  ✕
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}

      <div className="grid sm:grid-cols-2 gap-2 mb-6">
        {topics.map((t) => {
          const selected = priorities.includes(t);
          const atMax = !selected && priorities.length >= max;
          const examples =
            questionsByTopic.get(t)?.slice(0, 3).map((q) => q.statement) ?? [];
          const isHelpOpen = openHelp === t;

          const rowClass = selected
            ? "border-red-700 bg-red-50 dark:bg-red-900/30"
            : atMax
            ? "border-gray-200 dark:border-zinc-800 opacity-60"
            : "border-gray-200 dark:border-zinc-800 hover:border-red-300";

          const labelClass = selected
            ? "text-red-700 dark:text-red-300 font-medium"
            : atMax
            ? "text-gray-400 dark:text-gray-600"
            : "text-gray-700 dark:text-gray-300";

          return (
            <div
              key={t}
              className={`relative flex items-stretch rounded-lg border text-sm transition-colors ${rowClass}`}
            >
              <button
                type="button"
                disabled={atMax}
                onClick={() => toggle(t)}
                className={`flex-1 text-left px-3 py-2 rounded-l-lg ${
                  atMax ? "cursor-not-allowed" : ""
                } ${labelClass}`}
              >
                {selected && (
                  <span className="inline-block w-5 text-red-700 dark:text-red-300">
                    {priorities.indexOf(t) + 1}.
                  </span>
                )}
                {t}
              </button>
              {examples.length > 0 && (
                <button
                  type="button"
                  aria-label={`Show example statements for ${t}`}
                  aria-expanded={isHelpOpen}
                  onClick={(e) => {
                    e.stopPropagation();
                    setOpenHelp(isHelpOpen ? null : t);
                  }}
                  onMouseEnter={() => setOpenHelp(t)}
                  onMouseLeave={() =>
                    setOpenHelp((cur) => (cur === t ? null : cur))
                  }
                  onFocus={() => setOpenHelp(t)}
                  onBlur={() =>
                    setOpenHelp((cur) => (cur === t ? null : cur))
                  }
                  className={`flex-shrink-0 w-9 flex items-center justify-center rounded-r-lg border-l text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-zinc-800 hover:text-red-700 ${
                    selected
                      ? "border-red-300 dark:border-red-800"
                      : "border-gray-200 dark:border-zinc-800"
                  }`}
                >
                  <span
                    aria-hidden="true"
                    className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-gray-200 dark:bg-zinc-700 text-[10px] font-bold"
                  >
                    ?
                  </span>
                </button>
              )}

              {isHelpOpen && examples.length > 0 && (
                <div
                  role="tooltip"
                  className="absolute z-20 left-0 right-0 top-full mt-2 bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 rounded-lg shadow-lg p-3 text-xs text-gray-700 dark:text-gray-300"
                >
                  <p className="font-semibold text-gray-900 dark:text-gray-100 mb-2 text-[11px] uppercase tracking-wide">
                    Example statements in this topic
                  </p>
                  <ul className="space-y-1.5">
                    {examples.map((ex, i) => (
                      <li
                        key={i}
                        className="flex items-baseline gap-1.5 leading-snug"
                      >
                        <span className="text-red-700 flex-shrink-0">›</span>
                        <span>&ldquo;{ex}&rdquo;</span>
                      </li>
                    ))}
                  </ul>
                  <button
                    type="button"
                    onClick={() => setOpenHelp(null)}
                    className="mt-2 text-[10px] text-gray-400 hover:text-red-700 sm:hidden"
                  >
                    Close
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="flex justify-between items-center">
        <span className="text-xs text-gray-500 dark:text-gray-400">
          {priorities.length} of {max} selected
        </span>
        <button
          type="button"
          disabled={priorities.length === 0}
          onClick={onNext}
          className="px-5 py-2.5 bg-red-700 text-white rounded-lg hover:bg-red-800 disabled:bg-gray-300 disabled:cursor-not-allowed font-medium"
        >
          Next: policy questions &rarr;
        </button>
      </div>
    </div>
  );
}

function StanceStep({
  questionsByTopic,
  topics,
  priorities,
  answers,
  onAnswer,
  onBack,
  onNext,
}: {
  questionsByTopic: Map<string, Question[]>;
  topics: string[];
  priorities: string[];
  answers: Record<string, Answer>;
  onAnswer: (qid: string, a: Answer) => void;
  onBack: () => void;
  onNext: () => void;
}) {
  // Show priority topics first, then the rest.
  const sortedTopics = [
    ...priorities,
    ...topics.filter((t) => !priorities.includes(t)),
  ].filter((t) => questionsByTopic.has(t));

  const answered = Object.values(answers).filter((a) => a !== "skip").length;
  const total = Array.from(questionsByTopic.values()).flat().length;

  return (
    <div>
      <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100 mb-1">
        How do you stand on these statements?
      </h2>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-5">
        Skip anything you don&rsquo;t have a view on. Statements on your{" "}
        <strong>priority topics</strong> appear first.
      </p>

      <div className="sticky top-16 z-10 -mx-4 px-4 py-2 bg-white/95 dark:bg-zinc-900/95 backdrop-blur border-b border-gray-200 dark:border-zinc-800 mb-4">
        <div className="flex justify-between text-xs text-gray-500 dark:text-gray-400 mb-1">
          <span>
            {answered} of {total} answered
          </span>
          <button
            type="button"
            onClick={onNext}
            disabled={answered === 0}
            className="text-red-700 font-medium hover:underline disabled:text-gray-300 disabled:no-underline"
          >
            See results &rarr;
          </button>
        </div>
        <div className="h-1 bg-gray-100 dark:bg-zinc-800 rounded-full overflow-hidden">
          <div
            className="h-full bg-red-700 transition-all"
            style={{ width: `${total > 0 ? (answered / total) * 100 : 0}%` }}
          />
        </div>
      </div>

      <div className="space-y-6">
        {sortedTopics.map((topic) => {
          const isPriority = priorities.includes(topic);
          return (
            <section key={topic}>
              <h3 className="text-sm font-semibold uppercase tracking-wide mb-2 flex items-center gap-2">
                <span className="text-gray-700 dark:text-gray-300">{topic}</span>
                {isPriority && (
                  <span className="text-[10px] bg-red-700 text-white px-1.5 py-0.5 rounded">
                    Priority {priorities.indexOf(topic) + 1}
                  </span>
                )}
              </h3>
              <div className="space-y-2">
                {questionsByTopic.get(topic)!.map((q) => (
                  <QuestionCard
                    key={q.question_id}
                    question={q}
                    answer={answers[q.question_id]}
                    onAnswer={(a) => onAnswer(q.question_id, a)}
                  />
                ))}
              </div>
            </section>
          );
        })}
      </div>

      <div className="flex justify-between mt-8">
        <button
          type="button"
          onClick={onBack}
          className="px-4 py-2 text-gray-500 dark:text-gray-400 hover:text-red-700"
        >
          &larr; Back
        </button>
        <button
          type="button"
          onClick={onNext}
          disabled={answered === 0}
          className="px-5 py-2.5 bg-red-700 text-white rounded-lg hover:bg-red-800 disabled:bg-gray-300 disabled:cursor-not-allowed font-medium"
        >
          Next: constituency &rarr;
        </button>
      </div>
    </div>
  );
}

function QuestionCard({
  question,
  answer,
  onAnswer,
}: {
  question: Question;
  answer: Answer | undefined;
  onAnswer: (a: Answer) => void;
}) {
  return (
    <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-lg p-4">
      <p className="font-medium text-gray-900 dark:text-gray-100 mb-1">
        {question.statement}
      </p>
      {question.explainer && (
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
          {question.explainer}
        </p>
      )}
      <div className="grid grid-cols-4 gap-2">
        {(["agree", "neutral", "disagree", "skip"] as Answer[]).map((a) => (
          <button
            key={a}
            type="button"
            onClick={() => onAnswer(a)}
            className={`px-2 py-2 text-xs rounded-md border font-medium transition-colors ${
              answer === a
                ? a === "agree"
                  ? "border-green-500 bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-300"
                  : a === "disagree"
                  ? "border-red-500 bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-300"
                  : a === "neutral"
                  ? "border-amber-500 bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300"
                  : "border-gray-400 bg-gray-100 dark:bg-zinc-800 text-gray-600 dark:text-gray-300"
                : "border-gray-200 dark:border-zinc-700 text-gray-500 dark:text-gray-400 hover:border-red-300"
            }`}
          >
            {a === "agree"
              ? "Agree"
              : a === "neutral"
              ? "Neutral"
              : a === "disagree"
              ? "Disagree"
              : "Skip"}
          </button>
        ))}
      </div>
    </div>
  );
}

function ConstituencyStep({
  value,
  onChange,
  onBack,
  onSubmit,
  submitting,
}: {
  value: string;
  onChange: (v: string) => void;
  onBack: () => void;
  onSubmit: () => void;
  submitting: boolean;
}) {
  const parishes = [
    "St Helier",
    "St Saviour",
    "St Brelade",
    "St Clement",
    "St Lawrence",
    "Trinity",
    "Grouville",
    "St Peter",
    "St Ouen",
    "St John",
    "St Martin",
    "St Mary",
  ];

  return (
    <div>
      <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100 mb-1">
        Where do you vote? (optional)
      </h2>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-2">
        Choose your parish to filter results to candidates you can actually
        vote for: <strong>1 Connétable</strong>, <strong>2&ndash;4 Deputies</strong>{" "}
        (depending on your constituency), and <strong>up to 9 Senators</strong>{" "}
        (island-wide). Skip to see all 92 candidates ranked.
      </p>
      <p className="text-xs text-gray-500 dark:text-gray-400 mb-5">
        Not sure which constituency you&rsquo;re in?{" "}
        <a
          href="https://www.vote.je/constituency-finder/"
          target="_blank"
          rel="noopener noreferrer"
          className="text-red-700 underline hover:no-underline"
        >
          Look up by postcode on vote.je
        </a>
        .
      </p>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mb-6">
        {parishes.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => onChange(p === value ? "" : p)}
            className={`px-3 py-2 rounded-md border text-sm transition-colors ${
              value === p
                ? "border-red-700 bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-300 font-medium"
                : "border-gray-200 dark:border-zinc-700 text-gray-700 dark:text-gray-300 hover:border-red-300"
            }`}
          >
            {p}
          </button>
        ))}
      </div>

      <div className="flex justify-between">
        <button
          type="button"
          onClick={onBack}
          className="px-4 py-2 text-gray-500 dark:text-gray-400 hover:text-red-700"
        >
          &larr; Back
        </button>
        <button
          type="button"
          onClick={onSubmit}
          disabled={submitting}
          className="px-6 py-3 bg-red-700 text-white rounded-lg hover:bg-red-800 disabled:bg-gray-300 disabled:cursor-not-allowed font-semibold"
        >
          {submitting ? "Calculating&hellip;" : "See my matches"}
        </button>
      </div>
    </div>
  );
}

function ResultsView({
  payload,
  onRetake,
}: {
  payload: ResultsPayload;
  onRetake: () => void;
}) {
  const top = payload.results[0];
  return (
    <div>
      {top ? (
        <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-xl p-6 mb-6 text-center">
          <p className="text-sm text-gray-500 dark:text-gray-400 mb-1">
            Your closest match{payload.constituency ? ` in ${payload.constituency}` : ""}:
          </p>
          <Link
            href={`/candidates/${top.slug}`}
            onClick={() =>
              trackEvent("candidate_quiz_result_clicked", {
                rank: 1,
                slug: top.slug,
                name: top.name,
                match_pct: Math.round(top.match * 100),
                from: "top_match",
              })
            }
            className="text-3xl font-bold text-red-700 hover:underline"
          >
            {top.name}
          </Link>
          <p className="text-gray-500 dark:text-gray-400 mt-1 text-sm">
            {[top.role, top.constituency ?? (top.role === "Senator" ? "island-wide" : null)]
              .filter(Boolean)
              .join(" — ")}
          </p>
          <p className="text-5xl font-bold text-green-600 mt-4">
            {Math.round(top.match * 100)}%
          </p>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            agreement on policy &middot; {top.matched_questions}/{top.answered_questions}{" "}
            of your answers matched
          </p>
          <BreakdownTriple T={top.T} S={top.S} C={top.C} className="mt-4 justify-center" />
          {top.low_coverage && (
            <p className="text-xs text-amber-600 dark:text-amber-400 mt-3 max-w-md mx-auto">
              <strong>Low coverage:</strong> this candidate&rsquo;s manifesto
              didn&rsquo;t address most of your priority areas. The score is
              based on limited information.
            </p>
          )}
        </div>
      ) : (
        <div className="bg-amber-50 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-800 rounded-xl p-6">
          <p className="font-semibold mb-1">No candidates matched.</p>
          <p className="text-sm">
            Try removing the constituency filter to see all candidates.
          </p>
        </div>
      )}

      <h2 className="text-xl font-bold mb-3 text-gray-900 dark:text-gray-100">
        All candidates ranked
      </h2>
      <div className="space-y-2">
        {payload.results.map((r, i) => (
          <Link
            key={r.candidate_id}
            href={`/candidates/${r.slug}`}
            onClick={() =>
              trackEvent("candidate_quiz_result_clicked", {
                rank: i + 1,
                slug: r.slug,
                name: r.name,
                match_pct: Math.round(r.match * 100),
                from: "ranked_list",
              })
            }
            className="flex items-center gap-3 bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-lg p-3 hover:border-red-300 transition-colors"
          >
            <span className="w-6 text-right text-sm font-bold text-gray-400">
              {i + 1}
            </span>
            <div className="w-10 h-10 flex-shrink-0 rounded-md overflow-hidden bg-gray-100 dark:bg-zinc-800">
              {r.photo_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={r.photo_url}
                  alt={r.name}
                  className="w-full h-full object-cover"
                  loading="lazy"
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-gray-400">
                  {r.name.charAt(0)}
                </div>
              )}
            </div>
            <div className="flex-1 min-w-0">
              <p className="font-medium text-gray-900 dark:text-gray-100 truncate text-sm">
                {r.name}
                {r.is_incumbent && (
                  <span className="ml-2 text-[10px] bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-300 px-1.5 py-0.5 rounded">
                    Incumbent
                  </span>
                )}
                {r.low_coverage && (
                  <span className="ml-2 text-[10px] bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 px-1.5 py-0.5 rounded">
                    Low coverage
                  </span>
                )}
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                {[
                  r.role,
                  r.constituency ?? (r.role === "Senator" ? "island-wide" : null),
                  r.party,
                ]
                  .filter(Boolean)
                  .join(" — ")}
              </p>
            </div>
            <div className="text-right">
              <p
                className={`text-lg font-bold ${
                  r.match >= 0.7
                    ? "text-green-600"
                    : r.match >= 0.5
                    ? "text-amber-600"
                    : "text-red-600"
                }`}
              >
                {Math.round(r.match * 100)}%
              </p>
              <p className="text-[10px] text-gray-400">
                T {Math.round(r.T * 100)} · S {Math.round(r.S * 100)} · C{" "}
                {Math.round(r.C * 100)}
              </p>
            </div>
          </Link>
        ))}
      </div>

      <div className="mt-8 text-center">
        <button
          type="button"
          onClick={onRetake}
          className="px-6 py-3 bg-red-700 text-white rounded-lg hover:bg-red-800 font-semibold"
        >
          Retake quiz
        </button>
        <p className="mt-3 text-xs text-gray-500 dark:text-gray-400">
          <Link
            href="/candidates/methodology"
            onClick={() =>
              trackEvent("candidate_quiz_methodology_clicked", { from: "results" })
            }
            className="underline hover:text-red-700"
          >
            How are these scores calculated?
          </Link>
        </p>
      </div>
    </div>
  );
}

function BreakdownTriple({
  T,
  S,
  C,
  className = "",
}: {
  T: number;
  S: number;
  C: number;
  className?: string;
}) {
  return (
    <div className={`flex gap-4 text-xs text-gray-500 dark:text-gray-400 ${className}`}>
      <span>
        <span className="font-semibold text-gray-700 dark:text-gray-300">
          T {Math.round(T * 100)}%
        </span>{" "}
        priority overlap
      </span>
      <span>
        <span className="font-semibold text-gray-700 dark:text-gray-300">
          S {Math.round(S * 100)}%
        </span>{" "}
        stance alignment
      </span>
      <span>
        <span className="font-semibold text-gray-700 dark:text-gray-300">
          C {Math.round(C * 100)}%
        </span>{" "}
        coverage
      </span>
    </div>
  );
}
