# Recommendation Pipeline

Fovea has one discovery feed rather than several recommendation sections. Continue Watching is kept separate because it is a playback-resume task, not a recommendation.

## Current signals

- **Watch history and completion:** Fovea looks at tags attached to watched videos. A completed video gives its tags three times the weight of an in-progress video, because finishing a video is a stronger sign of interest.
- **Shared tags:** A candidate receives the combined weight of its tags that also appear in the watch-history profile. This is the strongest current signal.
- **Popularity:** Videos watched more often receive a small boost. The boost is capped, so a heavily watched item cannot overwhelm the interest profile.
- **Recency:** Newly added videos receive a small boost based on their stored add order. The twelve newest candidates use the `Recently added` explanation when no stronger tag explanation applies.
- **Exploration:** Every video receives a very small value derived from its UUID. It breaks otherwise-close results and gives lesser-known videos a consistent chance to surface. It is stable rather than reshuffled on every request, so scrolling is reliable.
- **Search history:** Every completed search stores its original query, timestamp, and result count. Query terms are normalized and matched against title terms, so searches can influence untagged videos.

## Scoring and explanations

The service adds the weighted tag score, capped popularity boost, recency boost, stable exploration value, and search-title score. Search overlap is multiplied by 1.5; tag overlap is multiplied by 3. A card explanation describes the largest personal signal: `Because you searched: …` when search contribution is at least as strong as tags, then `Shared tag: …`, `Recently added`, `Popular in your library`, or `Random discovery`.

## Ordering and pagination

Candidates are fully scored and sorted before a page is selected. Ordering is score descending, then added time descending, then UUID ascending. This makes equal scores deterministic. The API applies `offset` and `limit` only after this order is established, so separate pages do not overlap unless the underlying library or watch history changes between requests.

`GET /api/v1/feed/home` returns the Continue Watching row and one recommendation page. The frontend starts at offset zero and requests the next offset only when its scroll sentinel becomes visible.

## Search-history token matching

`search_history` stores `id`, `query`, `searched_at`, `result_count`, and an optional `clicked_video_id` reserved for later click tracking. The frontend needs no new UI: its existing debounced request to `GET /search` records a history row after the search succeeds.

Terms are lowercased and extracted as alphanumeric words. One-character terms and common connector words (`and`, `for`, `from`, `the`, `video`, `with`) are ignored. Each matching title token receives the accumulated weight of that term across history. Repeated searches therefore add weight. More recent rows receive a larger rank-based weight, based solely on stored `searched_at` and UUID order, which keeps the result deterministic.

The title-score helper is private to `RecommendationService`; later local similarity sources such as transcript text, OCR, embeddings, or generated metadata can replace or supplement that helper without changing `get_ranked_feed` or the homepage API.
