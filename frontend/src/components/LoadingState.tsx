import React from "react";

type LoadingStateProps = {
  message: string;
};

export function LoadingState({ message }: LoadingStateProps) {
  return (
    <div className="loading-spinner">
      <div className="spinner"></div>
      <span>{message}</span>
    </div>
  );
}
