import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import CoverageMap from './CoverageMap'
import { getInvestigations, getMeta, getProfiles, getRank } from './client'
import type { Investigation, Meta, ProfileConfig, RankResponse } from './client'

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [records, setRecords] = useState<Investigation[]>([])
  const [profiles, setProfiles] = useState<ProfileConfig | null>(null)
  const [profile, setProfile] = useState('iss')
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [custom, setCustom] = useState({ oxygen: '', pressure: '', flow: '', gravity: '' })
  const [customResult, setCustomResult] = useState<RankResponse | null>(null)
  const [customError, setCustomError] = useState('')
  const [customLoading, setCustomLoading] = useState(false)

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

  async function applyCustom(event: FormEvent) {
    event.preventDefault()
    setCustomError('')
    setCustomResult(null)
    if (!custom.oxygen.trim() || !custom.pressure.trim()) {
      setCustomError('Enter oxygen and pressure.')
      return
    }
    setCustomLoading(true)
    try {
      const result = await getRank('custom', {
        o2_fraction: Number(custom.oxygen) / 100,
        pressure_kpa: Number(custom.pressure),
        ...(custom.flow.trim() ? { flow_cm_s: Number(custom.flow) } : {}),
        ...(custom.gravity.trim() ? { gravity_level_g: Number(custom.gravity) } : {}),
      })
      setCustomResult(result)
    } catch (reason) {
      setCustomError(reason instanceof Error ? reason.message : 'Could not apply custom conditions')
    } finally { setCustomLoading(false) }
  }

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
        <select id="profile" value={profile} onChange={event => { setProfile(event.target.value); setCustomResult(null); setCustomError('') }}>
          {profiles.profiles.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select>
        {profile === 'custom' && <form onSubmit={applyCustom} aria-label="Custom environment conditions">
          <div className="custom-grid">
            <div><label htmlFor="custom-oxygen">Oxygen (%)</label><input id="custom-oxygen" type="number" min="0" max="100" step="any" required value={custom.oxygen} onChange={e => setCustom({ ...custom, oxygen: e.target.value })} /></div>
            <div><label htmlFor="custom-pressure">Pressure (kPa)</label><input id="custom-pressure" type="number" min="0.000001" step="any" required value={custom.pressure} onChange={e => setCustom({ ...custom, pressure: e.target.value })} /></div>
            <div><label htmlFor="custom-flow">Airflow (cm/s, optional)</label><input id="custom-flow" type="number" min="0" step="any" value={custom.flow} onChange={e => setCustom({ ...custom, flow: e.target.value })} /></div>
            <div><label htmlFor="custom-gravity">Gravity (g, optional)</label><input id="custom-gravity" type="number" min="0" step="any" value={custom.gravity} onChange={e => setCustom({ ...custom, gravity: e.target.value })} /></div>
          </div>
          <button type="submit" disabled={customLoading}>{customLoading ? 'Applying…' : 'Apply custom conditions'}</button>
          {customError && <p role="alert">{customError}</p>}
          {customResult && <p role="status">Applied: {Number(customResult.profile.oxygen.minimum) * 100}% O2 · {customResult.profile.pressure.minimum} kPa. Scores remain unavailable until evidence is reviewed.</p>}
        </form>}
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
