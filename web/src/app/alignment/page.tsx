import { AlignmentHeatmap } from "./heatmap";

export default function AlignmentPage() {
  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <h1 className="text-3xl font-bold mb-2">Alignment Matrix</h1>
      <p className="text-gray-600 mb-8 max-w-3xl">
        How often do each pair of members vote the same way? This heatmap shows
        pairwise agreement between all active members during the current term
        (2022&ndash;present). Green means high agreement, red means low. Hover
        over a cell to see the exact percentage.
      </p>
      <p className="md:hidden text-sm text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 mb-6">
        This heatmap is best viewed on a laptop or desktop screen.
      </p>
      <AlignmentHeatmap />
      <div className="mt-8 bg-white rounded-lg border border-gray-200 p-6 max-w-3xl text-sm text-gray-600">
        <p className="font-semibold text-gray-900 mb-1">What votes are included?</p>
        <p>
          Only the most meaningful votes are used: when the Assembly first
          decides whether to support a proposal in principle, and the final vote
          to pass it into law. Routine procedural votes, individual article
          amendments, and paragraph-by-paragraph votes are excluded, as they add
          noise without revealing genuine policy positions.
        </p>
      </div>
    </div>
  );
}
