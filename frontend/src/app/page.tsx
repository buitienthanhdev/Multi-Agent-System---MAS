"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_ATLAS_API_URL || "http://127.0.0.1:8000";

const DEMO_ACCOUNTS = [
  { label: "Owner (Toàn quyền điều hành)", token: "demo-owner-token" },
  { label: "Viewer (Chế độ chỉ đọc)", token: "demo-viewer-token" },
  { label: "Other Tenant (Test cách ly Workspace)", token: "demo-other-token" },
];

const MISSION_PRESETS = [
  {
    category: "💻 Kỹ thuật Phần mềm",
    prompt: "Phát triển phần mềm viết module Token Bucket Rate Limiter bảo vệ API Gateway và chạy kiểm thử tự động trong sandbox.",
  },
  {
    category: "📋 Quy trình SOP & Runbook",
    prompt: "Xây dựng quy trình SOP ứng phó sự cố bảo mật & khôi phục dữ liệu (Disaster Recovery Runbook) cho hệ thống Cloud nội bộ.",
  },
  {
    category: "🔎 Nghiên cứu Chuyên sâu",
    prompt: "Nghiên cứu thị trường xu hướng vật liệu xây dựng xanh và tiêu chuẩn phát thải thấp tại Việt Nam trong 14 ngày.",
  },
  {
    category: "🤝 Tư vấn & CSKH B2B",
    prompt: "Xây dựng kịch bản tư vấn kỹ thuật, xử lý khiếu nại và quy trình escalation cho đội ngũ chăm sóc khách hàng B2B.",
  },
  {
    category: "🎨 Nội dung & Thiết kế",
    prompt: "Tạo nội dung và media banner giới thiệu cẩm nang phối màu kiến trúc hiện đại cho căn hộ đô thị.",
  },
  {
    category: "📊 Khoa học Dữ liệu",
    prompt: "Phân tích dữ liệu chuỗi thời gian, kiểm định xu hướng song song (Parallel Trends) và đánh giá hiệu quả chuyển đổi đa kênh.",
  },
  {
    category: "🚀 Chiến dịch Tăng trưởng",
    prompt: "Ngân sách tối đa 30 triệu đồng, hãy tìm cách đưa doanh thu sơn OneCoat lên 80 triệu đồng trong 30 ngày.",
  },
];

const TASK_TYPE_VN: Record<string, string> = {
  software: "Kỹ thuật Phần mềm",
  docs_ops: "Quy trình & Vận hành",
  market_research: "Nghiên cứu Chuyên sâu",
  customer_care: "Tư vấn & CSKH",
  content_media: "Nội dung & Thiết kế",
  data_analysis: "Phân tích Dữ liệu",
  marketing_growth: "Tăng trưởng Kinh doanh",
  general_execution: "Giải quyết Bài toán Mở",
};

interface AgentProfile {
  id: string;
  handle: string;
  name: string;
  role: string;
  summonReason: string;
  avatar: string;
  accent: string;
  softBg: string;
}

const AGENT_ROSTER: Record<string, AgentProfile> = {
  user: {
    id: "user",
    handle: "@Bạn",
    name: "Người điều hành (Intent)",
    role: "Giao mục tiêu & Phê duyệt",
    summonReason: "Khởi phát mục tiêu (Intent) bằng ngôn ngữ tự nhiên và giữ quyền phê duyệt cuối cùng.",
    avatar: "👤",
    accent: "#1d4ed8",
    softBg: "#eff6ff",
  },
  compiler: {
    id: "compiler",
    handle: "@Compiler",
    name: "Kiến trúc sư Hợp đồng",
    role: "Chuẩn hóa mục tiêu & ràng buộc an toàn",
    summonReason: "Biên dịch câu lệnh tự nhiên thành Mission Contract, bóc tách chỉ tiêu và khóa các quyền nhạy cảm.",
    avatar: "🧭",
    accent: "#4338ca",
    softBg: "#eef2ff",
  },
  planner: {
    id: "planner",
    handle: "@Planner",
    name: "Tổng Công trình sư (Start Agent)",
    role: "Chọn chiến lược & triệu tập Subagents",
    summonReason: "Đánh giá các phương án đánh đổi, thiết lập đồ thị DAG và gọi đúng các Subagent chuyên môn vào làm việc.",
    avatar: "🧠",
    accent: "#6d28d9",
    softBg: "#f5f3ff",
  },
  research: {
    id: "research",
    handle: "@Researcher",
    name: "Chuyên gia Nghiên cứu",
    role: "Thu thập nguồn dữ liệu & lọc mã độc",
    summonReason: "Được gọi vào để khảo sát dữ liệu thực tế, kiểm tra nguồn và cô lập Prompt Injection trước khi biên soạn.",
    avatar: "🔎",
    accent: "#0369a1",
    softBg: "#f0f9ff",
  },
  content: {
    id: "content",
    handle: "@Writer",
    name: "Chuyên gia Biên soạn",
    role: "Soạn giải pháp, tài liệu SOP & bài viết",
    summonReason: "Được gọi vào để chuyển hóa dữ liệu nghiên cứu thành văn bản giải pháp, quy trình SOP hoặc thông điệp.",
    avatar: "✍️",
    accent: "#b45309",
    softBg: "#fffbeb",
  },
  media: {
    id: "media",
    handle: "@Designer",
    name: "Chuyên gia Thiết kế",
    role: "Thiết kế bố cục trực quan & Wireframe",
    summonReason: "Được gọi chạy song song để dựng khung bố cục hình ảnh (SVG Wireframe) đồng bộ với nội dung.",
    avatar: "🎨",
    accent: "#be185d",
    softBg: "#fdf2f8",
  },
  sales_assistance: {
    id: "sales_assistance",
    handle: "@Advisor",
    name: "Chuyên gia Tư vấn",
    role: "Xây dựng kịch bản tư vấn & CSKH",
    summonReason: "Được gọi vào để thiết kế Playbook hỏi đáp, xử lý khiếu nại và quy trình bàn giao khách hàng.",
    avatar: "🤝",
    accent: "#0f766e",
    softBg: "#f0fdfa",
  },
  software_engineering: {
    id: "software_engineering",
    handle: "@Engineer",
    name: "Kỹ sư Phần mềm",
    role: "Viết code & chạy Unit Test trong Sandbox",
    summonReason: "Được gọi vào để viết bản vá mã nguồn (Patch) và tự động kiểm thử AST + Unit Test trong môi trường cô lập.",
    avatar: "💻",
    accent: "#1d4ed8",
    softBg: "#eff6ff",
  },
  review: {
    id: "review",
    handle: "@Auditor",
    name: "Thanh tra Độc lập",
    role: "Kiểm duyệt chéo chất lượng & tuân thủ",
    summonReason: "Được gọi vào để kiểm tra độc lập đầu ra của @Writer, bác bỏ ngay nếu phát hiện thông số bịa đặt.",
    avatar: "🛡️",
    accent: "#b91c1c",
    softBg: "#fef2f2",
  },
  publishing: {
    id: "publishing",
    handle: "@Gateway",
    name: "Cổng Thực thi",
    role: "Kiểm tra phê duyệt & xuất bản an toàn",
    summonReason: "Được gọi vào để kiểm tra chữ ký SHA-256 Approval, giữ chỗ ngân sách và thực thi lệnh ra bên ngoài.",
    avatar: "⚡",
    accent: "#c2410c",
    softBg: "#fff7ed",
  },
  analytics: {
    id: "analytics",
    handle: "@Analyst",
    name: "Nhà Khoa học Dữ liệu",
    role: "Kiểm định thống kê DiD & tối ưu đóng vòng",
    summonReason: "Được gọi vào để đo dữ liệu nền (Baseline), kiểm định Parallel Trends và tính hiệu quả đối chứng (DiD).",
    avatar: "📊",
    accent: "#047857",
    softBg: "#ecfdf5",
  },
  report: {
    id: "report",
    handle: "@Reporter",
    name: "Thư ký Tổng hợp",
    role: "Tổng hợp báo cáo nghiệm thu cuối cùng",
    summonReason: "Được gọi ở chặng cuối để gom toàn bộ sản phẩm, bằng chứng đã xác minh và xuất Báo cáo Nghiệm thu.",
    avatar: "📑",
    accent: "#334155",
    softBg: "#f1f5f9",
  },
};

