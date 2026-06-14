# Clinical Cases Database Schema

- Database: `data/clinical_cases.db`
- Tables: `13`

## case_metrics

```sql
CREATE TABLE case_metrics (
        case_id TEXT PRIMARY KEY,
        lexical_diversity REAL,
        tfidf_concept_count INTEGER,
        concept_entropy REAL,
        teaching_density_score REAL,
        diversity_score REAL,
        FOREIGN KEY(case_id) REFERENCES cases(case_id)
    );
```

## case_texts

```sql
CREATE TABLE case_texts (
        case_id TEXT PRIMARY KEY,
        raw_markdown TEXT,
        clean_markdown TEXT,
        full_text TEXT,
        FOREIGN KEY(case_id) REFERENCES cases(case_id)
    );
```

## cases

```sql
CREATE TABLE cases (
        case_id TEXT PRIMARY KEY,
        section_id TEXT,
        subsection_id TEXT,
        slug TEXT,
        title TEXT,
        printed_start INTEGER,
        printed_end INTEGER,
        page_count INTEGER,
        total_chars INTEGER,
        source_pdf TEXT,
        case_md_path TEXT,
        clean_case_md_path TEXT,
        qa_json_path TEXT,
        metadata_json_path TEXT,
        status TEXT,
        needs_manual_review INTEGER,
        review_reason TEXT,
        FOREIGN KEY(section_id) REFERENCES sections(section_id),
        FOREIGN KEY(subsection_id) REFERENCES subsections(subsection_id)
    );
```

## clusters

```sql
CREATE TABLE clusters (
        cluster_id TEXT,
        case_id TEXT,
        embedding_model TEXT,
        method TEXT,
        k INTEGER,
        silhouette_score REAL,
        distance_to_centroid REAL,
        FOREIGN KEY(case_id) REFERENCES cases(case_id)
    );
```

## concepts

```sql
CREATE TABLE concepts (
        concept_id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id TEXT,
        concept TEXT,
        score REAL,
        source TEXT,
        FOREIGN KEY(case_id) REFERENCES cases(case_id)
    );
```

## embeddings

```sql
CREATE TABLE embeddings (
        embedding_id TEXT PRIMARY KEY,
        case_id TEXT,
        level TEXT,
        model_name TEXT,
        vector_dim INTEGER,
        vector_blob BLOB,
        created_at TEXT,
        FOREIGN KEY(case_id) REFERENCES cases(case_id)
    );
```

## llm_case_cards

```sql
CREATE TABLE llm_case_cards (
        case_id TEXT PRIMARY KEY,
        model_name TEXT,
        card_json TEXT,
        created_at TEXT,
        FOREIGN KEY(case_id) REFERENCES cases(case_id)
    );
```

## pages

```sql
CREATE TABLE pages (
        page_id TEXT PRIMARY KEY,
        case_id TEXT,
        page_number INTEGER,
        text TEXT,
        char_count INTEGER,
        FOREIGN KEY(case_id) REFERENCES cases(case_id)
    );
```

## qa_reports

```sql
CREATE TABLE qa_reports (
        case_id TEXT PRIMARY KEY,
        empty_pages TEXT,
        suspicious_low_text_pages TEXT,
        repeated_headers TEXT,
        repeated_footers TEXT,
        quality_flags TEXT,
        FOREIGN KEY(case_id) REFERENCES cases(case_id)
    );
```

## sections

```sql
CREATE TABLE sections (
        section_id TEXT PRIMARY KEY,
        title TEXT,
        printed_start INTEGER,
        printed_end INTEGER
    );
```

## star_case_scores

```sql
CREATE TABLE star_case_scores (
        case_id TEXT PRIMARY KEY,
        section_id TEXT,
        score REAL,
        rationale TEXT,
        source TEXT,
        FOREIGN KEY(case_id) REFERENCES cases(case_id),
        FOREIGN KEY(section_id) REFERENCES sections(section_id)
    );
```

## subsections

```sql
CREATE TABLE subsections (
        subsection_id TEXT PRIMARY KEY,
        section_id TEXT,
        slug TEXT,
        title TEXT,
        printed_start INTEGER,
        printed_end INTEGER,
        FOREIGN KEY(section_id) REFERENCES sections(section_id)
    );
```

## tags

```sql
CREATE TABLE tags (
        tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id TEXT,
        tag_family TEXT,
        tag_value TEXT,
        confidence REAL,
        source TEXT,
        FOREIGN KEY(case_id) REFERENCES cases(case_id)
    );
```
