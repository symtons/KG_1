import { useEffect, useMemo, useState } from "react";
import "./App.css";
import { api } from "./api";
import CandidateList from "./components/CandidateList";
import BridgeGraph from "./components/BridgeGraph";
import VerificationCard from "./components/VerificationCard";
import PrecisionChart from "./components/PrecisionChart";
import SearchBar from "./components/SearchBar";
import EntityCard from "./components/EntityCard";

function label(id) {
  return id.replaceAll("_", " ");
}

// Spaces and underscores are treated as equivalent, so "kv cache" matches
// the entity id "kv_cache".
function normalize(s) {
  return s.trim().toLowerCase().replace(/[\s_]+/g, "_");
}

export default function App() {
  const [stats, setStats] = useState(null);
  const [candidates, setCandidates] = useState([]);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [graph, setGraph] = useState(null);

  const [query, setQuery] = useState("");
  const [entity, setEntity] = useState(null);
  const [entityStatus, setEntityStatus] = useState("idle"); // idle | notfound

  useEffect(() => {
    api.stats().then(setStats).catch(console.error);
    // fetch the full ranked set (candidates.jsonl caps at 1000) so the
    // filter box has everything to search over, not just the first page
    api.candidates(1000, 0).then((res) => setCandidates(res.results)).catch(console.error);
  }, []);

  useEffect(() => {
    if (!selected) return;
    setDetail(null);
    setGraph(null);
    api.candidateDetail(selected.a, selected.c).then(setDetail).catch(console.error);
    api.bridgeGraph(selected.a, selected.c).then(setGraph).catch(console.error);
  }, [selected]);

  const filteredCandidates = useMemo(() => {
    const q = normalize(query);
    if (!q) return candidates;
    return candidates.filter((c) => c.a.includes(q) || c.c.includes(q));
  }, [candidates, query]);

  function handleQueryChange(value) {
    setQuery(value);
    // an in-progress edit invalidates whatever entity card is showing —
    // only a fresh Enter press repopulates it
    setEntity(null);
    setEntityStatus("idle");
  }

  function handleSearchEnter() {
    const q = normalize(query);
    if (!q) return;
    const knownEntity = candidates.some((c) => c.a === q || c.c === q);
    if (!knownEntity) {
      setEntity(null);
      setEntityStatus("notfound");
      return;
    }
    api
      .entity(q)
      .then((res) => {
        setEntity(res);
        setEntityStatus("idle");
      })
      .catch(() => {
        setEntity(null);
        setEntityStatus("notfound");
      });
  }

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
          <SearchBar
            value={query}
            onChange={handleQueryChange}
            onEnter={handleSearchEnter}
            matchCount={filteredCandidates.length}
            totalCount={candidates.length}
          />
          <CandidateList
            candidates={filteredCandidates}
            selected={selected}
            onSelect={setSelected}
            isFiltered={query.trim().length > 0}
          />
        </div>

        <div className="detail-pane">
          {entityStatus === "notfound" && (
            <div className="empty-state">
              No entity found matching &ldquo;{query}&rdquo; among the ranked candidates.
            </div>
          )}

          {entity && (
            <EntityCard entity={entity} selected={selected} onSelectCandidate={setSelected} />
          )}

          {!selected && !entity && entityStatus === "idle" && stats && (
            <>
              <div className="empty-state">
                Select a candidate on the left to see its bridge structure and manual
                verification, or search for a concept above.
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
