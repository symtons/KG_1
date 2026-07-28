function label(id) {
  return id.replaceAll("_", " ");
}

export default function EntityCard({ entity, selected, onSelectCandidate }) {
  return (
    <div className="entity-card">
      <div className="entity-card-header">
        <h2>{label(entity.canonical_name)}</h2>
        <span className="badge entity-type">{entity.type}</span>
      </div>
      <p className="subtitle">
        mentioned in {entity.pre_cutoff_mentions} pre-cutoff paper
        {entity.pre_cutoff_mentions === 1 ? "" : "s"} &middot; {entity.candidates.length} ranked
        candidate pair{entity.candidates.length === 1 ? "" : "s"}
      </p>

      {entity.neighbors.length > 0 && (
        <>
          <h3>Strongest relation-graph neighbors</h3>
          <div className="neighbor-chips">
            {entity.neighbors.map((n) => (
              <span key={`${n.relation}-${n.neighbor}-${n.direction}`} className="neighbor-chip">
                {n.direction === "out" ? (
                  <>
                    <span className="chip-relation">{n.relation}</span> &rarr; {label(n.neighbor)}
                  </>
                ) : (
                  <>
                    {label(n.neighbor)} &rarr; <span className="chip-relation">{n.relation}</span>
                  </>
                )}
                <span className="chip-count">{n.shared_papers}</span>
              </span>
            ))}
          </div>
        </>
      )}

      {entity.candidates.length > 0 && (
        <>
          <h3>Appears in these ranked candidates</h3>
          <div className="entity-candidates">
            {entity.candidates
              .slice()
              .sort((x, y) => x.rank - y.rank)
              .map((cand) => {
                const other = cand.a === entity.canonical_name ? cand.c : cand.a;
                const isSelected = selected && selected.a === cand.a && selected.c === cand.c;
                return (
                  <div
                    key={`${cand.a}::${cand.c}`}
                    className={`candidate-row${isSelected ? " selected" : ""}`}
                    onClick={() => onSelectCandidate(cand)}
                  >
                    <div>
                      <span className="rank">#{cand.rank}</span>
                      <span className="pair">&harr; {label(other)}</span>
                    </div>
                    <div className="meta-line">
                      <span className="score">score {cand.score.toFixed(2)}</span>
                      {cand.fails_at_bridge && <span className="badge fails-at">FAILS_AT</span>}
                      {cand.cross_origin && (
                        <span className="badge cross-origin">
                          {cand.origin_a}&harr;{cand.origin_c}
                        </span>
                      )}
                      {cand.verified?.verdict && (
                        <span className={`badge ${cand.verified.verdict}`}>
                          {cand.verified.verdict}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
          </div>
        </>
      )}
    </div>
  );
}
