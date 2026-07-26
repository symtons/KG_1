const METHODS = [
  { key: "system", label: "System", color: "var(--series-1)" },
  { key: "adamic_adar", label: "Adamic-Adar", color: "var(--series-2)" },
  { key: "random", label: "Random", color: "var(--series-3)" },
  { key: "similarity", label: "Similarity", color: "var(--series-4)" },
];

const CHART_H = 160;
const BAR_W = 22;
const GROUP_GAP = 44;
const BAR_GAP = 4;
const MAX_VAL = 0.5;
const AXIS_TOP = 16;
const AXIS_BOTTOM = CHART_H - 28;
const PLOT_H = AXIS_BOTTOM - AXIS_TOP;

function y(v) {
  return AXIS_BOTTOM - (v / MAX_VAL) * PLOT_H;
}

export default function PrecisionChart({ precision }) {
  if (!precision) return null;
  const groupW = BAR_W * 2 + BAR_GAP;
  const width = METHODS.length * (groupW + GROUP_GAP);

  return (
    <div className="chart-card">
      <h3>Manually-verified precision (top 20 per method)</h3>
      <svg width="100%" viewBox={`0 0 ${width} ${CHART_H}`} role="img" aria-label="Precision at 10 and 20 by method">
        <line x1={0} y1={AXIS_BOTTOM} x2={width} y2={AXIS_BOTTOM} stroke="var(--gridline)" strokeWidth="1" />
        {[0.1, 0.2, 0.3, 0.4, 0.5].map((tick) => (
          <line key={tick} x1={0} y1={y(tick)} x2={width} y2={y(tick)} stroke="var(--gridline)" strokeWidth="1" opacity="0.5" />
        ))}
        {METHODS.map((m, i) => {
          const p = precision[m.key];
          if (!p) return null;
          const gx = i * (groupW + GROUP_GAP) + GROUP_GAP / 2;
          return (
            <g key={m.key}>
              <rect
                x={gx} y={y(p.p10)} width={BAR_W} height={AXIS_BOTTOM - y(p.p10)}
                rx="3" fill={m.color} opacity="0.55"
              />
              <text x={gx + BAR_W / 2} y={y(p.p10) - 5} textAnchor="middle" fontSize="10" fill="var(--text-secondary)">
                {p.p10.toFixed(2)}
              </text>
              <rect
                x={gx + BAR_W + BAR_GAP} y={y(p.p20)} width={BAR_W} height={AXIS_BOTTOM - y(p.p20)}
                rx="3" fill={m.color}
              />
              <text x={gx + BAR_W + BAR_GAP + BAR_W / 2} y={y(p.p20) - 5} textAnchor="middle" fontSize="10" fontWeight="600" fill="var(--text-primary)">
                {p.p20.toFixed(2)}
              </text>
              <text x={gx + groupW / 2} y={CHART_H - 10} textAnchor="middle" fontSize="11" fill="var(--text-secondary)">
                {m.label}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="legend">
        <span className="legend-item">
          <span className="legend-swatch" style={{ background: "var(--series-1)", opacity: 0.55 }} />
          precision@10
        </span>
        <span className="legend-item">
          <span className="legend-swatch" style={{ background: "var(--series-1)" }} />
          precision@20
        </span>
      </div>
    </div>
  );
}
