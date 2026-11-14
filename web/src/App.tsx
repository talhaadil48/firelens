import { useEffect, useState } from 'react'
import CoverageMap from './CoverageMap'
import { getInvestigations, getMeta, getProfiles } from './client'
import type { Investigation, Meta, ProfileConfig } from './client'

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [records, setRecords] = useState<Investigation[]>([])
  const [profiles, setProfiles] = useState<ProfileConfig | null>(null)
  const [profile, setProfile] = useState('iss')
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([getMeta(controller.signal), getInvestigations(controller.signal), getProfiles(controller.signal)])
      .then(([status, list, config]) => { setMeta(status); setRecords(list.items); setProfiles(config) })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Could not load workspace')
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [])

  const visible = records.filter(item => `${item.title} ${item.accession}`.toLowerCase().includes(query.toLowerCase()))
  const selected = profiles?.profiles.find(item => item.id === profile)
  return <>
    <a className="skip-link" href="#main">Skip to research workspace</a>
    <header><a href="/" className="wordmark">Fire<span>Lens</span></a><span className="badge">Phase 2 · contract preview</span></header>
    <main id="main">
      <p className="eyebrow">MICROGRAVITY FIRE INTELLIGENCE</p>
      <h1>Find the evidence.<br /><span>Understand the conditions.</span></h1>
      <p className="intro">A research workspace for NASA combustion studies. Explore source-linked records before drawing conclusions.</p>
      <aside className="notice"><strong>Development fixtures</strong> — titles and identifiers come from NASA PSI. No reviewed experiment measurements, AI answers or relevance scores are available yet.</aside>
      {loading && <p role="status">Loading the research workspace…</p>}
      {error && <p role="alert" className="notice">{error}. Check your API URL or use VITE_DATA_MODE=mock.</p>}
      {meta && <p className="metadata">{meta.investigation_count} investigations · {meta.test_count} normalized tests · Snapshot {meta.snapshot_id}</p>}
      {profiles && <section aria-labelledby="scenario-heading">
        <h2 id="scenario-heading">Explore a scenario</h2>
        <label htmlFor="profile">Illustrative mission profile</label>
        <select id="profile" value={profile} onChange={event => setProfile(event.target.value)}>
          {profiles.profiles.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select>
        {selected && <p className="muted">{selected.description} No safety recommendation is implied.</p>}
      </section>}
      <section aria-labelledby="studies-heading">
        <div className="section-heading"><h2 id="studies-heading">Investigation library</h2><span className="muted">Real metadata / mock API</span></div>
        <label htmlFor="search">Search titles or PSI IDs</label>
        <input id="search" type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Try FLEX, BASS, or PSI-159" />
        <div className="cards">{visible.map(item => <article key={item.accession}>
          <p className="eyebrow">{item.accession} <span className="tag">METADATA ONLY</span></p>
          <h3>{item.title}</h3>
          <p className="muted">{item.research_area} · version {item.version}</p>
          <a href={item.source_url} target="_blank" rel="noreferrer">Open NASA source ↗</a>
        </article>)}</div>
        {!loading && !error && !visible.length && <p role="status">No investigations match your search.</p>}
      </section>
      <section aria-labelledby="coverage-heading"><h2 id="coverage-heading">Evidence coverage</h2><CoverageMap tests={[]} /></section>
    </main>
    <footer>Source: NASA Physical Sciences Informatics · Independent Space Apps project · AI-assisted development disclosed in the repository</footer>
  </>
}
