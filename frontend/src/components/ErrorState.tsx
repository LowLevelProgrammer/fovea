import React from "react";

type ErrorStateProps = {
  title: string;
  message: string;
};

export function ErrorState({ title, message }: ErrorStateProps) {
  return (
    <div className="error-card">
      <div className="error-title">{title}</div>
      <p className="error-message">{message}</p>
    </div>
  );
}
