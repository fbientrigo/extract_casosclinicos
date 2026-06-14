# Manual Review: OCR Subset Evaluation Report

Use this template to manually inspect and verify a small page-range subset of OCR outputs before proceeding to scale.

## 📋 Metadata
- **Book ID:** `<book_id>`
- **Source Page Range(s):** `<source_pages>`
- **OCR Profile Used:** `<ocr_profile>`
- **Languages Analyzed:** `<languages>`
- **Date/Time Evaluated:** `<date_time>`
- **Reviewer Name:** `<reviewer_name>`

---

## 🔍 Quality Assessment Checklist

### 1. Accuracy Summary
- **Pages that look good:** `[ ]` (List pages with high accuracy, correct character recognition, and clean output)
- **Pages that need re-OCR:** `[ ]` (List pages with substantial errors, noise, or missing text)

### 2. Failure Analysis
Analyze where and why the OCR pipeline failed to yield production-ready text:

- **Layout/Column Failures:**
  - *Describe issues (e.g. multi-column text read out of order, header/footer text merged into body):*
  
- **Table Failures:**
  - *Describe issues (e.g. alignment lost, cells merged incorrectly, data scrambled):*
  
- **Figure/Caption Failures:**
  - *Describe issues (e.g. caption merged into text block, figure content attempted as text, raw image paths missing):*
  
- **Language/Unicode Failures:**
  - *Describe issues (e.g. accents scrambled, non-English/non-Spanish characters misinterpreted, language-switching errors):*

---

## 🚦 Recommendation
Based on the quality of this subset, check **one** of the following paths:

- [ ] **Proceed to Full Chapter/Book Batch:** The quality is high and standard OCRmyPDF profile is sufficient.
- [ ] **Tune OCR Profile:** Adjust options (e.g., enable deskew, clean-final, change DPI, or increase timeout limit).
- [ ] **Try Docling:** The layout is highly structured/academic and requires deep document parsing (e.g., tables, hierarchies).
- [ ] **Try PaddleOCR:** Document contains challenging vertical text or complex mixed-direction layouts.
- [ ] **Manually Pre-process/Crop/Deskew:** The scans are low-contrast, heavily skewed, or contain margins that must be cropped first.

---

## 📝 Additional Notes & Observations
*Add any additional details or screenshots here.*
