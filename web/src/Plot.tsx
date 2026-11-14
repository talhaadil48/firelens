import createPlotlyComponent from 'react-plotly.js/factory'
import Plotly from 'plotly.js-basic-dist-min'
import type { TestRow } from './client'

const Plot = createPlotlyComponent(Plotly)

export default function CoveragePlot({ tests }: { tests: TestRow[] }) {
  return <Plot
    data={[{
      type: 'scatter', mode: 'markers',
      x: tests.map(row => row.o2_fraction == null ? null : row.o2_fraction * 100),
      y: tests.map(row => row.pressure_kpa ?? null),
      text: tests.map(row => `${row.accession}: ${row.test_id}`),
      marker: { color: '#63caff', size: 9 },
    }]}
    layout={{
      title: { text: 'Reviewed experimental coverage' },
      xaxis: { title: { text: 'Oxygen (%)' } }, yaxis: { title: { text: 'Pressure (kPa)' } },
      paper_bgcolor: '#101e2c', plot_bgcolor: '#101e2c', font: { color: '#edf4f8' }, autosize: true,
    }}
    config={{ responsive: true, displaylogo: false }}
    useResizeHandler style={{ width: '100%', height: 360 }}
  />
}
