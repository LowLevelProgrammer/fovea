import { Tag } from "../types/api";

type TagChipProps = {
  tag: Tag;
  onClick: () => void;
};

export function TagChip({ tag, onClick }: TagChipProps) {
  return <button className="tag-chip" onClick={onClick}>{tag.name}</button>;
}
