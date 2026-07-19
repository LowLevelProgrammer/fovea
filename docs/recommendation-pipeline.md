# Recommendation Pipeline

Fovea has one discovery feed rather than several recommendation sections. Continue Watching is kept separate because it is a playback-resume task, not a recommendation.

## Current signals

- **Watch history and completion:** Fovea looks at tags attached to watched videos. A completed video gives its tags three times the weight of an in-progress video, because finishing a video is a stronger sign of interest.
- **Shared tags:** A candidate receives the combined weight of its tags that also appear in the watch-history profile. This is the strongest current signal.
- **Popularity:** Videos watched more often receive a small boost. The boost is capped, so a heavily watched item cannot overwhelm the interest profile.
- **Recency:** Newly added videos receive a small boost based on their stored add order. The twelve newest candidates use the `Recently added` explanation when no stronger tag explanation applies.
- **Exploration:** Every video receives a very small value derived from its UUID. It breaks otherwise-close results and gives lesser-known videos a consistent chance to surface. It is stable rather than reshuffled on every request, so scrolling is reliable.

## Scoring and explanations

The service adds the weighted tag score, capped popularity boost, recency boost, and stable exploration value. A card explanation describes the strongest visible signal: `Shared tag: …` first, then `Recently added`, then `Popular in your library`, and finally `Random discovery`.

## Ordering and pagination

Candidates are fully scored and sorted before a page is selected. Ordering is score descending, then added time descending, then UUID ascending. This makes equal scores deterministic. The API applies `offset` and `limit` only after this order is established, so separate pages do not overlap unless the underlying library or watch history changes between requests.

`GET /api/v1/feed/home` returns the Continue Watching row and one recommendation page. The frontend starts at offset zero and requests the next offset only when its scroll sentinel becomes visible.

## Future search history

Search history is not stored or scored yet. When it is introduced, the implementation should add a concrete token-based score alongside the existing score calculation: normalize saved search terms, match them against video titles, and add that value before the final sort. No placeholder interface is needed until that data and behavior exist.
