const METHOD_LABELS = {
  system: "System",
  adamic_adar: "Adamic-Adar",
  random: "Random",
  similarity: "Similarity",
};

export default function VerificationCard({ verification }) {
  const entries = Object.entries(verification || {}).filter(([, v]) => v);
  if (entries.length === 0) {
    return (
      <div className="verification-card">
        <h3>Manual verification</h3>
        <p style={{ color: "var(--text-muted)", fontSize: 13, margin: 0 }}>
          Not in any method's top 20 — not part of the manually-verified set (EVAL_RESULTS.md).
        </p>
      </div>
    );
  }

  return (
    <div className="verification-card">
      <h3>Manual verification (EVAL_RESULTS.md)</h3>
      {entries.map(([method, v]) => (
        <div key={method} className="verification-row">
          <span className="method-name">{METHOD_LABELS[method] ?? method}</span>
          <div>
            <span className={`badge ${v.verdict === "confirm" ? "confirm" : "reject"}`}>
              {v.verdict} (rank #{v.rank})
            </span>
            {v.reason && (
              <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--text-secondary)" }}>
                {v.reason}
              </p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
