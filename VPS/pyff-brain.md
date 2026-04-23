import { useState, useEffect, useRef, useMemo } from "react";

const PYTHON_NODES = [
  { id: "py-syntax", label: "Syntax Mastery", icon: "⚡", detail: "variables, loops, functions, classes, decorators, comprehensions", angle: -90, radius: 220 },
  { id: "py-stdlib", label: "Standard Library", icon: "📦", detail: "os, sys, subprocess, pathlib, shutil, json, re, threading, asyncio", angle: -45, radius: 240 },
  { id: "py-fileio", label: "File I/O", icon: "📂", detail: "read/write files, binary, buffers, streams", angle: -10, radius: 220 },
  { id: "py-errors", label: "Error Handling", icon: "🛡️", detail: "try/except, custom exceptions, logging", angle: 30, radius: 230 },
  { id: "py-packages", label: "Package Ecosystem", icon: "🗂️", detail: "pip, venv, pyproject.toml", angle: 70, radius: 215 },
  { id: "py-subprocess", label: "Subprocess Control", icon: "🔧", detail: "running shell commands, Popen, communicate", angle: 105, radius: 235 },
  { id: "py-ds", label: "Data Structures", icon: "🗃️", detail: "lists, dicts, sets, tuples, dataclasses", angle: 140, radius: 220 },
  { id: "py-perf", label: "Performance", icon: "🚀", detail: "profiling, generators, memory management", angle: 175, radius: 215 },
];

const FFMPEG_NODES = [
  { id: "ff-cli", label: "Core CLI Syntax", icon: "💻", detail: "-i, -c:v, -c:a, -map, -filter_complex", angle: -90, radius: 220 },
  { id: "ff-vcodecs", label: "Video Codecs", icon: "🎥", detail: "H.264, H.265, VP9, AV1, ProRes", angle: -50, radius: 235 },
  { id: "ff-acodecs", label: "Audio Codecs", icon: "🎵", detail: "AAC, MP3, FLAC, Opus, PCM", angle: -15, radius: 220 },
  { id: "ff-filters", label: "Filters & Effects", icon: "✨", detail: "scale, crop, overlay, fade, drawtext, concat", angle: 25, radius: 240 },
  { id: "ff-formats", label: "Container Formats", icon: "📼", detail: "mp4, mkv, webm, mov, avi, ts", angle: 65, radius: 225 },
  { id: "ff-stream", label: "Streaming", icon: "📡", detail: "HLS, DASH, RTMP, UDP, TCP", angle: 100, radius: 235 },
  { id: "ff-frames", label: "Frame Extraction", icon: "🖼️", detail: "image sequences, thumbnails, frame capture", angle: 135, radius: 220 },
  { id: "ff-meta", label: "Metadata & Probing", icon: "🔍", detail: "ffprobe, streams, duration, bitrate", angle: 170, radius: 215 },
  { id: "ff-pyint", label: "Python + FFmpeg", icon: "🔗", detail: "subprocess calls, ffmpeg-python lib, pipes", angle: -130, radius: 230 },
];

const SPECIAL_NODES = [
  { id: "sp-query", label: "QUERY INTERCEPTOR", icon: "🎯", color: "#FFD700", glow: "#FFD700", detail: "Catches and parses any incoming question", x: 0, y: 360 },
  { id: "sp-context", label: "CONTEXT MATCHER", icon: "🧠", color: "#bf5fff", glow: "#bf5fff", detail: "Maps question to Python or FFmpeg knowledge node", x: -220, y: 410 },
  { id: "sp-answer", label: "ANSWER SYNTHESIZER", icon: "⚗️", color: "#00ffcc", glow: "#00ffcc", detail: "Combines multi-node knowledge to form precise answer", x: 220, y: 410 },
];

const toRad = (deg) => (deg * Math.PI) / 180;

const PYTHON_CENTER = { x: -340, y: 0 };
const FFMPEG_CENTER = { x: 340, y: 0 };
const CORE_CENTER = { x: 0, y: 0 };

function getPyNodePos(node) {
  const rad = toRad(node.angle);
  return {
    x: PYTHON_CENTER.x + Math.cos(rad) * node.radius,
    y: PYTHON_CENTER.y + Math.sin(rad) * node.radius,
  };
}

function getFfNodePos(node) {
  const rad = toRad(node.angle + 180);
  return {
    x: FFMPEG_CENTER.x + Math.cos(rad) * node.radius,
    y: FFMPEG_CENTER.y + Math.sin(rad) * node.radius,
  };
}

