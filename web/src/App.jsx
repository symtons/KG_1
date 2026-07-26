import { useEffect, useState } from "react";
import "./App.css";
import { api } from "./api";
import CandidateList from "./components/CandidateList";
import BridgeGraph from "./components/BridgeGraph";
import VerificationCard from "./components/VerificationCard";
import PrecisionChart from "./components/PrecisionChart";

function label(id) {
  return id.replaceAll("_", " ");
}

export default function App() {
  const [stats, setStats] = useState(null);
  const [candidates, setCandidates] = useState([]);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [graph, setGraph] = useState(null);

  useEffect(() => {
    api.stats().then(setStats).catch(console.error);
    api.candidates(200, 0).then((res) => setCandidates(res.results)).catch(console.error);
  }, []);

  useEffect(() => {
    if (!selected) return;
    setDetail(null);
    setGraph(null);
    api.candidateDetail(selected.a, selected.c).then(setDetail).catch(console.error);
    api.bridgeGraph(selected.a, selected.c).then(setGraph).catch(console.error);
  }, [selected]);

  return (
    <div className="app">
      <div className="topbar">
        <h1>Efficient-LLM-Inference Bridge Finder</h1>
        <p className="subtitle">
          Structural literature-based discovery — ranked concept bridges from the pre-2023 graph,
          checked against what the field actually connected after.
        </p>
      </div>

      {stats && (
        <div className="stats-row">
          <div className="stat-tile">
            <span className="value">{stats.papers.toLocaleString()}</span>
            <span className="label">Papers</span>
          </div>
          <div className="stat-tile">
            <span className="value">{stats.entities.toLocaleString()}</span>
            <span className="label">Entities</span>
          </div>
          <div className="stat-tile">
            <span className="value">{stats.mentions.toLocaleString()}</span>
            <span className="label">Mentions</span>
          </div>
          <div className="stat-tile">
            <span className="value">{stats.citations.toLocaleString()}</span>
            <span className="label">Citation edges</span>
          </div>
          <div className="stat-tile">
            <span className="value">{stats.candidates.toLocaleString()}</span>
            <span className="label">Ranked candidates</span>
          </div>
          <div className="stat-tile">
            <span className="value">{stats.precision.system.p20.toFixed(2)}</span>
            <span className="label">System precision@20</span>
          </div>
        </div>
      )}

      <div className="main">
        <div className="list-pane">
          <CandidateList candidates={candidates} selected={selected} onSelect={setSelected} />
        </div>

        <div className="detail-pane">
          {!selected && stats && (
            <>
              <div className="empty-state">
                Select a candidate on the left to see its bridge structure and manual
                verification.
              </div>
              <PrecisionChart precision={stats.precision} />
            </>
          )}

          {selected && (
            <>
              <div className="detail-header">
                <h2>
                  {label(selected.a)} &harr; {label(selected.c)}
                </h2>
                <p className="subtitle">
                  rank #{selected.rank} &middot; score {selected.score.toFixed(3)}
                  {detail && ` · Adamic-Adar raw ${detail.adamic_adar_raw.toFixed(3)}`}
                  {" · "}established on {selected.established_a} / {selected.established_c}{" "}
                  pre-cutoff papers
                </p>
              </div>

              <BridgeGraph graph={graph} />
              {detail && <VerificationCard verification={detail.verification} />}
              {stats && <PrecisionChart precision={stats.precision} />}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
