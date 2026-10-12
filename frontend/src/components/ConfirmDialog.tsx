import { AlertTriangle, XCircle } from "lucide-react";

type ConfirmDialogProps = {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  variant?: "danger" | "default";
  checkboxLabel?: string;
  checkboxChecked?: boolean;
  onCheckboxChange?: (checked: boolean) => void;
  onConfirm: () => void;
  onCancel: () => void;
};

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "确认",
  variant = "default",
  checkboxLabel,
  checkboxChecked = false,
  onCheckboxChange,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  if (!open) return null;

  return (
    <div className="dialog-overlay" onClick={onCancel}>
      <div className="dialog" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={title}>
        <div className="dialog-header">
          <div className={`dialog-icon ${variant === "danger" ? "danger" : "info"}`}>
            {variant === "danger" ? <XCircle size={20} /> : <AlertTriangle size={20} />}
          </div>
          <h3>{title}</h3>
        </div>
        <p className="dialog-message">{message}</p>
        {checkboxLabel && (
          <label className="filter-toggle dialog-checkbox">
            <input
              type="checkbox"
              checked={checkboxChecked}
              aria-label={checkboxLabel}
              onChange={(event) => onCheckboxChange?.(event.target.checked)}
            />
            <span>{checkboxLabel}</span>
          </label>
        )}
        <div className="dialog-actions">
          <button className="button secondary" onClick={onCancel}>取消</button>
          <button className={`button ${variant === "danger" ? "primary danger-confirm" : "primary"}`} onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