const styles = `
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');

  .brain-map-root {
    font-family: 'Inter', sans-serif;
    background: #0a0a0f;
    min-height: 100vh;
    color: #E0E0E0;
    overflow: hidden;
    position: relative;
  }

  @keyframes pulse-core {
    0%, 100% { r: 46; filter: drop-shadow(0 0 18px #FFD700) drop-shadow(0 0 40px #FFD700); }
    50% { r: 52; filter: drop-shadow(0 0 30px #FFD700) drop-shadow(0 0 70px #ffa500); }
  }

  @keyframes pulse-ring {
    0% { r: 56; opacity: 0.7; }
    100% { r: 95; opacity: 0; }
  }

  @keyframes pulse-ring2 {
    0% { r: 56; opacity: 0.5; }
    100% { r: 115; opacity: 0; }
  }

  @keyframes dash-anim {
    to { stroke-dashoffset: -40; }
  }

  @keyframes glow-py {
    0%, 100% { filter: drop-shadow(0 0 6px #00BFFF); }
    50% { filter: drop-shadow(0 0 16px #1E90FF); }
  }

  @keyframes glow-ff {
    0%, 100% { filter: drop-shadow(0 0 6px #FF4500); }
    50% { filter: drop-shadow(0 0 16px #FF6347); }
  }

  @keyframes glow-special {
    0%, 100% { filter: drop-shadow(0 0 8px #FFD700); }
    50% { filter: drop-shadow(0 0 22px #FFD700); }
  }

  @keyframes float-badge {
    0%, 100% { transform: translateY(0px); }
    50% { transform: translateY(-4px); }
  }

  @keyframes scanline {
    0% { transform: translateY(-100%); }
    100% { transform: translateY(100vh); }
  }

  @keyframes fade-in-up {
    from { opacity: 0; transform: translateY(12px); }
    to { opacity: 1; transform: translateY(0); }
  }

  @keyframes spin-slow {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }

  @keyframes orbit {
    from { transform: rotate(0deg) translateX(62px) rotate(0deg); }
    to { transform: rotate(360deg) translateX(62px) rotate(-360deg); }
  }

  .node-py:hover { animation: glow-py 1s ease-in-out infinite; cursor: pointer; }
  .node-ff:hover { animation: glow-ff 1s ease-in-out infinite; cursor: pointer; }
  .node-special { animation: glow-special 2s ease-in-out infinite; cursor: pointer; }
  .branch-btn { transition: all 0.2s ease; }
  .branch-btn:hover { opacity: 0.85; transform: scale(1.06); cursor: pointer; }

  .search-bar {
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(0,191,255,0.3);
    border-radius: 12px;
    color: #E0E0E0;
    font-family: 'Inter', sans-serif;
    outline: none;
    transition: all 0.3s ease;
  }
  .search-bar:focus {
    border-color: #00BFFF;
    background: rgba(0,191,255,0.08);
    box-shadow: 0 0 0 3px rgba(0,191,255,0.15);
  }
  .search-bar::placeholder { color: rgba(224,224,224,0.35); }

  .tooltip-box {
    animation: fade-in-up 0.2s ease forwards;
    pointer-events: none;
  }

  .legend-pill {
    border-radius: 999px;
    padding: 4px 14px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.03em;
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .header-glow {
    text-shadow: 0 0 20px rgba(0,191,255,0.5), 0 0 40px rgba(255,215,0,0.3);
  }

  .conn-py {
    stroke: #00BFFF;
    stroke-width: 1.5;
    fill: none;
    stroke-dasharray: 6 4;
    animation: dash-anim 1.4s linear infinite;
    opacity: 0.55;
  }
  .conn-ff {
    stroke: #FF4500;
    stroke-width: 1.5;
    fill: none;
    stroke-dasharray: 6 4;
    animation: dash-anim 1.4s linear infinite;
    opacity: 0.55;
  }
  .conn-special {
    stroke: #FFD700;
    stroke-width: 1.2;
    fill: none;
    stroke-dasharray: 4 5;
    animation: dash-anim 2s linear infinite;
    opacity: 0.45;
  }
  .conn-branch-py {
    stroke: #00BFFF;
    stroke-width: 2.5;
    fill: none;
    opacity: 0.5;
  }
  .conn-branch-ff {
    stroke: #FF4500;
    stroke-width: 2.5;
    fill: none;
    opacity: 0.5;
  }

  .bg-grid {
    position: absolute;
    inset: 0;
    background-image:
      linear-gradient(rgba(0,191,255,0.04) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0,191,255,0.04) 1px, transparent 1px);
    background-size: 48px 48px;
    pointer-events: none;
  }

  .bg-radial {
    position: absolute;
    inset: 0;
    background: radial-gradient(ellipse 60% 50% at 50% 50%, rgba(255,215,0,0.04) 0%, transparent 70%);
    pointer-events: none;
  }
`;

