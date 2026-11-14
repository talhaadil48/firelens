import { lazy, Suspense } from 'react'
import type { TestRow } from './client'

const Plot = lazy(() => import('./Plot'))

export default function CoverageMap({ tests }: { tests: TestRow[] }) {
  const reviewed = tests.filter(row =>
    row.evidence_type === 'measurement' && row.review_status === 'reviewed' &&
    !row.provenance.is_mock && row.oxygen_fraction != null && row.pressure_kpa != null,
  )
  if (!reviewed.length) return (
    <div className="empty-state" role="status">
      <strong>No reviewed measurement points yet</strong>
      <p>The coverage map will appear after normalization and science review. Raw CSV rows are not plotted as validated tests.</p>
    </div>
  )
  return <Suspense fallback={<p role="status">Loading chart…</p>}><Plot tests={reviewed} /></Suspense>
}
