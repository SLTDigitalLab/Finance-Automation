import { downloadCipJournalReview, downloadCipReport } from "./api";

describe("CIP journal review download", () => {
  const originalFetch = global.fetch;
  const originalCreateObjectURL = window.URL.createObjectURL;
  const originalRevokeObjectURL = window.URL.revokeObjectURL;

  afterEach(() => {
    global.fetch = originalFetch;
    jest.useRealTimers();
    if (originalCreateObjectURL) {
      window.URL.createObjectURL = originalCreateObjectURL;
    } else {
      delete window.URL.createObjectURL;
    }
    if (originalRevokeObjectURL) {
      window.URL.revokeObjectURL = originalRevokeObjectURL;
    } else {
      delete window.URL.revokeObjectURL;
    }
    localStorage.clear();
    jest.restoreAllMocks();
  });

  it("downloads the generated review using its period-specific filename", async () => {
    const filename = "CIP_Journal_Details_Review_Jul_26.xlsx";
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      blob: jest.fn().mockResolvedValue(new Blob(["review"])),
    });
    window.URL.createObjectURL = jest.fn().mockReturnValue("blob:cip-review");
    window.URL.revokeObjectURL = jest.fn();
    jest.useFakeTimers();
    jest.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function () {
      expect(this.download).toBe(filename);
    });

    await downloadCipJournalReview(filename, "Jul-26");

    expect(global.fetch).toHaveBeenCalledWith(
      `/api/cip/download-journal-review?filename=${encodeURIComponent(filename)}`,
      { headers: {} }
    );
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(1);
    expect(window.URL.revokeObjectURL).not.toHaveBeenCalled();
    jest.advanceTimersByTime(1000);
    expect(window.URL.revokeObjectURL).toHaveBeenCalledWith("blob:cip-review");
  });

  it("keeps the report download URL alive until the browser has started the download", async () => {
    const filename = "CIP_Reconciliation_Report_Jul_26.xlsx";
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      blob: jest.fn().mockResolvedValue(new Blob(["report"])),
    });
    window.URL.createObjectURL = jest.fn().mockReturnValue("blob:cip-report");
    window.URL.revokeObjectURL = jest.fn();
    jest.useFakeTimers();
    jest.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function () {
      expect(this.download).toBe(filename);
    });

    await downloadCipReport(filename, "Jul-26");

    expect(global.fetch).toHaveBeenCalledWith(
      `/api/cip/download?filename=${encodeURIComponent(filename)}`,
      { headers: {} }
    );
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(1);
    expect(window.URL.revokeObjectURL).not.toHaveBeenCalled();
    jest.advanceTimersByTime(1000);
    expect(window.URL.revokeObjectURL).toHaveBeenCalledWith("blob:cip-report");
  });
});
