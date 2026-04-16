"use client";

import { useEffect, useState } from "react";

interface ToastProps {
  message: string;
  onDismiss: () => void;
}

export function Toast({ message, onDismiss }: ToastProps) {
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => {
      setVisible(false);
      setTimeout(onDismiss, 300);
    }, 5000);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  return (
    <div
      className={`fixed bottom-6 right-6 z-50 max-w-sm transition-all duration-300 ${visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-2"}`}
    >
      <div className="bg-red-900/90 border border-red-700 rounded-lg px-4 py-3 shadow-xl flex items-start gap-3">
        <span className="text-red-300 text-sm flex-1">⚠️ {message}</span>
        <button
          onClick={() => { setVisible(false); setTimeout(onDismiss, 300); }}
          className="text-red-400 hover:text-red-200 text-sm shrink-0"
        >
          ✕
        </button>
      </div>
    </div>
  );
}
