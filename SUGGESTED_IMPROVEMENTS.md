# Suggested improvements

Review baseline: October 13, 2026, implementation commit `3be5122`.
These are proposed follow-ups, not implemented features.

## Current evidence

The 16 offline tests exercise 156/158 executable lines (98.7%) and 70/74
branches (94.6%). This is strong coverage, but not full coverage or proof that
every publication extracts accurately. PDF subprocess tests are mocked;
separate local smoke checks verified real EPUB and Poppler extraction.

Single-page PDF extraction already avoids parsing the entire PDF. One local
three-run comparison measured a median of 0.0242 seconds versus 2.9575 seconds,
with identical extracted text. That result is specific to the tested document.

## 1. Automate regression checks

Add GitHub Actions to run the synthetic test suite, branch coverage, package
build, and skill validation. Include an integration test using installed
Poppler and a generated, redistributable PDF, so argument mocks are not the
only automated evidence for PDF behavior. Test supported Python versions.

Acceptance: a clean checkout builds and passes without a personal Apple Books
library. Tests must never upload books, annotations, or library databases.

## 2. Expand accuracy fixtures

Add small synthetic EPUB/PDF cases covering nested navigation, missing spine
items, malformed metadata, font obfuscation versus protected content,
multi-column text, tables, formulas, and annotation edge cases. Test expected
limitations as well as successful extraction. Preserve useful paragraph
boundaries if doing so improves readability without breaking continuation.

Acceptance: fixtures have explicit expected text/order or documented warnings;
new tests catch actual regressions rather than merely increasing coverage.
Exercise the remaining branches where meaningful. Consider annotation
pagination so a large collection can be read completely.

## 3. Reduce repeated EPUB work

Benchmark repeated section reads and searches before choosing an approach.
First consider extracting only the requested spine item. If repeated full-text
search remains costly, add an optional local cache keyed by source identity
and freshness. Expanded EPUBs require invalidation when constituent files
change, not just when the top-level directory changes.

Acceptance: cached and uncached results match; edits invalidate stale entries;
benchmarks report cold and warm timings. Cached text stays local, outside the
repository, with a documented clear command. Originals remain untouched.

## 4. Add optional OCR for scanned PDFs

Keep normal text extraction fast. Offer explicit OCR for image-only pages
using an established local tool, producing temporary or separately stored
derived files. Do not overwrite source PDFs or imply OCR is exact.

Acceptance: generated scan fixtures yield usable text; output identifies OCR
provenance; missing dependencies and timeouts produce clear errors. Validate
page numbering and continuation, and document OCR's accuracy and speed limits.

## Scope

Prioritize regression checks and accuracy fixtures before adding more features.
Continue read-only access to Apple Books stores. Central agent integration,
MCP support, and changes to superai-skills remain separate decisions.
