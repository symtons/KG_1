function label(id) {
  return id.replaceAll("_", " ");
}

export default function CandidateList({ candidates, selected, onSelect }) {
  if (candidates.length === 0) {
    return <div className="empty-state">Loading candidates…</div>;
  }

  return (
    <div>
      {candidates.map((cand) => {
        const isSelected = selected && selected.a === cand.a && selected.c === cand.c;
        return (
          <div
            key={`${cand.a}::${cand.c}`}
            className={`candidate-row${isSelected ? " selected" : ""}`}
            onClick={() => onSelect(cand)}
          >
            <div>
              <span className="rank">#{cand.rank}</span>
              <span className="pair">{label(cand.a)} &harr; {label(cand.c)}</span>
            </div>
            <div className="meta-line">
              <span className="score">score {cand.score.toFixed(2)}</span>
              {cand.fails_at_bridge && <span className="badge fails-at">FAILS_AT</span>}
              {cand.cross_origin && (
                <span className="badge cross-origin">{cand.origin_a}&harr;{cand.origin_c}</span>
              )}
              {cand.verified?.verdict && (
                <span className={`badge ${cand.verified.verdict}`}>{cand.verified.verdict}</span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
