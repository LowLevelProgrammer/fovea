import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { TagChip } from "../components/TagChip";
import { useTags } from "../hooks/useTags";

type TagsPageProps = { onSelectTag: (tagName: string) => void };

export function TagsPage({ onSelectTag }: TagsPageProps) {
  const { tags, loading, error } = useTags();
  if (loading) return <LoadingState message="Loading tags..." />;
  if (error) return <ErrorState title="Tags Error" message={error} />;
  return <div><div className="page-header"><h2 className="page-title">Tags</h2></div>{tags.length === 0 ? <div className="no-videos"><h3>No tags available yet</h3><p>Tags are created automatically when videos are scanned.</p></div> : <div className="tag-list">{tags.map((tag) => <TagChip key={tag.id} tag={tag} onClick={() => onSelectTag(tag.name)} />)}</div>}</div>;
}
