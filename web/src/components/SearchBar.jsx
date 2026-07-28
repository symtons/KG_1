export default function SearchBar({ value, onChange, onEnter, matchCount, totalCount }) {
  return (
    <div className="search-bar">
      <div className="search-input-wrap">
        <input
          type="text"
          className="search-input"
          placeholder="Filter candidates, or press Enter to explore a concept…"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onEnter();
          }}
        />
        {value && (
          <button
            type="button"
            className="search-clear"
            aria-label="Clear search"
            onClick={() => onChange("")}
          >
            &times;
          </button>
        )}
      </div>
      <div className="search-count">
        {value
          ? `${matchCount} of ${totalCount} candidates`
          : `${totalCount} candidates`}
      </div>
    </div>
  );
}
