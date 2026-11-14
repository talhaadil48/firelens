import { Component } from "react";
import type { ReactNode } from "react";
export default class ChartBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <p className="notice error" role="alert">
        The chart could not load. Use the source table to inspect the evidence.
      </p>
    ) : (
      this.props.children
    );
  }
}
