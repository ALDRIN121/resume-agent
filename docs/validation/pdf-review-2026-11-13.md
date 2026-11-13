# Representative PDF review

Ten fictional profiles/selections produced ten released PDFs and eleven page images. All pages were inspected.

Actual Tectonic 0.15.0 and Poppler performed compilation, extraction and rendering. Each released file matched its approved PDF hash.

Source snapshots, complete display manifests, expected text, logs, canonical PDFs, exports and images remain in `task22-pdf-evidence/`.

| Case | Pages | Content and identity | Visual observation |
| --- | --- | --- | --- |
| 01-metrics | 1 | Exact approved stream and PDF hash match | No clipping, overlap or missing glyphs observed. |
| 02-latin-unicode | 1 | Exact approved stream and PDF hash match | No clipping, overlap or missing glyphs observed. |
| 03-escaped-characters | 1 | Exact approved stream and PDF hash match | No clipping, overlap or missing glyphs observed. |
| 04-skill-tokens | 1 | Exact approved stream and PDF hash match | No clipping, overlap or missing glyphs observed. |
| 05-project-omission-policy | 1 | Exact approved stream and PDF hash match | Repeated project description and first bullet are both retained from the approved source. No automatic deduplication. |
| 06-all-sections | 1 | Exact approved stream and PDF hash match | The current template presents contact fields vertically. Equal GitHub/LinkedIn handles are visually ambiguous without platform labels. |
| 07-minimal-profile | 1 | Exact approved stream and PDF hash match | No clipping, overlap or missing glyphs observed. |
| 08-explicit-append | 1 | Exact approved stream and PDF hash match | No clipping, overlap or missing glyphs observed. |
| 09-selected-omission | 1 | Exact approved stream and PDF hash match | No clipping, overlap or missing glyphs observed. |
| 10-multipage | 2 | Exact approved stream and PDF hash match | A two-line service paragraph continues onto page two. All 28 records and both metric values remain in order. |

The append case includes only the explicit fictional answer. The selected-omission case removes only the approved summary display. Signs, units, numeric order, C++/C# tokens and tested Latin accents remain intact.

The minimal profile deliberately leaves most of the page empty. The template uses a straightforward vertical layout. Contact-label clarity and paragraph breaks remain presentation limitations; the tests do not establish universal typography or language coverage.

These approvals are explicit synthetic QA fixture decisions. They are not participant decisions or usability pilot results.
