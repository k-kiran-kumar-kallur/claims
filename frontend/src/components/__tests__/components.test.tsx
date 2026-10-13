import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CitationProvider, CitedMarkdown } from "../CitationViewer";
import { fmtDate, StatusChip } from "../common";
import { qs } from "../../api/client";

const wrap = (ui: React.ReactNode) => render(
  <QueryClientProvider client={new QueryClient()}><MemoryRouter><CitationProvider>{ui}</CitationProvider></MemoryRouter></QueryClientProvider>,
);

describe("CitedMarkdown", () => {
  it("renders headings, bullets and numbered citation chips for every AI statement", () => {
    const id = "01a11f9d-77d8-7bb3-85ee-bcd5840178db";
    wrap(<CitedMarkdown md={`### Injury\n- Lifting injury on 09/14/2024 [[cite:${id}]]\n- Unsupported statement`} citations={{ [id]: { document_id: "d1", page_number: 2, line_start: 4, line_end: 4, quote: "lifting an 80 lb crate" } }} />);
    expect(screen.getByText("Injury")).toBeInTheDocument();
    expect(screen.getByText("[1]")).toBeInTheDocument();
    expect(screen.getByText(/Unsupported statement/)).toBeInTheDocument();
  });

  it("drops citation tokens that cannot be resolved", () => {
    wrap(<CitedMarkdown md={"- text [[cite:01a11f9d-77d8-7bb3-85ee-000000000000]]"} citations={{}} />);
    expect(screen.queryByText("[1]")).not.toBeInTheDocument();
  });
});

describe("helpers", () => {
  it("formats ISO dates as MM/DD/YYYY", () => expect(fmtDate("2024-09-14")).toBe("09/14/2024"));
  it("builds query strings without empty values", () => expect(qs({ a: 1, b: "", c: undefined, d: "x y" })).toBe("?a=1&d=x+y"));
  it("renders status chips with readable labels", () => {
    render(<StatusChip status="awaiting_human" />);
    expect(screen.getByText("awaiting human")).toBeInTheDocument();
  });
});
