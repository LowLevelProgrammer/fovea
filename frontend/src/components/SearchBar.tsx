type SearchBarProps = {
  value: string;
  onChange: (value: string) => void;
  autoFocus?: boolean;
};

export function SearchBar({ value, onChange, autoFocus = false }: SearchBarProps) {
  return (
    <label className="search-bar">
      <span className="sr-only">Search videos and tags</span>
      <span aria-hidden="true">⌕</span>
      <input
        autoFocus={autoFocus}
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="Search videos and tags"
      />
    </label>
  );
}
