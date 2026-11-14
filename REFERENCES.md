# References and attribution

## NASA data

NASA Physical Sciences Informatics (PSI), accessed 2026-11-14:
https://psi.nasa.gov/physci/repo/search?data_source=psi&data_type=investigation&q=combustion

| Accession | Investigation | Public record |
| --- | --- | --- |
| PSI-26 | Burning and Suppression of Solids | https://psi.nasa.gov/physci/repo/data/investigations/PSI-26 |
| PSI-25 | Burning and Suppression of Solids – II | https://psi.nasa.gov/physci/repo/data/investigations/PSI-25 |
| PSI-69 | Flame Extinguishment Experiment | https://psi.nasa.gov/physci/repo/data/investigations/PSI-69 |
| PSI-159 | ACME / Cool Flames Investigation with Gases | https://psi.nasa.gov/physci/repo/data/investigations/PSI-159 |
| PSI-100 | Spacecraft Fire Experiment – III | https://psi.nasa.gov/physci/repo/data/investigations/PSI-100 |

Machine-readable retrieval dates, manifest hashes and licenses are recorded in
`docs/context/source-inventory.json`. DOI fields stay null until a reliable source
mapping is reviewed; none are invented. PSI's portal backend is a discovered
integration, not a confirmed stable public API contract.

Challenge: https://www.spaceappschallenge.org/2026/challenges/flame-in-freefall/
NASA combustion background:
https://www.nasa.gov/glenn/glenn-expertise-space-exploration/physical-sciences-program/combustion-science/
NASA NTRS API: https://ntrs.nasa.gov/api/openapi/

## Software

- Python https://www.python.org/ ; uv https://docs.astral.sh/uv/
- FastAPI https://fastapi.tiangolo.com/ ; Pydantic https://docs.pydantic.dev/
- Pandas https://pandas.pydata.org/ ; Pandera https://pandera.readthedocs.io/
- React https://react.dev/ ; Vite https://vite.dev/
- TypeScript https://www.typescriptlang.org/ ; Tailwind https://tailwindcss.com/
- Plotly https://plotly.com/javascript/ ; Vitest https://vitest.dev/
- Ruff https://docs.astral.sh/ruff/ ; pytest https://docs.pytest.org/

Full dependency versions are in `uv.lock` and `web/package-lock.json`; their licenses
remain with their owners. No remote fonts, NASA logos, stock imagery, paid services
or production models are used in Phase 2. Azure and GoDaddy are planned later,
not claimed as active integrations.
