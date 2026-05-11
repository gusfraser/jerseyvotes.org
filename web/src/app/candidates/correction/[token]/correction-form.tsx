"use client";

import { useState } from "react";

export function CorrectionForm({ token }: { token: string }) {
  const [body, setBody] = useState("");
  const [contact, setContact] = useState("");
  const [status, setStatus] = useState<"idle" | "submitting" | "sent" | "error">("idle");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!body.trim()) return;
    setStatus("submitting");
    try {
      const resp = await fetch(`/api/candidates/correction/${token}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body, contact }),
      });
      if (!resp.ok) throw new Error("Submission failed");
      setStatus("sent");
      setBody("");
      setContact("");
    } catch {
      setStatus("error");
    }
  }

  if (status === "sent") {
    return (
      <div className="bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-800 rounded-lg p-4 text-sm text-green-800 dark:text-green-200">
        Thanks — your correction has been logged. We&rsquo;ll review and update
        within 24 hours.
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div>
        <label
          htmlFor="contact"
          className="block text-xs text-gray-500 dark:text-gray-400 mb-1"
        >
          Your email (optional, so we can follow up)
        </label>
        <input
          id="contact"
          type="email"
          value={contact}
          onChange={(e) => setContact(e.target.value)}
          className="w-full px-3 py-2 rounded-md border border-gray-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-sm text-gray-900 dark:text-gray-100"
        />
      </div>
      <div>
        <label
          htmlFor="body"
          className="block text-xs text-gray-500 dark:text-gray-400 mb-1"
        >
          What&rsquo;s wrong, and what should it say?
        </label>
        <textarea
          id="body"
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={6}
          required
          className="w-full px-3 py-2 rounded-md border border-gray-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-sm text-gray-900 dark:text-gray-100"
          placeholder="Example: On the housing statement about binding affordable targets, my manifesto actually supports binding targets — see paragraph 3."
        />
      </div>
      <div className="flex items-center justify-between">
        {status === "error" && (
          <p className="text-sm text-red-700">Something went wrong. Please try again or email gus@blockchain.je.</p>
        )}
        <button
          type="submit"
          disabled={status === "submitting" || !body.trim()}
          className="ml-auto px-5 py-2 bg-red-700 text-white rounded-md hover:bg-red-800 disabled:bg-gray-300 font-medium text-sm"
        >
          {status === "submitting" ? "Sending…" : "Send correction"}
        </button>
      </div>
    </form>
  );
}
