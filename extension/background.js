// background.js - minimal service worker for state management
// Stores the active student ID across tab reloads

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'GET_STUDENT_ID') {
    chrome.storage.local.get(['studentId'], (result) => {
      sendResponse({ studentId: result.studentId || 'demo_student_1' });
    });
    return true; // async
  }
  if (msg.type === 'SET_STUDENT_ID') {
    chrome.storage.local.set({ studentId: msg.studentId });
  }
});
