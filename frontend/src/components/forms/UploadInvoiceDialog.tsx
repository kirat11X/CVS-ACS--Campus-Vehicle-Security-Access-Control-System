import { useState, type FormEvent } from "react";
import { ApiError, api } from "../../api/client";
import { DELIVERY_ROOTS, useGates, useInvalidate } from "../../api/queries";
import type { DeliveryDetail } from "../../api/types";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";
import { Callout, ErrorNote } from "../ui/Feedback";
import { Field, Input, Select } from "../ui/Form";

/** Guard uploads an invoice photo / PDF from the console (POST /deliveries/process). */
export function UploadInvoiceDialog({
  token,
  initialOrderId = "",
  onClose,
  onProcessed,
}: {
  token: string;
  initialOrderId?: string;
  onClose: () => void;
  onProcessed: (detail: DeliveryDetail) => void;
}) {
  const gates = useGates();
  const invalidate = useInvalidate();
  const [orderId, setOrderId] = useState(initialOrderId);
  const [gateId, setGateId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const usable = (gates.data ?? []).filter((g) => g.status === "ACTIVE");

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setSubmitting(true);
    setError(null);
    const form = new FormData();
    form.set("order_id", orderId.trim());
    form.set("file", file);
    if (gateId) form.set("gate_id", gateId);
    try {
      const detail = await api.processDelivery(token, form);
      void invalidate(...DELIVERY_ROOTS);
      onProcessed(detail);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not process the invoice.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      title="Upload invoice"
      description="The server reads each line and screens it against the policy table. It only advises; you decide at the gate."
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="upload-invoice-form" variant="primary" loading={submitting} disabled={!orderId.trim() || !file}>
            Read and screen
          </Button>
        </>
      }
    >
      <form id="upload-invoice-form" onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Order ID" hint="As shown on the rider's app, e.g. D-20481">
            <Input className="font-mono uppercase" required maxLength={64} value={orderId} onChange={(e) => setOrderId(e.target.value)} autoComplete="off" />
          </Field>
          <Field label="Gate (optional)">
            <Select value={gateId} onChange={(e) => setGateId(e.target.value)} disabled={gates.isLoading}>
              <option value="">Not recorded</option>
              {usable.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name} ({g.id})
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="Invoice photo or PDF">
          <Input type="file" required accept="image/*,application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </Field>
        <Callout>Reading can take a few seconds. Nothing is blocked automatically; flagged lines wait for your decision.</Callout>
        <ErrorNote message={error} />
      </form>
    </Dialog>
  );
}