const STATUS_STYLE: Record<string, { label: string; bg: string; fg: string; border: string }> = {
  draft: { label: "Bản nháp", bg: "#f1f5f9", fg: "#475569", border: "#cbd5e1" },
  active: { label: "Đang thực hiện", bg: "#eff6ff", fg: "#1d4ed8", border: "#bfdbfe" },
  paused: { label: "Tạm dừng", bg: "#fffbeb", fg: "#b45309", border: "#fde68a" },
  completed: { label: "Hoàn thành", bg: "#ecfdf5", fg: "#047857", border: "#a7f3d0" },
  failed: { label: "Lỗi", bg: "#fef2f2", fg: "#b91c1c", border: "#fecaca" },
  cancelled: { label: "Đã hủy", bg: "#f1f5f9", fg: "#64748b", border: "#e2e8f0" },
  planned: { label: "Chờ tới lượt", bg: "#f8fafc", fg: "#64748b", border: "#e2e8f0" },
  running: { label: "Đang chạy...", bg: "#eff6ff", fg: "#1d4ed8", border: "#93c5fd" },
  waiting_approval: { label: "Chờ bạn duyệt", bg: "#fffbeb", fg: "#b45309", border: "#fcd34d" },
  blocked: { label: "Tạm chặn", bg: "#fef2f2", fg: "#b91c1c", border: "#fecaca" },
  awaiting_approval: { label: "Chờ bạn duyệt", bg: "#fffbeb", fg: "#b45309", border: "#fcd34d" },
  approved: { label: "Đã duyệt", bg: "#ecfdf5", fg: "#047857", border: "#a7f3d0" },
  succeeded: { label: "Đã hoàn tất", bg: "#ecfdf5", fg: "#047857", border: "#a7f3d0" },
};

function StatusBadge({ status }: { status: string }) {
  const st = STATUS_STYLE[status] || { label: status, bg: "#f1f5f9", fg: "#334155", border: "#cbd5e1" };
  return (
    <span
      style={{
        background: st.bg,
        color: st.fg,
        border: `1px solid ${st.border}`,
        padding: "2px 9px",
        borderRadius: 9999,
        fontSize: 11,
        fontWeight: 600,
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        whiteSpace: "nowrap",
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: st.fg }} />
      {st.label}
    </span>
  );
}

function vnd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "Không yêu cầu";
  return n.toLocaleString("vi-VN") + " ₫";
}

