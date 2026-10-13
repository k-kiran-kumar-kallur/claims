import { Alert, Box, Button } from "@mui/material";
import { Component, ReactNode } from "react";

/** Shows a readable error instead of a blank screen if a page fails to render. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <Box sx={{ p: 2 }}>
        <Alert severity="error" action={<Button color="inherit" onClick={() => this.setState({ error: null })}>Retry</Button>}>
          This section could not be displayed: {this.state.error.message}. Other tabs still work; please report this message.
        </Alert>
      </Box>
    );
  }
}
