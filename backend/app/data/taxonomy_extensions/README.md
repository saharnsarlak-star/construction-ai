# Taxonomy extensions

Drop JSON files here to **append** new categories without editing the main catalog.

Each file may contain:

```json
{
  "append_categories": [
    {
      "code": "37",
      "title_fa": "دسته جدید",
      "title_en": "New Category",
      "subcategories": [],
      "topics": [
        {
          "code": "37.01",
          "title_fa": "موضوع نمونه",
          "title_en": "Sample topic"
        }
      ]
    }
  ]
}
```

Rules:
- Every `code` must be **globally unique** across main catalog + all extensions.
- Prefer numeric dotted codes: root `NN`, sub `NN.N`, topic `NN.N.NN`.
- After editing, run: `python scripts/normalize_tender_taxonomy.py --check`
- Restart the backend to reload the catalog.
