# Similarity Service

Similarity answers a video-to-video question: given one source video, which library videos most resemble it? It has no user, watch-history, search-history, or homepage knowledge. Recommendation is separate because it ranks videos for a person's current interests.

## Current scoring

For each available video other than the source, the service adds:

- **4.0 per shared tag** — the strongest metadata signal.
- **2.5 per shared title token** — case-insensitive alphanumeric title terms.
- **1.0 per shared filename token** — filename-stem terms receive a smaller supplemental boost.
- **1.5 for the same direct folder** — compares stored media paths only; it never reads the host filesystem.
- **0.5 for durations within 10%**, or **0.2 within 25%** — uses existing probe data when both durations are known.

One-character words and common connector words are ignored for title and filename comparisons. Videos with no matching signal are omitted. Results sort by score descending, then added time descending, then UUID ascending.

The explanation describes the strongest applicable match: multiple tags, one shared tag, similar title, similar filename, same folder, or similar duration. Raw scores stay internal.

## API and future signals

`GET /api/v1/videos/{video_id}/similar?offset=0&limit=12` returns a paginated list, excluding the source video. The public `SimilarityService.get_similar` method remains a video-to-video contract. Future local signals such as OCR text, transcripts, embeddings, or generated metadata can be added inside the service without changing that API or making the service user-aware.
