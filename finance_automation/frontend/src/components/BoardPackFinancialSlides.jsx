import React, { useRef, useState } from "react";
import {
  Alert,
  Button,
  Chip,
  LinearProgress,
  Paper,
  Tooltip,
} from "@mui/material";
import {
  CheckCircle as CheckCircleIcon,
  CloudUpload as UploadIcon,
  Delete as DeleteIcon,
  Description as FileIcon,
  Download as DownloadIcon,
  Slideshow as SlidesIcon,
} from "@mui/icons-material";
import {
  downloadBoardPackSlides,
  generateBoardPackSlides,
} from "../services/api";

const ACCEPTED_EXTENSIONS = [".xlsx", ".xlsm"];
const MAX_FILE_SIZE_MB = 50;

const formatSize = (bytes) =>
  bytes >= 1024 * 1024
    ? `${(bytes / (1024 * 1024)).toFixed(1)} MB`
    : `${Math.ceil(bytes / 1024)} KB`;

function validateFile(file) {
  if (!ACCEPTED_EXTENSIONS.some((ext) => file.name.toLowerCase().endsWith(ext))) {
    return "Select the Ratio and Balance Sheet Excel file (.xlsx or .xlsm).";
  }
  if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
    return `The file is larger than ${MAX_FILE_SIZE_MB} MB.`;
  }
  return null;
}

export default function BoardPackFinancialSlides() {
  const inputRef = useRef(null);
  const [file, setFile] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  const selectFile = (selected) => {
    if (!selected) return;
    setResult(null);
    const problem = validateFile(selected);
    if (problem) {
      setFile(null);
      setError(problem);
      return;
    }
    setError("");
    setFile(selected);
  };

  const clearFile = () => {
    setFile(null);
    setResult(null);
    setError("");
    if (inputRef.current) inputRef.current.value = "";
  };

  const handleGenerate = async () => {
    if (!file) return;
    setGenerating(true);
    setError("");
    setResult(null);
    try {
      setResult(await generateBoardPackSlides(file));
    } catch (err) {
      setError(err.message || "Failed to generate the Ratio and Balance Sheet slides");
    } finally {
      setGenerating(false);
    }
  };

  const handleDownload = async () => {
    if (!result?.filename) return;
    setDownloading(true);
    try {
      await downloadBoardPackSlides(result.filename);
    } catch (err) {
      setError(err.message || "Failed to download the PowerPoint");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <Paper elevation={0} sx={{ borderRadius: 3, border: "1px solid #dce5ee", p: { xs: 3, md: 4 } }}>
      <h3 className="text-lg font-black text-[#082f49]">Ratio &amp; Balance Sheet slides</h3>
      <p className="mt-1 text-sm font-semibold text-slate-500">
        Upload the workbook containing the Ratio tab and the final Group Balance Sheet tab.
        This creates a separate two-slide PowerPoint without changing the full board pack.
      </p>

      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && inputRef.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          selectFile(event.dataTransfer.files?.[0]);
        }}
        className={`mt-5 flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-8 text-center transition ${
          dragging ? "border-[#1B6B93] bg-sky-50" : "border-slate-300 bg-slate-50 hover:border-[#1B6B93] hover:bg-sky-50/60"
        }`}
      >
        <UploadIcon sx={{ fontSize: 40, color: "#1B6B93" }} />
        <p className="mt-3 text-sm font-extrabold text-[#082f49]">Drop the Ratio workbook here or click to browse</p>
        <p className="mt-1 text-xs font-semibold text-slate-500">.xlsx or .xlsm, up to {MAX_FILE_SIZE_MB} MB</p>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_EXTENSIONS.join(",")}
          className="hidden"
          onChange={(event) => selectFile(event.target.files?.[0])}
        />
      </div>

      {file && (
        <div className="mt-4 flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3">
          <div className="flex min-w-0 items-center gap-3">
            <FileIcon sx={{ color: "#7AB648" }} />
            <div className="min-w-0">
              <p className="truncate text-sm font-extrabold text-slate-800">{file.name}</p>
              <p className="text-xs font-semibold text-slate-500">{formatSize(file.size)}</p>
            </div>
          </div>
          <Tooltip title="Remove file">
            <span>
              <Button onClick={clearFile} disabled={generating} sx={{ minWidth: 36, color: "#64748b" }}>
                <DeleteIcon fontSize="small" />
              </Button>
            </span>
          </Tooltip>
        </div>
      )}

      {error && <Alert severity="error" sx={{ mt: 3, fontWeight: 600 }}>{error}</Alert>}

      <Button
        onClick={handleGenerate}
        disabled={!file || generating}
        variant="contained"
        startIcon={<SlidesIcon />}
        sx={{
          mt: 3,
          height: 46,
          px: 4,
          textTransform: "none",
          fontWeight: 900,
          borderRadius: 1.5,
          backgroundColor: "#0B3041",
          "&:hover": { backgroundColor: "#1B6B93" },
        }}
      >
        {generating ? "Generating…" : "Generate 2 Slides"}
      </Button>
      {generating && <LinearProgress sx={{ mt: 2, borderRadius: 1 }} />}

      {result && (
        <div className="mt-6 rounded-xl border border-emerald-200 bg-emerald-50 p-5">
          <div className="flex items-start gap-3">
            <CheckCircleIcon sx={{ color: "#047857", mt: 0.25 }} />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-black text-emerald-900">Two slides ready</p>
              <p className="mt-1 break-all text-xs font-semibold text-emerald-800">{result.filename}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Chip size="small" label={`Period: ${result.period}`} sx={{ fontWeight: 800, backgroundColor: "#d1fae5", color: "#065f46" }} />
                <Chip size="small" label={`${result.slide_count} slides`} sx={{ fontWeight: 800, backgroundColor: "#d1fae5", color: "#065f46" }} />
              </div>
              <p className="mt-3 text-xs font-semibold text-emerald-900">
                Tabs read: {result.sheets_used.join(", ")}
              </p>
            </div>
          </div>
          <Button
            onClick={handleDownload}
            disabled={downloading}
            variant="contained"
            startIcon={<DownloadIcon />}
            sx={{
              mt: 3,
              height: 44,
              px: 3.5,
              textTransform: "none",
              fontWeight: 900,
              borderRadius: 1.5,
              backgroundColor: "#7AB648",
              "&:hover": { backgroundColor: "#6AA038" },
            }}
          >
            {downloading ? "Downloading…" : "Download PowerPoint (.pptx)"}
          </Button>
        </div>
      )}
    </Paper>
  );
}
