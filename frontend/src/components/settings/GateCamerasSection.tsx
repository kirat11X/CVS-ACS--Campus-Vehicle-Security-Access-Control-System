import {
  Activity,
  AlertCircle,
  Camera,
  CheckCircle2,
  Play,
  Plus,
  RefreshCw,
  Sliders,
  Square,
  Wifi,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { ApiError, api } from "../../api/client";
import { useInvalidate, useStreamSettings } from "../../api/queries";
import type {
  GateStreamConfigItem,
  GateStreamConfigUpdateItem,
  StreamTestResponse,
} from "../../api/types";
import { useSession } from "../../auth/AuthContext";
import { cx } from "../../lib/cx";
import { Button } from "../ui/Button";
import { ErrorNote } from "../ui/Feedback";
import { Field, Input } from "../ui/Form";
import { Section } from "../ui/Layout";
import { useToast } from "../ui/Toast";

export function GateCamerasSection() {
  const { token, user } = useSession();
  const isAdmin = user.role === "ADMIN";
  const notify = useToast();
  const invalidate = useInvalidate();
  const { data: settings } = useStreamSettings(4000);

  const [budget, setBudget] = useState<number>(15);
  const [gates, setGates] = useState<GateStreamConfigItem[]>([]);
  const [testResults, setTestResults] = useState<Record<string, StreamTestResponse | null>>({});
  const [testingGate, setTestingGate] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Add Gate dialog state
  const [showAddGate, setShowAddGate] = useState(false);
  const [newGateId, setNewGateId] = useState("");
  const [newGateName, setNewGateName] = useState("");
  const [newGateIp, setNewGateIp] = useState("192.168.1.103");
  const [newGatePort, setNewGatePort] = useState(8080);

  // Sync server data into local draft state
  useEffect(() => {
    if (settings) {
      setBudget(settings.total_fps_budget);
      setGates(settings.gates);
    }
  }, [settings]);

  const activeCount = useMemo(() => gates.filter((g) => g.enabled).length, [gates]);
  const perGateTargetFps = useMemo(() => {
    if (activeCount <= 0) return budget;
    return Math.max(2.0, Math.round((budget / activeCount) * 10) / 10);
  }, [budget, activeCount]);

  const updateGateDraft = (gateId: string, updates: Partial<GateStreamConfigItem>) => {
    setGates((prev) =>
      prev.map((g) => {
        if (g.gate_id !== gateId) return g;
        const next = { ...g, ...updates };
        const path = next.stream_path.startsWith("/") ? next.stream_path : `/${next.stream_path}`;
        next.stream_url = `${next.protocol.toLowerCase()}://${next.ip_address}:${next.port}${path}`;
        return next;
      })
    );
  };

  const saveSettings = async () => {
    if (!isAdmin) return;
    setSaving(true);
    setError(null);
    try {
      const payloadGates: GateStreamConfigUpdateItem[] = gates.map((g) => ({
        gate_id: g.gate_id,
        gate_name: g.gate_name,
        enabled: g.enabled,
        ip_address: g.ip_address,
        port: g.port,
        protocol: g.protocol,
        stream_path: g.stream_path,
        custom_url: g.custom_url,
      }));

      const res = await api.updateStreamSettings(token, {
        total_fps_budget: budget,
        gates: payloadGates,
      });

      setBudget(res.total_fps_budget);
      setGates(res.gates);
      await invalidate("stream-settings");
      notify("Gate camera stream settings saved.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save stream settings.");
    } finally {
      setSaving(false);
    }
  };

  const handleTestConnection = async (gate: GateStreamConfigItem) => {
    if (!isAdmin) return;
    setTestingGate(gate.gate_id);
    setTestResults((prev) => ({ ...prev, [gate.gate_id]: null }));
    try {
      const res = await api.testGateStream(token, gate.gate_id, {
        ip_address: gate.ip_address,
        port: gate.port,
        protocol: gate.protocol,
        stream_path: gate.stream_path,
        custom_url: gate.custom_url,
      });
      setTestResults((prev) => ({ ...prev, [gate.gate_id]: res }));
      if (res.status === "ok") {
        notify(`Gate ${gate.gate_id}: ${res.message}`);
      }
    } catch (err) {
      const errMsg = err instanceof ApiError ? err.message : "Test request failed.";
      setTestResults((prev) => ({
        ...prev,
        [gate.gate_id]: {
          status: "error",
          gate_id: gate.gate_id,
          tested_url: gate.stream_url,
          latency_ms: null,
          message: errMsg,
        },
      }));
    } finally {
      setTestingGate(null);
    }
  };

  const handleToggleStream = async (gate: GateStreamConfigItem) => {
    if (!isAdmin) return;
    try {
      if (gate.enabled) {
        const res = await api.stopGateStream(token, gate.gate_id);
        setGates(res.gates);
        notify(`Gate ${gate.gate_id} stream stopped.`);
      } else {
        const res = await api.startGateStream(token, gate.gate_id);
        setGates(res.gates);
        notify(`Gate ${gate.gate_id} stream started.`);
      }
      await invalidate("stream-settings");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to toggle stream.");
    }
  };

  const handleAddGate = () => {
    const gid = newGateId.trim().toUpperCase();
    if (!gid) return;
    if (gates.some((g) => g.gate_id === gid)) {
      setError(`Gate with ID '${gid}' already exists in configuration.`);
      return;
    }
    const path = "/video";
    const newItem: GateStreamConfigItem = {
      gate_id: gid,
      gate_name: newGateName.trim() || `Campus Gate ${gid.replace("GATE_", "")}`,
      enabled: false,
      ip_address: newGateIp.trim() || "192.168.1.103",
      port: Number(newGatePort) || 8080,
      protocol: "http",
      stream_path: path,
      custom_url: null,
      stream_url: `http://${newGateIp.trim() || "192.168.1.103"}:${newGatePort || 8080}${path}`,
      is_running: false,
      effective_fps: 0,
      actual_fps: 0,
    };
    setGates((prev) => [...prev, newItem]);
    setShowAddGate(false);
    setNewGateId("");
    setNewGateName("");
    notify(`Gate ${gid} added. Click 'Save camera settings' to commit.`);
  };

  return (
    <Section
      title="Gate Cameras & Stream Settings"
      description="Multi-gate IP/mobile camera capture with dynamic adaptive FPS budget allocation (Android IP Webcam / RTSP)."
    >
      <div className="space-y-6">
        {/* Adaptive FPS Budget Control Card */}
        <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-5 dark:border-slate-800 dark:bg-slate-900/50">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <Sliders className="h-5 w-5 text-sky-600 dark:text-sky-400" />
                <h3 className="font-semibold text-slate-900 dark:text-white">Adaptive FPS Budget</h3>
                <span className="rounded-md bg-sky-100 px-2 py-0.5 text-xs font-semibold text-sky-800 dark:bg-sky-950 dark:text-sky-300">
                  {budget.toFixed(1)} FPS Total
                </span>
              </div>
              <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
                Budget is dynamically divided equally among active gates (minimum 2.0 FPS per gate).
              </p>
            </div>

            {/* Live Formula Badge */}
            <div className="flex items-center gap-2 rounded-lg bg-white px-3 py-2 text-xs shadow-sm ring-1 ring-slate-200 dark:bg-slate-950 dark:ring-slate-800">
              <Activity className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
              <div>
                <span className="font-semibold text-slate-800 dark:text-slate-200">
                  {activeCount} Active Gate{activeCount === 1 ? "" : "s"}
                </span>
                <span className="mx-1.5 text-slate-400">→</span>
                <span className="font-bold text-emerald-600 dark:text-emerald-400">
                  {perGateTargetFps.toFixed(1)} FPS / Gate
                </span>
              </div>
            </div>
          </div>

          {/* Budget Slider */}
          {isAdmin && (
            <div className="mt-4 flex items-center gap-4">
              <input
                type="range"
                min="5"
                max="30"
                step="1"
                value={budget}
                onChange={(e) => setBudget(Number(e.target.value))}
                className="h-2 w-full cursor-pointer accent-sky-600 dark:accent-sky-400"
              />
              <div className="w-16 font-mono text-sm font-semibold text-slate-900 dark:text-white">
                {budget} FPS
              </div>
            </div>
          )}
        </div>

        {/* Gate Cards Grid */}
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
          {gates.map((gate) => {
            const test = testResults[gate.gate_id];

            return (
              <div
                key={gate.gate_id}
                className={cx(
                  "flex flex-col justify-between rounded-xl border p-5 transition-colors",
                  gate.enabled
                    ? "border-sky-300 bg-white shadow-sm dark:border-sky-800/80 dark:bg-slate-900"
                    : "border-slate-200 bg-slate-50/50 opacity-90 dark:border-slate-800 dark:bg-slate-950/40"
                )}
              >
                <div>
                  {/* Gate Card Header */}
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <Camera className="h-4 w-4 text-slate-700 dark:text-slate-300" />
                        <h4 className="font-semibold text-slate-900 dark:text-white">
                          {gate.gate_name || gate.gate_id}
                        </h4>
                        <span className="font-mono text-xs text-slate-500">({gate.gate_id})</span>
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-2">
                        {gate.enabled ? (
                          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700 ring-1 ring-inset ring-emerald-600/20 dark:bg-emerald-950/60 dark:text-emerald-400">
                            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                            Active (Streaming)
                          </span>
                        ) : (
                          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-400">
                            Standby (Disabled)
                          </span>
                        )}

                        <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-mono text-slate-700 dark:bg-slate-800 dark:text-slate-300">
                          Target: {gate.enabled ? `${perGateTargetFps.toFixed(1)} FPS` : "0.0 FPS"}
                        </span>

                        <span
                          className={cx(
                            "rounded-md px-2 py-0.5 text-xs font-mono font-semibold",
                            gate.actual_fps > 0
                              ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300"
                              : "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400"
                          )}
                        >
                          Live: {gate.actual_fps.toFixed(1)} FPS
                        </span>
                      </div>
                    </div>

                    {/* Enable Toggle Button */}
                    {isAdmin && (
                      <Button
                        variant={gate.enabled ? "secondary" : "primary"}
                        size="sm"
                        icon={gate.enabled ? <Square className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                        onClick={() => handleToggleStream(gate)}
                      >
                        {gate.enabled ? "Stop" : "Enable Gate"}
                      </Button>
                    )}
                  </div>

                  {/* Input Fields */}
                  <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <Field label="Protocol">
                      <select
                        value={gate.protocol}
                        disabled={!isAdmin}
                        onChange={(e) => {
                          const proto = e.target.value;
                          const defaultPath = proto === "http" ? "/video" : "/h264_aac.sdp";
                          updateGateDraft(gate.gate_id, { protocol: proto, stream_path: defaultPath });
                        }}
                        className="w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-900 shadow-sm focus:border-sky-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                      >
                        <option value="http">HTTP (MJPEG)</option>
                        <option value="rtsp">RTSP (H.264)</option>
                      </select>
                    </Field>

                    <Field label="IP Address" className="sm:col-span-2">
                      <Input
                        value={gate.ip_address}
                        disabled={!isAdmin}
                        onChange={(e) => updateGateDraft(gate.gate_id, { ip_address: e.target.value })}
                        placeholder="192.168.1.100"
                        className="font-mono text-xs"
                      />
                    </Field>

                    <Field label="Port">
                      <Input
                        type="number"
                        min="1"
                        max="65535"
                        value={gate.port}
                        disabled={!isAdmin}
                        onChange={(e) => updateGateDraft(gate.gate_id, { port: Number(e.target.value) })}
                        placeholder="8080"
                        className="font-mono text-xs"
                      />
                    </Field>

                    <Field label="Stream Path" className="sm:col-span-2">
                      <Input
                        value={gate.stream_path}
                        disabled={!isAdmin}
                        onChange={(e) => updateGateDraft(gate.gate_id, { stream_path: e.target.value })}
                        placeholder="/video"
                        className="font-mono text-xs"
                      />
                    </Field>
                  </div>

                  {/* URL Preview */}
                  <div className="mt-3 rounded-md bg-slate-100/70 p-2 text-xs font-mono text-slate-600 dark:bg-slate-950/60 dark:text-slate-400">
                    <span className="text-slate-400">Stream URL: </span>
                    <span className="font-semibold text-slate-800 dark:text-slate-200">{gate.stream_url}</span>
                  </div>

                  {/* Test Result Message */}
                  {test && (
                    <div
                      className={cx(
                        "mt-3 flex items-start gap-2 rounded-lg p-2.5 text-xs",
                        test.status === "ok"
                          ? "bg-emerald-50 text-emerald-800 ring-1 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:ring-emerald-800"
                          : "bg-rose-50 text-rose-800 ring-1 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-300 dark:ring-rose-800"
                      )}
                    >
                      {test.status === "ok" ? (
                        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
                      ) : (
                        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-600 dark:text-rose-400" />
                      )}
                      <div>
                        <p className="font-medium">{test.message}</p>
                        {test.latency_ms && <p className="text-[11px] opacity-80">Latency: {test.latency_ms} ms</p>}
                      </div>
                    </div>
                  )}

                  {gate.last_error && !test && (
                    <div className="mt-3 text-xs text-rose-600 dark:text-rose-400">
                      <span className="font-medium">Stream Error:</span> {gate.last_error}
                    </div>
                  )}
                </div>

                {/* Card Footer Actions */}
                <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3 dark:border-slate-800/80">
                  <div className="text-[11px] text-slate-500">
                    {gate.last_seen_at
                      ? `Last frame: ${new Date(gate.last_seen_at).toLocaleTimeString()}`
                      : "No frames captured yet"}
                  </div>

                  {isAdmin && (
                    <Button
                      variant="ghost"
                      size="sm"
                      loading={testingGate === gate.gate_id}
                      icon={<Wifi className="h-3.5 w-3.5" />}
                      onClick={() => handleTestConnection(gate)}
                    >
                      Test Connection
                    </Button>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Add Gate Modal / Form */}
        {showAddGate && (
          <div className="rounded-xl border border-dashed border-sky-300 bg-sky-50/40 p-4 dark:border-sky-800 dark:bg-sky-950/20">
            <h4 className="font-semibold text-slate-900 dark:text-white">Add New Gate Camera</h4>
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-4">
              <Field label="Gate ID">
                <Input
                  value={newGateId}
                  onChange={(e) => setNewGateId(e.target.value)}
                  placeholder="GATE_4"
                  className="font-mono text-xs"
                />
              </Field>
              <Field label="Gate Name">
                <Input
                  value={newGateName}
                  onChange={(e) => setNewGateName(e.target.value)}
                  placeholder="West Delivery Gate"
                  className="text-xs"
                />
              </Field>
              <Field label="IP Address">
                <Input
                  value={newGateIp}
                  onChange={(e) => setNewGateIp(e.target.value)}
                  placeholder="192.168.1.104"
                  className="font-mono text-xs"
                />
              </Field>
              <Field label="Port">
                <Input
                  type="number"
                  value={newGatePort}
                  onChange={(e) => setNewGatePort(Number(e.target.value))}
                  placeholder="8080"
                  className="font-mono text-xs"
                />
              </Field>
            </div>
            <div className="mt-3 flex gap-2">
              <Button size="sm" variant="primary" onClick={handleAddGate} disabled={!newGateId.trim()}>
                Add Gate
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setShowAddGate(false)}>
                Cancel
              </Button>
            </div>
          </div>
        )}

        <ErrorNote message={error} />

        {/* Global Save Actions */}
        {isAdmin && (
          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="primary"
              loading={saving}
              icon={<RefreshCw className="h-4 w-4" />}
              onClick={saveSettings}
            >
              Save Camera Settings
            </Button>

            {!showAddGate && (
              <Button
                variant="secondary"
                icon={<Plus className="h-4 w-4" />}
                onClick={() => setShowAddGate(true)}
              >
                Add Another Gate
              </Button>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}
