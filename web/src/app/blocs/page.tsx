import type { Metadata } from "next";
import { BlocsChart } from "./chart";

export const metadata: Metadata = {
  title: "Voting Blocs",
  description:
    "Discover informal voting coalitions in the Jersey States Assembly. Members positioned by how they actually vote — not by party or label.",
};

export default function BlocsPage() {
  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <h1 className="text-3xl font-bold mb-2">Voting Blocs</h1>
      <p className="text-gray-600 mb-8 max-w-3xl">
        This chart shows where each member sits politically, based entirely on
        how they actually vote. Members who vote the same way appear close
        together; members who frequently disagree are far apart.
      </p>

      <BlocsChart />

      {/* Explanation section */}
      <div className="mt-12 max-w-3xl bg-white rounded-lg border border-gray-200 p-8 space-y-6">
        <h2 className="text-xl font-bold text-gray-900">How to read this chart</h2>

        <div className="space-y-4 text-gray-700">
          <div>
            <h3 className="font-semibold text-gray-900">
              What are the axes?
            </h3>
            <p>
              The axes are not pre-defined labels like &ldquo;left&rdquo; or
              &ldquo;right&rdquo;. They are calculated mathematically from every
              Principles and Third Reading vote in the current term
              (2022&ndash;present).
            </p>
            <p className="mt-2">
              <strong>Main voting divide</strong> (horizontal): This captures
              the single biggest pattern of disagreement in the Assembly.
              Members on opposite ends of this axis vote against each other most
              often. Think of it as the primary fault line in the chamber.
            </p>
            <p className="mt-2">
              <strong>Secondary voting divide</strong> (vertical): Politics
              isn&apos;t one-dimensional. Two members might agree on the main
              divide but still disagree on other issues. The vertical axis
              captures this second, independent pattern of disagreement. For
              example, members might align on economic issues but split on
              social or constitutional questions. Together, the two axes create
              a map showing the full picture of who agrees with whom.
            </p>
          </div>

          <div>
            <h3 className="font-semibold text-gray-900">
              What do the colours mean?
            </h3>
            <p>
              Members are grouped into blocs using clustering &mdash; an
              algorithm that finds natural groupings based on voting similarity.
              Members in the same colour bloc vote together most of the time.
              These blocs are not political parties; they are informal coalitions
              that emerge from the data.
            </p>
          </div>

          <div>
            <h3 className="font-semibold text-gray-900">
              Why do some members sit alone?
            </h3>
            <p>
              A member far from any cluster has a unique voting pattern that
              doesn&apos;t consistently align with any group. This could mean
              they vote independently, have low participation (making their
              position less certain), or hold a distinctive mix of views.
            </p>
          </div>

          <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm">
            <p className="font-semibold text-gray-900 mb-1">Methodology</p>
            <p>
              Positions are calculated using{" "}
              <a
                href="https://en.wikipedia.org/wiki/Principal_component_analysis"
                target="_blank"
                rel="noopener noreferrer"
                className="text-red-700 hover:underline"
              >
                Principal Component Analysis (PCA)
              </a>{" "}
              on the member-vote matrix. Each member&apos;s votes on Principles
              and Third Reading divisions are encoded as +1 (Pour) or -1
              (Contre). PCA finds the directions of greatest variation in this
              data. Blocs are identified using k-means clustering on the
              resulting coordinates. Only the current term (July 2022 onwards)
              is included.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
