import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2 } from "lucide-react";

const ToastContext = createContext(() => {});

export function ToastProvider({ children }) {
  const [toast, setToast] = useState(null);
  const timer = useRef(null);

  const show = useCallback((message, isError = false) => {
    clearTimeout(timer.current);
    setToast({ message, isError, key: Date.now() });
    timer.current = setTimeout(() => setToast(null), 4000);
  }, []);

  useEffect(() => () => clearTimeout(timer.current), []);

  return (
    <ToastContext.Provider value={show}>
      {children}
      {toast && (
        <div key={toast.key} className={`toast${toast.isError ? " error" : ""}`} role={toast.isError ? "alert" : "status"}>
          {toast.isError ? <AlertCircle size={18} /> : <CheckCircle2 size={18} />}
          {toast.message}
        </div>
      )}
    </ToastContext.Provider>
  );
}

// toast(message, isError?)
export function useToast() {
  return useContext(ToastContext);
}
