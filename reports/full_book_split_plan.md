# Full Book PDF Splitting & Case Extraction Plan

This document details the design, configuration, implementation, and verification of the localized PDF splitting and clinical case extraction pipeline. The examples use a real medical textbook with ~783 pages organized in 6 sections.

## 1. Page Slicing and Offset Contract

Through empirical validation (visual verification and page-count checks) on one section, the relationship between printed pages and PDF pages has been formalized as follows:

*   **PDF Viewer Page**: `pdf_viewer_page = printed_book_page + 1`
*   **Internal 0-based PDF Slicing Page**: `internal_zero_based_page_index = printed_book_page`
*   **Inclusive Book Ranges**: The printed page ranges listed in the table of contents (TOC) are inclusive. E.g., printed range `112-128` means page 112 through 128 are fully included.
*   **End-Exclusive Slicing Interval**: To extract the inclusive printed range `[printed_start_page, printed_end_page]`, Python's `pypdf` page slicing must use:
    $$\text{Internal Page Slice} = [ \text{printed\_start\_page}, \text{printed\_end\_page} + 1 )$$

### Concrete Example
For a subsection spanning printed pages `112-128`:
*   **Printed start**: 112, **Printed end**: 128
*   **PDF viewer range**: `[113, 129]` (PDF pages 113 to 129 inclusive)
*   **Internal 0-based indices**: `[112, 129)` (extracting indices 112 through 128, which yields exactly 17 pages).

---

## 2. Table of Contents Source and Section Boundaries

The source of truth for the entire book hierarchy and starting page numbers is your book's TOC transcription (typically saved as `book/<book_id>/indice_contenidos.md`).

### Section-Level Page Ranges
To prevent overlap and ensure gapless coverage, each section's ending page is derived from the next section's starting page minus 1. The final section's end is inferred from the known total pages of the PDF.

| Section | Title (example) | Printed Start | Printed End | Expected Page Count | Status / Notes |
|---|---|---|---|---|---|
| **Section 0** | Preface | 27 | 28 | 2 | Optional (included in manifest) |
| **Section I** | Topic A | 29 | 108 | 80 | Verified |
| **Section II** | Topic B | 109 | 302 | 194 | Verified (Regression Target) |
| **Section III** | Topic C | 303 | 430 | 128 | Verified |
| **Section IV** | Topic D | 431 | 460 | 30 | Verified |
| **Section V** | Topic E | 461 | 610 | 150 | Verified |
| **Section VI** | Topic F | 611 | 782 | 172 | **Uncertainty Flagged**: last subsection inferred to end at the final PDF page. |

---

## 3. Output Hierarchy Directory Structure

To keep artifacts structured and easy to index, splits are saved under the `book/` folder using the following naming conventions:

*   **Section-Level PDFs**:
    `book/seccionN/sectionN.pdf`
*   **Case-Level PDFs**:
    `book/seccionN/<subsection_slug>/<printed_start>_<case_slug>.pdf`

### Slugging Rules (Python `unicodedata` & `re`):
- All lowercase characters.
- Accents removed (Unicode normalization `NFD`).
- Spaces and punctuation replaced with underscores (`_`).
- Consecutive underscores collapsed.
- Leading/trailing underscores stripped.
- Examples:
  - "Anemias microcíticas" $\rightarrow$ `anemias_microciticas`
  - "Síndromes linfoproliferativos" $\rightarrow$ `sindromes_linfoproliferativos`
  - "VIH (dos casos) caso 1" $\rightarrow$ `vih_dos_casos_caso_1`

---

## 4. Validation and Safety Strategy

To guarantee that no page truncation or off-by-one errors occur during extraction, we enforce a strict multi-level validation strategy:

1.  **Dry-run Integrity Check**:
    Before running any destructive file operations, `--dry-run` compiles the manifest and saves metadata to `book/book_split_dryrun_manifest.json`, letting us verify the entire pipeline structure.
2.  **SHA-256 Checksum Matching**:
    When running `--execute`, the script computes the original PDF's SHA-256 to ensure we are working with the correct book file. Each book's manifest records its expected checksum.
3.  **Loud Page-Count Assertions**:
    After a PDF slice is written to disk, it is immediately re-opened via `pypdf.PdfReader` to count its actual pages. The script performs an assertion check:
    $$\text{actual\_page\_count} == \text{expected\_page\_count}$$
    If a mismatch is found, a `RuntimeError` is raised immediately, and the process terminates.
4.  **Execute Manifest Tracking**:
    A full output summary of the executed splits (including paths, page counts, slices, and source SHA) is written to `book/book_split_execute_manifest.json`.
5.  **Git Protection**:
    Explicit ignore rules have been added to [.gitignore](.gitignore) to protect the workspace:
    ```git
    book/seccion*/
    book/prefacio/
    book/book_split_execute_manifest.json
    book/book_split_dryrun_manifest.json
    ```

---

## 5. Execution and Validation Commands

The following commands are used to test, run, and verify the pipeline:

### A. Validate manifest and bounds (Dry-run all)
```powershell
.\.venv\Scripts\python scripts/split_book_from_manifest.py --dry-run --section all
```

### B. Validate debugging limits (Dry-run with limit of 20)
```powershell
.\.venv\Scripts\python scripts/split_book_from_manifest.py --dry-run --section all --limit 20
```

### C. Extract and verify all high-level Section PDFs
```powershell
.\.venv\Scripts\python scripts/split_book_from_manifest.py --execute --sections-only --section all
```

### D. Execute full section regression check (Section + Cases)
```powershell
.\.venv\Scripts\python scripts/split_book_from_manifest.py --execute --section seccion2
```