export default function AIBrainMap() {
  const [pyExpanded, setPyExpanded] = useState(true);
  const [ffExpanded, setFfExpanded] = useState(true);
  const [search, setSearch] = useState("");
  const [hoveredNode, setHoveredNode] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [pulse, setPulse] = useState(0);
  const svgRef = useRef(null);

  useEffect(() => {
    const interval = setInterval(() => setPulse((p) => p + 1), 2000);
    return () => clearInterval(interval);
  }, []);

  const allNodes = useMemo(() => {
    const py = PYTHON_NODES.map((n) => ({ ...n, branch: "python", pos: getPyNodePos(n) }));
    const ff = FFMPEG_NODES.map((n) => ({ ...n, branch: "ffmpeg", pos: getFfNodePos(n) }));
    const sp = SPECIAL_NODES.map((n) => ({ ...n, branch: "special", pos: { x: n.x, y: n.y } }));
    return [...py, ...ff, ...sp];
  }, []);

  const filtered = useMemo(() => {
    if (!search.trim()) return new Set();
    const q = search.toLowerCase();
    const matches = new Set();
    allNodes.forEach((n) => {
      if (
        n.label.toLowerCase().includes(q) ||
        (n.detail && n.detail.toLowerCase().includes(q))
      ) matches.add(n.id);
    });
    if ("python".includes(q)) PYTHON_NODES.forEach((n) => matches.add(n.id));
    if ("ffmpeg".includes(q)) FFMPEG_NODES.forEach((n) => matches.add(n.id));
    if ("core".includes(q) || "brain".includes(q) || "agent".includes(q)) matches.add("core");
    return matches;
  }, [search, allNodes]);

  const isHighlighted = (id) => search.trim() === "" || filtered.has(id);
  const isDimmed = (id) => search.trim() !== "" && !filtered.has(id);

  const activeInfo = selectedNode || hoveredNode;
  const activeData = activeInfo ? allNodes.find((n) => n.id === activeInfo) : null;

  const SVG_W = 1100;
  const SVG_H = 900;
  const VB = `-${SVG_W / 2} -${SVG_H / 2 - 60} ${SVG_W} ${SVG_H}`;

  function cubicPath(x1, y1, x2, y2) {
    const mx = (x1 + x2) / 2;
    return `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
  }

  return (
    <>
      <style>{styles}</style>
      <div className="brain-map-root" style={{ minHeight: "100vh" }}>
        <div className="bg-grid" />
        <div className="bg-radial" />

        {/* Header */}
        <div style={{
          position: "relative", zIndex: 10, padding: "22px 32px 12px",
          display: "flex", flexDirection: "column", alignItems: "center", gap: 14
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{
              width: 10, height: 10, borderRadius: "50%",
              background: "#FFD700", boxShadow: "0 0 10px #FFD700, 0 0 25px #FFD700",
              animation: "glow-special 1.5s ease-in-out infinite"
            }} />
            <h1 className="header-glow" style={{
              fontSize: 22, fontWeight: 800, letterSpacing: "0.08em",
              color: "#E0E0E0", margin: 0, textTransform: "uppercase"
            }}>
              AI Agent — Neural Brain Map
            </h1>
            <div style={{
              width: 10, height: 10, borderRadius: "50%",
              background: "#FFD700", boxShadow: "0 0 10px #FFD700, 0 0 25px #FFD700",
              animation: "glow-special 1.5s ease-in-out infinite"
            }} />
          </div>

          {/* Search Bar */}
          <div style={{ display: "flex", alignItems: "center", gap: 10, width: "100%", maxWidth: 480 }}>
            <div style={{ position: "relative", flex: 1 }}>
              <span style={{
                position: "absolute", left: 14, top: "50%", transform: "translateY(-50%)",
                fontSize: 15, opacity: 0.5, pointerEvents: "none"
              }}>🔍</span>
              <input
                className="search-bar"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search nodes, topics, keywords..."
                style={{ width: "100%", padding: "10px 14px 10px 40px", fontSize: 13, boxSizing: "border-box" }}
              />
            </div>
            {search && (
              <button
                onClick={() => setSearch("")}
                style={{
                  background: "rgba(255,255,255,0.08)", border: "1px solid rgba(255,255,255,0.15)",
                  color: "#E0E0E0", borderRadius: 8, padding: "8px 14px", cursor: "pointer",
                  fontSize: 12, fontFamily: "Inter, sans-serif"
                }}
              >Clear</button>
            )}
          </div>

          {/* Legend */}
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "center" }}>
            <div className="legend-pill" style={{ background: "rgba(0,191,255,0.12)", border: "1px solid rgba(0,191,255,0.35)", color: "#00BFFF" }}>
              <span>🐍</span> Python Branch
            </div>
            <div className="legend-pill" style={{ background: "rgba(255,69,0,0.12)", border: "1px solid rgba(255,69,0,0.35)", color: "#FF6347" }}>
              <span>🎬</span> FFmpeg Branch
            </div>
            <div className="legend-pill" style={{ background: "rgba(255,215,0,0.10)", border: "1px solid rgba(255,215,0,0.35)", color: "#FFD700" }}>
              <span>⚡</span> Special Nodes
            </div>
            <div className="legend-pill" style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.15)", color: "#aaa" }}>
              <span>👆</span> Click to expand/collapse
            </div>
          </div>
        </div>

        {/* SVG Brain Map */}
        <div style={{ position: "relative", width: "100%", flex: 1 }}>
          <svg
            ref={svgRef}
            viewBox={VB}
            style={{ width: "100%", height: "calc(100vh - 180px)", minHeight: 580, display: "block" }}
            xmlns="http://www.w3.org/2000/svg"
          >
            <defs>
              <radialGradient id="core-grad" cx="50%" cy="50%" r="50%">
                <stop offset="0%" stopColor="#fff8dc" />
                <stop offset="40%" stopColor="#FFD700" />
                <stop offset="100%" stopColor="#b8860b" />
              </radialGradient>
              <radialGradient id="py-branch-grad" cx="50%" cy="50%" r="50%">
                <stop offset="0%" stopColor="#1E90FF" />
                <stop offset="100%" stopColor="#00BFFF" stopOpacity="0.5" />
              </radialGradient>
              <radialGradient id="ff-branch-grad" cx="50%" cy="50%" r="50%">
                <stop offset="0%" stopColor="#FF6347" />
                <stop offset="100%" stopColor="#FF4500" stopOpacity="0.5" />
              </radialGradient>
              <filter id="glow-gold">
                <feGaussianBlur stdDeviation="6" result="coloredBlur" />
                <feMerge><feMergeNode in="coloredBlur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              <filter id="glow-cyan">
                <feGaussianBlur stdDeviation="4" result="coloredBlur" />
                <feMerge><feMergeNode in="coloredBlur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              <filter id="glow-red">
                <feGaussianBlur stdDeviation="4" result="coloredBlur" />
                <feMerge><feMergeNode in="coloredBlur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              <filter id="glow-soft">
                <feGaussianBlur stdDeviation="3" result="coloredBlur" />
                <feMerge><feMergeNode in="coloredBlur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              <linearGradient id="conn-py-grad" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#FFD700" stopOpacity="0.6" />
                <stop offset="100%" stopColor="#00BFFF" stopOpacity="0.6" />
              </linearGradient>
              <linearGradient id="conn-ff-grad" x1="1" y1="0" x2="0" y2="0">
                <stop offset="0%" stopColor="#FFD700" stopOpacity="0.6" />
                <stop offset="100%" stopColor="#FF4500" stopOpacity="0.6" />
              </linearGradient>
              <marker id="arrow-py" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto">
                <path d="M0,0 L0,6 L6,3 z" fill="#00BFFF" opacity="0.6" />
              </marker>
              <marker id="arrow-ff" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto">
                <path d="M0,0 L0,6 L6,3 z" fill="#FF4500" opacity="0.6" />
              </marker>
            </defs>

            {/* Background ambient glows */}
            <ellipse cx={PYTHON_CENTER.x} cy={PYTHON_CENTER.y} rx="190" ry="170"
              fill="rgba(0,191,255,0.03)" />
            <ellipse cx={FFMPEG_CENTER.x} cy={FFMPEG_CENTER.y} rx="190" ry="170"
              fill="rgba(255,69,0,0.03)" />

            {/* Core to Branch connections */}
            <path
              d={`M${CORE_CENTER.x},${CORE_CENTER.y} Q${(CORE_CENTER.x + PYTHON_CENTER.x) / 2},${CORE_CENTER.y - 30} ${PYTHON_CENTER.x},${PYTHON_CENTER.y}`}
              stroke="url(#conn-py-grad)" strokeWidth="3" fill="none" opacity="0.6"
              strokeDasharray="10 5"
              style={{ animation: "dash-anim 2s linear infinite" }}
            />
            <path
              d={`M${CORE_CENTER.x},${CORE_CENTER.y} Q${(CORE_CENTER.x + FFMPEG_CENTER.x) / 2},${CORE_CENTER.y - 30} ${FFMPEG_CENTER.x},${FFMPEG_CENTER.y}`}
              stroke="url(#conn-ff-grad)" strokeWidth="3" fill="none" opacity="0.6"
              strokeDasharray="10 5"
              style={{ animation: "dash-anim 2s linear infinite" }}
            />

            {/* Special Node connections to core */}
            {SPECIAL_NODES.map((sp) => (
              <path
                key={`sp-conn-${sp.id}`}
                d={cubicPath(CORE_CENTER.x, CORE_CENTER.y, sp.x, sp.y - 18)}
                className="conn-special"
              />
            ))}

            {/* Python branch connections */}
            {pyExpanded && PYTHON_NODES.map((node) => {
              const pos = getPyNodePos(node);
              const dim = isDimmed(node.id);
              return (
                <path
                  key={`py-line-${node.id}`}
                  d={cubicPath(PYTHON_CENTER.x, PYTHON_CENTER.y, pos.x, pos.y)}
                  className="conn-py"
                  opacity={dim ? 0.1 : 0.55}
                  markerEnd="url(#arrow-py)"
                />
              );
            })}

            {/* FFmpeg branch connections */}
            {ffExpanded && FFMPEG_NODES.map((node) => {
              const pos = getFfNodePos(node);
              const dim = isDimmed(node.id);
              return (
                <path
                  key={`ff-line-${node.id}`}
                  d={cubicPath(FFMPEG_CENTER.x, FFMPEG_CENTER.y, pos.x, pos.y)}
                  className="conn-ff"
                  opacity={dim ? 0.1 : 0.55}
                  markerEnd="url(#arrow-ff)"
                />
              );
            })}

            {/* Python sub-nodes */}
            {pyExpanded && PYTHON_NODES.map((node) => {
              const pos = getPyNodePos(node);
              const dim = isDimmed(node.id);
              const hl = isHighlighted(node.id);
              const isHov = hoveredNode === node.id || selectedNode === node.id;
              return (
                <g
                  key={node.id}
                  transform={`translate(${pos.x},${pos.y})`}
                  className="node-py"
                  style={{ opacity: dim ? 0.18 : 1, transition: "opacity 0.3s" }}
                  onMouseEnter={() => setHoveredNode(node.id)}
                  onMouseLeave={() => setHoveredNode(null)}
                  onClick={() => setSelectedNode(selectedNode === node.id ? null : node.id)}
                  filter={isHov ? "url(#glow-cyan)" : hl && !dim ? "url(#glow-soft)" : "none"}
                >
                  <circle r={isHov ? 34 : 28} fill="rgba(0,191,255,0.08)"
                    stroke={isHov ? "#1E90FF" : "#00BFFF"}
                    strokeWidth={isHov ? 2.2 : 1.2}
                    style={{ transition: "all 0.25s ease" }}
                  />
                  <circle r={isHov ? 22 : 18}
                    fill={isHov ? "rgba(30,144,255,0.35)" : "rgba(0,191,255,0.15)"}
                    style={{ transition: "all 0.25s ease" }}
                  />
                  {search && hl && (
                    <circle r={36} fill="none" stroke="#00BFFF" strokeWidth="2"
                      opacity="0.5" strokeDasharray="4 3"
                      style={{ animation: "spin-slow 4s linear infinite" }}
                    />
                  )}
                  <text textAnchor="middle" dominantBaseline="middle"
                    fontSize={isHov ? 16 : 13} style={{ userSelect: "none" }}>{node.icon}</text>
                  <text
                    y={isHov ? 46 : 38}
                    textAnchor="middle"
                    fontSize={isHov ? 10.5 : 9.5}
                    fontWeight={isHov ? 700 : 500}
                    fill={isHov ? "#1E90FF" : "#00BFFF"}
                    fontFamily="Inter, sans-serif"
                    style={{ userSelect: "none", transition: "all 0.25s ease" }}
                  >
                    {node.label.length > 14 ? node.label.substring(0, 14) + "…" : node.label}
                  </text>
                </g>
              );
            })}

            {/* FFmpeg sub-nodes */}
            {ffExpanded && FFMPEG_NODES.map((node) => {
              const pos = getFfNodePos(node);
              const dim = isDimmed(node.id);
              const hl = isHighlighted(node.id);
              const isHov = hoveredNode === node.id || selectedNode === node.id;
              return (
                <g
                  key={node.id}
                  transform={`translate(${pos.x},${pos.y})`}
                  className="node-ff"
                  style={{ opacity: dim ? 0.18 : 1, transition: "opacity 0.3s" }}
                  onMouseEnter={() => setHoveredNode(node.id)}
                  onMouseLeave={() => setHoveredNode(null)}
                  onClick={() => setSelectedNode(selectedNode === node.id ? null : node.id)}
                  filter={isHov ? "url(#glow-red)" : hl && !dim ? "url(#glow-soft)" : "none"}
                >
                  <circle r={isHov ? 34 : 28} fill="rgba(255,69,0,0.08)"
                    stroke={isHov ? "#FF6347" : "#FF4500"}
                    strokeWidth={isHov ? 2.2 : 1.2}
                    style={{ transition: "all 0.25s ease" }}
                  />
                  <circle r={isHov ? 22 : 18}
                    fill={isHov ? "rgba(255,99,71,0.35)" : "rgba(255,69,0,0.15)"}
                    style={{ transition: "all 0.25s ease" }}
                  />
                  {search && hl && (
                    <circle r={36} fill="none" stroke="#FF4500" strokeWidth="2"
                      opacity="0.5" strokeDasharray="4 3"
                      style={{ animation: "spin-slow 4s linear infinite" }}
                    />
                  )}
                  <text textAnchor="middle" dominantBaseline="middle"
                    fontSize={isHov ? 16 : 13} style={{ userSelect: "none" }}>{node.icon}</text>
                  <text
                    y={isHov ? 46 : 38}
                    textAnchor="middle"
                    fontSize={isHov ? 10.5 : 9.5}
                    fontWeight={isHov ? 700 : 500}
                    fill={isHov ? "#FF6347" : "#FF4500"}
                    fontFamily="Inter, sans-serif"
                    style={{ userSelect: "none", transition: "all 0.25s ease" }}
                  >
                    {node.label.length > 14 ? node.label.substring(0, 14) + "…" : node.label}
                  </text>
                </g>
              );
            })}

            {/* Python Branch Node */}
            <g
              transform={`translate(${PYTHON_CENTER.x},${PYTHON_CENTER.y})`}
              className="branch-btn"
              onClick={() => setPyExpanded((p) => !p)}
              onMouseEnter={() => setHoveredNode("py-branch")}
              onMouseLeave={() => setHoveredNode(null)}
              style={{ cursor: "pointer" }}
              filter={hoveredNode === "py-branch" ? "url(#glow-cyan)" : "none"}
            >
              <circle r="58" fill="rgba(0,191,255,0.06)" stroke="#00BFFF" strokeWidth="1.5" />
              <circle r="46" fill="url(#py-branch-grad)" opacity="0.85" />
              <circle r="46" fill="none" stroke="#00BFFF" strokeWidth="1.8"
                strokeDasharray={pyExpanded ? "none" : "5 4"}
              />
              <circle r="58" fill="none" stroke="#00BFFF" strokeWidth="0.8" opacity="0.3"
                strokeDasharray="3 6"
                style={{ animation: "spin-slow 12s linear infinite" }}
              />
              <text textAnchor="middle" y="-10" fontSize="22" style={{ userSelect: "none" }}>🐍</text>
              <text textAnchor="middle" y="8" fontSize="9.5" fontWeight="700"
                fill="#ffffff" fontFamily="Inter, sans-serif" style={{ userSelect: "none" }}>
                PYTHON
              </text>
              <text textAnchor="middle" y="22" fontSize="8.5" fontWeight="500"
                fill="rgba(255,255,255,0.7)" fontFamily="Inter, sans-serif" style={{ userSelect: "none" }}>
                {pyExpanded ? "[ collapse ]" : "[ expand ]"}
              </text>
            </g>

            {/* FFmpeg Branch Node */}
            <g
              transform={`translate(${FFMPEG_CENTER.x},${FFMPEG_CENTER.y})`}
              className="branch-btn"
              onClick={() => setFfExpanded((p) => !p)}
              onMouseEnter={() => setHoveredNode("ff-branch")}
              onMouseLeave={() => setHoveredNode(null)}
              style={{ cursor: "pointer" }}
              filter={hoveredNode === "ff-branch" ? "url(#glow-red)" : "none"}
            >
              <circle r="58" fill="rgba(255,69,0,0.06)" stroke="#FF4500" strokeWidth="1.5" />
              <circle r="46" fill="url(#ff-branch-grad)" opacity="0.85" />
              <circle r="46" fill="none" stroke="#FF4500" strokeWidth="1.8"
                strokeDasharray={ffExpanded ? "none" : "5 4"}
              />
              <circle r="58" fill="none" stroke="#FF4500" strokeWidth="0.8" opacity="0.3"
                strokeDasharray="3 6"
                style={{ animation: "spin-slow 12s linear infinite reverse" }}
              />
              <text textAnchor="middle" y="-10" fontSize="22" style={{ userSelect: "none" }}>🎬</text>
              <text textAnchor="middle" y="8" fontSize="9.5" fontWeight="700"
                fill="#ffffff" fontFamily="Inter, sans-serif" style={{ userSelect: "none" }}>
                FFMPEG
              </text>
              <text textAnchor="middle" y="22" fontSize="8.5" fontWeight="500"
                fill="rgba(255,255,255,0.7)" fontFamily="Inter, sans-serif" style={{ userSelect: "none" }}>
                {ffExpanded ? "[ collapse ]" : "[ expand ]"}
              </text>
            </g>

            {/* Core pulsating node */}
            <g
              transform={`translate(${CORE_CENTER.x},${CORE_CENTER.y})`}
              onMouseEnter={() => setHoveredNode("core")}
              onMouseLeave={() => setHoveredNode(null)}
              onClick={() => setSelectedNode(selectedNode === "core" ? null : "core")}
              style={{ cursor: "pointer" }}
            >
              {/* Pulse rings */}
              <circle r="0" fill="none" stroke="#FFD700" strokeWidth="1.5"
                key={`ring1-${pulse}`}
                style={{
                  animation: "pulse-ring 2.2s ease-out forwards",
                  transformOrigin: "center"
                }}
              />
              <circle r="0" fill="none" stroke="#ffa500" strokeWidth="1"
                key={`ring2-${pulse}`}
                style={{
                  animation: "pulse-ring2 2.8s ease-out 0.4s forwards",
                  transformOrigin: "center"
                }}
              />
              {/* Orbit ring */}
              <circle r="68" fill="none" stroke="#FFD700" strokeWidth="0.6"
                opacity="0.2" strokeDasharray="4 8"
                style={{ animation: "spin-slow 8s linear infinite" }}
              />
              <circle r="82" fill="none" stroke="#ffa500" strokeWidth="0.4"
                opacity="0.15" strokeDasharray="3 10"
                style={{ animation: "spin-slow 14s linear infinite reverse" }}
              />
              <circle r="55" fill="rgba(255,215,0,0.07)" stroke="#FFD700" strokeWidth="1.5" opacity="0.5" />
              <circle r="46" fill="rgba(255,215,0,0.12)" />
              <circle r="38" fill="url(#core-grad)"
                filter="url(#glow-gold)"
                style={{ animation: "pulse-core 2.5s ease-in-out infinite" }}
              />
              <text textAnchor="middle" y="-8" fontSize="18" style={{ userSelect: "none" }}>🧠</text>
              <text textAnchor="middle" y="8" fontSize="8" fontWeight="800"
                fill="#0a0a0f" fontFamily="Inter, sans-serif" letterSpacing="0.05em" style={{ userSelect: "none" }}>
                AI AGENT
              </text>
              <text textAnchor="middle" y="20" fontSize="6.5" fontWeight="700"
                fill="#0a0a0f" fontFamily="Inter, sans-serif" letterSpacing="0.08em" style={{ userSelect: "none" }}>
                CORE BRAIN
              </text>
            </g>

            {/* Special Nodes */}
            {SPECIAL_NODES.map((sp) => {
              const isHov = hoveredNode === sp.id || selectedNode === sp.id;
              const dim = isDimmed(sp.id);
              return (
                <g
                  key={sp.id}
                  transform={`translate(${sp.x},${sp.y})`}
                  className="node-special"
                  style={{
                    opacity: dim ? 0.18 : 1,
                    transition: "opacity 0.3s",
                    cursor: "pointer"
                  }}
                  onMouseEnter={() => setHoveredNode(sp.id)}
                  onMouseLeave={() => setHoveredNode(null)}
                  onClick={() => setSelectedNode(selectedNode === sp.id ? null : sp.id)}
                  filter={isHov ? "url(#glow-gold)" : "url(#glow-soft)"}
                >
                  <rect
                    x="-68" y="-20" width="136" height="40" rx="20"
                    fill="rgba(0,0,0,0.7)"
                    stroke={sp.color}
                    strokeWidth={isHov ? 2 : 1.4}
                    style={{ transition: "all 0.25s" }}
                  />
                  <rect
                    x="-68" y="-20" width="136" height="40" rx="20"
                    fill={sp.color} opacity="0.07"
                  />
                  <text textAnchor="middle" y="-5" fontSize="11" style={{ userSelect: "none" }}>{sp.icon}</text>
                  <text textAnchor="middle" y="9" fontSize="8" fontWeight="800"
                    fill={sp.color} fontFamily="Inter, sans-serif" letterSpacing="0.08em"
                    style={{ userSelect: "none" }}>
                    {sp.label}
                  </text>
                </g>
              );
            })}

            {/* Tooltip / Info Panel in SVG */}
            {activeData && activeData.detail && (
              <g transform={`translate(0, ${SVG_H / 2 - 120})`}>
                <rect x="-240" y="-28" width="480" height="56" rx="12"
                  fill="rgba(10,10,20,0.92)" stroke="rgba(255,255,255,0.12)" strokeWidth="1" />
                <text textAnchor="middle" y="-10" fontSize="10" fontWeight="700"
                  fill="#E0E0E0" fontFamily="Inter, sans-serif" style={{ userSelect: "none" }}>
                  {activeData.icon} {activeData.label}
                </text>
                <text textAnchor="middle" y="8" fontSize="8.5" fontWeight="400"
                  fill="rgba(224,224,224,0.65)" fontFamily="Inter, sans-serif" style={{ userSelect: "none" }}>
                  {activeData.detail && activeData.detail.length > 70
                    ? activeData.detail.substring(0, 70) + "…"
                    : activeData.detail}
                </text>
              </g>
            )}
          </svg>
        </div>

        {/* Bottom Stats Bar */}
        <div style={{
          position: "fixed", bottom: 0, left: 0, right: 0,
          background: "rgba(10,10,15,0.92)", borderTop: "1px solid rgba(255,255,255,0.07)",
          padding: "8px 24px", display: "flex", justifyContent: "center",
          gap: 32, zIndex: 20, backdropFilter: "blur(8px)"
        }}>
          {[
            { label: "Python Nodes", value: PYTHON_NODES.length, color: "#00BFFF" },
            { label: "FFmpeg Nodes", value: FFMPEG_NODES.length, color: "#FF4500" },
            { label: "Special Nodes", value: SPECIAL_NODES.length, color: "#FFD700" },
            { label: "Total Connections", value: PYTHON_NODES.length + FFMPEG_NODES.length + SPECIAL_NODES.length + 2, color: "#bf5fff" },
          ].map((stat) => (
            <div key={stat.label} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
              <span style={{ fontSize: 16, fontWeight: 800, color: stat.color }}>{stat.value}</span>
              <span style={{ fontSize: 10, color: "rgba(224,224,224,0.45)", letterSpacing: "0.04em" }}>{stat.label}</span>
            </div>
          ))}
          {search && (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
              <span style={{ fontSize: 16, fontWeight: 800, color: "#00ffcc" }}>{filtered.size}</span>
              <span style={{ fontSize: 10, color: "rgba(224,224,224,0.45)", letterSpacing: "0.04em" }}>Search Matches</span>
            </div>
          )}
        </div>
      </div>
    </>
  );
}