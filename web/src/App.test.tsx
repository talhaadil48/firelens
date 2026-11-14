import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import App from './App'
import CoverageMap from './CoverageMap'
import { ask, getCompare, getRank } from './client'
import type { FixtureBundle } from './client'

const fixture = JSON.parse(readFileSync('public/fixtures.json', 'utf8')) as FixtureBundle

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => fixture }))
})

describe('Phase 2 preview', () => {
  it('shows real metadata and explicitly states the mock boundary', async () => {
    render(<App />)
    expect(await screen.findByText('Flame Extinguishment Experiment')).toBeInTheDocument()
    expect(screen.getByText(/No reviewed experiment measurements/)).toBeInTheDocument()
    expect(screen.getByText(/5 investigations · 0 normalized tests/)).toBeInTheDocument()
    const links = screen.getAllByRole('link', { name: /Open NASA source/ })
    expect(links).toHaveLength(5)
    expect(links.every(link => link.getAttribute('href')?.startsWith('https://psi.nasa.gov/'))).toBe(true)
  })

  it('filters records and handles an empty search', async () => {
    render(<App />)
    await screen.findByText('Flame Extinguishment Experiment')
    fireEvent.change(screen.getByLabelText('Search titles or PSI IDs'), { target: { value: 'PSI-69' } })
    expect(screen.getAllByRole('link', { name: /Open NASA source/ })).toHaveLength(1)
    fireEvent.change(screen.getByLabelText('Search titles or PSI IDs'), { target: { value: 'missing-study' } })
    expect(screen.getByText('No investigations match your search.')).toBeInTheDocument()
  })

  it('reports request failures rather than displaying invented records', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 }))
    render(<App />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Request failed (503)')
    expect(screen.queryByRole('link', { name: /Open NASA source/ })).not.toBeInTheDocument()
  })

  it('does not plot points when there are no reviewed measurements', () => {
    render(<CoverageMap tests={[]} />)
    expect(screen.getByRole('status')).toHaveTextContent('No reviewed measurement points yet')
  })

  it('switches illustrative scenarios without suggesting validation', async () => {
    render(<App />)
    await screen.findByText('Flame Extinguishment Experiment')
    fireEvent.change(screen.getByLabelText('Illustrative mission profile'), { target: { value: 'rover' } })
    await waitFor(() => expect(screen.getByText(/not a NASA vehicle requirement/)).toBeInTheDocument())
  })
})

describe('offline client contracts', () => {
  it('does not manufacture relevance scores', async () => {
    const rank = await getRank('moon_base')
    expect(rank.profile.id).toBe('moon_base')
    expect(rank.items.every(item => item.score === null)).toBe(true)
  })

  it('rejects duplicate comparisons', async () => {
    await expect(getCompare(['PSI-26', 'PSI-26'])).rejects.toThrow('distinct')
  })

  it('streams an explicit insufficient-evidence result', async () => {
    const events = []
    for await (const event of ask('Which material is safest?')) events.push(event)
    expect(events.map(event => event.event)).toEqual(['progress', 'answer', 'done'])
    expect(events[1].data).toMatchObject({ status: 'insufficient_evidence', citations: [] })
  })
})
