const pptxgen = require("pptxgenjs");

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.author = "claude-code-delegate";
pres.title = "ADR Summary — Architecture Decision Records";

const C = {
  navy: "1E2761",
  ice: "CADCFC",
  white: "FFFFFF",
  light: "F0F4F8",
  teal: "1C7293",
  slate: "36454F",
  green: "2C5F2D",
  amber: "B85042",
  gray: "8899AA",
};

function addSlideNum(slide, num, total) {
  slide.addText(`${num} / ${total}`, {
    x: 8.5, y: 5.15, w: 1.2, h: 0.35,
    fontSize: 9, color: C.gray, align: "right", fontFace: "Calibri",
  });
}

const TOTAL = 8;

// ---------- TITLE ----------
{
  const s = pres.addSlide();
  s.background = { color: C.navy };
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.teal },
  });
  s.addText("Architecture Decision Records", {
    x: 0.8, y: 1.4, w: 8.4, h: 1.0,
    fontSize: 36, fontFace: "Calibri", bold: true, color: C.white, margin: 0,
  });
  s.addText("claude-code-delegate — ADR 0001 through 0006", {
    x: 0.8, y: 2.5, w: 8.4, h: 0.5,
    fontSize: 16, fontFace: "Calibri", color: C.ice, margin: 0,
  });
  s.addText("Architecture Review · May 2026", {
    x: 0.8, y: 3.2, w: 8.4, h: 0.4,
    fontSize: 13, fontFace: "Calibri", color: C.teal, margin: 0,
  });
  addSlideNum(s, 1, TOTAL);
}

// ---------- ADR SLIDES ----------
const adrs = [
  {
    num: "0001", title: "DeepSeek V4 Provider",
    status: "Accepted",
    decision: "Default to DeepSeek V4 models (Pro for reasoning, Flash for subagents) routed through cc-switch.",
    rationale: [
      "Competitive reasoning at significantly lower cost than Anthropic direct API",
      "cc-switch abstracts provider config — no provider-specific credentials in wrapper",
      "Provider-agnostic via CLAUDE_DELEGATE_MODEL; switching provider requires only an env var",
      "Retry transient 429/5xx with bounded exponential backoff; fail closed with diagnostics",
    ],
  },
  {
    num: "0002", title: "MCP Server",
    status: "Proposed",
    decision: "Add an MCP server (stdio JSON-RPC) alongside the existing shell wrapper. Both coexist.",
    rationale: [
      "Shell wrapper has discovery fragility, shell invocation tax, and no programmatic contract",
      "MCP provides automatic discovery, typed tool contracts, structured error handling",
      "Server imports existing Python modules — ~50 lines of glue code over shared modules",
      "Wrapper stays as CLI fallback; no backward-compatibility break",
    ],
  },
  {
    num: "0003", title: "CI/CD Quality Gates",
    status: "Accepted (2026-05-12)",
    decision: "Adopt deterministic, no-live-service CI quality gates as the merge/release confidence boundary.",
    rationale: [
      "Manual discipline does not scale — gates automate the 'forgot to run tests' failure mode",
      "Mocked external services (fake claude, mock MCP) keep CI fast and deterministic",
      "Local and CI parity via a single documented command",
      "External-system testing deferred to future secret-backed CI environment",
    ],
  },
  {
    num: "0004", title: "Async Delegation Leases",
    status: "Accepted (2026-05-13)",
    decision: "Use --start / --poll contract with single-flight lease semantics for long-running delegations.",
    rationale: [
      "Synchronous blocking forces orchestrator to hold connection indefinitely",
      "Hard timeout aborts work that may still be productive — leases preserve running work",
      "Detached supervisor survives --start process crash; jobs persist on disk",
      "Polling reads file state, not process state — reliable across process/session boundaries",
    ],
  },
  {
    num: "0005", title: "OpenCode Executor",
    status: "Accepted",
    decision: "Add OpenCode (opencode run) as a second executor backend alongside Claude Code.",
    rationale: [
      "Removes Anthropic dependency — pipeline works without Anthropic API key",
      "Shared pipeline architecture; only invocation and parsing differ between backends",
      "Model mapping via static dictionary; OpenCode uses provider/model format",
      "Trade-off: no effort control, no MCP config passing, no subagent control in OpenCode backend",
    ],
  },
  {
    num: "0006", title: "Architecture Deepening",
    status: "Accepted (2026-05-17)",
    decision: "Apply five independent refactoring slices: heartbeat, pipeline params, classifier, MCP, parser.",
    rationale: [
      "Heartbeat duplicated across invokers → extracted to shared heartbeat.py",
      "Pipeline param resolution copy-pasted between sync/async → shared _resolve_pipeline_config",
      "Classifier and envelope builder split across files → merged into classifier.py",
      "MCP server used dynamic imports → declarative module imports at load time",
      "Compact parser handled two formats monolithically → per-backend adapters",
    ],
  },
];

