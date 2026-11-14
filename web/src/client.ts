import type { components } from './api.generated'

type Schema = components['schemas']
export type Meta = Schema['MetaResponse']
export type Investigation = Schema['Investigation']
export type TestRow = Schema['ExperimentalTest']
export type ProfileConfig = Schema['ProfileConfig']
export type InvestigationList = Schema['InvestigationList']
export type RankResponse = Schema['RankResponse']
export type CompareResponse = Schema['CompareResponse']
export type TestList = Schema['TestList']
export type ExportResponse = Schema['ExportResponse']

export interface FixtureBundle {
  meta: Meta
  profiles: ProfileConfig
  investigations: InvestigationList
  investigation: Investigation
  rank: RankResponse
  tests: TestList
  compare: CompareResponse
  export: ExportResponse
}

const mode = import.meta.env.VITE_DATA_MODE ?? 'mock'
const base = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')
if (!['mock', 'api'].includes(mode)) throw new Error('VITE_DATA_MODE must be mock or api')

async function fetchJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal })
  if (!response.ok) throw new Error(`Request failed (${response.status})`)
  return response.json() as Promise<T>
}

async function fixtures(signal?: AbortSignal): Promise<FixtureBundle> {
  return fetchJson<FixtureBundle>('/fixtures.json', signal)
}

export async function getMeta(signal?: AbortSignal): Promise<Meta> {
  return mode === 'api' ? fetchJson<Meta>(`${base}/meta`, signal) : (await fixtures(signal)).meta
}

export async function getProfiles(signal?: AbortSignal): Promise<ProfileConfig> {
  return mode === 'api' ? fetchJson<ProfileConfig>(`${base}/profiles`, signal) : (await fixtures(signal)).profiles
}

export async function getInvestigations(signal?: AbortSignal): Promise<InvestigationList> {
  return mode === 'api'
    ? fetchJson<InvestigationList>(`${base}/investigations`, signal)
    : (await fixtures(signal)).investigations
}

export async function getInvestigation(id: string, signal?: AbortSignal): Promise<Investigation> {
  if (mode === 'api') return fetchJson<Investigation>(`${base}/investigations/${encodeURIComponent(id)}`, signal)
  const found = (await fixtures(signal)).investigations.items.find(item => item.accession === id)
  if (!found) throw new Error(`Unknown investigation: ${id}`)
  return found
}

export async function getTests(signal?: AbortSignal): Promise<TestList> {
  return mode === 'api' ? fetchJson<TestList>(`${base}/tests`, signal) : (await fixtures(signal)).tests
}

export async function getRank(profile = 'iss', signal?: AbortSignal): Promise<RankResponse> {
  if (mode === 'api') return fetchJson<RankResponse>(`${base}/rank?profile=${encodeURIComponent(profile)}`, signal)
  const fixture = await fixtures(signal)
  const selected = fixture.profiles.profiles.find(item => item.id === profile)
  if (!selected) throw new Error(`Unknown profile: ${profile}`)
  return { ...fixture.rank, profile: selected }
}

export async function getCompare(ids: string[], signal?: AbortSignal): Promise<CompareResponse> {
  if (ids.length < 2 || ids.length > 3 || new Set(ids).size !== ids.length) {
    throw new Error('Choose 2–3 distinct investigations')
  }
  if (mode === 'api') return fetchJson<CompareResponse>(`${base}/compare?ids=${encodeURIComponent(ids.join(','))}`, signal)
  const fixture = await fixtures(signal)
  const items = ids.map(id => {
    const item = fixture.investigations.items.find(record => record.accession === id)
    if (!item) throw new Error(`Unknown investigation: ${id}`)
    return item
  })
  return {
    ...fixture.compare, investigations: items,
    different: items.map(item => `${item.accession}: ${item.title}`),
  }
}

export interface ChatEvent {
  event: 'progress' | 'answer' | 'done'
  data: Schema['ProgressEvent'] | Schema['AnswerEvent'] | Schema['DoneEvent']
}

export async function* ask(question: string, signal?: AbortSignal): AsyncGenerator<ChatEvent> {
  if (!question.trim() || question.length > 2000) throw new Error('Enter a question of 1–2000 characters')
  if (mode === 'mock') {
    yield { event: 'progress', data: { stage: 'retrieval', message: 'Offline mock; no LLM called.' } }
    yield { event: 'answer', data: {
      text: 'Insufficient evidence: no reviewed experimental findings in this Phase 2 fixture.',
      status: 'insufficient_evidence', mode: 'mock', citations: [],
    } }
    yield { event: 'done', data: { finish_reason: 'insufficient_evidence' } }
    return
  }
  const response = await fetch(`${base}/chat`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, investigation_ids: [] }), signal,
  })
  if (!response.ok || !response.body) throw new Error(`Chat failed (${response.status})`)
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let pending = ''
  try {
    while (true) {
      const chunk = await reader.read()
      if (chunk.done) break
      pending += decoder.decode(chunk.value, { stream: true })
      // Server emits LF-delimited SSE. Decode UTF-8 across arbitrary network chunks.
      let boundary: number
      while ((boundary = pending.indexOf('\n\n')) >= 0) {
        const frame = pending.slice(0, boundary)
        pending = pending.slice(boundary + 2)
        const event = frame.split('\n').find(line => line.startsWith('event: '))?.slice(7)
        const data = frame.split('\n').filter(line => line.startsWith('data: ')).map(line => line.slice(6)).join('\n')
        if (event && ['progress', 'answer', 'done'].includes(event) && data) {
          yield { event: event as ChatEvent['event'], data: JSON.parse(data) as ChatEvent['data'] }
        }
      }
    }
  } finally {
    await reader.cancel()
    reader.releaseLock()
  }
}
