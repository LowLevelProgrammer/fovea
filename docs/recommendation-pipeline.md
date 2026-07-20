# Recommendation Pipeline

Fovea has one discovery feed rather than several recommendation sections. Continue Watching is kept separate because it is a playback-resume task, not a recommendation.

## Current signals

- **Watched title keywords:** Fovea tokenizes watched titles and scores candidates with overlapping title terms. Completed watches contribute three times the keyword weight of in-progress watches. This is a primary signal, so meaningful title overlap can recommend untagged videos.
- **Watch history and tags:** Tags attached to watched videos form another strong interest profile. A completed video gives its tags three times the weight of an in-progress video; manually assigned watched tags receive a small additional multiplier.
- **Shared tags:** A candidate receives the combined weight of its tags that also appear in the watch-history profile.
- **Popularity:** Videos watched more often receive a small boost. The boost is capped, so a heavily watched item cannot overwhelm the interest profile.
- **Recency:** Newly added videos receive a small boost based on their stored add order. The twelve newest candidates use the `Recently added` explanation when no stronger tag explanation applies.
- **Exploration:** Every video receives a very small value derived from its UUID. It breaks otherwise-close results and gives lesser-known videos a consistent chance to surface. It is stable rather than reshuffled on every request, so scrolling is reliable.
- **Search history:** Every completed search stores its original query, timestamp, and result count. Query terms are normalized and matched against title terms, so searches can help discover untagged videos when watch history is limited.

## Scoring and explanations

The service adds tag overlap ×3, watched-title overlap ×2, search-title overlap ×0.4, capped popularity, recency, and stable exploration. This keeps watched metadata ahead of searches over time. A card explains the strongest personal contribution: `Shared tag: …`, then `Shared keyword: …`, then `Because you searched: …`; otherwise it uses `Recently added`, `Popular in your library`, or `Random discovery`.

## Ordering and pagination

Candidates are fully scored and sorted before a page is selected. Ordering is score descending, then added time descending, then UUID ascending. This makes equal scores deterministic. The API applies `offset` and `limit` only after this order is established, so separate pages do not overlap unless the underlying library or watch history changes between requests.

`GET /api/v1/feed/home` returns the Continue Watching row and one recommendation page. The frontend starts at offset zero and requests the next offset only when its scroll sentinel becomes visible.

## Search-history token matching

`search_history` stores `id`, `query`, `searched_at`, `result_count`, and an optional `clicked_video_id` reserved for later click tracking. The frontend needs no new UI: its existing debounced request to `GET /search` records a history row after the search succeeds.

Terms are lowercased and extracted as alphanumeric words. One-character terms, English connector words, and generic video terms such as `tutorial`, `guide`, `intro`, `learn`, and `using` are ignored. The stop-word set is configurable through the tokenizer helper. Only the 50 most recent history rows are profiled; within that window, newer rows receive a larger rank-based weight based solely on stored `searched_at` and UUID order. Repeated searches add weight, while older searches eventually leave the profile.

The title-score helper is private to `RecommendationService`; later local similarity sources such as transcript text, OCR, embeddings, or generated metadata can replace or supplement that helper without changing `get_ranked_feed` or the homepage API.
