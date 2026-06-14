# Section PDF Splitting Test Report

This report documents the design, mathematics, and verification results of splitting a book section and extracting selected case studies under two key subsections.

The example below uses a hematology section from a clinical cases textbook (~783 pages total). The same approach applies to any book configured with the pipeline.

---

## 🧮 Mathematics & Page Offset Rules

When dealing with scanned textbook PDFs, there is often a discrepancy between the printed page numbers and the physical pages within the PDF file itself. To ensure exact page alignment, we established the following rules:

1. **The Offset Rule:**
   - The PDF viewer page number is exactly **printed book page + 1**.
   - Example: Printed book page `21` appears as PDF viewer page `22`.
   - Formula: 
     $$\text{pdf\_viewer\_page} = \text{printed\_book\_page} + 1$$

2. **Internal Slicing Index (Zero-Based):**
   - In Python PDF parsing libraries (such as `pypdf`), indices are zero-based.
   - The zero-based start index of a printed range maps directly to the printed book page number:
     $$\text{internal\_zero\_based\_page\_index} = \text{pdf\_viewer\_page} - 1 = \text{printed\_book\_page}$$
   - Because printed ranges are inclusive but python slices are end-exclusive, we define the slicing range `[start, end]` as:
     $$\text{internal\_slice} = [\text{printed\_start}, \text{printed\_end} + 1)$$
   - The expected page count is exactly:
     $$\text{expected\_page\_count} = \text{printed\_end} - \text{printed\_start} + 1$$

---

## 🎯 Target Selections

### Why This Section Was Chosen
The hematology section (printed pages 109 to 302 inclusive) represents a large, contiguous section containing rich clinical cases across multiple disorders. It provides an ideal playground for dry-running the splitting script because it encompasses a large section (194 pages) and multiple structured subsections.

### Extracted Subsections (Non-Contiguous)
Two subsections inside the section were selected for extraction:

1. **Subsection A** (Printed pages 112 to 128 inclusive; 17 pages total)
   - Extracted cases:
     - `112-116`: Case 1 (5 pages)
     - `117-120`: Case 2 (4 pages)
     - `121-124`: Case 3 (4 pages)
     - `125-128`: Case 4 (4 pages)

2. **Subsection B** (Printed pages 204 to 240 inclusive; 37 pages total)
   - Extracted cases:
     - `204-208`: Case 1 (5 pages)
     - `209-213`: Case 2 (5 pages)
     - `214-219`: Case 3 (6 pages)
     - `220-225`: Case 4 (6 pages)
     - `226-230`: Case 5 (5 pages)
     - `231-235`: Case 6 (5 pages)
     - `236-240`: Case 7 (5 pages)

---

## 📂 Expected Output Directory & File Map

All extracted output files are contained within a Git-ignored directory under `book/seccion<N>/` to maintain data policy boundaries:

* **Section-Level PDF Output:**
  - `book/seccion<N>/seccion<N>_<topic>_<start>_<end>.pdf`
* **Subsection Cases:**
  - `book/seccion<N>/<subsection_slug>/<start>_<case_slug>.pdf`

The naming follows the slugging rules documented in [full_book_split_plan.md](full_book_split_plan.md).
