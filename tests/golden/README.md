# Golden fidelity corpus

Place hard examples here, one folder per case:

```text
tests/golden/
  math_integral_bounds/
    source.pdf
    expected.json
  chemistry_charge/
    source.png
    expected.json
```

`expected.json` uses the extraction shape:

```json
{
  "questions": [
    {
      "number": 1,
      "page": 1,
      "statement": "...",
      "options": ["..."],
      "answer": "",
      "solution": ""
    }
  ]
}
```

Run live GCP extraction and compare:

```bash
python golden_benchmark.py tests/golden
```

This intentionally makes paid GCP calls. Start with 50 difficult examples and treat
silent semantic errors (wrong values/signs/bounds/units/charges marked verified) as the
release-blocking metric.