function ArtifactAttachment({ title, content, downloadUrl }: { title: string; content: string; downloadUrl?: string }) {
  const [expanded, setExpanded] = useState<boolean>(false);
  const lines = content.split("\n");
  const isLong = lines.length > 8 || content.length > 420;
  const preview = isLong && !expanded ? content.slice(0, 380).trim() + "..." : content;

  return (
    <div
      style={{
        marginTop: 12,
        background: "#f8fafc",
        border: "1px solid #e2e8f0",
        borderRadius: 10,
        padding: "12px 14px",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8, gap: 8 }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: "#0f172a" }}>📄 Tài liệu đính kèm: {title}</span>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          {isLong && (
            <button
              type="button"
              onClick={() => setExpanded(!expanded)}
              style={{
                background: "#ffffff",
                color: "#2563eb",
                border: "1px solid #cbd5e1",
                borderRadius: 6,
                padding: "3px 9px",
                fontSize: 11,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              {expanded ? "Thu gọn ▲" : "Xem đầy đủ ▼"}
            </button>
          )}
          {downloadUrl && (
            <a
              href={`${API_BASE}${downloadUrl}`}
              target="_blank"
              rel="noreferrer"
              style={{ fontSize: 11, fontWeight: 600, color: "#2563eb" }}
            >
              Tải file ↗
            </a>
          )}
        </div>
      </div>
      <pre
        style={{
          fontSize: 12.5,
          color: "#334155",
          whiteSpace: "pre-wrap",
          lineHeight: 1.6,
          margin: 0,
          maxHeight: expanded ? 480 : 200,
          overflowY: "auto",
        }}
      >
        {preview}
      </pre>
    </div>
  );
}

interface ChatMessage {
  id: string;
  agent: AgentProfile;
  toHandles: string[];
  title: string;
  body: string;
  attachmentTitle?: string;
  attachmentContent?: string;
  downloadUrl?: string;
  tag?: string;
  actionCard?: any;
  isUser?: boolean;
}

interface DagStage {
  stageIndex: number;
  label: string;
  tasks: any[];
}

export default function AtlasCleanWorkspace() {
  const [token, setToken] = useState<string>(DEMO_ACCOUNTS[0].token);
  const [health, setHealth] = useState<any>(null);
  const [workspaceId, setWorkspaceId] = useState<string>("");
  const [missions, setMissions] = useState<any[]>([]);
  const [selectedMissionId, setSelectedMissionId] = useState<string>("");
  const [missionDetail, setMissionDetail] = useState<any>(null);
  const [planData, setPlanData] = useState<any>({ plan: null, tasks: [], dependencies: [], decisions: [] });
  const [runs, setRuns] = useState<any[]>([]);
  const [artifacts, setArtifacts] = useState<any[]>([]);
  const [evidence, setEvidence] = useState<any[]>([]);
  const [evaluations, setEvaluations] = useState<any[]>([]);
  const [actions, setActions] = useState<any[]>([]);
  const [budget, setBudget] = useState<any>({ accounts: [], entries: [] });
  const [kpis, setKpis] = useState<any>(null);

  const [sidebarTab, setSidebarTab] = useState<"missions" | "agents">("missions");
  const [rightPanelTab, setRightPanelTab] = useState<"flow" | "files">("flow");
  const [selectedNodeKey, setSelectedNodeKey] = useState<string>("");

  const [chatInput, setChatInput] = useState<string>("");
  const [liveMode, setLiveMode] = useState<boolean>(false);
  const [sending, setSending] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string>("");
  const [infoMsg, setInfoMsg] = useState<string>("");
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  const apiFetch = useCallback(
    async (path: string, opts: RequestInit = {}) => {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        ...((opts.headers as Record<string, string>) || {}),
      };
      const res = await fetch(`${API_BASE}${path}`, { ...opts, headers });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(`${res.status}: ${errBody.detail || JSON.stringify(errBody)}`);
      }
      return res.json();
    },
    [token]
  );

  const loadWorkspaceData = useCallback(
    async (wsId: string) => {
      if (!wsId) return;
      try {
        const ms = await apiFetch(`/api/missions?workspace_id=${wsId}`);
        setMissions(ms);
        if (ms.length > 0 && !ms.some((m: any) => m.id === selectedMissionId)) {
          setSelectedMissionId(ms[0].id);
        }
      } catch (e: any) {
        setErrorMsg(e.message);
      }
    },
    [apiFetch, selectedMissionId]
  );

  const loadMissionAll = useCallback(
    async (mid: string) => {
      if (!mid) return;
      try {
        const [det, pl, rs, arts, evs, evals, acts, bdg, kpiData] = await Promise.all([
          apiFetch(`/api/missions/${mid}`),
          apiFetch(`/api/missions/${mid}/plan`),
          apiFetch(`/api/missions/${mid}/runs`),
          apiFetch(`/api/missions/${mid}/artifacts`),
          apiFetch(`/api/missions/${mid}/evidence`),
          apiFetch(`/api/missions/${mid}/evaluations`),
          apiFetch(`/api/missions/${mid}/actions`),
          apiFetch(`/api/missions/${mid}/budget`),
          apiFetch(`/api/missions/${mid}/kpis`),
        ]);
        setMissionDetail(det);
        setPlanData(pl);
        setRuns(rs);
        setArtifacts(arts);
        setEvidence(evs);
        setEvaluations(evals);
        setActions(acts);
        setBudget(bdg);
        setKpis(kpiData);
      } catch (e: any) {
        setErrorMsg(e.message);
      }
    },
    [apiFetch]
  );

  useEffect(() => {
    setErrorMsg("");
    fetch(`${API_BASE}/api/health`)
      .then((r) => r.json())
      .then(setHealth)
      .catch((e) => setErrorMsg(`Không kết nối được backend (${API_BASE}): ${e.message}`));
    apiFetch("/api/me")
      .then((u) => {
        const ws = u.workspaces?.[0]?.id || "";
        setWorkspaceId(ws);
        loadWorkspaceData(ws);
      })
      .catch((e) => setErrorMsg(e.message));
  }, [token, apiFetch, loadWorkspaceData]);

  useEffect(() => {
    if (selectedMissionId) {
      setSelectedNodeKey("");
      loadMissionAll(selectedMissionId);
    }
  }, [selectedMissionId, loadMissionAll]);

  // Auto-refresh while tasks are actively running
  useEffect(() => {
    if (!selectedMissionId || missionDetail?.status !== "active") return;
    const hasRunningOrPlanned = planData.tasks?.some((t: any) => t.status === "running" || t.status === "planned");
    if (!hasRunningOrPlanned) return;
    const timer = setInterval(() => {
      loadMissionAll(selectedMissionId);
    }, 3000);
    return () => clearInterval(timer);
  }, [selectedMissionId, missionDetail?.status, planData.tasks, loadMissionAll]);

  const handleDispatchChat = async (customPrompt?: string) => {
    const text = (customPrompt ?? chatInput).trim();
    if (!text || !workspaceId) return;
    setSending(true);
    setErrorMsg("");
    try {
      const created = await apiFetch("/api/missions/dispatch", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspaceId,
          request: text,
          is_demo: !liveMode,
          fast_mode: !liveMode,
        }),
      });
      setChatInput("");
      setInfoMsg("Đã giao nhiệm vụ! Xem luồng triệu tập Subagent ở cột bên phải và cuộc hội thoại ở giữa.");
      await loadWorkspaceData(workspaceId);
      setSelectedMissionId(created.id);
      await loadMissionAll(created.id);
      setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: "smooth" }), 150);
    } catch (e: any) {
      setErrorMsg(e.message);
    } finally {
      setSending(false);
    }
  };

  const handleWorkerStep = async () => {
    if (!selectedMissionId) return;
    setSending(true);
    setErrorMsg("");
    try {
      const res = await apiFetch(`/api/worker/step?mission_id=${selectedMissionId}`, { method: "POST" });
      setInfoMsg(`Đội Agent vừa thực hiện xong thêm ${res.tasks_executed} bước công việc.`);
      await loadWorkspaceData(workspaceId);
      await loadMissionAll(selectedMissionId);
    } catch (e: any) {
      setErrorMsg(e.message);
    } finally {
      setSending(false);
    }
  };

  const handleActionDecision = async (actionId: string, payloadHash: string, decision: "approved" | "rejected") => {
    setErrorMsg("");
    try {
      await apiFetch(`/api/actions/${actionId}/decide`, {
        method: "POST",
        body: JSON.stringify({
          decision,
          payload_hash: payloadHash,
          comment: decision === "approved" ? "Người điều hành phê duyệt trực tiếp" : "Người điều hành từ chối",
        }),
      });
      if (decision === "approved") {
        await apiFetch(`/api/worker/step?mission_id=${selectedMissionId}`, { method: "POST" });
      }
      setInfoMsg(
        decision === "approved"
          ? "Đã phê duyệt lệnh! Các Subagent tiếp theo đã chạy hoàn tất."
          : "Đã từ chối lệnh thực thi."
      );
      await loadWorkspaceData(workspaceId);
      await loadMissionAll(selectedMissionId);
    } catch (e: any) {
      setErrorMsg(e.message);
    }
  };

  const handleLifecycle = async (op: "activate" | "pause" | "resume" | "cancel") => {
    if (!selectedMissionId) return;
    setErrorMsg("");
    try {
      await apiFetch(`/api/missions/${selectedMissionId}/${op}`, { method: "POST" });
      await loadWorkspaceData(workspaceId);
      await loadMissionAll(selectedMissionId);
    } catch (e: any) {
      setErrorMsg(e.message);
    }
  };

  // Group DAG tasks into topological stages (parallel tasks share the same stage level, like the user's diagram!)
  const dagStages: DagStage[] = useMemo(() => {
    const tasks: any[] = planData.tasks || [];
    const deps: any[] = planData.dependencies || [];
    if (!tasks.length) return [];

    const depthMap: Record<string, number> = {};
    const taskById: Record<string, any> = Object.fromEntries(tasks.map((t) => [t.id, t]));

    const computeDepth = (tid: string, visited = new Set<string>()): number => {
      if (tid in depthMap) return depthMap[tid];
      if (visited.has(tid)) return 0;
      visited.add(tid);
      const parentIds = deps.filter((d) => d.task_id === tid).map((d) => d.depends_on_id);
      if (!parentIds.length) {
        depthMap[tid] = 0;
        return 0;
      }
      const d = 1 + Math.max(...parentIds.map((pid) => (taskById[pid] ? computeDepth(pid, visited) : 0)));
      depthMap[tid] = d;
      return d;
    };

    tasks.forEach((t) => computeDepth(t.id));
    const maxDepth = Math.max(0, ...Object.values(depthMap));
    const stages: DagStage[] = [];
    for (let lvl = 0; lvl <= maxDepth; lvl++) {
      const stageTasks = tasks.filter((t) => (depthMap[t.id] ?? 0) === lvl);
      if (stageTasks.length) {
        stages.push({
          stageIndex: lvl + 1,
          label:
            stageTasks.length > 1
              ? `Chặng ${lvl + 1} — Phân nhánh ${stageTasks.length} Subagent chạy song song`
              : `Chặng ${lvl + 1} — Chuyển tiếp tuần tự`,
          tasks: stageTasks,
        });
      }
    }
    return stages;
  }, [planData.tasks, planData.dependencies]);

  // Identify which step is currently active or waiting so we can highlight it at the top of the tracker
  const currentFocusTask = useMemo(() => {
    const tasks: any[] = planData.tasks || [];
    return (
      tasks.find((t) => t.status === "running") ||
      tasks.find((t) => t.status === "waiting_approval") ||
      tasks.find((t) => t.status === "planned") ||
      tasks[tasks.length - 1] ||
      null
    );
  }, [planData.tasks]);

  // Build conversation stream
  const chatStream: ChatMessage[] = useMemo(() => {
    if (!missionDetail) return [];
    const msgs: ChatMessage[] = [];
    const contract = missionDetail.contract || {};
    const taskById: Record<string, any> = Object.fromEntries((planData.tasks || []).map((t: any) => [t.id, t]));

    msgs.push({
      id: `user-${missionDetail.id}`,
      agent: AGENT_ROSTER.user,
      toHandles: ["@Compiler", "@Planner"],
      title: "Mục tiêu khởi phát (Intent)",
      body: missionDetail.raw_request,
      tag: contract.domain_label || TASK_TYPE_VN[missionDetail.task_type] || missionDetail.task_type,
      isUser: true,
    });

    const budgetStr = contract.budget?.amount_minor ? vnd(contract.budget.amount_minor) : "Không yêu cầu ngân sách";
    const targetStr = contract.target?.amount_minor
      ? vnd(contract.target.amount_minor)
      : `${contract.success_metrics?.length || 1} tiêu chí chất lượng đầu ra`;
    msgs.push({
      id: `compiler-${missionDetail.id}`,
      agent: AGENT_ROSTER.compiler,
      toHandles: ["@Planner"],
      title: "Chuẩn hóa Hợp đồng & Ràng buộc An toàn",
      body:
        `• Lĩnh vực: ${contract.domain_label || TASK_TYPE_VN[missionDetail.task_type] || missionDetail.task_type}\n` +
        `• Ngân sách: ${budgetStr}  |  Chỉ tiêu nghiệm thu: ${targetStr}\n` +
        (contract.unresolved_questions?.length ? `• Điểm cần lưu ý: ${contract.unresolved_questions[0]}\n` : "") +
        `➔ Bàn giao cho @Planner (Start Agent) triệu tập các Subagent.`,
      tag: `Contract v${missionDetail.current_version}`,
    });

    if (planData.plan) {
      const taskLines = (planData.tasks || []).map((t: any, idx: number) => {
        const capAgent = AGENT_ROSTER[t.capability] || AGENT_ROSTER.planner;
        return `${idx + 1}. ${capAgent.avatar} ${capAgent.name} (${capAgent.handle}) — ${t.title}`;
      });
      const summonedHandles = Array.from(
        new Set<string>(
          (planData.tasks || []).map((t: any) => (AGENT_ROSTER[t.capability] || AGENT_ROSTER.planner).handle)
        )
      );
      msgs.push({
        id: `plan-${planData.plan.id}`,
        agent: AGENT_ROSTER.planner,
        toHandles: summonedHandles,
        title: `Triệu tập ${planData.tasks?.length || 0} Subagents & Phân luồng công việc`,
        body:
          `Tôi đã chọn phương án "${planData.plan.chosen_option}" và kích hoạt luồng phối hợp:\n` +
          taskLines.join("\n"),
        tag: `${planData.tasks?.length || 0} Subagents`,
      });
    }

    const artsByTask: Record<string, any[]> = {};
    for (const a of artifacts) {
      const k = a.task_id || "none";
      artsByTask[k] = artsByTask[k] || [];
      artsByTask[k].push(a);
    }
    const evsByTask: Record<string, any[]> = {};
    for (const e of evidence) {
      const k = e.task_id || "none";
      evsByTask[k] = evsByTask[k] || [];
      evsByTask[k].push(e);
    }

    let evalIdx = 0;

    for (const r of runs) {
      const task = taskById[r.task_id];
      const sp = AGENT_ROSTER[r.capability] || AGENT_ROSTER.planner;
      const taskArts = artsByTask[r.task_id] || [];
      const taskEvs = evsByTask[r.task_id] || [];

      const downstreamHandles = (planData.dependencies || [])
        .filter((d: any) => d.depends_on_id === r.task_id)
        .map((d: any) => {
          const dt = taskById[d.task_id];
          return dt ? (AGENT_ROSTER[dt.capability] || AGENT_ROSTER.planner).handle : "@Planner";
        });
      const toHandles = downstreamHandles.length ? Array.from(new Set<string>(downstreamHandles)) : ["@Bạn"];

      let title = task?.title || sp.role;
      let body = "";
      let attachmentTitle: string | undefined;
      let attachmentContent: string | undefined;
      let downloadUrl: string | undefined;

      if (r.capability === "research") {
        const verifiedCount = taskEvs.filter((e) => e.kind === "verified_fact").length;
        const flaggedCount = taskEvs.filter((e) => e.untrusted_flags?.length > 0).length;
        body =
          `Đã thu thập và kiểm tra ${taskEvs.length} nguồn dữ liệu (${verifiedCount} thông tin xác thực` +
          (flaggedCount > 0 ? `, đã chặn ${flaggedCount} nguồn chứa mã độc Prompt Injection` : "") +
          `).\n` +
          (taskEvs.length > 0 ? `• Tóm tắt: "${taskEvs[0].claim.slice(0, 180)}..."\n` : "") +
          `➔ Chuyển kết quả khảo sát cho ${toHandles.join(", ")}.`;
      } else if (r.capability === "content") {
        body =
          r.attempt > 1
            ? `Đã tiếp thu yêu cầu của @Auditor, loại bỏ hoàn toàn các thông số chưa xác minh và hoàn thiện bản thảo mới (Lần #${r.attempt}).\n➔ Gửi lại @Auditor kiểm duyệt.`
            : `Đã biên soạn xong bản thảo dựa trên dữ liệu của @Researcher.\n➔ Chuyển sang @Auditor kiểm duyệt độc lập.`;
      } else if (r.capability === "review") {
        const evObj = evaluations[evalIdx] || evaluations[evaluations.length - 1];
        evalIdx += 1;
        if (evObj && evObj.verdict !== "accepted") {
          toHandles.splice(0, toHandles.length, "@Writer");
          title = "⚠️ Yêu cầu @Writer chỉnh sửa lại bản thảo";
          body =
            `Qua kiểm duyệt độc lập, tôi phát hiện điểm chưa đạt chuẩn:\n` +
            `• ${(evObj.findings || []).join("\n• ")}\n` +
            `➔ Yêu cầu @Writer sửa lại trước khi cho phép chuyển tiếp!`;
        } else {
          title = "✅ Đã duyệt chất lượng & tính tuân thủ";
          body =
            `Bản thảo đã đạt toàn bộ tiêu chí kiểm tra độc lập (không chứa thông số bịa đặt hay từ ngữ vi phạm).\n` +
            `➔ Cho phép chuyển sang ${toHandles.join(", ")}.`;
        }
      } else if (r.capability === "software_engineering") {
        body =
          `Đã viết xong bản vá mã nguồn (Patch) và chạy kiểm thử tự động trong môi trường Sandbox cô lập (Unit Test: PASSED 100%).\n` +
          `➔ Bàn giao bản vá cho ${toHandles.join(", ")}.`;
      } else if (r.capability === "media") {
        body = `Đã thiết kế xong bố cục trực quan (SVG Wireframe).\n➔ Chuyển giao cho ${toHandles.join(", ")}.`;
      } else if (r.capability === "sales_assistance") {
        body =
          `Đã xây dựng xong Playbook Tư vấn & Quy trình xử lý tình huống khách hàng.\n` +
          `➔ Chuyển giao cho ${toHandles.join(", ")}.`;
      } else if (r.capability === "analytics") {
        const mode = task?.input?.mode || "baseline";
        body =
          mode === "baseline"
            ? `Đã đo dữ liệu nền (Baseline) và kiểm định xu hướng song song (Parallel Trends).\n• ${taskEvs.map((e) => e.claim).join("\n• ")}`
            : `Đã phân tích đối chứng Difference-in-Differences (DiD) và hiệu quả chuyển đổi:\n• ${taskEvs.map((e) => e.claim).join("\n• ")}`;
      } else if (r.capability === "publishing") {
        body =
          task?.status === "waiting_approval"
            ? `Lệnh xuất bản ra bên ngoài đã sẵn sàng. Cần @Bạn nhấn nút Phê duyệt ở thẻ bên dưới trước khi thực thi.`
            : `Đã xác nhận phê duyệt và thực thi xuất bản thành công kèm biên nhận (Receipt).`;
      } else if (r.capability === "report") {
        body = `Đã tổng hợp toàn bộ kết quả đã xác minh, các ước tính thống kê và trạng thái ngân sách thành Báo cáo Nghiệm thu hoàn chỉnh.`;
      }

      if (taskArts.length > 0) {
        const latestArt = taskArts[taskArts.length - 1];
        const latestVer = latestArt.versions?.[latestArt.versions.length - 1];
        if (latestVer?.content_preview) {
          attachmentTitle = latestArt.title;
          attachmentContent = latestVer.content_preview;
          downloadUrl = latestVer.download_url;
        }
      }

      msgs.push({
        id: `run-${r.id}`,
        agent: sp,
        toHandles,
        title,
        body,
        attachmentTitle,
        attachmentContent,
        downloadUrl,
        tag: r.usage?.total_tokens ? `${r.usage.total_tokens} tokens` : undefined,
      });
    }

    for (const act of actions) {
      if (act.status === "awaiting_approval") {
        msgs.push({
          id: `action-${act.id}`,
          agent: AGENT_ROSTER.publishing,
          toHandles: ["@Bạn"],
          title: `⏸️ Chờ @Bạn phê duyệt lệnh: ${act.action_type}`,
          body: `Mọi hành động tác động ra ngoài hệ thống đều phải được bạn phê duyệt. Kiểm tra nội dung bên dưới và nhấn nút Phê duyệt để hoàn tất nhiệm vụ:`,
          actionCard: act,
        });
      }
    }

    for (const dec of planData.decisions || []) {
      if (dec.kind === "closed_loop_optimization") {
        msgs.push({
          id: `dec-${dec.id}`,
          agent: AGENT_ROSTER.planner,
          toHandles: ["@Bạn"],
          title: "🔄 Đề xuất Tối ưu Chiến lược Tiếp theo (Closed-Loop Optimization)",
          body: dec.summary,
          tag: "Tự động tối ưu từ dữ liệu",
        });
      }
    }

    return msgs;
  }, [missionDetail, planData, runs, artifacts, evidence, evaluations, actions]);

  const completedTasksCount = (planData.tasks || []).filter((t: any) => t.status === "completed").length;
  const totalTasksCount = (planData.tasks || []).length;
  const progressPct = totalTasksCount > 0 ? Math.round((completedTasksCount / totalTasksCount) * 100) : 0;

  return (
    <div style={{ minHeight: "100vh", background: "#f8fafc", color: "#0f172a", display: "flex", flexDirection: "column" }}>
      {/* Clean Top Bar */}
      <header
        style={{
          background: "#ffffff",
          borderBottom: "1px solid #e2e8f0",
          padding: "12px 24px",
          position: "sticky",
          top: 0,
          zIndex: 40,
        }}
      >
        <div
          style={{
            maxWidth: 1620,
            margin: "0 auto",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 16,
            flexWrap: "wrap",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: 10,
                background: "#2563eb",
                color: "#ffffff",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontWeight: 700,
                fontSize: 15,
              }}
            >
              AT
            </div>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 16, fontWeight: 700, color: "#0f172a" }}>Multi-Agent-System (MAS)</span>
                <span
                  style={{
                    background: "#f1f5f9",
                    color: "#334155",
                    fontSize: 11,
                    fontWeight: 600,
                    padding: "2px 8px",
                    borderRadius: 6,
                  }}
                >
                  Không gian Điều phối Cộng đồng AI Đa Tác Nhân
                </span>
              </div>
              <div style={{ fontSize: 11.5, color: "#64748b", marginTop: 1 }}>
                Mô hình AI: <strong style={{ color: "#334155" }}>{health?.llm || "ollama:gemma4:12b"}</strong>
              </div>
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <select
              value={token}
              onChange={(e) => setToken(e.target.value)}
              style={{
                background: "#f8fafc",
                color: "#334155",
                border: "1px solid #cbd5e1",
                padding: "7px 12px",
                borderRadius: 8,
                fontSize: 12,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              {DEMO_ACCOUNTS.map((a) => (
                <option key={a.token} value={a.token}>
                  {a.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </header>

      {/* Notification Banners */}
      <div style={{ maxWidth: 1620, width: "100%", margin: "0 auto", padding: "0 24px" }}>
        {errorMsg && (
          <div
            style={{
              marginTop: 12,
              background: "#fef2f2",
              color: "#991b1b",
              border: "1px solid #fecaca",
              padding: "10px 16px",
              borderRadius: 10,
              fontSize: 12.5,
              fontWeight: 500,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <span><strong>Thông báo lỗi:</strong> {errorMsg}</span>
            <button onClick={() => setErrorMsg("")} style={{ border: "none", background: "none", cursor: "pointer", fontWeight: 700, color: "#991b1b" }}>✕</button>
          </div>
        )}
        {infoMsg && (
          <div
            style={{
              marginTop: 12,
              background: "#ecfdf5",
              color: "#065f46",
              border: "1px solid #a7f3d0",
              padding: "10px 16px",
              borderRadius: 10,
              fontSize: 12.5,
              fontWeight: 500,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <span>{infoMsg}</span>
            <button onClick={() => setInfoMsg("")} style={{ border: "none", background: "none", cursor: "pointer", fontWeight: 700, color: "#065f46" }}>✕</button>
          </div>
        )}
      </div>

      {/* 3-Column Harmonious Workspace: Left Rooms (275px) | Center Chat (1fr) | Right Live Agent Flow Tracker (370px) */}
      <div
        className="atlas-workspace-grid"
        style={{
          maxWidth: 1620,
          width: "100%",
          margin: "0 auto",
          padding: "16px 24px 26px 24px",
          flex: 1,
        }}
      >
        {/* LEFT COLUMN: Mission Rooms & Agent Directory */}
        <aside
          style={{
            background: "#ffffff",
            border: "1px solid #e2e8f0",
            borderRadius: 14,
            overflow: "hidden",
            boxShadow: "0 1px 3px rgba(15, 23, 42, 0.03)",
          }}
        >
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", borderBottom: "1px solid #e2e8f0", background: "#f8fafc" }}>
            <button
              onClick={() => setSidebarTab("missions")}
              style={{
                padding: "12px 8px",
                border: "none",
                borderBottom: sidebarTab === "missions" ? "2px solid #2563eb" : "2px solid transparent",
                background: sidebarTab === "missions" ? "#ffffff" : "transparent",
                color: sidebarTab === "missions" ? "#1d4ed8" : "#64748b",
                fontSize: 12,
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              Nhiệm vụ ({missions.length})
            </button>
            <button
              onClick={() => setSidebarTab("agents")}
              style={{
                padding: "12px 8px",
                border: "none",
                borderBottom: sidebarTab === "agents" ? "2px solid #2563eb" : "2px solid transparent",
                background: sidebarTab === "agents" ? "#ffffff" : "transparent",
                color: sidebarTab === "agents" ? "#1d4ed8" : "#64748b",
                fontSize: 12,
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              Đội ngũ AI (11)
            </button>
          </div>

          {sidebarTab === "missions" ? (
            <div style={{ padding: 12, display: "flex", flexDirection: "column", gap: 8, maxHeight: "calc(100vh - 170px)", overflowY: "auto" }}>
              {missions.map((m) => {
                const active = m.id === selectedMissionId;
                const domainText = TASK_TYPE_VN[m.task_type] || m.task_type;
                return (
                  <div
                    key={m.id}
                    onClick={() => setSelectedMissionId(m.id)}
                    style={{
                      padding: "11px 12px",
                      borderRadius: 10,
                      cursor: "pointer",
                      background: active ? "#eff6ff" : "#ffffff",
                      border: active ? "1.5px solid #2563eb" : "1px solid #e2e8f0",
                      transition: "all 0.12s ease",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 6, marginBottom: 5 }}>
                      <span style={{ fontSize: 11, fontWeight: 700, color: active ? "#1d4ed8" : "#64748b" }}>
                        {domainText}
                      </span>
                      <StatusBadge status={m.status} />
                    </div>
                    <div style={{ fontSize: 12.5, fontWeight: 600, color: "#0f172a", lineHeight: 1.45 }}>
                      {m.title.slice(0, 82)}{m.title.length > 82 ? "..." : ""}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div style={{ padding: 12, display: "flex", flexDirection: "column", gap: 8, maxHeight: "calc(100vh - 170px)", overflowY: "auto" }}>
              {Object.values(AGENT_ROSTER)
                .filter((a) => a.id !== "user")
                .map((ag) => (
                  <div
                    key={ag.id}
                    style={{
                      display: "flex",
                      alignItems: "flex-start",
                      gap: 10,
                      padding: "9px 10px",
                      borderRadius: 10,
                      background: "#f8fafc",
                      border: "1px solid #e2e8f0",
                    }}
                  >
                    <div
                      style={{
                        width: 34,
                        height: 34,
                        borderRadius: 9,
                        background: ag.softBg,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: 17,
                        flexShrink: 0,
                      }}
                    >
                      {ag.avatar}
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <span style={{ fontSize: 12.5, fontWeight: 700, color: "#0f172a" }}>{ag.name}</span>
                        <code style={{ fontSize: 10.5, color: ag.accent, fontWeight: 600 }}>{ag.handle}</code>
                      </div>
                      <div style={{ fontSize: 11, color: "#475569", marginTop: 2, lineHeight: 1.4 }}>
                        {ag.summonReason}
                      </div>
                    </div>
                  </div>
                ))}
            </div>
          )}
        </aside>

        {/* CENTER COLUMN: Community Chat Stream */}
        <main
          style={{
            background: "#ffffff",
            border: "1px solid #e2e8f0",
            borderRadius: 14,
            boxShadow: "0 1px 3px rgba(15, 23, 42, 0.03)",
            display: "flex",
            flexDirection: "column",
            minHeight: "calc(100vh - 125px)",
            overflow: "hidden",
          }}
        >
          {missionDetail && (
            <div style={{ borderBottom: "1px solid #e2e8f0", padding: "15px 22px", background: "#ffffff" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: 260 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
                    <StatusBadge status={missionDetail.status} />
                    <span
                      style={{
                        fontSize: 11,
                        fontWeight: 600,
                        color: "#475569",
                        background: "#f1f5f9",
                        padding: "2px 9px",
                        borderRadius: 9999,
                      }}
                    >
                      {missionDetail.contract?.domain_label || TASK_TYPE_VN[missionDetail.task_type] || missionDetail.task_type}
                    </span>
                  </div>
                  <h1 style={{ fontSize: 15.5, fontWeight: 700, color: "#0f172a", margin: 0, lineHeight: 1.45 }}>
                    {missionDetail.raw_request}
                  </h1>
                </div>

                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  {missionDetail.status === "active" && (
                    <>
                      <button
                        onClick={handleWorkerStep}
                        disabled={sending}
                        style={{
                          background: "#2563eb",
                          color: "#ffffff",
                          border: "none",
                          padding: "8px 14px",
                          borderRadius: 8,
                          fontSize: 12,
                          fontWeight: 600,
                          cursor: "pointer",
                        }}
                      >
                        {sending ? "Đang xử lý..." : "▶ Chạy bước tiếp theo"}
                      </button>
                      <button
                        onClick={() => handleLifecycle("pause")}
                        style={{
                          background: "#ffffff",
                          color: "#b45309",
                          border: "1px solid #fcd34d",
                          padding: "8px 12px",
                          borderRadius: 8,
                          fontSize: 12,
                          fontWeight: 600,
                          cursor: "pointer",
                        }}
                      >
                        Tạm dừng
                      </button>
                    </>
                  )}
                  {missionDetail.status === "paused" && (
                    <button
                      onClick={() => handleLifecycle("resume")}
                      style={{
                        background: "#2563eb",
                        color: "#ffffff",
                        border: "none",
                        padding: "8px 14px",
                        borderRadius: 8,
                        fontSize: 12,
                        fontWeight: 600,
                        cursor: "pointer",
                      }}
                    >
                      Tiếp tục chạy
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Conversation Feed */}
          <div
            style={{
              flex: 1,
              padding: "20px 24px",
              overflowY: "auto",
              display: "flex",
              flexDirection: "column",
              gap: 16,
              background: "#f8fafc",
            }}
          >
            {chatStream.map((msg) => (
              <div
                key={msg.id}
                style={{
                  display: "flex",
                  gap: 13,
                  alignItems: "flex-start",
                }}
              >
                <div
                  style={{
                    width: 38,
                    height: 38,
                    borderRadius: 10,
                    background: msg.agent.softBg,
                    border: "1px solid #e2e8f0",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 18,
                    flexShrink: 0,
                    marginTop: 2,
                  }}
                >
                  {msg.agent.avatar}
                </div>

                <div
                  style={{
                    flex: 1,
                    background: "#ffffff",
                    border: msg.isUser ? "1.5px solid #93c5fd" : "1px solid #e2e8f0",
                    borderRadius: 12,
                    padding: "14px 18px",
                    boxShadow: "0 1px 2px rgba(15, 23, 42, 0.02)",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      gap: 8,
                      flexWrap: "wrap",
                      marginBottom: 6,
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      <span style={{ fontSize: 13, fontWeight: 700, color: "#0f172a" }}>{msg.agent.name}</span>
                      <span
                        style={{
                          fontSize: 11,
                          fontWeight: 600,
                          color: msg.agent.accent,
                          background: msg.agent.softBg,
                          padding: "1px 7px",
                          borderRadius: 6,
                        }}
                      >
                        {msg.agent.handle}
                      </span>
                      <span style={{ fontSize: 11.5, color: "#94a3b8" }}>➔</span>
                      {msg.toHandles.map((h) => (
                        <span
                          key={h}
                          style={{
                            fontSize: 11,
                            fontWeight: 600,
                            color: "#334155",
                            background: "#f1f5f9",
                            padding: "1px 7px",
                            borderRadius: 6,
                          }}
                        >
                          {h}
                        </span>
                      ))}
                    </div>

                    {msg.tag && (
                      <span
                        style={{
                          fontSize: 11,
                          fontWeight: 600,
                          color: "#64748b",
                          background: "#f8fafc",
                          border: "1px solid #e2e8f0",
                          padding: "2px 8px",
                          borderRadius: 6,
                        }}
                      >
                        {msg.tag}
                      </span>
                    )}
                  </div>

                  <div style={{ fontSize: 14, fontWeight: 700, color: "#0f172a", marginBottom: 5 }}>
                    {msg.title}
                  </div>

                  <div
                    style={{
                      fontSize: 13.5,
                      color: "#334155",
                      lineHeight: 1.65,
                      whiteSpace: "pre-line",
                    }}
                  >
                    {msg.body}
                  </div>

                  {msg.attachmentContent && (
                    <ArtifactAttachment
                      title={msg.attachmentTitle || "Tài liệu đầu ra"}
                      content={msg.attachmentContent}
                      downloadUrl={msg.downloadUrl}
                    />
                  )}

                  {msg.actionCard && (
                    <div
                      style={{
                        marginTop: 12,
                        background: "#fffbeb",
                        border: "1px solid #fcd34d",
                        borderRadius: 10,
                        padding: 14,
                      }}
                    >
                      <div style={{ fontSize: 12, fontWeight: 600, color: "#92400e", marginBottom: 6 }}>
                        Kênh thực thi: <code>{msg.actionCard.connector}</code> • Mã kiểm tra toàn vẹn (SHA-256):{" "}
                        <code>{msg.actionCard.payload_hash?.slice(0, 14)}...</code>
                      </div>
                      <pre
                        style={{
                          background: "#ffffff",
                          border: "1px solid #fde68a",
                          padding: 10,
                          borderRadius: 8,
                          fontSize: 12,
                          whiteSpace: "pre-wrap",
                          color: "#334155",
                        }}
                      >
                        {JSON.stringify(msg.actionCard.payload, null, 2)}
                      </pre>
                      <div style={{ display: "flex", gap: 10, marginTop: 12 }}>
                        <button
                          onClick={() =>
                            handleActionDecision(msg.actionCard.id, msg.actionCard.payload_hash, "approved")
                          }
                          style={{
                            background: "#059669",
                            color: "#ffffff",
                            border: "none",
                            padding: "8px 16px",
                            borderRadius: 8,
                            fontSize: 12.5,
                            fontWeight: 600,
                            cursor: "pointer",
                          }}
                        >
                          ✓ Phê duyệt & Cho phép tiếp tục
                        </button>
                        <button
                          onClick={() =>
                            handleActionDecision(msg.actionCard.id, msg.actionCard.payload_hash, "rejected")
                          }
                          style={{
                            background: "#ffffff",
                            color: "#b91c1c",
                            border: "1px solid #fecaca",
                            padding: "8px 16px",
                            borderRadius: 8,
                            fontSize: 12.5,
                            fontWeight: 600,
                            cursor: "pointer",
                          }}
                        >
                          ✕ Từ chối
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ))}
            <div ref={chatEndRef} />
          </div>

          {/* Bottom Chat Composer */}
          <div style={{ borderTop: "1px solid #e2e8f0", padding: "14px 20px", background: "#ffffff" }}>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10, alignItems: "center" }}>
              <span style={{ fontSize: 11.5, fontWeight: 600, color: "#64748b", marginRight: 4 }}>
                Mẫu công việc nhanh:
              </span>
              {MISSION_PRESETS.map((p, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => setChatInput(p.prompt)}
                  style={{
                    background: "#f8fafc",
                    color: "#334155",
                    border: "1px solid #e2e8f0",
                    padding: "4px 10px",
                    borderRadius: 9999,
                    fontSize: 11.5,
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  {p.category}
                </button>
              ))}
            </div>

            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <textarea
                rows={2}
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleDispatchChat();
                  }
                }}
                placeholder="Nhập công việc bất kỳ bạn muốn giao cho Đội AI (Nhấn Enter để gửi)..."
                style={{
                  flex: 1,
                  background: "#f8fafc",
                  color: "#0f172a",
                  border: "1px solid #cbd5e1",
                  borderRadius: 10,
                  padding: "10px 14px",
                  fontSize: 13.5,
                  lineHeight: 1.45,
                  resize: "none",
                }}
              />
              <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end" }}>
                <label
                  style={{
                    fontSize: 11.5,
                    color: "#475569",
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    cursor: "pointer",
                    fontWeight: 600,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={liveMode}
                    onChange={(e) => setLiveMode(e.target.checked)}
                  />
                  Dùng LLM thực (Ollama)
                </label>
                <button
                  onClick={() => handleDispatchChat()}
                  disabled={sending || !chatInput.trim()}
                  style={{
                    background: sending || !chatInput.trim() ? "#94a3b8" : "#2563eb",
                    color: "#ffffff",
                    border: "none",
                    padding: "10px 18px",
                    borderRadius: 10,
                    fontSize: 13,
                    fontWeight: 700,
                    cursor: sending || !chatInput.trim() ? "not-allowed" : "pointer",
                    whiteSpace: "nowrap",
                  }}
                >
                  {sending ? "Đang gửi..." : "Giao việc cho Đội AI ➤"}
                </button>
              </div>
            </div>
          </div>
        </main>

        {/* RIGHT COLUMN: LIVE AGENT FLOW & SUBAGENT CALL TRACKER (Inspired by the Intent -> Start_Agent -> Subagents diagram!) */}
        <aside
          style={{
            background: "#ffffff",
            border: "1px solid #e2e8f0",
            borderRadius: 14,
            overflow: "hidden",
            boxShadow: "0 1px 3px rgba(15, 23, 42, 0.03)",
            position: "sticky",
            top: 76,
          }}
        >
          {/* Right Panel Tabs */}
          <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", borderBottom: "1px solid #e2e8f0", background: "#f8fafc" }}>
            <button
              onClick={() => setRightPanelTab("flow")}
              style={{
                padding: "12px 10px",
                border: "none",
                borderBottom: rightPanelTab === "flow" ? "2px solid #2563eb" : "2px solid transparent",
                background: rightPanelTab === "flow" ? "#ffffff" : "transparent",
                color: rightPanelTab === "flow" ? "#1d4ed8" : "#64748b",
                fontSize: 12,
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              ⚡ Tiến trình & Gọi AI ({completedTasksCount}/{totalTasksCount})
            </button>
            <button
              onClick={() => setRightPanelTab("files")}
              style={{
                padding: "12px 10px",
                border: "none",
                borderBottom: rightPanelTab === "files" ? "2px solid #2563eb" : "2px solid transparent",
                background: rightPanelTab === "files" ? "#ffffff" : "transparent",
                color: rightPanelTab === "files" ? "#1d4ed8" : "#64748b",
                fontSize: 12,
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              📂 Hồ sơ & Số liệu ({artifacts.length})
            </button>
          </div>

          {rightPanelTab === "flow" ? (
            <div
              style={{
                padding: 16,
                maxHeight: "calc(100vh - 140px)",
                overflowY: "auto",
                display: "flex",
                flexDirection: "column",
                gap: 14,
              }}
            >
              {/* Overall Progress Bar + Active Callout */}
              <div
                style={{
                  background: "#f8fafc",
                  border: "1px solid #e2e8f0",
                  borderRadius: 12,
                  padding: 14,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: "#0f172a" }}>Tiến độ tổng thể nhiệm vụ</span>
                  <span style={{ fontSize: 12, fontWeight: 700, color: "#2563eb" }}>
                    {completedTasksCount}/{totalTasksCount} bước ({progressPct}%)
                  </span>
                </div>
                <div style={{ width: "100%", height: 8, background: "#e2e8f0", borderRadius: 9999, overflow: "hidden" }}>
                  <div
                    style={{
                      width: `${progressPct}%`,
                      height: "100%",
                      background: progressPct === 100 ? "#10b981" : "#2563eb",
                      transition: "width 0.3s ease",
                    }}
                  />
                </div>

                {currentFocusTask && (
                  <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid #e2e8f0", fontSize: 12 }}>
                    <div style={{ color: "#64748b", fontWeight: 600, fontSize: 11 }}>TRẠNG THÁI HIỆN TẠI:</div>
                    {(() => {
                      const ag = AGENT_ROSTER[currentFocusTask.capability] || AGENT_ROSTER.planner;
                      if (missionDetail?.status === "completed") {
                        return (
                          <div style={{ color: "#047857", fontWeight: 700, marginTop: 2 }}>
                            ✓ Toàn bộ các Subagent đã hoàn thành và bàn giao báo cáo!
                          </div>
                        );
                      }
                      if (currentFocusTask.status === "waiting_approval") {
                        return (
                          <div style={{ color: "#b45309", fontWeight: 700, marginTop: 2 }}>
                            ⏸ Đang dừng tại {ag.avatar} {ag.name} ({ag.handle}) — Chờ bạn nhấn Phê duyệt trong khung chat.
                          </div>
                        );
                      }
                      return (
                        <div style={{ color: "#1d4ed8", fontWeight: 700, marginTop: 2 }}>
                          ▶ Đang gọi {ag.avatar} {ag.name} ({ag.handle}): {currentFocusTask.title}
                        </div>
                      );
                    })()}
                  </div>
                )}
              </div>

              {/* Visual Flow Graph: Intent -> Start Agent (@Planner) -> Branched Subagents */}
              <div>
                <div style={{ fontSize: 11.5, fontWeight: 700, color: "#64748b", marginBottom: 10, letterSpacing: "0.02em" }}>
                  SƠ ĐỒ TRIỆU TẬP & PHỐI HỢP AI (CLICK ĐỂ XEM CHI TIẾT)
                </div>

                {/* ROOT NODE 1: INTENT */}
                <div
                  style={{
                    background: "#eff6ff",
                    border: "1.5px solid #93c5fd",
                    borderRadius: 12,
                    padding: "10px 12px",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontSize: 16 }}>👤</span>
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 700, color: "#1e40af" }}>1. Intent (Mục tiêu từ Bạn)</div>
                      <div style={{ fontSize: 11, color: "#3b82f6" }}>Khởi phát yêu cầu tự nhiên</div>
                    </div>
                  </div>
                  <StatusBadge status="completed" />
                </div>

                {/* Connector Line */}
                <div style={{ display: "flex", alignItems: "center", paddingLeft: 22, height: 22 }}>
                  <div style={{ width: 2, height: "100%", background: "#93c5fd" }} />
                  <span style={{ fontSize: 10.5, color: "#64748b", marginLeft: 8 }}>chuẩn hóa & giao việc ↓</span>
                </div>

                {/* ROOT NODE 2: START_AGENT (@Compiler + @Planner) */}
                <div
                  style={{
                    background: "#f5f3ff",
                    border: "1.5px solid #c4b5fd",
                    borderRadius: 12,
                    padding: "11px 12px",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontSize: 16 }}>🧠</span>
                      <div>
                        <div style={{ fontSize: 12.5, fontWeight: 700, color: "#5b21b6" }}>
                          2. Start Agent (@Planner)
                        </div>
                        <div style={{ fontSize: 11, color: "#6d28d9" }}>
                          Tổng Công trình sư • Phương án: {planData.plan?.chosen_option || "default"}
                        </div>
                      </div>
                    </div>
                    <StatusBadge status={planData.plan ? "completed" : "planned"} />
                  </div>
                  <div style={{ fontSize: 11.5, color: "#475569", marginTop: 4, lineHeight: 1.45 }}>
                    Phân tích bài toán, chia thành <strong>{dagStages.length} chặng</strong> và tự động triệu tập{" "}
                    <strong>{totalTasksCount} Subagents</strong> chuyên môn bên dưới:
                  </div>
                </div>

                {/* STAGES OF SUBAGENTS (Branching parallel & sequential nodes) */}
                {dagStages.map((stage) => (
                  <React.Fragment key={stage.stageIndex}>
                    {/* Branch Connector */}
                    <div style={{ display: "flex", alignItems: "center", paddingLeft: 22, height: 26 }}>
                      <div style={{ width: 2, height: "100%", background: "#cbd5e1" }} />
                      <span
                        style={{
                          fontSize: 10.5,
                          fontWeight: 700,
                          color: "#475569",
                          background: "#f1f5f9",
                          padding: "2px 8px",
                          borderRadius: 9999,
                          marginLeft: 8,
                        }}
                      >
                        {stage.label}
                      </span>
                    </div>

                    {/* Container for Subagents in this stage */}
                    <div
                      style={{
                        background: "#f8fafc",
                        border: "1px dashed #cbd5e1",
                        borderRadius: 12,
                        padding: 10,
                        display: "flex",
                        flexDirection: "column",
                        gap: 10,
                      }}
                    >
                      {stage.tasks.map((t: any) => {
                        const ag = AGENT_ROSTER[t.capability] || AGENT_ROSTER.planner;
                        const taskRuns = runs.filter((r) => r.task_id === t.id);
                        const lastRun = taskRuns[taskRuns.length - 1];
                        const isDone = t.status === "completed";
                        const isWaiting = t.status === "waiting_approval";
                        const isRunning = t.status === "running";
                        const isSelected = selectedNodeKey === t.key;

                        const depNames = (planData.dependencies || [])
                          .filter((d: any) => d.task_id === t.id)
                          .map((d: any) => {
                            const parentTask = (planData.tasks || []).find((x: any) => x.id === d.depends_on_id);
                            return parentTask
                              ? (AGENT_ROSTER[parentTask.capability] || AGENT_ROSTER.planner).handle
                              : "";
                          })
                          .filter(Boolean);

                        return (
                          <div
                            key={t.id}
                            onClick={() => setSelectedNodeKey(isSelected ? "" : t.key)}
                            className={isRunning || isWaiting ? "agent-node-active" : ""}
                            style={{
                              background: "#ffffff",
                              border: `1.5px solid ${
                                isDone
                                  ? "#86efac"
                                  : isWaiting
                                  ? "#fcd34d"
                                  : isRunning
                                  ? "#60a5fa"
                                  : "#e2e8f0"
                              }`,
                              borderRadius: 10,
                              padding: "10px 12px",
                              cursor: "pointer",
                              transition: "all 0.15s ease",
                            }}
                          >
                            {/* Subagent Node Header */}
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 6 }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                                <span
                                  style={{
                                    width: 28,
                                    height: 28,
                                    borderRadius: 8,
                                    background: ag.softBg,
                                    display: "flex",
                                    alignItems: "center",
                                    justifyContent: "center",
                                    fontSize: 15,
                                  }}
                                >
                                  {ag.avatar}
                                </span>
                                <div>
                                  <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                                    <span style={{ fontSize: 12.5, fontWeight: 700, color: "#0f172a" }}>
                                      {ag.name}
                                    </span>
                                    <code
                                      style={{
                                        fontSize: 10.5,
                                        fontWeight: 700,
                                        color: ag.accent,
                                        background: ag.softBg,
                                        padding: "1px 5px",
                                        borderRadius: 4,
                                      }}
                                    >
                                      {ag.handle}
                                    </code>
                                  </div>
                                  <div style={{ fontSize: 10.5, color: "#64748b" }}>
                                    Subagent • Mã bước: <code>{t.key}</code>
                                  </div>
                                </div>
                              </div>
                              <StatusBadge status={t.status} />
                            </div>

                            {/* Task Mission & Why this AI was summoned */}
                            <div
                              style={{
                                marginTop: 8,
                                paddingTop: 7,
                                borderTop: "1px solid #f1f5f9",
                                fontSize: 11.5,
                                color: "#334155",
                                lineHeight: 1.45,
                              }}
                            >
                              <div>
                                <strong>Nhiệm vụ giao:</strong> {t.title}
                              </div>
                              <div style={{ color: "#64748b", marginTop: 3 }}>
                                <strong>Lý do gọi {ag.handle}:</strong> {ag.summonReason}
                              </div>
                              {depNames.length > 0 && (
                                <div style={{ color: "#475569", marginTop: 3, fontSize: 11 }}>
                                  🔗 Nhận bàn giao dữ liệu từ: <strong>{depNames.join(", ")}</strong>
                                </div>
                              )}
                            </div>

                            {/* Expanded runtime telemetry when clicked */}
                            {(isSelected || isWaiting || isRunning) && (
                              <div
                                style={{
                                  marginTop: 8,
                                  padding: "7px 9px",
                                  background: "#f8fafc",
                                  borderRadius: 8,
                                  border: "1px solid #e2e8f0",
                                  fontSize: 11,
                                  color: "#475569",
                                }}
                              >
                                <div>• Đầu ra kỳ vọng: {t.expected_output}</div>
                                <div>
                                  • Số lần chạy (Attempts): <strong>{t.attempts}/{t.max_attempts}</strong>
                                  {lastRun ? ` • Provider: ${lastRun.provider}` : ""}
                                </div>
                                {lastRun?.usage?.total_tokens ? (
                                  <div>
                                    • Tiêu thụ: <strong>{lastRun.usage.total_tokens} tokens</strong> ({lastRun.usage.latency_ms} ms)
                                  </div>
                                ) : null}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </React.Fragment>
                ))}
              </div>
            </div>
          ) : (
            /* FILES, EVIDENCE & METRICS TAB */
            <div
              style={{
                padding: 14,
                maxHeight: "calc(100vh - 140px)",
                overflowY: "auto",
                display: "flex",
                flexDirection: "column",
                gap: 12,
              }}
            >
              {kpis?.summary && (
                <div style={{ padding: 12, background: "#ecfdf5", border: "1px solid #a7f3d0", borderRadius: 10, fontSize: 12 }}>
                  <div style={{ fontWeight: 700, color: "#047857", marginBottom: 4 }}>
                    📊 Kiểm định Thống kê (DiD & Parallel Trends)
                  </div>
                  <div>• Doanh thu tăng thêm: <strong>+{vnd(kpis.summary.did_inference.incremental_revenue_minor)}</strong></div>
                  <div>• Parallel Trends p-value: <strong>{kpis.summary.did_inference.parallel_trends_pvalue}</strong></div>
                  <div>• Hiệu quả iROAS: <strong>{kpis.summary.roi.incremental_roas}x</strong></div>
                </div>
              )}

              <div>
                <div style={{ fontSize: 12, fontWeight: 700, color: "#0f172a", marginBottom: 8 }}>
                  Sản phẩm Bàn giao ({artifacts.length})
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {artifacts.map((art) => {
                    const latest = art.versions?.[art.versions.length - 1];
                    return (
                      <div
                        key={art.id}
                        style={{
                          padding: 10,
                          borderRadius: 10,
                          background: "#f8fafc",
                          border: "1px solid #e2e8f0",
                          fontSize: 12,
                        }}
                      >
                        <div style={{ fontWeight: 700, color: "#0f172a" }}>📄 {art.title}</div>
                        <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
                          Loại: <code>{art.kind}</code> • Phiên bản v{art.current_version}
                        </div>
                        {latest?.download_url && (
                          <div style={{ marginTop: 6 }}>
                            <a
                              href={`${API_BASE}${latest.download_url}`}
                              target="_blank"
                              rel="noreferrer"
                              style={{ fontSize: 11.5, fontWeight: 600, color: "#2563eb" }}
                            >
                              Mở / Tải file gốc ↗
                            </a>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              <div>
                <div style={{ fontSize: 12, fontWeight: 700, color: "#0f172a", marginBottom: 8 }}>
                  Kho Bằng chứng ({evidence.length})
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {evidence.map((e) => (
                    <div
                      key={e.id}
                      style={{
                        padding: 10,
                        borderRadius: 10,
                        background: "#f8fafc",
                        border: "1px solid #e2e8f0",
                        fontSize: 11.5,
                      }}
                    >
                      <span style={{ fontWeight: 700, color: e.kind === "verified_fact" ? "#047857" : "#b45309" }}>
                        [{e.kind === "verified_fact" ? "ĐÃ XÁC MINH" : e.kind.toUpperCase()}]
                      </span>{" "}
                      <span style={{ color: "#334155" }}>{e.claim}</span>
                    </div>
                  ))}
                </div>
              </div>

              {budget.accounts?.length > 0 && (
                <div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: "#0f172a", marginBottom: 6 }}>
                    Sổ Ngân sách (Budget Ledger)
                  </div>
                  {budget.accounts.map((a: any) => (
                    <div key={a.account_id} style={{ fontSize: 11.5, padding: "5px 0", borderBottom: "1px solid #f1f5f9" }}>
                      <strong>{a.category}:</strong> Đã quyết toán {vnd(a.settled)} / Hạn mức {vnd(a.limit)}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
