import { render, screen } from "@testing-library/react";
import HomePage from "@/app/page";

describe("HomePage", () => {
  it("renders the AORIA RH heading", () => {
    render(<HomePage />);
    expect(screen.getByText("AORIA RH")).toBeInTheDocument();
  });
});
