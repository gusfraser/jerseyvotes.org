# Manual manifestos

This folder holds manifestos supplied directly to Jerseyvotes.org by candidates
who don't publish anything substantial online — they campaign through social
media posts, printed leaflets, hustings handouts, or by sending a document
straight to us. Source files are checked into git so anyone can audit exactly
what was supplied and what text was derived from it.

## Adding a candidate

1. Create a folder named after the candidate's `vote.je` slug — the URL
   segment on their vote.je profile, which matches `candidates.vote_je_slug`
   in the database. For example `https://www.vote.je/candidates/jane-doe-2`
   becomes:

   ```
   pipeline/manual_manifestos/jane-doe-2/
   ```

2. Drop the supplied files into that folder. Supported formats:

   | Extension                              | Handled by                                       |
   | -------------------------------------- | ------------------------------------------------ |
   | `.pdf`                                 | Claude PDF (multi-column-aware; see `extract_pdf_claude.py`) |
   | `.docx`                                | `python-docx`                                    |
   | `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp` | Claude vision (scanned pages, social-media screenshots) |
   | `.txt`, `.md`                          | Read directly as UTF-8                           |

   Use whatever filenames make the source obvious — `pinned-facebook-post-2026-05-22.png`,
   `manifesto.docx`, `hustings-handout-p1.jpg`, etc.

3. Add a `metadata.yaml` next to the files describing where this came from:

   ```yaml
   candidate_slug: jane-doe-2          # required — must match vote_je_slug
   source_label: manually_supplied     # see "Source labels" below
   note: |
     Word document emailed by candidate on 22 May 2026. Confirmed by
     reply this is her current platform for the 2026 election.

   # Optional — set if the same document is also publicly viewable somewhere
   # (e.g. a candidate's public Facebook post). Used as the source URL on
   # the candidate's profile page instead of the GitHub folder URL.
   # original_url: https://www.facebook.com/jane.doe/posts/1234567890

   # Optional — explicit ordered list of files to process. Defaults to all
   # supported files in this folder in lexicographic order.
   # files:
   #   - manifesto.docx
   #   - addendum.pdf
   ```

4. Run the ingest script (from the repo root):

   ```bash
   python pipeline/ingest_manual_manifestos.py --slug jane-doe-2
   ```

   It extracts text from each file, writes the combined result to
   `extracted.txt` in the candidate's folder, and updates
   `candidates.enhanced_manifesto_*` for that slug. Re-runs reuse
   `extracted.txt` — pass `--no-cache` if you want to re-extract.

5. Commit everything — source files, `metadata.yaml`, and `extracted.txt` —
   so the audit trail is in git history. Then refresh the topic / stance
   analysis:

   ```bash
   python pipeline/classify_candidates.py --name "Jane Doe"
   ```

   `classify_candidates.py` already detects that `enhanced_manifesto_fetched_at`
   is newer than `classified_at` and re-runs that candidate, so a no-arg run
   also works if you'd rather refresh everyone that's pending.

## Source labels

The `source_label` field surfaces in the UI on the candidate's profile page
as the provenance of the extended manifesto. Use whichever is most accurate:

- `manually_supplied` (default) — candidate or their agent sent us the
  document(s) directly. The repo folder is the authoritative source.
- `social_media_capture` — captured from a public social-media post that
  might be edited or deleted later. Set `original_url:` to the post URL.
- `printed_handout` — captured from physical leaflets or hustings handouts.

If you need a label that isn't in this list, add it both to
`MANUAL_SOURCE_LABELS` in `ingest_manual_manifestos.py` and to
`ENHANCED_SOURCE_LABELS` in `web/src/app/candidates/[slug]/page.tsx` so it
renders with a friendly name.

## Transparency invariant

The database CHECK constraint
[`enhanced_manifesto_text_must_have_source_url`](../migrations/004_manifesto_text_must_have_url.sql)
refuses to store manifesto text without a public source URL. For manually-
supplied manifestos, that URL is either:

- the `original_url` from `metadata.yaml` (preferred when the document is
  also publicly available), or
- the GitHub URL of this folder — `https://github.com/gusfraser/jerseyvotes.org/tree/main/pipeline/manual_manifestos/<slug>/` —
  so any reader can click through and see exactly which files were used.

Either way the link surfaces on the candidate profile page and on the
methodology page's transparency claim.

## Why files live in the repo and not behind a private store

Two reasons:

1. **Audit**: the methodology page promises that every word we analyse
   traces to a public document. If we only kept these privately, that
   promise would not hold.
2. **Reproducibility**: a future contributor (or sceptic) running the
   pipeline from scratch needs to see what was supplied — git history is
   the simplest way to make that available.

If a candidate doesn't want their supplied document published in the repo,
they have the same option as anyone else: use the token-gated review page
linked from their candidate profile to opt out. They'll then appear in the
candidates index as standing but not analysed.
