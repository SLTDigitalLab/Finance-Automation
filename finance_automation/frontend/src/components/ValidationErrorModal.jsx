import React from "react";
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Typography,
  Box,
} from "@mui/material";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";

export default function ValidationErrorModal({ open, onClose, message }) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="xs"
      fullWidth
      PaperProps={{
        sx: {
          borderRadius: 3,
          p: 1,
          boxShadow: "0 20px 40px rgba(0, 0, 0, 0.2)",
        },
      }}
    >
      <DialogTitle sx={{ pb: 1, pt: 2.5, px: 3 }}>
        <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
          <Box
            sx={{
              width: 44,
              height: 44,
              borderRadius: "50%",
              backgroundColor: "#FEE2E2",
              display: "grid",
              placeItems: "center",
              flexShrink: 0,
            }}
          >
            <ErrorOutlineIcon sx={{ color: "#DC2626", fontSize: 26 }} />
          </Box>
          <Typography variant="h6" sx={{ fontWeight: 800, color: "#1E293B" }}>
            Unsupported File Format
          </Typography>
        </Box>
      </DialogTitle>

      <DialogContent sx={{ py: 1.5, px: 3 }}>
        <Typography
          variant="body1"
          sx={{ color: "#475569", fontWeight: 500, lineHeight: 1.6 }}
        >
          {message ||
            "This file is not supported. Standard Trial Balance files cannot be uploaded to the system. Please upload the 'PTD - Shared Revenue only' file."}
        </Typography>
      </DialogContent>

      <DialogActions sx={{ p: 2.5, pt: 1.5 }}>
        <Button
          onClick={onClose}
          variant="contained"
          fullWidth
          sx={{
            backgroundColor: "#0B3041",
            color: "#FFFFFF",
            fontWeight: 800,
            textTransform: "none",
            borderRadius: 2,
            py: 1.2,
            fontSize: "0.95rem",
            "&:hover": {
              backgroundColor: "#143D52",
            },
          }}
        >
          Got it
        </Button>
      </DialogActions>
    </Dialog>
  );
}
