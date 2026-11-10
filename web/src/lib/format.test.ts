import { describe, expect, it } from "vitest";

import {
  formatDateTime,
  formatFileSize,
  percent,
  truncate,
} from "./format";

describe("format", () => {
  it("formats file sizes", () => {
    expect(formatFileSize(512)).toBe("512 B");
    expect(formatFileSize(2048)).toBe("2.0 KB");
    expect(formatFileSize(1024 * 1024)).toBe("1.00 MB");
  });

  it("formats nullable percentages", () => {
    expect(percent(null)).toBe("—");
    expect(percent(0.5)).toBe("50.0%");
  });

  it("truncates long text", () => {
    expect(truncate("abcdef", 3)).toBe("abc…");
    expect(truncate("abc", 3)).toBe("abc");
  });

  it("formats ISO dates and preserves invalid input", () => {
    expect(formatDateTime("2026-11-10T12:00:00Z")).toContain("2026");
    expect(formatDateTime("not-a-date")).toBe("not-a-date");
  });
});
