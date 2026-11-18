import { useEffect, useId, useRef } from "react";

// A modal yes/no question. Esc, the Cancel button, or a click outside cancels.
// icon: a lucide icon shown above the title; confirmIcon: one inside the confirm button.
export default function ConfirmDialog({ open, title, icon: Icon, confirmIcon: ConfirmIcon, children, confirmLabel = "Confirm", cancelLabel = "Cancel", onConfirm, onCancel }) {
  const ref = useRef(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog ref={ref} className="confirm" aria-labelledby={titleId}
      onCancel={(e) => { e.preventDefault(); onCancel(); }}
      onClick={(e) => { if (e.target === ref.current) onCancel(); }}>
      <div className="confirm-inner">
        {Icon && <span className="confirm-icon" aria-hidden="true"><Icon size={22} /></span>}
        <h2 id={titleId}>{title}</h2>
        <div className="confirm-body">{children}</div>
        <div className="confirm-actions">
          <button type="button" className="btn btn-secondary" onClick={onCancel}>{cancelLabel}</button>
          <button type="button" className="btn btn-primary" onClick={onConfirm} autoFocus>
            {ConfirmIcon && <ConfirmIcon size={16} />} {confirmLabel}
          </button>
        </div>
      </div>
    </dialog>
  );
}