adrs.forEach((adr, i) => {
  const s = pres.addSlide();
  s.background = { color: C.light };

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.teal },
  });

  s.addText(`ADR ${adr.num}`, {
    x: 0.6, y: 0.4, w: 2.5, h: 0.35,
    fontSize: 11, fontFace: "Calibri", color: C.teal, bold: true, margin: 0,
  });

  s.addText(adr.title, {
    x: 0.6, y: 0.75, w: 8.8, h: 0.5,
    fontSize: 26, fontFace: "Calibri", bold: true, color: C.navy, margin: 0,
  });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.6, y: 1.35, w: 1.6, h: 0.32, fill: { color: adr.status.startsWith("Accepted") ? C.green : C.amber },
  });
  s.addText(adr.status, {
    x: 0.6, y: 1.35, w: 1.6, h: 0.32,
    fontSize: 10, fontFace: "Calibri", color: C.white, align: "center", valign: "middle", bold: true, margin: 0,
  });

  s.addText("Decision", {
    x: 0.6, y: 1.9, w: 8.8, h: 0.3,
    fontSize: 13, fontFace: "Calibri", bold: true, color: C.navy, margin: 0,
  });
  s.addText(adr.decision, {
    x: 0.6, y: 2.2, w: 8.8, h: 0.7,
    fontSize: 12, fontFace: "Calibri", color: C.slate, margin: 0, valign: "top",
  });

  s.addText("Rationale", {
    x: 0.6, y: 2.95, w: 8.8, h: 0.3,
    fontSize: 13, fontFace: "Calibri", bold: true, color: C.navy, margin: 0,
  });

  const bulletOpts = adr.rationale.map((r, ri) => ({
    text: r,
    options: { bullet: true, breakLine: ri < adr.rationale.length - 1, fontSize: 11, fontFace: "Calibri", color: C.slate },
  }));
  s.addText(bulletOpts, {
    x: 0.6, y: 3.25, w: 8.8, h: 1.8, valign: "top", margin: 0, paraSpaceAfter: 4,
  });

  addSlideNum(s, i + 2, TOTAL);
});

// ---------- SUMMARY ----------
{
  const s = pres.addSlide();
  s.background = { color: C.navy };

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.teal },
  });

  s.addText("ADR Summary", {
    x: 0.8, y: 0.5, w: 8.4, h: 0.6,
    fontSize: 28, fontFace: "Calibri", bold: true, color: C.white, margin: 0,
  });

  const rows = [
    ["#", "Title", "Status", "Category"],
    ["0001", "DeepSeek V4 Provider", "Accepted", "Infrastructure"],
    ["0002", "MCP Server", "Proposed", "Architecture"],
    ["0003", "CI/CD Quality Gates", "Accepted", "Process"],
    ["0004", "Async Delegation Leases", "Accepted", "Architecture"],
    ["0005", "OpenCode Executor", "Accepted", "Architecture"],
    ["0006", "Architecture Deepening", "Accepted", "Refactoring"],
  ];

  const headerOpts = { bold: true, color: C.white, fontSize: 11, fontFace: "Calibri", align: "center", valign: "middle" };
  const cellOpts = { color: C.ice, fontSize: 10, fontFace: "Calibri", align: "center", valign: "middle" };

  const tableData = rows.map((row, ri) =>
    row.map((cell) => ({
      text: cell,
      options: ri === 0 ? { ...headerOpts, fill: { color: C.teal } } : { ...cellOpts, fill: { color: ri % 2 === 0 ? "1A2D5A" : C.navy } },
    }))
  );

  s.addTable(tableData, {
    x: 0.8, y: 1.4, w: 8.4,
    colW: [0.8, 3.0, 2.0, 2.6],
    rowH: [0.35, 0.35, 0.35, 0.35, 0.35, 0.35, 0.35],
    border: { pt: 0.5, color: "2A4A7A" },
  });

  s.addText("5/6 ADRs accepted · 1 proposed · Categories cover infra, architecture, process, and refactoring", {
    x: 0.8, y: 4.5, w: 8.4, h: 0.4,
    fontSize: 11, fontFace: "Calibri", color: C.ice, align: "center", margin: 0,
  });

  addSlideNum(s, 8, TOTAL);
}

pres.writeFile({ fileName: "docs/adr-summary.pptx" }).then(() => console.log("OK: docs/adr-summary.pptx"));
