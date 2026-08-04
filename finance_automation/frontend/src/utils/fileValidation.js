/**
 * Validates the uploaded Trial Balance text file by reading its contents.
 * @param {File} file - The file object from the dropzone/input.
 * @param {string} key - The key for current/previous year trial balance.
 */
export function validateTrialBalanceFile(file, key) {
  return new Promise((resolve) => {
    if (!file) {
      resolve({ isValid: true, errorMessage: null });
      return;
    }

    const fileName = file.name.toLowerCase();
    const isTxt = fileName.endsWith(".txt") || file.type === "text/plain";

    // Standard rejection message per exact specification
    const rejectionMessage =
      "This file is not supported. Standard Trial Balance files cannot be uploaded to the system. Please upload the 'PTD - Shared Revenue only' file.";

    if (!isTxt) {
      // Non-txt files (e.g. Excel) pass text check
      resolve({ isValid: true, errorMessage: null });
      return;
    }

    const reader = new FileReader();

    reader.onload = function (e) {
      try {
        const fileContent = e.target.result || "";

        // Check internal text markers (case-insensitive)
        const lowerContent = fileContent.toLowerCase();
        const isYTD = lowerContent.includes("year to date as of");
        const isPTD =
          lowerContent.includes("period to date for") ||
          lowerContent.includes("period to date");

        // Standard trial balance files contain YTD or lack PTD
        if (isYTD || !isPTD) {
          resolve({
            isValid: false,
            errorMessage: rejectionMessage,
          });
          return;
        }

        console.log("File accepted: PTD Shared Revenue file confirmed for", key);
        resolve({ isValid: true, errorMessage: null });
      } catch (err) {
        console.error("Error validating Trial Balance text file:", err);
        resolve({
          isValid: false,
          errorMessage: rejectionMessage,
        });
      }
    };

    reader.onerror = function () {
      resolve({
        isValid: false,
        errorMessage: rejectionMessage,
      });
    };

    // Read full file (or up to 2MB slice) to scan headers anywhere in the file
    const blobSlice = file.size > 2097152 ? file.slice(0, 2097152) : file;
    reader.readAsText(blobSlice);
  });
}
