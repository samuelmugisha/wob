# Retrieval benchmark

The spec's acceptance criteria (§13) call for **≥90% retrieval recall on an annotated pilot benchmark**. A benchmark measures that: for each question, a WOB domain reviewer records which passages a good search *must* find. The harness then reports how many of those passages the retriever returns in its top *k*.

## Writing a benchmark

Copy `demo-benchmark.json` and replace its cases with real ones from the pilot category. For each case, fill in:

- **`category`**: the award category's code, as shown in the URL slug when the category was created.
- **`candidate`**: the candidate's full name. If two candidates in the category share a name, use `finalist_category_id` instead.
- **`criterion`** *or* **`query`**:
  - Use `criterion` (a rubric criterion code) to test exactly what the assessor will retrieve.
  - Use `query` for free-text questions.
- **`relevant`**: one or more items that must be retrieved. Each item has:
  - **`document`** (optional): the file name.
  - **`quote`**: a short, distinctive phrase that appears in the indexed text. Check it with *View text* in the UI; the match ignores case and spacing.

Annotate from the evidence, not from what the search currently returns. A useful pilot set has 30–50 cases per category. Include the hard cases the spec lists: scanned files, duplicate names, contradictory dates, missing evidence and limited online visibility.

## Running it

Run inside Docker, where the real embedding and reranking models are installed:

```bash
docker compose --env-file .env -f infrastructure/docker/compose.yaml run --rm --no-deps \
  -v "$PWD/ai/evaluation:/benchmarks" worker \
  python -m app.evaluation.retrieval /benchmarks/demo-benchmark.json --output /benchmarks/report.json
```

The command exits with status 1 when recall is below `target_recall`. Each report records the embedding and reranker model IDs and the retrieval settings, so results can be compared across tuning changes, such as chunk size or candidate pool sizes (spec §5.2).
