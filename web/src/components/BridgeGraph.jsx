import { ReactFlow, Background, Controls, Handle, Position } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

function EndpointNode({ data }) {
  return (
    <div
      style={{
        padding: "10px 14px",
        borderRadius: 8,
        background: "var(--series-1)",
        color: "#fff",
        fontSize: 13,
        fontWeight: 600,
        maxWidth: 180,
        textAlign: "center",
        boxShadow: "0 1px 3px rgba(0,0,0,0.2)",
      }}
    >
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      {data.label.replaceAll("_", " ")}
    </div>
  );
}

function BridgeNode({ data }) {
  return (
    <div
      style={{
        padding: "6px 10px",
        borderRadius: 6,
        background: "var(--surface-card)",
        border: "1px solid var(--border)",
        color: "var(--text-primary)",
        fontSize: 11,
        maxWidth: 150,
        textAlign: "center",
      }}
    >
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
      <div>{data.label.replaceAll("_", " ")}</div>
      <div style={{ fontSize: 9, color: "var(--text-muted)" }}>degree {data.degree}</div>
    </div>
  );
}

const nodeTypes = { endpoint: EndpointNode, bridge: BridgeNode };

export default function BridgeGraph({ graph }) {
  if (!graph) return null;

  const edges = graph.edges.map((e) => ({
    ...e,
    type: "smoothstep",
    style: {
      stroke: e.highlighted ? "var(--series-2)" : "var(--text-muted)",
      strokeWidth: e.highlighted ? 2.5 : 1.5,
    },
    labelStyle: { fontSize: 10, fill: "var(--text-secondary)" },
    labelBgStyle: { fill: "var(--surface-card)" },
  }));

  return (
    <div className="graph-card">
      <ReactFlow
        nodes={graph.nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        nodesDraggable={true}
        nodesConnectable={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
