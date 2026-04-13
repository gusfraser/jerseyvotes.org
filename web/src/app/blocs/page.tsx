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

          <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm space-y-3">
            <p className="font-semibold text-gray-900">Methodology &amp; assumptions</p>

            <div>
              <p className="font-medium text-gray-800 mb-1">Which votes are included</p>
              <p className="text-gray-700">
                Only <strong>Principles</strong> and <strong>Third Reading</strong>{" "}divisions from the current term (July 2022&ndash;present) are used. These are the votes that best represent a member&rsquo;s genuine policy stance &mdash; they are the key decisions on whether a proposition should proceed and what its final form should be.
              </p>
              <p className="text-gray-700 mt-1">
                <strong>Excluded:</strong> Amendment votes, procedural motions, paragraph-by-paragraph votes, and Articles votes. These are excluded because they often reflect tactical or procedural considerations rather than overall policy position, and including them adds noise.
              </p>
            </div>

            <div>
              <p className="font-medium text-gray-800 mb-1">How absences are handled</p>
              <p className="text-gray-700">
                Only <strong>Pour</strong> and <strong>Contre</strong>{" "}votes are used in the analysis. If a member was absent, excused, or abstained on a vote, that division is simply not counted for them &mdash; it doesn&rsquo;t push them toward any position. Members with fewer votes will have less reliable positions on the chart.
              </p>
            </div>

            <div>
              <p className="font-medium text-gray-800 mb-1">The 5-bloc grouping</p>
              <p className="text-gray-700">
                The number of blocs (5) is fixed. The algorithm finds the best 5-group split of the data &mdash; it does not determine how many groups there &ldquo;should&rdquo; be. The data may naturally contain fewer or more clusters; 5 was chosen as a reasonable starting point for a chamber of 49.
              </p>
            </div>

            <div>
              <p className="font-medium text-gray-800 mb-1">Technical approach</p>
              <p className="text-gray-700">
                Positions are calculated using{" "}
                <a
                  href="https://en.wikipedia.org/wiki/Principal_component_analysis"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-red-700 hover:underline"
                >
                  Principal Component Analysis (PCA)
                </a>{" "}
                on the member-vote matrix (Pour = +1, Contre = &minus;1, absent/abstained = not included). PCA finds the directions of greatest variation. Blocs are then identified using k-means clustering on the two-dimensional coordinates.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
